"""In-memory adapter implementations for tests (Git, scope store, FAISS, etc.)."""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
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
    authored_datetime: datetime = datetime.now(tz=UTC)

    @property
    def author(self) -> _Author:
        return _Author(self.author_name, self.author_email)


class InMemoryGitRepo:
    """Minimal GitPython-compatible repository used in tests."""

    def __init__(
        self,
        *,
        blame_map: dict[str, list[tuple[object, Sequence[int]]]] | None = None,
        history_map: dict[str, list[object]] | None = None,
    ) -> None:
        self.git_dir = Path("/tmp/git/.git")
        self._blame_map = blame_map or {}
        self._history_map = history_map or {}
        self._blame_errors: dict[str, Exception] = {}
        self._history_errors: dict[str, Exception] = {}

    def set_blame_result(
        self,
        path: str,
        entries: list[tuple[object, Sequence[int]]],
    ) -> None:
        self._blame_map[path] = entries

    def set_history(self, path: str, commits: list[object]) -> None:
        self._history_map[path] = commits

    def set_blame_error(self, path: str, exc: Exception) -> None:
        self._blame_errors[path] = exc

    def set_history_error(self, path: str, exc: Exception) -> None:
        self._history_errors[path] = exc

    # GitPython API surface -------------------------------------------------
    def blame_incremental(self, path: str, *_: Any, **__: Any) -> Iterable[tuple[object, Sequence[int]]]:
        if path in self._blame_errors:
            raise self._blame_errors[path]
        return list(self._blame_map.get(path, []))

    def iter_commits(
        self,
        rev: str = "HEAD",
        paths: str | Sequence[str] | None = None,
        max_count: int | None = None,
        **__: Any,
    ) -> Iterable[object]:
        _ = rev
        key: str | None
        if isinstance(paths, (list, tuple)):
            key = paths[0] if paths else None
        else:
            key = paths
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
        record = self._data.get(name)
        if record is None:
            return None
        value, expires_at = record
        if expires_at is not None and expires_at <= time.monotonic():
            self._data.pop(name, None)
            return None
        return value

    async def setex(self, name: str, time_seconds: int, value: bytes) -> bool | None:
        expires_at = time.monotonic() + time_seconds if time_seconds > 0 else None
        self._data[name] = (value, expires_at)
        return True

    async def set(self, name: str, value: bytes) -> bool | None:
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

    def snapshot(self) -> dict[str, tuple[bytes, float | None]]:
        """Return a shallow copy of stored entries for assertions."""
        return dict(self._data)


class _InMemoryFAISSRuntime:
    """FAISS runtime tuning stub."""

    def __init__(self) -> None:
        self._active: dict[str, Any] = {"nprobe": 32}

    def get_runtime_tuning(self) -> dict[str, Any]:
        return {"active": dict(self._active)}

    def set_runtime_tuning(self, params: dict[str, Any]) -> dict[str, Any]:
        self._active.update(params)
        return self.get_runtime_tuning()


class InMemoryFAISSManager:
    """Simple FAISS manager stub returning preset search results."""

    def __init__(self, results: list[Any] | None = None) -> None:
        self.autotune_profile_path = Path("/tmp/faiss-autotune.json")
        self._results = results or []
        self.search_calls = 0
        self.runtime = _InMemoryFAISSRuntime()
        self.vec_dim = 128

    def search(self, *_: Any, **__: Any) -> list[Any]:
        self.search_calls += 1
        return self._results
