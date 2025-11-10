"""CodeIntel-specific exception hierarchy with Problem Details support.

This module defines domain-specific exceptions for CodeIntel MCP server operations.
All exceptions inherit from ``KgFoundryError`` and include automatic RFC 9457
Problem Details mapping with appropriate HTTP status codes and structured context.

The exception hierarchy is organized by operation category:

- **File Operations**: ``FileOperationError``, ``FileReadError``, ``InvalidLineRangeError``
- **Git Operations**: ``GitOperationError``
- **Search Operations**: Use ``VectorSearchError``, ``EmbeddingError`` from kgfoundry_common

Examples
--------
Raising file operation error:

>>> raise FileReadError("Binary file or encoding error", path="binary_file.png")

Raising invalid line range error with context:

>>> raise InvalidLineRangeError(
...     "start_line must be positive", path="src/main.py", line_range=(0, 10)
... )

Raising Git operation error:

>>> try:
...     git_client.blame_range(path, start, end)
... except git.exc.GitCommandError as exc:
...     raise GitOperationError("Git blame failed", path=path, git_command="blame") from exc
"""

from __future__ import annotations

from kgfoundry_common.errors import ErrorCode, KgFoundryError

# ==================== File Operation Errors ====================


class FileOperationError(KgFoundryError):
    """Base exception for file operation errors.

    Raised when file operations fail (read, validation, path resolution, etc.).
    Subclass this for specific file operation error types.

    This exception is appropriate for **user errors** (bad input, file not found,
    invalid parameters) and maps to 400 Bad Request.

    Parameters
    ----------
    message : str
        Human-readable error message explaining what went wrong.
    path : str
        File path that caused the error. Included in context for debugging.
    cause : Exception | None, optional
        Underlying exception that caused the file operation failure. Use
        ``raise ... from cause`` to preserve exception chain. Defaults to None.

    Examples
    --------
    >>> raise FileOperationError("Invalid file path", path="/etc/passwd")
    Traceback (most recent call last):
        ...
    FileOperationError[file-operation-error]: Invalid file path

    With cause chain:

    >>> try:
    ...     path.resolve(strict=True)
    ... except FileNotFoundError as exc:
    ...     raise FileOperationError("Path resolution failed", path=str(path)) from exc

    Notes
    -----
    HTTP Status: 400 Bad Request (user error)
    Error Code: "file-operation-error"
    Context: ``{"path": "<file_path>"}``
    """

    def __init__(
        self,
        message: str,
        path: str,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(
            message,
            code=ErrorCode.FILE_OPERATION_ERROR,
            http_status=400,
            context={"path": path},
            cause=cause,
        )


class FileReadError(FileOperationError):
    """Raised when file cannot be read due to encoding or binary content.

    This exception is raised when attempting to read a file that is binary
    (non-text) or has an unsupported encoding. It's appropriate for files that
    exist and are accessible, but cannot be decoded as UTF-8 text.

    Common causes:

    - Binary files (images, executables, archives)
    - Files with non-UTF-8 encoding (e.g., Latin-1, UTF-16)
    - Corrupted text files with invalid byte sequences

    Parameters
    ----------
    message : str
        Human-readable error message (e.g., "Binary file or encoding error").
    path : str
        File path that couldn't be read.
    cause : Exception | None, optional
        Underlying exception (typically ``UnicodeDecodeError``). Defaults to None.

    Examples
    --------
    Wrap UnicodeDecodeError:

    >>> try:
    ...     content = path.read_text(encoding="utf-8")
    ... except UnicodeDecodeError as exc:
    ...     raise FileReadError("Binary file or encoding error", path=str(path)) from exc

    Direct raise:

    >>> if path.suffix in {".png", ".jpg", ".pdf"}:
    ...     raise FileReadError("Binary file type not supported", path=str(path))

    Notes
    -----
    HTTP Status: 400 Bad Request (inherited from FileOperationError)
    Error Code: "file-operation-error" (inherited)
    Context: ``{"path": "<file_path>"}``

    The error handling decorator will map this to Problem Details with
    appropriate status and error code.
    """


class InvalidLineRangeError(FileOperationError):
    """Raised when line range parameters are invalid.

    This exception is raised when line range validation fails (negative line
    numbers, start > end, etc.). It provides structured context including the
    invalid line range for debugging.

    Parameters
    ----------
    message : str
        Human-readable error message explaining constraint violation.
        Examples: "start_line must be a positive integer",
        "end_line must be a positive integer",
        "start_line must be less than or equal to end_line".
    path : str
        File path being accessed.
    line_range : tuple[int | None, int | None] | None, optional
        Requested line range (start_line, end_line) for error context. Either
        or both values may be None if not provided. Defaults to None.

    Examples
    --------
    Negative start_line:

    >>> if start_line is not None and start_line <= 0:
    ...     raise InvalidLineRangeError(
    ...         "start_line must be a positive integer",
    ...         path="src/main.py",
    ...         line_range=(start_line, end_line),
    ...     )

    Start > end:

    >>> if start_line > end_line:
    ...     raise InvalidLineRangeError(
    ...         "start_line must be less than or equal to end_line",
    ...         path="src/main.py",
    ...         line_range=(start_line, end_line),
    ...     )

    Notes
    -----
    HTTP Status: 400 Bad Request (user error)
    Error Code: "invalid-parameter"
    Context: ``{"path": "<file_path>", "start_line": 0, "end_line": 10}``

    The line_range context is included in Problem Details extensions for
    debugging and client error messages.
    """

    def __init__(
        self,
        message: str,
        path: str,
        line_range: tuple[int | None, int | None] | None = None,
    ) -> None:
        context: dict[str, object] = {"path": path}
        if line_range is not None:
            context["start_line"] = line_range[0]
            context["end_line"] = line_range[1]

        # Override parent __init__ to add line_range to context
        # We call KgFoundryError.__init__ directly to customize error code
        KgFoundryError.__init__(
            self,
            message,
            code=ErrorCode.INVALID_PARAMETER,
            http_status=400,
            context=context,
        )


class PathNotFoundError(KgFoundryError):
    """Raised when a requested repository path does not exist."""

    def __init__(
        self,
        message: str,
        path: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(
            message,
            code=ErrorCode.PATH_NOT_FOUND,
            http_status=404,
            context={"path": path},
            cause=cause,
        )


class PathNotDirectoryError(KgFoundryError):
    """Raised when a repository path is expected to be a directory but is not."""

    def __init__(
        self,
        message: str,
        path: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(
            message,
            code=ErrorCode.PATH_NOT_DIRECTORY,
            http_status=400,
            context={"path": path},
            cause=cause,
        )


# ==================== Git Operation Errors ====================


class GitOperationError(KgFoundryError):
    """Base exception for Git operation errors.

    Raised when Git operations fail (blame, history, log, etc.). This is
    appropriate for **system errors** (Git command failed, repository corrupted,
    Git binary not found) and maps to 500 Internal Server Error.

    The exception includes optional path and Git command context for debugging.

    Parameters
    ----------
    message : str
        Human-readable error message explaining what went wrong.
    path : str | None, optional
        File path that was being operated on. Include this when the error is
        related to a specific file. Defaults to None.
    git_command : str | None, optional
        Git command that failed (e.g., "blame", "log", "show"). Helps identify
        which Git operation failed. Defaults to None.
    cause : Exception | None, optional
        Underlying exception (typically ``git.exc.GitCommandError``). Use
        ``raise ... from cause`` to preserve exception chain. Defaults to None.

    Examples
    --------
    Wrap GitCommandError from blame:

    >>> try:
    ...     git_client.blame_range(path, 1, 10)
    ... except git.exc.GitCommandError as exc:
    ...     raise GitOperationError(
    ...         "Git blame failed", path="src/main.py", git_command="blame"
    ...     ) from exc

    Wrap GitCommandError from log:

    >>> try:
    ...     git_client.file_history(path, limit=50)
    ... except git.exc.GitCommandError as exc:
    ...     raise GitOperationError(
    ...         "Git log failed", path="src/main.py", git_command="log"
    ...     ) from exc

    Repository-level error (no specific file):

    >>> if not repo_path.exists():
    ...     raise GitOperationError("Repository not found", path=None, git_command=None)

    Notes
    -----
    HTTP Status: 500 Internal Server Error (system error)
    Error Code: "git-operation-error"
    Context: ``{"path": "<file_path>", "git_command": "blame"}``

    Both path and git_command are optional in context (only included if provided).
    """

    def __init__(
        self,
        message: str,
        path: str | None = None,
        git_command: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        context: dict[str, object] = {}
        if path is not None:
            context["path"] = path
        if git_command is not None:
            context["git_command"] = git_command

        super().__init__(
            message,
            code=ErrorCode.GIT_OPERATION_ERROR,
            http_status=500,
            context=context,
            cause=cause,
        )


class RuntimeLifecycleError(KgFoundryError):
    """Raised when a runtime fails to initialize or shut down."""

    def __init__(
        self,
        message: str,
        *,
        runtime: str,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(
            message,
            code=ErrorCode.RUNTIME_ERROR,
            http_status=500,
            context={"runtime": runtime},
            cause=cause,
        )


class RuntimeUnavailableError(KgFoundryError):
    """Raised when a runtime dependency is missing or disabled."""

    def __init__(
        self,
        message: str,
        *,
        runtime: str,
        detail: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        context: dict[str, object] = {"runtime": runtime}
        if detail:
            context["detail"] = detail
        super().__init__(
            message,
            code=ErrorCode.RESOURCE_UNAVAILABLE,
            http_status=503,
            context=context,
            cause=cause,
        )


# ==================== Re-exports ====================

# Search operation errors are already defined in kgfoundry_common.errors.
# We don't redefine them here, but document them for reference.
#
# Available search exceptions:
# - VectorSearchError: Raised for FAISS search failures, index not ready, etc.
# - EmbeddingError: Raised for vLLM embedding generation failures
#
# Import from kgfoundry_common.errors:
#   VectorSearchError, EmbeddingError


__all__ = [
    "FileOperationError",
    "FileReadError",
    "GitOperationError",
    "InvalidLineRangeError",
    "PathNotDirectoryError",
    "PathNotFoundError",
    "RuntimeLifecycleError",
    "RuntimeUnavailableError",
]
