from __future__ import annotations

import asyncio
import time as time_module
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import pytest
from codeintel_rev.app.scope_store import AsyncSingleFlight, LRUCache, ScopeStore
from codeintel_rev.mcp_server.schemas import ScopeIn


class FakeClock:
    """Simple monotonic clock for deterministic TTL testing."""

    def __init__(self) -> None:
        self._now = 0.0

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_lru_cache_evicts_least_recently_used() -> None:
    clock = FakeClock()
    cache: LRUCache[str, int] = LRUCache(maxsize=2, ttl_seconds=None, now_fn=clock.now)

    cache.set("a", 1)
    cache.set("b", 2)

    assert cache.get("a") == 1  # refresh recency of "a"

    cache.set("c", 3)  # should evict "b"

    assert "a" in cache
    assert "c" in cache
    assert cache.get("b") is None
    assert cache.snapshot() == {"a": 1, "c": 3}


def test_lru_cache_ttl_expires_entries_on_access() -> None:
    clock = FakeClock()
    cache: LRUCache[str, str] = LRUCache(maxsize=4, ttl_seconds=1.0, now_fn=clock.now)

    cache.set("token", "value")
    assert cache.get("token") == "value"

    clock.advance(0.9)
    assert cache.get("token") == "value"

    clock.advance(0.2)
    assert cache.get("token") is None
    assert "token" not in cache
    assert len(cache) == 0


def test_lru_cache_is_thread_safe() -> None:
    cache: LRUCache[str, int] = LRUCache(maxsize=128, ttl_seconds=None)

    def writer_reader(idx: int) -> int | None:
        cache.set(f"key-{idx}", idx)
        return cache.get(f"key-{idx}")

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(writer_reader, range(64)))

    observed = {value for value in results if value is not None}
    assert observed == set(range(64))
    assert len(cache) == 64


class FakeRedis:
    """Minimal in-memory Redis analogue for testing."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, float | None]] = {}
        self.get_calls = 0
        self.set_calls = 0
        self.setex_calls: list[int] = []

    async def get(self, name: str) -> bytes | None:
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
        expires_at = time_module.monotonic() + time if time > 0 else None
        self.setex_calls.append(time)
        self._data[name] = (value, expires_at)
        return True

    async def set(self, name: str, value: bytes) -> bool | None:
        self.set_calls += 1
        self._data[name] = (value, None)
        return True

    async def delete(self, *names: str) -> int | None:
        removed = 0
        for entry in names:
            if self._data.pop(entry, None) is not None:
                removed += 1
        return removed

    async def close(self) -> None:
        self._data.clear()

    def contains(self, key: str) -> bool:
        return key in self._data


def _sample_scope() -> ScopeIn:
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
    redis = FakeRedis()
    store = ScopeStore(redis, l1_maxsize=8, l1_ttl_seconds=30.0, l2_ttl_seconds=3600)

    scope = _sample_scope()
    await store.set("session-1", scope)

    result = await store.get("session-1")

    assert result == scope
    assert store.metrics.l1_hits == 1
    assert store.metrics.l2_hits == 0
    assert redis.get_calls == 0

    await store.close()


@pytest.mark.asyncio
async def test_scope_store_l2_fetch_coalesces_requests() -> None:
    redis = FakeRedis()
    store = ScopeStore(redis, l1_maxsize=8, l1_ttl_seconds=30.0, l2_ttl_seconds=3600)

    scope = _sample_scope()
    await store.set("session-2", scope)

    store.evict_l1("session-2")

    results = await asyncio.gather(*(store.get("session-2") for _ in range(5)))

    assert results == [scope] * 5
    assert redis.get_calls == 1
    assert store.metrics.l2_hits == 1
    assert store.metrics.l2_misses == 0

    await store.close()


@pytest.mark.asyncio
async def test_scope_store_delete_clears_l1_and_l2() -> None:
    redis = FakeRedis()
    store = ScopeStore(redis, l1_maxsize=8, l1_ttl_seconds=30.0, l2_ttl_seconds=3600)

    scope = _sample_scope()
    await store.set("session-3", scope)
    await store.delete("session-3")

    assert store.metrics.l1_hits == 0
    assert await store.get("session-3") is None
    assert not redis.contains("scope:session-3")

    await store.close()


@pytest.mark.asyncio
async def test_scope_store_without_l2_ttl_uses_set() -> None:
    redis = FakeRedis()
    store = ScopeStore(redis, l1_maxsize=8, l1_ttl_seconds=30.0, l2_ttl_seconds=None)

    await store.set("session-4", _sample_scope())

    assert redis.set_calls == 1
    assert not redis.setex_calls

    await store.close()


@pytest.mark.asyncio
async def test_async_single_flight_coalesces_calls() -> None:
    flight: AsyncSingleFlight[str, int] = AsyncSingleFlight()
    call_count = 0

    async def expensive_call() -> int:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.01)
        return 42

    results = await asyncio.gather(
        *[flight.do("scope", expensive_call) for _ in range(10)]
    )

    assert all(result == 42 for result in results)
    assert call_count == 1


@pytest.mark.asyncio
async def test_async_single_flight_propagates_exceptions_and_allows_retry() -> None:
    flight: AsyncSingleFlight[str, int] = AsyncSingleFlight()
    call_count = 0

    async def failing_call() -> int:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0)
        message = "boom"
        raise RuntimeError(message)

    with pytest.raises(RuntimeError):
        await asyncio.gather(
            flight.do("scope", failing_call), flight.do("scope", failing_call)
        )

    assert call_count == 1

    async def succeeding_call() -> int:
        await asyncio.sleep(0)
        return 7

    result = await flight.do("scope", succeeding_call)
    assert result == 7
