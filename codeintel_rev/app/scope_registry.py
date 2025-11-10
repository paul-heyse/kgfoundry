"""Session-scoped scope registry for CodeIntel MCP (legacy helper).

This helper predates the Redis-backed :mod:`codeintel_rev.app.scope_store` that
ApplicationContext wires up automatically today. The registry is still available
for standalone tooling, but production adapters should use ``context.scope_store``
directly rather than mutating ``ApplicationContext``.

Key Components
--------------
ScopeRegistry : class
    Thread-safe registry mapping session IDs to ScopeIn dictionaries.

Design Principles
-----------------
- **Thread Safety**: Uses threading.RLock for concurrent access protection
- **LRU Behavior**: Updates timestamps on access for activity-based expiration
- **Immutable Results**: Returns copies of stored scopes to prevent mutation
- **Fail-Safe**: Missing sessions return None rather than raising exceptions

Example Usage
--------------
Initialize registry manually (e.g., in a short-lived script). When running the
full FastAPI app, use ``ApplicationContext.scope_store`` instead—application
contexts are frozen and cannot be reassigned after creation.

>>> registry = ScopeRegistry()
>>> registry.set_scope("session", {"languages": ["python"]})

Store scope for a session:

>>> session_id = "abc123..."
>>> scope = {"languages": ["python"], "include_globs": ["src/**"]}
>>> registry.set_scope(session_id, scope)

Retrieve scope in adapter:

>>> scope = registry.get_scope(session_id)
>>> if scope:
...     # Apply scope filters
...     include_globs = scope.get("include_globs")

Prune expired sessions (background task):

>>> pruned = registry.prune_expired(max_age_seconds=3600)
>>> logger.info(f"Pruned {pruned} expired sessions")

See Also
--------
codeintel_rev.app.middleware : Session ID extraction and ContextVar management
codeintel_rev.mcp_server.scope_utils : Scope merging and filtering utilities
"""

from __future__ import annotations

import time
from copy import deepcopy
from threading import RLock
from typing import TYPE_CHECKING, cast

from kgfoundry_common.logging import get_logger
from kgfoundry_common.prometheus import build_counter, build_gauge

if TYPE_CHECKING:
    from codeintel_rev.mcp_server.schemas import ScopeIn

LOGGER = get_logger(__name__)

# Prometheus metrics for scope management
_active_sessions_gauge = build_gauge(
    "codeintel_active_sessions",
    "Number of active sessions in scope registry",
)

_scope_operations_total = build_counter(
    "codeintel_scope_operations_total",
    "Total scope operations",
    ("operation",),
)


class ScopeRegistry:
    """Thread-safe registry for session-scoped query scopes.

    Maintains an in-memory mapping of session IDs to ScopeIn dictionaries with
    last-accessed timestamps for LRU expiration. Designed for concurrent access
    from FastAPI request handlers running in a threadpool.

    Notes
    -----
    The registry is NOT persistent—server restart clears all sessions. For
    persistent scope storage, consider Redis or database backing (Phase 3+).

    Performance characteristics:
    - set_scope: O(1) with lock acquisition overhead (~1μs)
    - get_scope: O(1) with lock acquisition + dict copy (~2μs)
    - prune_expired: O(n) where n = active session count

    Thread safety:
    - All public methods acquire _lock before dict access.
    - RLock prevents deadlocks when methods call each other.
    - ContextVar in middleware ensures session ID isolation across threads.

    Internal attributes (not part of public API):
    - ``_scopes``: Internal storage: {session_id: (scope, last_accessed_timestamp)}.
      Timestamps are from time.monotonic() for monotonic clock guarantees.
    - ``_lock``: Reentrant lock protecting dict operations. RLock allows same thread
      to acquire lock multiple times (e.g., set_scope calls _update_timestamp).

    Examples
    --------
    Create registry and store scope:

    >>> registry = ScopeRegistry()
    >>> session_id = "test-session-123"
    >>> scope = {"languages": ["python"], "include_globs": ["**/*.py"]}
    >>> registry.set_scope(session_id, scope)
    >>> retrieved = registry.get_scope(session_id)
    >>> retrieved == scope
    True

    Scope expiration:

    >>> import time
    >>> registry.set_scope("old-session", {"languages": ["python"]})
    >>> time.sleep(2)
    >>> pruned = registry.prune_expired(max_age_seconds=1)
    >>> pruned
    1
    >>> registry.get_scope("old-session") is None
    True
    """

    def __init__(self) -> None:
        self._scopes: dict[str, tuple[ScopeIn, float]] = {}
        self._lock = RLock()
        # Initialize metrics gauge to 0
        _active_sessions_gauge.set(0)
        LOGGER.info("Initialized ScopeRegistry with Prometheus metrics")

    def set_scope(self, session_id: str, scope: ScopeIn) -> None:
        """Store scope for session.

        Creates or updates session entry with current timestamp. If session
        already exists, overwrites previous scope (last-write-wins semantics).

        Parameters
        ----------
        session_id : str
            Unique session identifier (typically UUID from middleware).
        scope : ScopeIn
            Scope configuration to store. May contain repos, branches, globs,
            languages. Empty dict is valid (means "no filters").

        Examples
        --------
        >>> registry = ScopeRegistry()
        >>> registry.set_scope("session1", {"languages": ["python"]})
        >>> registry.set_scope("session2", {"include_globs": ["src/**"]})

        Notes
        -----
        The method stores a deep copy of the scope dict, preventing subsequent
        caller mutations from affecting the cached value. Callers may safely
        reuse or modify the original scope object after calling ``set_scope``.
        """
        timestamp = time.monotonic()
        is_new_session = False
        with self._lock:
            is_new_session = session_id not in self._scopes
            immutable_scope = cast("ScopeIn", deepcopy(scope))
            self._scopes[session_id] = (immutable_scope, timestamp)
            session_count = len(self._scopes)
            if is_new_session:
                # Update metrics while holding the lock to reflect the current registry state
                _active_sessions_gauge.set(session_count)

        _scope_operations_total.labels(operation="set").inc()

        LOGGER.info(
            "Set scope for session",
            extra={
                "session_id": session_id,
                "scope_fields": list(immutable_scope.keys()),
                "timestamp": timestamp,
            },
        )

    def get_scope(self, session_id: str) -> ScopeIn | None:
        """Retrieve scope for session.

        Returns a copy of the stored scope to prevent caller mutations from
        affecting registry state. Updates last-accessed timestamp for LRU
        tracking (accessed sessions are less likely to be pruned).

        Parameters
        ----------
        session_id : str
            Session identifier to look up.

        Returns
        -------
        ScopeIn | None
            Copy of stored scope if session exists, None otherwise.

        Examples
        --------
        >>> registry = ScopeRegistry()
        >>> registry.set_scope("session1", {"languages": ["python"]})
        >>> scope = registry.get_scope("session1")
        >>> scope
        {'languages': ['python']}
        >>> registry.get_scope("nonexistent") is None
        True

        Notes
        -----
        Returning None for missing sessions allows adapters to gracefully
        fall back to "no scope" behavior without catching exceptions.
        """
        timestamp = time.monotonic()
        with self._lock:
            entry = self._scopes.get(session_id)
            if entry is None:
                LOGGER.debug(
                    "Scope not found for session",
                    extra={"session_id": session_id},
                )
                return None

            scope, _old_timestamp = entry
            # Update timestamp (LRU tracking)
            self._scopes[session_id] = (scope, timestamp)

            # Return copy to prevent caller mutation
            # Cast is safe because scope is ScopeIn from _scopes dict
            scope_copy = cast("ScopeIn", deepcopy(scope))

            # Update metrics
            _scope_operations_total.labels(operation="get").inc()

            LOGGER.debug(
                "Retrieved scope for session",
                extra={
                    "session_id": session_id,
                    "scope_fields": list(scope_copy.keys()),
                },
            )
            return scope_copy

    def clear_scope(self, session_id: str) -> None:
        """Remove scope for session.

        Deletes session entry from registry. Subsequent get_scope calls for
        this session will return None. Clearing non-existent sessions is a
        no-op (does not raise exception).

        Parameters
        ----------
        session_id : str
            Session identifier to remove.

        Examples
        --------
        >>> registry = ScopeRegistry()
        >>> registry.set_scope("session1", {"languages": ["python"]})
        >>> registry.clear_scope("session1")
        >>> registry.get_scope("session1") is None
        True
        >>> registry.clear_scope("nonexistent")  # No error

        Notes
        -----
        This method is useful for explicit session cleanup (e.g., user logout).
        For automatic cleanup, use prune_expired() in a background task.
        """
        with self._lock:
            if session_id in self._scopes:
                del self._scopes[session_id]
                session_count = len(self._scopes)
                # Update metrics
                _active_sessions_gauge.set(session_count)
                _scope_operations_total.labels(operation="clear").inc()
                LOGGER.info(
                    "Cleared scope for session",
                    extra={"session_id": session_id},
                )
            else:
                LOGGER.debug(
                    "Attempted to clear nonexistent session",
                    extra={"session_id": session_id},
                )

    def prune_expired(self, max_age_seconds: int) -> int:
        """Remove sessions inactive for longer than max_age_seconds.

        Iterates all sessions and removes those whose last-accessed timestamp
        is older than threshold. This prevents memory leaks from abandoned
        sessions (e.g., clients that crash without cleanup).

        The method is designed to be called from a background task (e.g.,
        every 10 minutes) rather than on every request for performance.

        Parameters
        ----------
        max_age_seconds : int
            Inactivity threshold in seconds. Sessions with (current_time -
            last_accessed) > max_age_seconds are removed. Typical value: 3600
            (1 hour).

        Returns
        -------
        int
            Number of sessions pruned.

        Examples
        --------
        >>> registry = ScopeRegistry()
        >>> registry.set_scope("session1", {"languages": ["python"]})
        >>> import time
        >>> time.sleep(2)
        >>> pruned = registry.prune_expired(max_age_seconds=1)
        >>> pruned
        1
        >>> registry.get_scope("session1") is None
        True

        Notes
        -----
        Time measurement uses time.monotonic() to avoid issues with system
        clock adjustments (e.g., NTP corrections, daylight saving).

        For large session counts (>10K), consider incremental pruning: remove
        a fixed number of oldest sessions per invocation rather than iterating
        all sessions at once.
        """
        current_time = time.monotonic()
        pruned_count = 0

        with self._lock:
            # Identify expired sessions
            expired_sessions = [
                session_id
                for session_id, (_, timestamp) in self._scopes.items()
                if (current_time - timestamp) > max_age_seconds
            ]

            # Remove expired sessions
            for session_id in expired_sessions:
                del self._scopes[session_id]
                pruned_count += 1

            session_count = len(self._scopes)
            if pruned_count > 0:
                # Update metrics while holding the lock to reflect the current registry state
                _active_sessions_gauge.set(session_count)

        if pruned_count > 0:
            _scope_operations_total.labels(operation="prune").inc(pruned_count)
            LOGGER.info(
                "Pruned expired sessions",
                extra={
                    "pruned_count": pruned_count,
                    "max_age_seconds": max_age_seconds,
                    "remaining_sessions": session_count,
                },
            )
        else:
            LOGGER.debug(
                "No expired sessions to prune",
                extra={"max_age_seconds": max_age_seconds},
            )

        return pruned_count

    def get_session_count(self) -> int:
        """Return number of active sessions.

        Useful for monitoring and health checks. If count exceeds threshold
        (e.g., 10,000), it may indicate pruning failure or attack (session
        exhaustion).

        Returns
        -------
        int
            Number of sessions currently in registry.

        Examples
        --------
        >>> registry = ScopeRegistry()
        >>> registry.get_session_count()
        0
        >>> registry.set_scope("session1", {})
        >>> registry.set_scope("session2", {})
        >>> registry.get_session_count()
        2
        """
        with self._lock:
            return len(self._scopes)


__all__ = ["ScopeRegistry"]
