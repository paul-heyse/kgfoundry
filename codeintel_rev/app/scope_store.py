"""Scope store utilities for session state management."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable, Iterator, MutableMapping
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Any, Protocol, cast

import msgspec

if TYPE_CHECKING:
    from codeintel_rev.mcp_server.schemas import ScopeIn as ScopeMapping
else:
    ScopeMapping = dict[str, Any]

ScopeIn = ScopeMapping


class SupportsAsyncRedis(Protocol):
    """Protocol describing the Redis operations required by ``ScopeStore``."""

    async def get(self, name: str) -> bytes | None:
        """Retrieve a value by ``key``."""

    async def setex(self, name: str, time: int, value: bytes) -> bool | None:
        """Set ``key`` to ``value`` with the provided TTL in seconds."""

    async def set(self, name: str, value: bytes) -> bool | None:
        """Set ``key`` to ``value`` without TTL semantics."""

    async def delete(self, *names: str) -> int | None:
        """Delete ``key`` if present."""

    async def close(self) -> None:
        """Close open Redis connections."""


@dataclass(slots=True, frozen=True)
class _CacheRecord[ValueT]:
    """Internal cache record containing a value and its insertion timestamp."""

    value: ValueT
    inserted_at: float


class LRUCache[KeyT: Hashable, ValueT]:
    """Thread-safe least-recently-used cache with TTL-based eviction.

    Parameters
    ----------
    maxsize : int, optional
        Maximum number of entries to retain. Must be positive.
    ttl_seconds : float | None, optional
        Time-to-live for each entry in seconds. When ``None``, entries never
        expire due to age.
    now_fn : Callable[[], float], optional
        Injectable monotonic time source, primarily for testing. Defaults to
        ``time.monotonic``.

    Raises
    ------
    ValueError
        If ``maxsize`` is not positive or if ``ttl_seconds`` is provided but
        not positive (when not ``None``).
    """

    def __init__(
        self,
        maxsize: int = 256,
        ttl_seconds: float | None = 300.0,
        *,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if maxsize <= 0:
            msg = f"maxsize must be positive, got {maxsize}"
            raise ValueError(msg)

        if ttl_seconds is not None and ttl_seconds <= 0:
            msg = f"ttl_seconds must be positive or None, got {ttl_seconds}"
            raise ValueError(msg)

        self._maxsize = maxsize
        self._ttl_seconds = ttl_seconds
        self._now = now_fn
        self._lock = RLock()
        self._store: OrderedDict[KeyT, _CacheRecord[ValueT]] = OrderedDict()

    def get(self, key: KeyT) -> ValueT | None:
        """
        Return the cached value for ``key`` or ``None`` if it is missing or stale.

        Parameters
        ----------
        key : KeyT
            Cache key to retrieve.

        Returns
        -------
        ValueT | None
            Cached value when present and not expired; otherwise ``None``.
        """
        with self._lock:
            record = self._store.get(key)
            if record is None:
                return None

            if self._is_expired(record):
                self._store.pop(key, None)
                return None

            self._store.move_to_end(key, last=True)
            return record.value

    def set(self, key: KeyT, value: ValueT) -> None:
        """Insert or update ``key`` with ``value`` and refresh its recency."""
        with self._lock:
            if key in self._store:
                self._store.pop(key, None)

            self._store[key] = _CacheRecord(value=value, inserted_at=self._now())
            self._enforce_size()

    def delete(self, key: KeyT) -> None:
        """Remove ``key`` from the cache if present."""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries from the cache."""
        with self._lock:
            self._store.clear()

    def __contains__(self, key: object) -> bool:
        """
        Return ``True`` when ``key`` is present and not expired.

        Parameters
        ----------
        key : object
            Candidate cache key.

        Returns
        -------
        bool
            ``True`` if the key exists and has not expired; otherwise ``False``.
        """
        with self._lock:
            if not isinstance(key, Hashable) or key not in self._store:
                return False

            typed_key = cast("KeyT", key)
            record = self._store.get(typed_key)
            if record is None:
                return False

            if self._is_expired(record):
                self._store.pop(typed_key, None)
                return False

            return True

    def __len__(self) -> int:
        """
        Return the number of live entries in the cache.

        Returns
        -------
        int
            Count of entries that have not expired.
        """
        with self._lock:
            self._purge_expired_entries()
            return len(self._store)

    def items(self) -> Iterator[tuple[KeyT, ValueT]]:
        """
        Yield current cache entries, purging expired ones as needed.

        Yields
        ------
        tuple[KeyT, ValueT]
            Key-value pairs for each live cache entry in LRU order.
        """
        with self._lock:
            for key in list(self._store.keys()):
                record = self._store.get(key)
                if record is None or self._is_expired(record):
                    self._store.pop(key, None)
                    continue
                yield key, record.value

    def snapshot(self) -> MutableMapping[KeyT, ValueT]:
        """
        Return a shallow copy of the cache contents.

        Returns
        -------
        MutableMapping[KeyT, ValueT]
            Ordered mapping containing live cache entries.
        """
        with self._lock:
            self._purge_expired_entries()
            return OrderedDict((key, record.value) for key, record in self._store.items())

    def _enforce_size(self) -> None:
        while len(self._store) > self._maxsize:
            self._store.popitem(last=False)

    def _purge_expired_entries(self) -> None:
        if self._ttl_seconds is None:
            return

        now = self._now()
        expired_keys = [
            key for key, record in self._store.items() if self._has_expired(record.inserted_at, now)
        ]
        for key in expired_keys:
            self._store.pop(key, None)

    def _is_expired(self, record: _CacheRecord[ValueT]) -> bool:
        if self._ttl_seconds is None:
            return False
        return self._has_expired(record.inserted_at, self._now())

    def _has_expired(self, inserted_at: float, now: float) -> bool:
        if self._ttl_seconds is None:
            return False
        return now - inserted_at >= self._ttl_seconds


class AsyncSingleFlight[KeyT: Hashable, ValueT]:
    """Deduplicate concurrent coroutine execution keyed by ``KeyT``."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._inflight: dict[KeyT, asyncio.Future[ValueT]] = {}

    async def do(self, key: KeyT, fn: Callable[[], Awaitable[ValueT]]) -> ValueT:
        """
        Execute ``fn`` once for all concurrent callers associated with ``key``.

        Parameters
        ----------
        key : KeyT
            Deduplication key.
        fn : Callable[[], Awaitable[ValueT]]
            Awaitable factory executed at most once while in-flight for ``key``.

        Returns
        -------
        ValueT
            Result produced by ``fn``.
        """
        async with self._lock:
            inflight = self._inflight.get(key)
            if inflight is None:
                inflight = asyncio.create_task(self._execute(key, fn))
                self._inflight[key] = inflight

        return await asyncio.shield(inflight)

    async def _execute(self, key: KeyT, fn: Callable[[], Awaitable[ValueT]]) -> ValueT:
        try:
            return await fn()
        finally:
            async with self._lock:
                self._inflight.pop(key, None)


@dataclass(slots=True, frozen=True)
class ScopeStoreMetrics:
    """Runtime counters describing scope store cache performance."""

    l1_hits: int = 0
    l1_misses: int = 0
    l2_hits: int = 0
    l2_misses: int = 0

    def record_l1_hit(self) -> None:
        """Increment the L1 hit counter."""
        self.l1_hits += 1

    def record_l1_miss(self) -> None:
        """Increment the L1 miss counter."""
        self.l1_misses += 1

    def record_l2_hit(self) -> None:
        """Increment the L2 hit counter."""
        self.l2_hits += 1

    def record_l2_miss(self) -> None:
        """Increment the L2 miss counter."""
        self.l2_misses += 1

    @property
    def l1_hit_rate(self) -> float:
        """Return the L1 hit rate as a floating point ratio."""
        total = self.l1_hits + self.l1_misses
        return self.l1_hits / total if total else 0.0

    @property
    def l2_hit_rate(self) -> float:
        """Return the L2 hit rate as a floating point ratio."""
        total = self.l2_hits + self.l2_misses
        return self.l2_hits / total if total else 0.0

    def as_dict(self) -> dict[str, float | int]:
        """
        Return a serialisable snapshot of the metrics.

        Returns
        -------
        dict[str, float | int]
            Dictionary containing counters and hit rates.
        """
        return {
            "l1_hits": self.l1_hits,
            "l1_misses": self.l1_misses,
            "l1_hit_rate": self.l1_hit_rate,
            "l2_hits": self.l2_hits,
            "l2_misses": self.l2_misses,
            "l2_hit_rate": self.l2_hit_rate,
        }


class ScopeStore:
    """Redis-backed scope store with L1/L2 caching and single-flight coalescing."""

    def __init__(
        self,
        redis_client: SupportsAsyncRedis,
        *,
        l1_maxsize: int = 256,
        l1_ttl_seconds: float | None = 300.0,
        l2_ttl_seconds: int | None = 3600,
        key_prefix: str = "scope",
    ) -> None:
        if not key_prefix:
            msg = "key_prefix must be non-empty"
            raise ValueError(msg)

        self._redis = redis_client
        self._l1: LRUCache[str, ScopeIn] = LRUCache(maxsize=l1_maxsize, ttl_seconds=l1_ttl_seconds)
        self._flight: AsyncSingleFlight[str, ScopeIn | None] = AsyncSingleFlight()
        self._metrics = ScopeStoreMetrics()
        self._l2_ttl_seconds = l2_ttl_seconds
        self._key_prefix = key_prefix

    @property
    def metrics(self) -> ScopeStoreMetrics:
        """Return live cache metrics."""
        return self._metrics

    async def get(self, session_id: str) -> ScopeIn | None:
        """
        Retrieve scope for ``session_id``, favouring the L1 cache.

        Parameters
        ----------
        session_id : str
            Session identifier to retrieve.

        Returns
        -------
        ScopeIn | None
            Scope data when present; otherwise ``None``.

        Raises
        ------
        ValueError
            If ``session_id`` is empty.
        """
        if not session_id:
            msg = "session_id must be non-empty"
            raise ValueError(msg)

        cached = self._l1.get(session_id)
        if cached is not None:
            self._metrics.record_l1_hit()
            return cached

        self._metrics.record_l1_miss()
        return await self._flight.do(session_id, lambda: self._fetch_from_l2(session_id))

    async def set(self, session_id: str, scope: ScopeIn) -> None:
        """
        Persist scope for ``session_id`` in both caches.

        Parameters
        ----------
        session_id : str
            Session identifier to update.
        scope : ScopeIn
            Scope payload to cache.

        Raises
        ------
        ValueError
            If ``session_id`` is empty.
        """
        if not session_id:
            msg = "session_id must be non-empty"
            raise ValueError(msg)

        scope_copy = dict(scope)
        self._l1.set(session_id, cast("ScopeIn", scope_copy))

        key = self._redis_key(session_id)
        payload = msgspec.json.encode(scope_copy)

        if self._l2_ttl_seconds is None:
            await self._redis.set(key, payload)
        elif self._l2_ttl_seconds > 0:
            await self._redis.setex(key, self._l2_ttl_seconds, payload)
        else:
            await self._redis.delete(key)

    async def delete(self, session_id: str) -> None:
        """
        Remove cached scope for ``session_id`` from both layers.

        Parameters
        ----------
        session_id : str
            Session identifier to remove.

        Raises
        ------
        ValueError
            If ``session_id`` is empty.
        """
        if not session_id:
            msg = "session_id must be non-empty"
            raise ValueError(msg)

        self._l1.delete(session_id)
        await self._redis.delete(self._redis_key(session_id))

    def evict_l1(self, session_id: str) -> None:
        """
        Remove ``session_id`` from the L1 cache only.

        Parameters
        ----------
        session_id : str
            Session identifier to evict.

        Raises
        ------
        ValueError
            If ``session_id`` is empty.
        """
        if not session_id:
            msg = "session_id must be non-empty"
            raise ValueError(msg)

        self._l1.delete(session_id)

    async def close(self) -> None:
        """Close underlying Redis resources."""
        await self._redis.close()

    def _redis_key(self, session_id: str) -> str:
        return f"{self._key_prefix}:{session_id}"

    async def _fetch_from_l2(self, session_id: str) -> ScopeIn | None:
        key = self._redis_key(session_id)
        data = await self._redis.get(key)

        if data is None:
            self._metrics.record_l2_miss()
            return None

        try:
            scope = cast("ScopeIn", msgspec.json.decode(data, type=dict[str, Any]))
        except msgspec.DecodeError:
            self._metrics.record_l2_miss()
            await self._redis.delete(key)
            return None

        self._metrics.record_l2_hit()
        self._l1.set(session_id, scope)
        return scope


__all__ = ["AsyncSingleFlight", "LRUCache", "ScopeStore", "ScopeStoreMetrics"]
