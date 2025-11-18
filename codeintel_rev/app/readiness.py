"""Filesystem readiness probes used during startup."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from codeintel_rev.config.paths import ResolvedPaths
from kgfoundry_common.errors import ConfigurationError

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


class ReadinessError(ConfigurationError):
    """Raised when critical filesystem resources are unavailable."""


def _ok(path: Path, message: str = "ok") -> ProbeResult:
    return ProbeResult(subject=path, status="ok", message=message)


def _warn(path: Path, message: str) -> ProbeResult:
    return ProbeResult(subject=path, status="warn", message=message)


def _err(path: Path, message: str) -> ProbeResult:
    return ProbeResult(subject=path, status="error", message=message)


def check_file(
    path: Path,
    *,
    must_exist: bool = True,
    readable: bool = True,
    writable: bool = False,
) -> ProbeResult:
    """Return the readiness status for ``path`` assuming it should be a file.

    Parameters
    ----------
    path : Path
        Target path that should represent a regular file.
    must_exist : bool, optional
        Whether a missing file constitutes an error, by default ``True``.
    readable : bool, optional
        Require read access when the file exists, by default ``True``.
    writable : bool, optional
        Require write access when the file exists, by default ``False``.

    Returns
    -------
    ProbeResult
        Result containing the probe subject, status, and diagnostic message.
    """
    try:
        exists = path.exists()
    except OSError as exc:  # pragma: no cover - filesystem edge
        return _err(path, f"stat failed: {exc.strerror or exc}")

    status: Status = "ok"
    message = "ok"

    if not exists:
        if must_exist:
            status = "error"
            message = "file missing"
        else:
            message = "file optional"
    else:
        if must_exist and not path.is_file():
            status = "error"
            message = "not a regular file"
        if status == "ok" and readable:
            try:
                with path.open("rb"):
                    pass
            except OSError as exc:
                status = "error"
                message = f"file not readable: {exc.strerror or exc}"
        if status == "ok" and writable and not os.access(path, os.W_OK):
            status = "error"
            message = "file not writable"

    return _ok(path, message) if status == "ok" else _err(path, message)


def _probe_directory_permissions(
    path: Path,
    *,
    readable: bool,
    writable: bool,
    executable_on_posix: bool,
) -> str | None:
    if readable and not os.access(path, os.R_OK):
        return "directory not readable"
    if writable and not os.access(path, os.W_OK):
        return "directory not writable"
    if executable_on_posix and os.name == "posix" and not os.access(path, os.X_OK):
        return "directory lacks +x"
    return None


def check_directory(
    path: Path,
    *,
    must_exist: bool = True,
    readable: bool = True,
    writable: bool = True,
    executable_on_posix: bool = True,
) -> ProbeResult:
    """Return the readiness status for ``path`` assuming it should be a directory.

    Parameters
    ----------
    path : Path
        Target path that should represent a directory.
    must_exist : bool, optional
        Whether absence is treated as an error, by default ``True``.
    readable : bool, optional
        Require read access when the directory exists, by default ``True``.
    writable : bool, optional
        Require write access when the directory exists, by default ``True``.
    executable_on_posix : bool, optional
        Require execute permission on POSIX hosts, by default ``True``.

    Returns
    -------
    ProbeResult
        Result indicating the readiness status for the directory.
    """
    try:
        exists = path.exists()
    except OSError as exc:  # pragma: no cover - filesystem edge
        return _err(path, f"stat failed: {exc.strerror or exc}")

    status: Status = "ok"
    message = "ok"

    if not exists:
        if must_exist:
            status = "error"
            message = "directory missing"
        else:
            message = "directory optional"
    else:
        if must_exist and not path.is_dir():
            status = "error"
            message = "not a directory"
        if status == "ok":
            permission_issue = _probe_directory_permissions(
                path,
                readable=readable,
                writable=writable,
                executable_on_posix=executable_on_posix,
            )
            if permission_issue:
                status = "error"
                message = permission_issue
        if status == "ok" and writable:
            try:
                with tempfile.NamedTemporaryFile(dir=path, delete=True):
                    pass
            except OSError as exc:
                status = "error"
                message = f"directory write probe failed: {exc.strerror or exc}"

    return _ok(path, message) if status == "ok" else _err(path, message)


def validate_paths(paths: ResolvedPaths) -> list[ProbeResult]:
    """Run readiness probes for the critical filesystem paths.

    Parameters
    ----------
    paths : ResolvedPaths
        Canonical filesystem layout returned by :func:`resolve_application_paths`.

    Returns
    -------
    list[ProbeResult]
        Collected probe results for logging and readiness reporting.
    """
    results: list[ProbeResult] = [
        check_directory(paths.repo_root),
        check_directory(paths.config_dir, writable=False),
        check_file(paths.config_file),
        check_directory(paths.data_dir),
        check_directory(paths.vectors_dir),
        check_directory(paths.logs_dir, writable=True),
        check_directory(paths.cache_dir),
        check_directory(paths.tmp_dir),
        check_directory(paths.plugins_dir, writable=False),
    ]
    return results


def raise_on_errors(results: Iterable[ProbeResult]) -> None:
    """Raise ``ReadinessError`` when any probe reports an error.

    Raises
    ------
    ReadinessError
        Raised when any ``ProbeResult`` has status ``"error"``. The exception
        detail string concatenates the failing paths, matching our RFC 9457
        Problem Details envelopes for readiness failures.
    """
    errors = [probe for probe in results if probe.status == "error"]
    if not errors:
        return
    details = "; ".join(f"{entry.subject}: {entry.message}" for entry in errors)
    raise ReadinessError(details)
