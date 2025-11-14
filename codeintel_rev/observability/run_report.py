"""Utilities for composing run reports from JSONL ledgers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class LedgerRunReport:
    """Structured run report derived from a run ledger."""

    run_id: str
    stopped_because: str | None
    steps: list[dict[str, Any]]
    warnings: list[str]
    ledger_path: str


def load_ledger(path: Path) -> list[dict[str, Any]]:
    """Return all JSONL records contained in ``path`` (best effort).

    Parameters
    ----------
    path : Path
        Path to the JSONL ledger file to read.

    Returns
    -------
    list[dict[str, Any]]
        List of parsed JSON records from the ledger. Returns an empty list if
        the file doesn't exist or if parsing errors occur (errors are silently
        skipped).
    """
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def infer_stop_reason(events: Iterable[Mapping[str, Any]]) -> str | None:
    """Return a human-readable stop reason based on structured step events.

    Parameters
    ----------
    events : Iterable[Mapping[str, Any]]
        Sequence of step event dictionaries to analyze for failure status.

    Returns
    -------
    str | None
        Human-readable stop reason string (format: "kind:detail" or "kind:status"),
        or None if no failures are found in the events.
    """
    last_failure: str | None = None
    for event in events:
        status = str(event.get("status") or "ok")
        if status in {"failed", "timed_out"}:
            kind = str(event.get("kind") or "unknown")
            detail = event.get("detail")
            last_failure = f"{kind}:{detail}" if detail else f"{kind}:{status}"
    return last_failure


def build_run_report(run_id: str, ledger_path: Path) -> LedgerRunReport:
    """Compose a report for ``run_id`` using the JSONL ledger at ``ledger_path``.

    Parameters
    ----------
    run_id : str
        Run identifier to include in the report.
    ledger_path : Path
        Path to the JSONL ledger file containing step events.

    Returns
    -------
    LedgerRunReport
        Structured report object containing run metadata, stop reason, warnings,
        and step events.
    """
    steps = load_ledger(ledger_path)
    stop_reason = infer_stop_reason(steps)
    warnings = [
        str(step.get("detail"))
        for step in steps
        if step.get("status") == "degraded" and step.get("detail")
    ]
    return LedgerRunReport(
        run_id=run_id,
        stopped_because=stop_reason,
        steps=steps,
        warnings=warnings,
        ledger_path=str(ledger_path),
    )
