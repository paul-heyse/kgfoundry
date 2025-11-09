"""Filesystem utilities using pathlib for safe, typed operations.

This module provides helpers for directory management, file I/O, and path
operations using `pathlib.Path` exclusively. All functions are fully typed
and documented to replace legacy `os.path` usage.

Examples
--------
>>> from pathlib import Path
>>> from kgfoundry_common.fs import ensure_dir, read_text, write_text
>>> base = Path("/tmp/test")
>>> ensure_dir(base / "subdir")
>>> write_text(base / "file.txt", "content")
>>> content = read_text(base / "file.txt")
"""

# [nav:section public-api]

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Literal

from kgfoundry_common.logging import get_logger

logger = get_logger(__name__)


def ensure_dir(path: Path, *, exist_ok: bool = True) -> Path:
    """Create directory if it does not exist, including parent directories.

    Creates the specified directory path and all intermediate parent directories
    if they do not exist. Uses pathlib's mkdir with parents=True for atomic
    directory creation.

    Parameters
    ----------
    path : Path
        Directory path to create. May be absolute or relative.
    exist_ok : bool, optional
        If True, do not raise an exception if the directory already exists.
        Defaults to True.

    Returns
    -------
    Path
        The created or existing directory path (same as input).

    Notes
    -----
    This call delegates to :meth:`pathlib.Path.mkdir`. Filesystem-level errors
    such as ``PermissionError`` or ``FileExistsError`` propagate unchanged.

    Examples
    --------
    >>> from pathlib import Path
    >>> ensure_dir(Path("/tmp/data/subdir"))
    Path('/tmp/data/subdir')
    """
    path.mkdir(parents=True, exist_ok=exist_ok)
    return path


def safe_join(base: Path, *parts: str | Path) -> Path:
    """Join path components safely, preventing directory traversal.

    Joins path components relative to a base directory and validates that the
    resolved path does not escape the base directory. This prevents path
    traversal attacks by ensuring all resolved paths are within the base.

    Parameters
    ----------
    base : Path
        Base directory path. Must be absolute to enable validation.
    *parts : str | Path
        Relative path components to join. These are joined relative to base.

    Returns
    -------
    Path
        Resolved absolute path that is guaranteed to be within the base
        directory.

    Raises
    ------
    ValueError
        If base is not absolute or if the resolved path escapes the base
        directory (path traversal attempt).

    Examples
    --------
    >>> from pathlib import Path
    >>> base = Path("/safe/base")
    >>> safe_join(base, "file.txt")
    Path('/safe/base/file.txt')
    >>> safe_join(base, "..", "etc", "passwd")  # doctest: +SKIP
    ValueError: Path escapes base directory
    """
    if not base.is_absolute():
        msg = f"Base path must be absolute: {base}"
        raise ValueError(msg)
    resolved = (base / Path(*parts)).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        msg = f"Path escapes base directory: {resolved}"
        raise ValueError(msg) from exc
    return resolved


def read_text(path: Path, encoding: str = "utf-8") -> str:
    """Read text file contents with explicit encoding.

    Reads a text file and returns its contents as a string. Uses the specified
    encoding to decode bytes. This is a convenience wrapper around
    pathlib.Path.read_text().

    Parameters
    ----------
    path : Path
        File path to read. Must exist and be readable.
    encoding : str, optional
        Text encoding to use for decoding bytes. Defaults to "utf-8".

    Returns
    -------
    str
        File contents as a decoded string.

    Notes
    -----
    This helper delegates to :meth:`pathlib.Path.read_text`, so filesystem
    errors such as ``FileNotFoundError`` or ``PermissionError`` will surface
    unchanged.

    Examples
    --------
    >>> from pathlib import Path
    >>> write_text(Path("/tmp/test.txt"), "hello")
    >>> read_text(Path("/tmp/test.txt"))
    'hello'
    """
    return path.read_text(encoding=encoding)


def write_text(path: Path, data: str, encoding: str = "utf-8") -> None:
    """Write text data to a file, creating parent directories if needed.

    Writes text content to a file, encoding it using the specified encoding.
    Creates parent directories if they do not exist. Uses pathlib's write_text
    for atomic file operations.

    Parameters
    ----------
    path : Path
        File path to write. Parent directories will be created if needed.
    data : str
        Text content to write. Will be encoded using the specified encoding.
    encoding : str, optional
        Text encoding to use for encoding the string to bytes. Defaults to "utf-8".

    Notes
    -----
    Exceptions raised by :func:`ensure_dir` or :meth:`pathlib.Path.write_text`
    (for example ``OSError`` or ``PermissionError``) propagate to callers.

    Examples
    --------
    >>> from pathlib import Path
    >>> write_text(Path("/tmp/output.txt"), "content")
    >>> read_text(Path("/tmp/output.txt"))
    'content'
    """
    ensure_dir(path.parent, exist_ok=True)
    path.write_text(data, encoding=encoding)


def atomic_write(
    path: Path,
    data: str | bytes,
    mode: Literal["text", "binary"] = "text",
) -> None:
    """Write data atomically using a temporary file and rename.

    Writes data to a file using an atomic operation: first writes to a temporary
    file in the same directory, then renames it to the final path. This ensures
    that the final file is either completely written or not present, preventing
    partial writes in case of crashes.

    Parameters
    ----------
    path : Path
        Final file path to write. Parent directories will be created if needed.
    data : str | bytes
        Content to write. Must be str for text mode or bytes for binary mode.
    mode : Literal['text', 'binary'], optional
        Write mode. Use "text" for string data (UTF-8 encoding) or "binary"
        for bytes data. Defaults to "text".

    Raises
    ------
    ValueError
        If mode is "text" but data is bytes, or mode is "binary" but data is str.

    Notes
    -----
    Filesystem errors raised by :func:`ensure_dir`, :func:`tempfile.NamedTemporaryFile`,
    or :meth:`pathlib.Path.replace` propagate to the caller.

    Notes
    -----
    The atomic operation ensures that concurrent readers never see a partially
    written file. The temporary file is created in the same directory as the
    final path to ensure the rename operation succeeds (requires same filesystem).

    Examples
    --------
    >>> from pathlib import Path
    >>> atomic_write(Path("/tmp/atomic.txt"), "safe content")
    >>> read_text(Path("/tmp/atomic.txt"))
    'safe content'
    """
    ensure_dir(path.parent, exist_ok=True)
    tmp_path: Path | None = None
    try:
        dir_arg = str(path.parent) if path.parent else None
        if mode == "text":
            if not isinstance(data, str):
                msg = "text mode requires str data"
                raise ValueError(msg)
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=dir_arg,
                delete=False,
                encoding="utf-8",
            ) as temp_file:
                tmp_path = Path(temp_file.name)
                temp_file.write(data)
                temp_file.flush()
        else:
            if not isinstance(data, bytes):
                msg = "binary mode requires bytes data"
                raise ValueError(msg)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=dir_arg,
                delete=False,
            ) as temp_file:
                tmp_path = Path(temp_file.name)
                temp_file.write(data)
                temp_file.flush()
        if tmp_path is not None:
            tmp_path.replace(path)
    finally:
        if tmp_path is not None and sys.exc_info()[0] is not None:
            tmp_path.unlink(missing_ok=True)
