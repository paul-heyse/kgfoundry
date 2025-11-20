"""Tests for scope store components: LRU cache, async single-flight, and scope store."""

from __future__ import annotations

import asyncio
import time as time_module
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import pytest
from codeintel_rev.app.scope_store import AsyncSingleFlight, LRUCache, ScopeStore
from codeintel_rev.mcp_server.schemas import ScopeIn

from tests._helpers import assertions

# Test constants for single-flight test results
_EXPECTED_SINGLE_FLIGHT_RESULT = 42


class FakeClock:
    """Simple monotonic clock for deterministic TTL testing."""

    def __init__(self) -> None:
        """Initialize fake clock with zero time."""
        self._now = 0.0

    def now(self) -> float:
        """Return current clock time.

        Returns
        -------
        float
            Current clock time value.
        """
        return self._now

    def advance(self, seconds: float) -> None:
        """Advance clock by specified seconds."""
        self._now += seconds


def test_lru_cache_evicts_least_recently_used() -> None:
    """Test that LRU cache evicts least recently used entries when capacity is exceeded."""
    clock = FakeClock()
    cache: LRUCache[str, int] = LRUCache(maxsize=2, ttl_seconds=None, now_fn=clock.now)

    cache.set("a", 1)
    cache.set("b", 2)

    assertions.expect_equal(cache.get("a"), 1)  # refresh recency of "a"

    cache.set("c", 3)  # should evict "b"

    snapshot = cache.snapshot()
    assertions.expect_in("a", snapshot)
    assertions.expect_in("c", snapshot)
    assertions.expect_equal(cache.get("b"), None)
    assertions.expect_equal(cache.snapshot(), {"a": 1, "c": 3})


def test_lru_cache_ttl_expires_entries_on_access() -> None:
    """Test that LRU cache expires entries based on TTL when accessed."""
    clock = FakeClock()
    cache: LRUCache[str, str] = LRUCache(maxsize=4, ttl_seconds=1.0, now_fn=clock.now)

    cache.set("token", "value")
    assertions.expect_equal(cache.get("token"), "value")

    clock.advance(0.9)
    assertions.expect_equal(cache.get("token"), "value")

    clock.advance(0.2)
    assertions.expect_equal(cache.get("token"), None)
    assertions.expect_false("token" in cache, reason="token should be expired")
    assertions.expect_equal(len(cache), 0)


def test_lru_cache_is_thread_safe() -> None:
    """Test that LRU cache operations are thread-safe under concurrent access."""
    cache: LRUCache[str, int] = LRUCache(maxsize=128, ttl_seconds=None)

    def writer_reader(idx: int) -> int | None:
        """Write and read cache entry for thread safety test.

        Parameters
        ----------
        idx : int
            Index used to generate unique cache key and value.

        Returns
        -------
        int | None
            Cached value if found, None otherwise.
        """
        cache.set(f"key-{idx}", idx)
        return cache.get(f"key-{idx}")

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(writer_reader, range(64)))

    observed = {value for value in results if value is not None}
    assertions.expect_equal(observed, set(range(64)))
    assertions.expect_equal(len(cache), 64)


class FakeRedis:
    """Minimal in-memory Redis analogue for testing."""

    def __init__(self) -> None:
        """Initialize fake Redis with empty data store."""
        self._data: dict[str, tuple[bytes, float | None]] = {}
        self.get_calls = 0
        self.set_calls = 0
        self.setex_calls: list[int] = []

    async def get(self, name: str) -> bytes | None:
        """Get value by key, returning None if expired or missing.

        Returns
        -------
        bytes | None
            Value associated with key, or None if expired or missing.
        """
        self.get_calls += 1
        record = self._data.get(name)
        if record is None:
            return None
        value, expires_at = record
        if expires_at is not None and expires_at <= time_module.monotonic():
            self._data.pop(name, None)
            return None
        return value

    async def setex(self, name: str, time: int, value: bytes) -> bool | None:
        """Set value with expiration time.

        Returns
        -------
        bool | None
            True on success.
        """
        expires_at = time_module.monotonic() + time if time > 0 else None
        self.setex_calls.append(time)
        self._data[name] = (value, expires_at)
        return True

    async def set(self, name: str, value: bytes) -> bool | None:
        """Set value without expiration.

        Returns
        -------
        bool | None
            True on success.
        """
        self.set_calls += 1
        self._data[name] = (value, None)
        return True

    async def delete(self, *names: str) -> int | None:
        """Delete one or more keys, returning count of deleted keys.

        Returns
        -------
        int | None
            Number of keys deleted.
        """
        removed = 0
        for entry in names:
            if self._data.pop(entry, None) is not None:
                removed += 1
        return removed

    async def close(self) -> None:
        """Clear all data."""
        self._data.clear()

    def contains(self, key: str) -> bool:
        """Check if key exists in store.

        Returns
        -------
        bool
            True if key exists, False otherwise.
        """
        return key in self._data


def _sample_scope() -> ScopeIn:
    """Create sample scope for testing.

    Returns
    -------
    ScopeIn
        Scope dictionary with test values.
    """
    return cast(
        "ScopeIn",
        {
            "repos": ["kgfoundry"],
            "branches": ["main"],
            "include_globs": ["src/**"],
            "exclude_globs": [],
            "languages": ["python"],
        },
    )


@pytest.mark.asyncio
async def test_scope_store_prefers_l1_cache() -> None:
    """Test that scope store prefers L1 cache hits over L2 Redis lookups."""
    redis = FakeRedis()
    store = ScopeStore(redis, l1_maxsize=8, l1_ttl_seconds=30.0, l2_ttl_seconds=3600)

    scope = _sample_scope()
    await store.set("session-1", scope)

    result = await store.get("session-1")

    assertions.expect_equal(result, scope)
    assertions.expect_equal(store.metrics.l1_hits, 1)
    assertions.expect_equal(store.metrics.l2_hits, 0)
    assertions.expect_equal(redis.get_calls, 0)

    await store.close()


@pytest.mark.asyncio
async def test_scope_store_l2_fetch_coalesces_requests() -> None:
    """Test that concurrent L2 fetches are coalesced via single-flight semantics."""
    redis = FakeRedis()
    store = ScopeStore(redis, l1_maxsize=8, l1_ttl_seconds=30.0, l2_ttl_seconds=3600)

    scope = _sample_scope()
    await store.set("session-2", scope)

    store.evict_l1("session-2")

    results = await asyncio.gather(*(store.get("session-2") for _ in range(5)))

    assertions.expect_sequence_equal(results, [scope] * 5)
    assertions.expect_equal(redis.get_calls, 1)
    assertions.expect_equal(store.metrics.l2_hits, 1)
    assertions.expect_equal(store.metrics.l2_misses, 0)

    await store.close()


@pytest.mark.asyncio
async def test_scope_store_delete_clears_l1_and_l2() -> None:
    """Test that delete operation clears both L1 cache and L2 Redis storage."""
    redis = FakeRedis()
    store = ScopeStore(redis, l1_maxsize=8, l1_ttl_seconds=30.0, l2_ttl_seconds=3600)

    scope = _sample_scope()
    await store.set("session-3", scope)
    await store.delete("session-3")

    assertions.expect_equal(store.metrics.l1_hits, 0)
    assertions.expect_equal(await store.get("session-3"), None)
    assertions.expect_false(
        redis.contains("scope:session-3"), reason="session-3 should be deleted from redis"
    )

    await store.close()


@pytest.mark.asyncio
async def test_scope_store_without_l2_ttl_uses_set() -> None:
    """Test that scope store uses SET instead of SETEX when L2 TTL is None."""
    redis = FakeRedis()
    store = ScopeStore(redis, l1_maxsize=8, l1_ttl_seconds=30.0, l2_ttl_seconds=None)

    await store.set("session-4", _sample_scope())

    assertions.expect_equal(redis.set_calls, 1)
    assertions.expect_false(
        bool(redis.setex_calls), reason="should not use setex when l2_ttl_seconds is None"
    )

    await store.close()


@pytest.mark.asyncio
async def test_async_single_flight_coalesces_calls() -> None:
    """Test that async single-flight coalesces concurrent calls to the same key."""
    flight: AsyncSingleFlight[str, int] = AsyncSingleFlight()
    call_count = 0

    async def expensive_call() -> int:
        """Simulate expensive async operation for single-flight test.

        Returns
        -------
        int
            Expected single-flight result constant.
        """
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.01)
        return _EXPECTED_SINGLE_FLIGHT_RESULT

    results = await asyncio.gather(*[flight.do("scope", expensive_call) for _ in range(10)])

    assertions.expect_true(
        all(result == _EXPECTED_SINGLE_FLIGHT_RESULT for result in results),
        reason=f"all results should be {_EXPECTED_SINGLE_FLIGHT_RESULT}",
    )
    assertions.expect_equal(call_count, 1)


@pytest.mark.asyncio
async def test_async_single_flight_propagates_exceptions_and_allows_retry() -> None:
    """Test that async single-flight propagates exceptions and allows retry after failure."""
    flight: AsyncSingleFlight[str, int] = AsyncSingleFlight()
    call_count = 0

    async def failing_call() -> int:
        """Simulate async operation that raises RuntimeError.

        Raises
        ------
        RuntimeError
            Always raised with message "boom" to test error propagation.
        """
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0)
        message = "boom"
        raise RuntimeError(message)

    with pytest.raises(RuntimeError):
        await asyncio.gather(flight.do("scope", failing_call), flight.do("scope", failing_call))

    assertions.expect_equal(call_count, 1)

    async def succeeding_call() -> int:
        """Simulate async operation that succeeds after previous failure.

        Returns
        -------
        int
            Success value 7.
        """
        await asyncio.sleep(0)
        return 7

    result = await flight.do("scope", succeeding_call)
    assertions.expect_equal(result, 7)
