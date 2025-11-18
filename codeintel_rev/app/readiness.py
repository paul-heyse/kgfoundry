"""Filesystem readiness probes used during startup."""

from __future__ import annotations

import os
import shutil
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

FAISS_INDEX_SOURCE_ENV = "CODEINTEL_FAISS_INDEX_SOURCE"
FAISS_IDMAP_SOURCE_ENV = "CODEINTEL_FAISS_IDMAP_SOURCE"
DUCKDB_CATALOG_SOURCE_ENV = "CODEINTEL_DUCKDB_SOURCE"
STUB_NOTICE = "# Auto-generated stub by readiness bootstrap.\n"


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

    Notes
    -----
    Critical roots (``repo_root`` and ``config_dir``) are probed before any
    bootstrapping. When either path is missing or inaccessible the error is
    reported immediately and no directories are created implicitly. For all
    other assets we probe first to capture the failure signal, then create
    stub directories/files so the next execution has the necessary structure.
    """
    results: list[ProbeResult] = []

    repo_probe = check_directory(paths.repo_root)
    if repo_probe.status == "error" and repo_probe.message == "directory missing":
        repo_probe = _err(paths.repo_root, "Repository root does not exist")
    preflight = [
        repo_probe,
        check_directory(paths.config_dir, writable=False),
    ]
    results.extend(preflight)
    if any(probe.status == "error" for probe in preflight):
        return results

    results.extend(
        [
            check_file(paths.config_file),
            check_directory(paths.data_dir),
            check_directory(paths.vectors_dir),
            check_directory(paths.logs_dir, writable=True),
            check_directory(paths.cache_dir),
            check_directory(paths.tmp_dir),
            check_directory(paths.plugins_dir, writable=False),
        ]
    )
    _bootstrap_paths(paths)
    return results


def _bootstrap_paths(paths: ResolvedPaths) -> None:
    """Ensure key directories/files exist with stubs until production assets arrive."""
    directories = {
        paths.repo_root,
        paths.config_dir,
        paths.data_dir,
        paths.vectors_dir,
        paths.lucene_dir,
        paths.splade_dir,
        paths.logs_dir,
        paths.cache_dir,
        paths.tmp_dir,
        paths.plugins_dir,
    }
    for directory in directories:
        _ensure_directory_stub(directory)

    _ensure_text_stub(
        paths.config_file,
        STUB_NOTICE + "# Replace with real configuration content or set CODEINTEL_CONFIG_FILE.\n",
    )

    _ensure_file_with_pivot(
        paths.faiss_index,
        env_var=FAISS_INDEX_SOURCE_ENV,
        stub_payload=b"FAISS index stub - replace with production artifact.\n",
    )
    _ensure_file_with_pivot(
        paths.faiss_idmap_path,
        env_var=FAISS_IDMAP_SOURCE_ENV,
        stub_payload=b"faiss_row,external_id\n0,-1\n",
    )
    _ensure_file_with_pivot(
        paths.duckdb_path,
        env_var=DUCKDB_CATALOG_SOURCE_ENV,
        stub_payload=b"",
    )


def _ensure_directory_stub(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"Unable to create directory '{path}': {exc.strerror or exc}"
        raise ReadinessError(msg) from exc
    marker = path / ".stub"
    if marker.exists():
        return
    try:
        marker.write_text(
            STUB_NOTICE + "# Remove when replacing with real assets.\n",
            encoding="utf-8",
        )
    except OSError as exc:
        msg = f"Unable to write stub marker '{marker}': {exc.strerror or exc}"
        raise ReadinessError(msg) from exc


def _ensure_text_stub(path: Path, payload: str) -> None:
    if path.exists():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    except OSError as exc:
        msg = f"Unable to create text stub '{path}': {exc.strerror or exc}"
        raise ReadinessError(msg) from exc


def _ensure_file_with_pivot(path: Path, *, env_var: str, stub_payload: bytes) -> None:
    if _pivot_from_env(path, env_var):
        return
    if path.exists():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(stub_payload)
    except OSError as exc:
        msg = f"Unable to create stub file '{path}': {exc.strerror or exc}"
        raise ReadinessError(msg) from exc


def _pivot_from_env(target: Path, env_var: str) -> bool:
    source_value = os.getenv(env_var)
    if not source_value:
        return False
    source = Path(source_value).expanduser()
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return True
    try:
        if source.is_dir():
            Path(target).symlink_to(source, target_is_directory=True)
        else:
            Path(target).symlink_to(source)
    except OSError:
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    return True


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
