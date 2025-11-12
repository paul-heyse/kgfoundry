# SPDX-License-Identifier: MIT
"""Helpers for collecting Pyright/Pyrefly error summaries."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True, frozen=True)
class TypeFileSummary:
    """Aggregated type-checker results for a single file."""

    file: str
    error_count: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class TypeSummary:
    """Mapping of file path → :class:`TypeFileSummary`."""

    by_file: dict[str, TypeFileSummary] = field(default_factory=dict)


async def _run_command_async(
    cmd: Sequence[str],
    cwd: str | None,
    time_limit: int,
) -> tuple[int, str, str]:
    """Run a command asynchronously and capture stdout/stderr.

    Returns
    -------
    tuple[int, str, str]
        Return code, stdout, and stderr content.
    """
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=time_limit
        )
    except TimeoutError:
        process.kill()
        stdout_bytes, stderr_bytes = await process.communicate()
        return 1, "", "command timed out"
    stdout = stdout_bytes.decode("utf-8") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8") if stderr_bytes else ""
    return_code = process.returncode if process.returncode is not None else 1
    return return_code, stdout, stderr


def _try_run(
    cmd: Sequence[str],
    cwd: str | None = None,
    time_limit: int = 300,
) -> tuple[int, str, str]:
    """Run the asynchronous helper in a synchronous context.

    Returns
    -------
    tuple[int, str, str]
        Execution result triple (code, stdout, stderr).
    """
    try:
        return asyncio.run(_run_command_async(cmd, cwd, time_limit))
    except (OSError, RuntimeError) as exc:  # pragma: no cover - process launch failures
        return 127, "", str(exc)


def collect_pyright(path: str | None = None) -> TypeSummary | None:
    """Run Pyright (or BasedPyright) and summarize diagnostics.

    Returns
    -------
    TypeSummary | None
        Summary of diagnostics, if any were produced.
    """
    for exe in ("pyright", "basedpyright"):
        code, stdout, _stderr = _try_run([exe, "--outputjson"], cwd=path)
        if code != 0 or not stdout.strip():
            continue
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            continue
        summary = TypeSummary()
        for diag in payload.get("generalDiagnostics", []):
            file_path = diag.get("file") or ""
            if not file_path:
                continue
            entry = summary.by_file.setdefault(file_path, TypeFileSummary(file=file_path))
            summary.by_file[file_path] = TypeFileSummary(
                file=entry.file,
                error_count=entry.error_count + 1,
                notes=entry.notes,
            )
        return summary
    return None


def collect_pyrefly(report_path: str | None) -> TypeSummary | None:
    """Parse a Pyrefly JSON/JSONL report produced by CI.

    Returns
    -------
    TypeSummary | None
        Parsed summary when the report exists.
    """
    if not report_path:
        return None
    path = Path(report_path)
    if not path.exists():
        return None
    summary = TypeSummary()
    try:
        if path.suffix == ".jsonl":
            _parse_pyrefly_jsonl(path, summary)
        else:
            _parse_pyrefly_json(path, summary)
    except (json.JSONDecodeError, OSError):
        return None
    return summary


def _parse_pyrefly_jsonl(path: Path, summary: TypeSummary) -> None:
    """Apply Pyrefly records from a JSONL file to the summary."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        _apply_pyrefly_record(record, summary)


def _parse_pyrefly_json(path: Path, summary: TypeSummary) -> None:
    """Apply Pyrefly records from a JSON file to the summary."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    for record in payload.get("results", []):
        _apply_pyrefly_record(record, summary)


def _apply_pyrefly_record(record: dict[str, str], summary: TypeSummary) -> None:
    """Merge a single Pyrefly record into the summary."""
    file_path = record.get("file") or record.get("path") or ""
    if not file_path or record.get("severity") != "error":
        return
    entry = summary.by_file.setdefault(file_path, TypeFileSummary(file=file_path))
    summary.by_file[file_path] = TypeFileSummary(
        file=entry.file,
        error_count=entry.error_count + 1,
        notes=entry.notes,
    )
