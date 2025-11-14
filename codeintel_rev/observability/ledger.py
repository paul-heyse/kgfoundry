"""Append-only run ledger utilities."""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["RunLedger", "dated_run_dir", "ensure_ledger_root"]


def ensure_ledger_root(root_dir: Path) -> Path:
    """Ensure the run-ledger root exists and return it.

    Parameters
    ----------
    root_dir : Path
        Directory path to ensure exists. Parent directories are created if needed.

    Returns
    -------
    Path
        Absolute path to the ledger root directory.
    """
    root_dir.mkdir(parents=True, exist_ok=True)
    return root_dir


def dated_run_dir(base_dir: Path | None, *, stamp: datetime | None = None) -> Path:
    """Return the YYYY-MM-DD ledger directory under ``base_dir``.

    Parameters
    ----------
    base_dir : Path | None
        Base directory for ledger storage. If None, defaults to "data".
    stamp : datetime | None, optional
        Timestamp to use for date segmentation. If None, uses current UTC time.

    Returns
    -------
    Path
        Resolved path to the YYYY-MM-DD ledger directory under the base directory.
    """
    resolved_base = (base_dir or Path("data")).resolve()
    day = (stamp or datetime.now(tz=UTC)).strftime("%Y-%m-%d")
    return ensure_ledger_root(resolved_base / "telemetry" / "runs" / day)


@dataclass(slots=True, frozen=True)
class RunLedger:
    """Append-only JSONL ledger scoped to a single run."""

    run_id: str
    session_id: str | None
    path: Path
    _handle: io.TextIOWrapper | None = None

    def _set_attr(self, **changes: object) -> None:
        for key, value in changes.items():
            object.__setattr__(self, key, value)  # noqa: PLC2801

    @classmethod
    def open(cls, root_dir: Path, *, run_id: str, session_id: str | None) -> RunLedger:
        """Return a ledger instance for ``run_id`` rooted under ``root_dir``.

        Parameters
        ----------
        root_dir : Path
            Base directory for ledger storage. The ledger file is created under
            a date-segmented subdirectory.
        run_id : str
            Unique identifier for the run. Used as part of the ledger filename.
        session_id : str | None
            Optional session identifier for partitioning ledgers. If None,
            uses "anonymous" as the session identifier.

        Returns
        -------
        RunLedger
            Open ledger bound to the provided run/session identifiers.
        """
        ensure_ledger_root(root_dir)
        path = root_dir / f"{run_id}.jsonl"
        handle = path.open("a", encoding="utf-8")
        return cls(run_id=run_id, session_id=session_id, path=path, _handle=handle)

    def append(self, record: Mapping[str, Any]) -> None:
        """Append a JSON record to the ledger."""
        handle = self._handle
        if handle is None:
            handle = self.path.open("a", encoding="utf-8")
            self._set_attr(_handle=handle)
        payload = {
            "run_id": self.run_id,
            "session_id": self.session_id,
            **dict(record),
        }
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()

    def close(self) -> None:
        """Flush and close the ledger handle if it is open."""
        handle = self._handle
        if handle is None:
            return
        try:
            handle.flush()
        finally:
            handle.close()
            self._set_attr(_handle=None)
