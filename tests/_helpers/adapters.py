"""In-memory adapter implementations for tests (Git, scope store, FAISS, etc.)."""

from __future__ import annotations

import asyncio
import tempfile
import time as time_module
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from threading import Lock
from typing import Any, cast

import git


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

        Returns
        -------
        Iterable[tuple[object, Sequence[int]]]
            List of (commit, line_numbers) tuples.

        Raises
        ------
        Exception
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

        Raises
        ------
        Exception
            If set_history_error was called for any of the paths, raises the configured exception.
        """
        _ = rev
        key: str | None = None
        if isinstance(paths, (list, tuple)):
            candidate = paths[0] if paths else None
            key = candidate if isinstance(candidate, str) else str(candidate) if candidate else None
        elif isinstance(paths, str):
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

    def __init__(self, repo: git.Repo) -> None:
        self.repo: git.Repo = repo
        self.calls = 0
        self.side_effect: Exception | None = None

    def __call__(self, repo_path: Path) -> git.Repo:
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
        if expires_at is not None and expires_at <= time_module.monotonic():
            self._data.pop(name, None)
            return None
        return value

    async def setex(self, name: str, time: int, value: bytes) -> bool | None:
        """Set value with expiration time.

        Parameters
        ----------
        name : str
            Key to store value under.
        time : int
            Expiration time in seconds (0 means no expiration).
        value : bytes
            Value to store.

        Returns
        -------
        bool | None
            True on success.
        """
        expires_at = time_module.monotonic() + time if time > 0 else None
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
        self.search_side_effect: Exception | None = None

    def search(self, *_: object, **__: object) -> list[Any]:
        """Return pre-configured search results and increment call counter.

        Returns
        -------
        list[Any]
            List of pre-configured search results.

        Raises
        ------
        Exception
            If search_side_effect is set, raises the configured exception.
        """
        self.search_calls += 1
        if self.search_side_effect is not None:
            raise self.search_side_effect
        return self._results


# ---------------------- Files + History adapter fakes ---------------------- #


@dataclass(slots=True)
class _FileRecord:
    """Internal file record for in-memory adapters."""

    content: bytes
    mtime: float

    @property
    def size(self) -> int:
        return len(self.content)


class InMemoryFileAdapter:
    """In-memory file adapter with deterministic metadata and tracking."""

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or Path("/")
        self._files: dict[str, _FileRecord] = {}
        self.read_calls = 0
        self.list_calls = 0
        self.write_calls = 0
        self._lock = Lock()

    def add_file(self, rel_path: str, content: str | bytes, *, mtime: float | None = None) -> None:
        """Insert or overwrite a file."""
        payload = content.encode("utf-8") if isinstance(content, str) else content
        record = _FileRecord(content=payload, mtime=mtime or time_module.time())
        with self._lock:
            self._files[rel_path] = record

    def read_file(
        self,
        rel_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, object]:
        """Return file content and metadata.

        Parameters
        ----------
        rel_path : str
            Relative file path to read.
        start_line : int | None, optional
            Optional starting line number (1-indexed) for partial file reads.
        end_line : int | None, optional
            Optional ending line number (1-indexed) for partial file reads.

        Returns
        -------
        dict[str, object]
            Mapping containing path, content, lines, size, and mtime.

        Raises
        ------
        FileNotFoundError
            If the requested path is not present in the in-memory store.
        """
        with self._lock:
            record = self._files.get(rel_path)
        if record is None:
            message = f"File not found: {rel_path}"
            raise FileNotFoundError(message)
        self.read_calls += 1
        text = record.content.decode("utf-8", errors="ignore")
        lines = text.splitlines()
        if start_line is not None or end_line is not None:
            start = start_line - 1 if start_line and start_line > 0 else 0
            stop = end_line if end_line and end_line > 0 else len(lines)
            lines = lines[start:stop]
        sliced_text = "\n".join(lines)
        return {
            "path": rel_path,
            "content": sliced_text,
            "lines": len(lines),
            "size": record.size,
            "mtime": record.mtime,
        }

    def list_paths(
        self,
        *,
        root: str | None = None,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, object]]:
        """Return metadata for files matching glob/language filters.

        Parameters
        ----------
        root : str | None, optional
            Optional root directory prefix to filter paths.
        include_globs : list[str] | None, optional
            Optional list of glob patterns to include.
        exclude_globs : list[str] | None, optional
            Optional list of glob patterns to exclude.
        max_results : int | None, optional
            Optional maximum number of results to return.

        Returns
        -------
        list[dict[str, object]]
            List of file metadata dictionaries with path, size, and mtime.
        """
        root_prefix = f"{root.rstrip('/')}/" if root else ""
        include = include_globs or ["**"]
        exclude = exclude_globs or []
        results: list[dict[str, object]] = []
        with self._lock:
            items = list(self._files.items())
        for rel_path, record in items:
            if root and not rel_path.startswith(root_prefix):
                continue
            rel = rel_path if not root_prefix else rel_path[len(root_prefix) :]
            if not any(fnmatch(rel_path, pattern) or fnmatch(rel, pattern) for pattern in include):
                continue
            if any(fnmatch(rel_path, pattern) or fnmatch(rel, pattern) for pattern in exclude):
                continue
            results.append(
                {
                    "path": rel_path,
                    "size": record.size,
                    "mtime": record.mtime,
                }
            )
            if max_results is not None and len(results) >= max_results:
                break
        self.list_calls += 1
        return results

    def write_file(self, rel_path: str, content: str | bytes) -> None:
        """Write file content and update metadata."""
        self.add_file(rel_path, content)
        self.write_calls += 1


class InMemoryAsyncFileAdapter:
    """Async wrapper around InMemoryFileAdapter."""

    def __init__(self, file_adapter: InMemoryFileAdapter | None = None) -> None:
        self._file_adapter = file_adapter or InMemoryFileAdapter()

    async def list_paths(
        self,
        *,
        root: str | None = None,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, object]]:
        return self._file_adapter.list_paths(
            root=root,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            max_results=max_results,
        )

    async def read_file(
        self,
        rel_path: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, object]:
        return self._file_adapter.read_file(rel_path, start_line=start_line, end_line=end_line)

    async def write_file(self, rel_path: str, content: str | bytes) -> None:
        self._file_adapter.write_file(rel_path, content)

    @property
    def file_adapter(self) -> InMemoryFileAdapter:
        return self._file_adapter


class InMemoryHistoryAdapter:
    """Async history adapter backed by InMemoryGitRepo."""

    def __init__(self, repo: InMemoryGitRepo | None = None, delay_seconds: float = 0.0) -> None:
        self.repo = repo or InMemoryGitRepo()
        self.blame_calls = 0
        self.history_calls = 0
        self.delay_seconds = delay_seconds

    async def blame_range(
        self,
        *,
        path: str,
        start_line: int,
        end_line: int,
    ) -> list[dict[str, object]]:
        self.blame_calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        entries = self.repo.blame_incremental(path)
        results: list[dict[str, object]] = []
        for commit, lines in entries:
            if not isinstance(commit, InMemoryCommit):
                continue
            for line in lines:
                if line < start_line or line > end_line:
                    continue
                results.append(
                    {
                        "line": line,
                        "author": commit.author_name,
                        "email": commit.author_email,
                        "sha": commit.hexsha[:7],
                        "date": commit.authored_datetime.isoformat(),
                        "message": commit.summary,
                    }
                )
        return results

    async def file_history(self, *, path: str, limit: int) -> list[dict[str, object]]:
        self.history_calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        commits = list(self.repo.iter_commits(paths=path, max_count=limit))
        results: list[dict[str, object]] = []
        for commit in commits:
            if not isinstance(commit, InMemoryCommit):
                continue
            results.append(
                {
                    "sha": commit.hexsha[:7],
                    "full_sha": commit.hexsha,
                    "author": commit.author_name,
                    "email": commit.author_email,
                    "date": commit.authored_datetime.isoformat(),
                    "message": commit.summary,
                }
            )
        return results

    def set_history(self, path: str, commits: list[InMemoryCommit]) -> None:
        """Set commit history for a file path."""
        self.repo.set_history(path, cast("list[object]", commits))

    def set_blame(self, path: str, blame: list[tuple[InMemoryCommit, Sequence[int]]]) -> None:
        """Set blame mapping for a file path."""
        self.repo.set_blame_result(path, cast("list[tuple[object, Sequence[int]]]", blame))
