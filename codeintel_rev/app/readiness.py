"""Filesystem readiness probes that avoid mutating the environment."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from codeintel_rev.config.paths import ResolvedPaths

Status = Literal["ok", "warn", "error"]

__all__ = [
    "ProbeResult",
    "ReadinessError",
    "check_directory",
    "check_file",
    "raise_on_errors",
    "validate_paths",
]


@dataclass(slots=True)
class ProbeResult:
    """Outcome of a filesystem probe."""

    subject: Path
    status: Status
    message: str


def _ok(path: Path, message: str = "ok") -> ProbeResult:
    """Create a ProbeResult indicating successful validation.

    Parameters
    ----------
    path : Path
        Path that was validated successfully.
    message : str, optional
        Success message (default: "ok").

    Returns
    -------
    ProbeResult
        ProbeResult with status="ok" and the provided message.
    """
    return ProbeResult(subject=path, status="ok", message=message)


def _err(path: Path, message: str) -> ProbeResult:
    """Create a ProbeResult indicating validation failure.

    Parameters
    ----------
    path : Path
        Path that failed validation.
    message : str
        Error message describing the failure.

    Returns
    -------
    ProbeResult
        ProbeResult with status="error" and the provided message.
    """
    return ProbeResult(subject=path, status="error", message=message)


def check_file(
    path: Path,
    *,
    must_exist: bool = True,
    readable: bool = True,
    writable: bool = False,
) -> ProbeResult:
    """Validate an individual file without mutating the filesystem.

    Parameters
    ----------
    path : Path
        File path to validate.
    must_exist : bool, optional
        Whether the file must exist (default: True).
    readable : bool, optional
        Whether the file must be readable (default: True).
    writable : bool, optional
        Whether the file must be writable (default: False).

    Returns
    -------
    ProbeResult
        Probe outcome describing the file status.
    """
    if must_exist and (not path.exists() or not path.is_file()):
        return _err(path, "missing or not a regular file")
    if path.exists():
        if readable and not os.access(path, os.R_OK):
            return _err(path, "file not readable")
        if writable and not os.access(path, os.W_OK):
            return _err(path, "file not writable")
    return _ok(path)


def check_directory(
    path: Path,
    *,
    must_exist: bool = True,
    readable: bool = True,
    writable: bool = True,
    executable_on_posix: bool = True,
) -> ProbeResult:
    """Validate directory presence and permissions.

    Parameters
    ----------
    path : Path
        Directory path to validate.
    must_exist : bool, optional
        Whether the directory must exist (default: True).
    readable : bool, optional
        Whether the directory must be readable (default: True).
    writable : bool, optional
        Whether the directory must be writable (default: True).
    executable_on_posix : bool, optional
        Whether the directory must be executable on POSIX systems (default: True).

    Returns
    -------
    ProbeResult
        Probe outcome describing the directory status.
    """
    if must_exist and (not path.exists() or not path.is_dir()):
        return _err(path, "missing or not a directory")
    if path.exists():
        if readable and not os.access(path, os.R_OK):
            return _err(path, "directory not readable")
        if writable and not os.access(path, os.W_OK):
            return _err(path, "directory not writable")
        if executable_on_posix and os.name == "posix" and not os.access(path, os.X_OK):
            return _err(path, "directory not searchable (+x)")
        if writable:
            try:
                with NamedTemporaryFile(dir=path, delete=True):
                    pass
            except OSError as exc:
                detail = exc.strerror or str(exc)
                return _err(path, f"directory write probe failed: {detail}")
    return _ok(path)


def validate_paths(paths: ResolvedPaths) -> list[ProbeResult]:
    """Run the canonical path probes for an application deployment.

    Parameters
    ----------
    paths : ResolvedPaths
        Resolved filesystem paths to validate.

    Returns
    -------
    list[ProbeResult]
        Probe results for each required path.
    """
    results: list[ProbeResult] = []
    results.append(check_directory(paths.repo_root))
    results.append(check_directory(paths.config_dir))
    results.append(check_file(paths.config_file))
    results.append(check_directory(paths.data_dir))
    results.append(check_directory(paths.logs_dir))
    results.append(check_directory(paths.cache_dir))
    results.append(check_directory(paths.tmp_dir))
    results.append(check_directory(paths.plugins_dir, writable=False))
    return results


class ReadinessError(RuntimeError):
    """Raised when one or more readiness probes fail."""


def raise_on_errors(results: Iterable[ProbeResult]) -> None:
    r"""Raise a single aggregated error when any probe returned ``error``.

    Parameters
    ----------
    results : Iterable[ProbeResult]
        Iterable of probe results to check for errors.

    Raises
    ------
    ReadinessError
        Raised when at least one probe reported ``status == \"error\"``.
    """
    errors = [result for result in results if result.status == "error"]
    if not errors:
        return
    details = "; ".join(f"{error.subject}: {error.message}" for error in errors)
    raise ReadinessError(details)
