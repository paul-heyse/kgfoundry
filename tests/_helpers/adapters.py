"""In-memory adapter implementations for tests (Git, scope store, FAISS, etc.)."""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import tempfile
from typing import Any


@dataclass(slots=True)
class _Author:
    """Simple author representation used by in-memory commits."""

    name: str
    email: str


@dataclass(slots=True)
class InMemoryCommit:
    """Light-weight commit object mimicking GitPython attributes."""

    hexsha: str
    author_name: str = "Test Author"
    author_email: str = "test@example.com"
    summary: str = "Test commit"
    authored_datetime: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def author(self) -> _Author:
        """Return author object with name and email.

        Returns
        -------
        _Author
            Author object with name and email attributes.
        """
        return _Author(self.author_name, self.author_email)


class InMemoryGitRepo:
    """Minimal GitPython-compatible repository used in tests."""

    def __init__(
        self,
        *,
        blame_map: dict[str, list[tuple[object, Sequence[int]]]] | None = None,
        history_map: dict[str, list[object]] | None = None,
    ) -> None:
        self.git_dir = Path(tempfile.gettempdir()) / "git" / ".git"
        self._blame_map = blame_map or {}
        self._history_map = history_map or {}
        self._blame_errors: dict[str, Exception] = {}
        self._history_errors: dict[str, Exception] = {}

    def set_blame_result(
        self,
        path: str,
        entries: list[tuple[object, Sequence[int]]],
    ) -> None:
        """Configure blame result for a file path.

        Parameters
        ----------
        path : str
            File path to configure blame for.
        entries : list[tuple[object, Sequence[int]]]
            List of (commit, line_numbers) tuples to return for blame.
        """
        self._blame_map[path] = entries

    def set_history(self, path: str, commits: list[object]) -> None:
        """Configure commit history for a file path.

        Parameters
        ----------
        path : str
            File path to configure history for.
        commits : list[object]
            List of commit objects to return for history.
        """
        self._history_map[path] = commits

    def set_blame_error(self, path: str, exc: Exception) -> None:
        """Configure exception to raise for blame on a file path.

        Parameters
        ----------
        path : str
            File path to configure error for.
        exc : Exception
            Exception to raise when blame is called for this path.
        """
        self._blame_errors[path] = exc

    def set_history_error(self, path: str, exc: Exception) -> None:
        """Configure exception to raise for history on a file path.

        Parameters
        ----------
        path : str
            File path to configure error for.
        exc : Exception
            Exception to raise when history is called for this path.
        """
        self._history_errors[path] = exc

    # GitPython API surface -------------------------------------------------
    def blame_incremental(
        self, path: str, *_: object, **__: object
    ) -> Iterable[tuple[object, Sequence[int]]]:
        """Return blame entries for a file path or raise configured error.

        Parameters
        ----------
        path : str
            File path to get blame for.
        *_ : Any
            Additional positional arguments (ignored).
        **__ : Any
            Additional keyword arguments (ignored).

        Returns
        -------
        Iterable[tuple[object, Sequence[int]]]
            List of (commit, line_numbers) tuples.

        Notes
        -----
        If set_blame_error was called for this path, raises the configured exception.
        """
        if path in self._blame_errors:
            raise self._blame_errors[path]
        return list(self._blame_map.get(path, []))

    def iter_commits(
        self,
        rev: str = "HEAD",
        paths: str | Sequence[str] | None = None,
        max_count: int | None = None,
        **__: object,
    ) -> Iterable[object]:
        """Iterate over commits for specified paths or raise configured error.

        Parameters
        ----------
        rev : str, optional
            Revision to iterate (ignored, defaults to "HEAD").
        paths : str | Sequence[str] | None, optional
            File path(s) to get commits for, by default None.
        max_count : int | None, optional
            Maximum number of commits to return, by default None.
        **__ : Any
            Additional keyword arguments (ignored).

        Returns
        -------
        Iterable[object]
            List of commit objects from configured history.

        Notes
        -----
        If set_history_error was called for any of the paths, raises the configured exception.
        """
        _ = rev
        key = (paths[0] if paths else None) if isinstance(paths, (list, tuple)) else paths
        path_key = key or ""
        if path_key in self._history_errors:
            raise self._history_errors[path_key]
        commits = list(self._history_map.get(path_key, []))
        if max_count is not None:
            commits = commits[:max_count]
        return commits


class RecordingRepoFactory:
    """Callable factory that records invocations for assertions."""

    def __init__(self, repo: InMemoryGitRepo | object) -> None:
        self.repo = repo
        self.calls = 0
        self.side_effect: Exception | None = None

    def __call__(self, repo_path: Path) -> object:
        self.calls += 1
        _ = repo_path
        if self.side_effect is not None:
            raise self.side_effect
        return self.repo


class InMemoryScopeStore:
    """Async key-value store mimicking Redis behavior for scopes."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, float | None]] = {}

    async def get(self, name: str) -> bytes | None:
        """Get value by key, returning None if expired or missing.

        Parameters
        ----------
        name : str
            Key to look up.

        Returns
        -------
        bytes | None
            Value associated with key, or None if expired or missing.
        """
        record = self._data.get(name)
        if record is None:
            return None
        value, expires_at = record
        if expires_at is not None and expires_at <= time.monotonic():
            self._data.pop(name, None)
            return None
        return value

    async def setex(self, name: str, time_seconds: int, value: bytes) -> bool | None:
        """Set value with expiration time.

        Parameters
        ----------
        name : str
            Key to store value under.
        time_seconds : int
            Expiration time in seconds (0 means no expiration).
        value : bytes
            Value to store.

        Returns
        -------
        bool | None
            True on success.
        """
        expires_at = time.monotonic() + time_seconds if time_seconds > 0 else None
        self._data[name] = (value, expires_at)
        return True

    async def set(self, name: str, value: bytes) -> bool | None:
        """Set value without expiration.

        Parameters
        ----------
        name : str
            Key to store value under.
        value : bytes
            Value to store.

        Returns
        -------
        bool | None
            True on success.
        """
        self._data[name] = (value, None)
        return True

    async def delete(self, *names: str) -> int | None:
        """Delete one or more keys, returning count of deleted keys.

        Parameters
        ----------
        *names : str
            One or more keys to delete.

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
        """Clear all stored entries.

        Notes
        -----
        This method clears the internal data dictionary, removing all stored
        key-value pairs and their expiration timestamps.
        """
        self._data.clear()

    def snapshot(self) -> dict[str, tuple[bytes, float | None]]:
        """Return a shallow copy of stored entries for assertions.

        Returns
        -------
        dict[str, tuple[bytes, float | None]]
            Shallow copy of internal data dictionary for test assertions.
        """
        return dict(self._data)


class _InMemoryFAISSRuntime:
    """FAISS runtime tuning stub."""

    def __init__(self) -> None:
        self._active: dict[str, Any] = {"nprobe": 32}

    def get_runtime_tuning(self) -> dict[str, Any]:
        """Return current runtime tuning parameters.

        Returns
        -------
        dict[str, Any]
            Dictionary with "active" key containing current tuning parameters.
        """
        return {"active": dict(self._active)}

    def set_runtime_tuning(self, params: dict[str, Any]) -> dict[str, Any]:
        """Update runtime tuning parameters.

        Parameters
        ----------
        params : dict[str, Any]
            Parameters to merge into active runtime tuning.

        Returns
        -------
        dict[str, Any]
            Updated tuning parameters dictionary.
        """
        self._active.update(params)
        return self.get_runtime_tuning()


class InMemoryFAISSManager:
    """Simple FAISS manager stub returning preset search results."""

    def __init__(self, results: list[Any] | None = None) -> None:
        self.autotune_profile_path = Path(tempfile.gettempdir()) / "faiss-autotune.json"
        self._results = results or []
        self.search_calls = 0
        self.runtime = _InMemoryFAISSRuntime()
        self.vec_dim = 128

    def search(self, *_: object, **__: object) -> list[Any]:
        """Return pre-configured search results and increment call counter.

        Parameters
        ----------
        *_ : Any
            Positional arguments (ignored).
        **__ : Any
            Keyword arguments (ignored).

        Returns
        -------
        list[Any]
            List of pre-configured search results.
        """
        self.search_calls += 1
        return self._results
