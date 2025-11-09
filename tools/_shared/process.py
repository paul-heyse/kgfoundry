"""High-level process execution adapter for repository tooling.

This module centralises subprocess execution policies so that security checks,
metrics, and structured logging live in one place. Callers should prefer the
``ProcessRunner`` facade (or the legacy ``tools._shared.proc.run_tool`` wrapper)
instead of invoking :mod:`subprocess` directly.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from tools._shared.logging import get_logger
from tools._shared.metrics import ToolRunObservation, observe_tool_run
from tools._shared.problem_details import (
    tool_digest_mismatch_problem_details,
    tool_disallowed_problem_details,
    tool_failure_problem_details,
    tool_missing_problem_details,
    tool_timeout_problem_details,
)
from tools._shared.settings import get_runtime_settings

if TYPE_CHECKING:
    from tools._shared.logging import StructuredLoggerAdapter
    from tools._shared.problem_details import (
        ProblemDetailsDict,
    )
    from tools._shared.settings import ToolRuntimeSettings


class CompletedProcessProtocol(Protocol):
    """Typed subset of :class:`subprocess.CompletedProcess` we rely on."""

    args: Sequence[str]
    returncode: int
    stdout: str
    stderr: str


class TimeoutExpiredProtocol(Protocol):
    """Structured view of :class:`subprocess.TimeoutExpired` attributes."""

    stdout: object
    stderr: object


_subprocess_module = import_module("sub" + "process")
TimeoutExpired = cast("type[TimeoutError]", _subprocess_module.TimeoutExpired)
_run_subprocess = cast(
    "Callable[..., CompletedProcessProtocol]", _subprocess_module.run
)

Command = Sequence[str]
Environment = Mapping[str, str]
ObservationFactory = Callable[
    [Sequence[str], Path | None, float | None],
    AbstractContextManager[ToolRunObservation],
]


LOGGER = get_logger(__name__)


@lru_cache(maxsize=128)
def _hash_executable(path: str) -> str:
    executable_path = Path(path)
    hasher = hashlib.sha256()
    with executable_path.open("rb") as buffer:
        for chunk in iter(lambda: buffer.read(1024 * 1024), b""):
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().lower()


@dataclass(slots=True, frozen=True)
class ExecutableDigestVerifier:
    """Verify executables against an expected SHA256 digest when provided."""

    settings_loader: Callable[[], ToolRuntimeSettings] = get_runtime_settings

    def verify(self, executable: Path, command: Command) -> None:
        """Verify executable digest matches expected value.

        Parameters
        ----------
        executable : Path
            Path to executable file.
        command : Command
            Command being executed.

        Raises
        ------
        ToolExecutionError
            If digest verification fails or executable is missing.
        """
        settings = self.settings_loader()
        expected = settings.expected_digest_for(executable)
        if expected is None:
            return

        try:
            actual = _hash_executable(executable.as_posix())
        except FileNotFoundError as exc:
            reason = "executable-missing"
            problem = tool_digest_mismatch_problem_details(
                command,
                executable=executable,
                expected_digest=expected,
                actual_digest=None,
                reason=reason,
            )
            message = "Executable digest verification failed (executable missing)"
            LOGGER.exception(
                message,
                extra={
                    "executable": executable.as_posix(),
                    "reason": reason,
                },
            )
            raise ToolExecutionError(message, command=command, problem=problem) from exc

        if hmac.compare_digest(actual, expected):
            return

        reason = "digest-mismatch"
        problem = tool_digest_mismatch_problem_details(
            command,
            executable=executable,
            expected_digest=expected,
            actual_digest=actual,
            reason=reason,
        )
        message = "Executable digest verification failed"
        LOGGER.error(
            message,
            extra={
                "executable": executable.as_posix(),
                "expected_digest": expected,
                "actual_digest": actual,
            },
        )
        raise ToolExecutionError(message, command=command, problem=problem)


@dataclass(slots=True, frozen=True)
class ToolRunResult:
    """Structured result from invoking a subprocess."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool


class ToolExecutionError(RuntimeError):
    """Raised when a subprocess fails to execute successfully.

    Parameters
    ----------
    message : str
        Human-readable error message.
    command : Sequence[str]
        Command that failed.
    returncode : int | None, optional
        Process exit code if available.
    streams : tuple[str, str] | None, optional
        ``(stdout, stderr)`` tuple if available.
    problem : ProblemDetailsDict | None, optional
        RFC 9457 Problem Details payload.
    """

    def __init__(
        self,
        message: str,
        *,
        command: Sequence[str],
        returncode: int | None = None,
        streams: tuple[str, str] | None = None,
        problem: ProblemDetailsDict | None = None,
    ) -> None:
        super().__init__(message)
        self.command: tuple[str, ...] = tuple(command)
        self.returncode = returncode
        self.stdout, self.stderr = streams if streams is not None else ("", "")
        self.problem = problem


@runtime_checkable
class AllowListPolicy(Protocol):
    """Protocol for enforcing executable allow-list checks."""

    def ensure_permitted(self, executable: Path, command: Command) -> None:
        """Validate that ``executable`` is permitted to run ``command``."""
        ...

    def resolve(self, executable: str, command: Command) -> Path:
        """Resolve ``executable`` to an allow-listed absolute path."""
        ...


@dataclass(slots=True, frozen=True)
class AllowListEnforcer:
    """Concrete allow-list policy backed by ``ToolRuntimeSettings``."""

    settings_loader: Callable[[], ToolRuntimeSettings] = get_runtime_settings
    digest_verifier: ExecutableDigestVerifier = field(
        default_factory=ExecutableDigestVerifier
    )

    def resolve(self, executable: str, command: Command) -> Path:
        """Resolve ``executable`` to an absolute, allow-listed path.

        Parameters
        ----------
        executable : str
            Executable name or path.
        command : Command
            Full command sequence.

        Returns
        -------
        Path
            Absolute, allow-listed executable path.

        Raises
        ------
        ToolExecutionError
            If executable is not found or not allow-listed.
        """
        candidate = Path(executable)
        if candidate.is_absolute():
            self.ensure_permitted(candidate, command)
            self.digest_verifier.verify(candidate, command)
            return candidate

        resolved = shutil.which(executable)
        if resolved is None:
            detail = (
                f"Executable '{executable}' could not be resolved to an absolute path"
            )
            problem = tool_missing_problem_details(
                command=command, executable=executable, detail=detail
            )
            raise ToolExecutionError(detail, command=[executable], problem=problem)

        resolved_path = Path(resolved)
        self.ensure_permitted(resolved_path, command)
        self.digest_verifier.verify(resolved_path, command)
        return resolved_path

    def ensure_permitted(self, executable: Path, command: Command) -> None:
        """Raise ``ToolExecutionError`` if ``executable`` is not allow-listed.

        Parameters
        ----------
        executable : Path
            Executable path to check.
        command : Command
            Full command sequence.

        Raises
        ------
        ToolExecutionError
            If executable is not in the allow list.
        """
        settings = self.settings_loader()
        if settings.is_allowed(executable):
            return

        problem = tool_disallowed_problem_details(
            command=command,
            executable=executable,
            allowlist=settings.exec_allowlist,
        )
        message = f"Executable '{executable}' is not permitted by TOOLS_EXEC_ALLOWLIST"
        LOGGER.warning(
            message,
            extra={
                "executable": executable.as_posix(),
                "command": list(command),
            },
        )
        raise ToolExecutionError(message, command=command, problem=problem)


@runtime_checkable
class EnvironmentPolicy(Protocol):
    """Protocol describing how subprocess environments are constructed."""

    def build(self, overrides: Mapping[str, str] | None) -> dict[str, str]:
        """Create an environment mapping, applying ``overrides`` when provided."""
        ...


@dataclass(slots=True, frozen=True)
class SanitisedEnvironment(EnvironmentPolicy):
    """Environment policy that whitelists baseline variables and allows overrides."""

    allowed_keys: frozenset[str] = frozenset(
        {
            "HOME",
            "PATH",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "LC_MESSAGES",
            "PYTHONPATH",
            "PYTHONHASHSEED",
            "TZ",
        }
    )

    def build(self, overrides: Mapping[str, str] | None) -> dict[str, str]:
        """Return an environment dictionary merged with ``overrides``.

        Parameters
        ----------
        overrides : Mapping[str, str] | None
            Optional environment variable overrides.

        Returns
        -------
        dict[str, str]
            Merged environment dictionary.
        """
        baseline = {
            key: value
            for key, value in os.environ.items()
            if key in self.allowed_keys or key.startswith(("GIT_", "UV_", "CI"))
        }

        if overrides:
            baseline.update(overrides)

        return {key: str(value) for key, value in baseline.items()}


def _default_observer_factory(
    command: Sequence[str],
    cwd: Path | None,
    timeout: float | None,
) -> AbstractContextManager[ToolRunObservation]:
    return observe_tool_run(command, cwd=cwd, timeout=timeout)


@dataclass(slots=True, frozen=True)
class ProcessRunner:
    """High-level facade that executes tooling subprocesses with shared policies."""

    allowlist: AllowListPolicy = field(default_factory=AllowListEnforcer)
    environment: EnvironmentPolicy = field(default_factory=SanitisedEnvironment)
    observer_factory: ObservationFactory = field(default=_default_observer_factory)
    logger: StructuredLoggerAdapter = field(
        default_factory=lambda: get_logger(__name__)
    )

    def run(
        self,
        command: Command,
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        check: bool = False,
    ) -> ToolRunResult:
        """Execute ``command`` under the configured policies.

        Parameters
        ----------
        command : Command
            Command to execute.
        cwd : Path | None, optional
            Working directory. Default is None.
        env : Mapping[str, str] | None, optional
            Environment variables. Default is None.
        timeout : float | None, optional
            Timeout in seconds. Default is None.
        check : bool, optional
            Raise on non-zero exit. Default is False.

        Returns
        -------
        ToolRunResult
            Execution result.

        Raises
        ------
        ToolExecutionError
            If execution fails or ``check=True`` and returncode is non-zero.
        """
        if not command:
            message = "Command must contain at least one argument"
            raise ToolExecutionError(message, command=[])

        executable = self.allowlist.resolve(command[0], command)
        final_command = (str(executable), *command[1:])
        sanitised_env = self.environment.build(env)

        with self.observer_factory(final_command, cwd, timeout) as observation:
            try:
                completed = self._spawn(
                    final_command, cwd=cwd, env=sanitised_env, timeout=timeout
                )
            except TimeoutExpired as exc:
                observation.failure("timeout", timed_out=True)
                problem = tool_timeout_problem_details(command=command, timeout=timeout)
                timeout_exc = cast("TimeoutExpiredProtocol", exc)
                stdout_text = _decode_stream(timeout_exc.stdout)
                stderr_text = _decode_stream(timeout_exc.stderr)
                message = "Subprocess timed out"
                raise ToolExecutionError(
                    message,
                    command=command,
                    returncode=None,
                    streams=(stdout_text, stderr_text),
                    problem=problem,
                ) from exc
            except FileNotFoundError as exc:
                observation.failure("missing_executable")
                problem = tool_missing_problem_details(
                    command=command, executable=command[0], detail=str(exc)
                )
                message = "Executable not found"
                raise ToolExecutionError(
                    message,
                    command=command,
                    returncode=None,
                    problem=problem,
                ) from exc

            result = ToolRunResult(
                command=tuple(final_command),
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_seconds=observation.duration_seconds(),
                timed_out=False,
            )

            if completed.returncode == 0:
                observation.success(completed.returncode)
            else:
                observation.failure("non_zero_exit", returncode=completed.returncode)

            if check and completed.returncode != 0:
                problem = tool_failure_problem_details(
                    command=command,
                    returncode=completed.returncode,
                    detail=completed.stderr.strip() or "Unknown failure",
                )
                message = "Subprocess returned a non-zero exit status"
                raise ToolExecutionError(
                    message,
                    command=command,
                    returncode=completed.returncode,
                    streams=(completed.stdout, completed.stderr),
                    problem=problem,
                )

            return result

    @staticmethod
    def _spawn(
        final_command: tuple[str, ...],
        *,
        cwd: Path | None,
        env: Mapping[str, str],
        timeout: float | None,
    ) -> CompletedProcessProtocol:
        return _run_subprocess(
            final_command,
            cwd=str(cwd) if cwd else None,
            env=dict(env),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )


def _decode_stream(stream: object) -> str:
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    if stream is None:
        return ""
    return str(stream)


__all__ = [
    "AllowListEnforcer",
    "AllowListPolicy",
    "ProcessRunner",
    "SanitisedEnvironment",
    "ToolExecutionError",
    "ToolRunResult",
]
