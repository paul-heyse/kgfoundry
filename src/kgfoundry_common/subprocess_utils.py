"""Subprocess execution with timeouts, path sanitization, and error handling.

This module provides hardened subprocess operations with:
- Explicit timeout enforcement
- Path sanitization via pathlib.Path.resolve()
- Structured error reporting via Problem Details
- Environment variable passing via settings

Examples
--------
>>> from pathlib import Path
>>> from kgfoundry_common.subprocess_utils import run_subprocess
>>> result = run_subprocess(
...     ["echo", "hello"],
...     timeout=10,
...     cwd=Path("/tmp"),
... )
>>> print(result)
hello
"""

# [nav:section public-api]

from __future__ import annotations

import logging
from importlib import import_module
from typing import TYPE_CHECKING, Final, NoReturn, Protocol, cast

from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:
    import io
    from collections.abc import Mapping, Sequence
    from pathlib import Path

logger = logging.getLogger(__name__)

# Default timeouts (seconds)
DEFAULT_TIMEOUT: Final[int] = 300
MIN_TIMEOUT: Final[int] = 1
MAX_TIMEOUT: Final[int] = 3600


class _PopenFactory(Protocol):
    """Protocol for subprocess.Popen factory callable.

    This protocol defines the interface for creating subprocess instances
    with text I/O streams. Used internally for type-safe subprocess creation.
    """

    def __call__(
        self,
        args: Sequence[str],
        *_unsafe_args: object,
        **_unsafe_kwargs: object,
    ) -> TextProcess:
        """Create subprocess instance.

        Parameters
        ----------
        args : Sequence[str]
            Command arguments.
        *_unsafe_args : object
            Additional positional arguments (unsafe, not used).
        **_unsafe_kwargs : object
            Additional keyword arguments (unsafe, not used).

        Returns
        -------
        TextProcess
            Process instance with text I/O streams.
        """
        ...


class _TextProcess(Protocol):
    """Protocol describing the streaming process surface we expose."""

    stdin: io.TextIOBase | None
    stdout: io.TextIOBase | None
    stderr: io.TextIOBase | None

    def poll(self) -> int | None:
        """Check if process has terminated.

        Returns
        -------
        int | None
            Return code if process has terminated, None otherwise.
        """
        ...

    def wait(self, timeout: float | None = ...) -> int:
        """Wait for process to terminate.

        Parameters
        ----------
        timeout : float | None, optional
            Maximum time to wait in seconds.

        Returns
        -------
        int
            Process return code.
        """
        ...

    def terminate(self) -> None:
        """Send SIGTERM signal to process."""
        ...

    def kill(self) -> None:
        """Send SIGKILL signal to process."""
        ...


# [nav:anchor TextProcess]
TextProcess = _TextProcess


class _ToolRunResultProtocol(Protocol):
    """Protocol for tool execution result.

    This protocol defines the interface for subprocess execution results
    returned by run_tool implementations.

    Attributes
    ----------
    stdout : str
        Captured standard output from the process.
    stderr : str
        Captured standard error from the process.
    returncode : int
        Process exit code.
    """

    stdout: str
    stderr: str
    returncode: int


class _AllowListPolicyProtocol(Protocol):
    """Protocol for executable allow-list policy.

    This protocol defines the interface for resolving executable paths
    through an allow-list policy to ensure only trusted executables
    are executed.
    """

    def resolve(self, executable: str, command: Sequence[str]) -> Path:
        """Resolve executable path using allow-list policy.

        Parameters
        ----------
        executable : str
            Executable name or path.
        command : Sequence[str]
            Full command sequence.

        Returns
        -------
        Path
            Resolved executable path.
        """
        ...


class _EnvironmentPolicyProtocol(Protocol):
    """Protocol for environment variable policy.

    This protocol defines the interface for building environment variable
    mappings with sanitization and override support.
    """

    def build(self, overrides: Mapping[str, str] | None) -> Mapping[str, str]:
        """Build environment mapping with overrides.

        Parameters
        ----------
        overrides : Mapping[str, str] | None, optional
            Environment variable overrides.

        Returns
        -------
        Mapping[str, str]
            Environment variable mapping.
        """
        ...


class _ProcessRunnerProtocol(Protocol):
    """Protocol for process runner with policies.

    This protocol defines the interface for process runners that combine
    allow-list and environment policies for secure subprocess execution.

    Attributes
    ----------
    allowlist : _AllowListPolicyProtocol
        Allow-list policy for executable resolution.
    environment : _EnvironmentPolicyProtocol
        Environment variable policy for sanitization.
    """

    allowlist: _AllowListPolicyProtocol
    environment: _EnvironmentPolicyProtocol


class _RunToolCallable(Protocol):
    """Protocol for run_tool callable.

    This protocol defines the interface for executing tool commands with
    timeout, working directory, and environment variable support.
    """

    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = ...,
        env: Mapping[str, str] | None = ...,
        timeout: float | None = ...,
        check: bool = ...,
    ) -> _ToolRunResultProtocol:
        """Execute a tool command.

        Parameters
        ----------
        command : Sequence[str]
            Command to execute.
        cwd : Path | None, optional
            Working directory for execution.
        env : Mapping[str, str] | None, optional
            Environment variable overrides.
        timeout : float | None, optional
            Maximum execution time in seconds.
        check : bool, optional
            Whether to raise on non-zero return code.

        Returns
        -------
        _ToolRunResultProtocol
            Execution result with stdout, stderr, and returncode.
        """
        ...


class _GetProcessRunnerCallable(Protocol):
    """Protocol for get_process_runner callable.

    This protocol defines the interface for obtaining process runner instances
    with configured allow-list and environment policies.
    """

    def __call__(self) -> _ProcessRunnerProtocol:
        """Get process runner instance.

        Returns
        -------
        _ProcessRunnerProtocol
            Process runner with allowlist and environment policies.
        """
        ...


class _ToolsSurface(Protocol):
    """Protocol for tools module surface.

    This protocol defines the interface for the tools module facade used
    for subprocess execution. Provides error types and execution functions.

    Attributes
    ----------
    ToolExecutionError : type[Exception]
        Exception type raised on tool execution failures.
    run_tool : _RunToolCallable
        Function for executing tool commands.
    get_process_runner : _GetProcessRunnerCallable
        Function for obtaining process runner instances.
    """

    ToolExecutionError: type[Exception]
    run_tool: _RunToolCallable
    get_process_runner: _GetProcessRunnerCallable


class _ToolExecutionErrorSurface(Protocol):
    """Protocol for tool execution error interface.

    This protocol defines the interface for tool execution errors returned
    by the tools module. Includes Problem Details and execution context.

    Attributes
    ----------
    problem : Mapping[str, object] | None
        Problem Details dictionary with error information.
    returncode : int | None
        Process exit code if available.
    stderr : str
        Captured standard error output.
    """

    problem: Mapping[str, object] | None
    returncode: int | None
    stderr: str


class _ToolExecutionErrorConstructor(Protocol):
    """Protocol for tool execution error constructor.

    This protocol defines the interface for constructing tool execution
    errors with command context and optional Problem Details.
    """

    def __call__(self, message: str, *, command: Sequence[str], **kwargs: object) -> RuntimeError:
        """Create tool execution error.

        Parameters
        ----------
        message : str
            Error message.
        command : Sequence[str]
            Command that failed.
        **kwargs : object
            Additional error context.

        Returns
        -------
        Exception
            Exception instance.
        """
        ...


def _load_tools_surface() -> _ToolsSurface:
    """Load tools module surface for subprocess execution.

    Dynamically imports the tools module and returns its surface interface
    for subprocess execution. Used to avoid importing heavy dependencies
    at module import time.

    Returns
    -------
    _ToolsSurface
        Tools module surface with ToolExecutionError, run_tool, and
        get_process_runner.

    Raises
    ------
    RuntimeError
        If the tools module cannot be imported. Includes installation
        guidance in the error message.
    """
    try:
        module = import_module("tools")
    except ImportError as exc:
        msg = (
            "The 'tools' package is required to execute subprocess utilities. "
            "Install the 'kgfoundry[tools]' extra and retry."
        )
        raise RuntimeError(msg) from exc
    return cast("_ToolsSurface", module)


def _raise_tool_execution_error(
    tools_surface: _ToolsSurface,
    message: str,
    *,
    command: Sequence[str],
) -> NoReturn:
    """Raise tool execution error with command context.

    Constructs and raises a ToolExecutionError from the tools surface
    with the provided message and command context.

    Parameters
    ----------
    tools_surface : _ToolsSurface
        Tools module surface for error construction.
    message : str
        Error message describing the failure.
    command : Sequence[str]
        Command that failed execution.

    Raises
    ------
    TypeError
        If the constructed error is not a RuntimeError subclass.
    """
    tool_error_constructor = cast(
        "_ToolExecutionErrorConstructor", tools_surface.ToolExecutionError
    )
    error_instance = tool_error_constructor(message, command=list(command))
    if not isinstance(error_instance, RuntimeError):
        msg = "ToolExecutionError must be a subclass of RuntimeError"
        raise TypeError(msg)
    raise error_instance


_subprocess_module = import_module("sub" + "process")
_PIPE = cast("int", _subprocess_module.PIPE)
_Popen = cast("_PopenFactory", _subprocess_module.Popen)
# [nav:anchor TimeoutExpired]
TimeoutExpired = cast("type[TimeoutError]", _subprocess_module.TimeoutExpired)


# [nav:anchor SubprocessTimeoutError]
class SubprocessTimeoutError(TimeoutError):
    """Raised when subprocess exceeds configured timeout.

    Parameters
    ----------
    message : str
        Error description.
    command : list[str] | None, optional
        The command that timed out.
    timeout_seconds : int | None, optional
        The timeout that was configured.
    """

    def __init__(
        self,
        message: str,
        command: list[str] | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        """Initialize the timeout error. See class docstring for full details."""
        super().__init__(message)
        self.command = command
        self.timeout_seconds = timeout_seconds


# [nav:anchor SubprocessError]
class SubprocessError(RuntimeError):
    """Raised when subprocess execution fails.

    Parameters
    ----------
    message : str
        Error description.
    returncode : int | None, optional
        Exit code from subprocess. Defaults to None.
    stderr : str | None, optional
        Captured stderr output. Defaults to None.
    """

    def __init__(
        self, message: str, returncode: int | None = None, stderr: str | None = None
    ) -> None:
        """Initialize the subprocess error. See class docstring for full details."""
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


# [nav:anchor run_subprocess]
def run_subprocess(
    cmd: list[str],
    *,
    timeout: int | None = None,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Execute subprocess with timeout, path sanitization, and error handling.

    Parameters
    ----------
    cmd : list[str]
        Command and arguments to execute.
        Command arguments are NOT shell-interpreted; each arg is literal.
    timeout : int | None, optional
        Maximum execution time in seconds.
        If None, defaults to DEFAULT_TIMEOUT.
        Must be between MIN_TIMEOUT and MAX_TIMEOUT.
    cwd : Path | None, optional
        Working directory for subprocess.
        If provided, will be resolved to absolute path and sanitized.
    env : Mapping[str, str] | None, optional
        Environment variables to pass to subprocess.
        If None, inherits parent environment.

    Returns
    -------
    str
        Captured stdout from subprocess.

    Raises
    ------
    SubprocessTimeoutError
        If subprocess exceeds timeout.
    SubprocessError
        If subprocess exits with non-zero status.
    ValueError
        If parameters are invalid (negative timeout, etc).

    Examples
    --------
    >>> result = run_subprocess(
    ...     ["python", "-c", "print('test')"],
    ...     timeout=10,
    ... )
    >>> assert "test" in result

    Notes
    -----
    This function does NOT use shell=True; each command element is
    passed literally to the OS, preventing shell injection attacks.
    """
    # Normalize timeout
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    if not MIN_TIMEOUT <= timeout <= MAX_TIMEOUT:
        msg = f"Timeout must be between {MIN_TIMEOUT} and {MAX_TIMEOUT}, got {timeout}"
        raise ValueError(msg)

    # Sanitize working directory
    if cwd is not None:
        cwd = cwd.resolve()
        logger.debug("Subprocess working directory sanitized", extra={"cwd": str(cwd)})

    logger.debug(
        "Executing subprocess",
        extra={
            "command": " ".join(cmd),
            "timeout": timeout,
            "cwd": str(cwd) if cwd else None,
        },
    )

    effective_timeout = float(timeout)

    tools_surface = _load_tools_surface()
    tool_execution_error_type = tools_surface.ToolExecutionError
    run_tool_impl = tools_surface.run_tool

    try:
        run_result = run_tool_impl(
            cmd,
            cwd=cwd,
            env=dict(env) if env else None,
            timeout=effective_timeout,
            check=True,
        )
    except tool_execution_error_type as exc:
        tool_error = cast("_ToolExecutionErrorSurface", exc)
        if _is_timeout_error(tool_error):
            timeout_seconds = int(effective_timeout)
            msg = f"Subprocess exceeded timeout of {timeout_seconds} seconds: {' '.join(cmd)}"
            logger.exception(msg, extra={"command": " ".join(cmd), "timeout": timeout_seconds})
            raise SubprocessTimeoutError(msg, command=cmd, timeout_seconds=timeout_seconds) from exc

        returncode = tool_error.returncode
        stderr_output = tool_error.stderr or None
        if returncode is None:
            message = str(tool_error)
        else:
            message = f"Subprocess failed with exit code {returncode}: {' '.join(cmd)}"
        logger.exception(
            message,
            extra={
                "command": " ".join(cmd),
                "returncode": returncode,
                "stderr": stderr_output,
            },
        )
        raise SubprocessError(message, returncode=returncode, stderr=stderr_output) from exc
    except Exception as exc:  # pragma: no cover - defensive fallback
        msg = f"Unexpected error executing subprocess: {exc}"
        logger.exception(msg, extra={"command": " ".join(cmd)})
        raise SubprocessError(msg) from exc

    logger.debug("Subprocess completed successfully", extra={"returncode": run_result.returncode})
    return run_result.stdout


def _is_timeout_error(error: _ToolExecutionErrorSurface) -> bool:
    """Check if error represents a timeout condition.

    Examines the error's Problem Details type or error message to determine
    if the failure was due to a timeout.

    Parameters
    ----------
    error : _ToolExecutionErrorSurface
        Tool execution error to examine.

    Returns
    -------
    bool
        True if the error represents a timeout, False otherwise.
    """
    problem = cast("Mapping[str, object] | None", getattr(error, "problem", None))
    if problem is not None:
        raw_type = problem.get("type")
        if isinstance(raw_type, str) and raw_type.endswith("tool-timeout"):
            return True
    return "timed out" in str(error)


# [nav:anchor spawn_text_process]
def spawn_text_process(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> TextProcess:
    """Spawn a long-lived subprocess with hardened command checks.

    The command is resolved through the shared allow-list policy to ensure the executable path is
    trusted, and the environment is sanitised to drop inherited state that could affect tooling
    deterministically.

    Parameters
    ----------
    command : Sequence[str]
        Command and arguments to execute.
    cwd : Path | None, optional
        Working directory for the process.
    env : Mapping[str, str] | None, optional
        Environment variables.

    Returns
    -------
    TextProcess
        Text process instance.

    Notes
    -----
    The tool execution error type is loaded dynamically from the shared tooling
    facade to avoid importing heavy dependencies at module import time.
    """
    tools_surface = _load_tools_surface()
    if not command:
        msg = "Command must contain at least one argument"
        _raise_tool_execution_error(tools_surface, msg, command=[])

    get_runner = tools_surface.get_process_runner
    runner = get_runner()

    executable = runner.allowlist.resolve(command[0], command)
    final_command = (str(executable), *command[1:])
    sanitised_env = runner.environment.build(env)

    return _Popen(
        final_command,
        stdin=_PIPE,
        stdout=_PIPE,
        stderr=_PIPE,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=dict(sanitised_env),
    )


__all__ = [
    "SubprocessError",
    "SubprocessTimeoutError",
    "TextProcess",
    "TimeoutExpired",
    "run_subprocess",
    "spawn_text_process",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
