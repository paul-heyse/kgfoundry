# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TypeFileSummary:
    file: str
    error_count: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class TypeSummary:
    by_file: dict[str, TypeFileSummary] = field(default_factory=dict)


def _try_run(cmd: str, cwd: str | None = None, timeout: int = 90) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            shlex.split(cmd),
            check=False, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            timeout=timeout,
            text=True,
        )
        return p.returncode, p.stdout, p.stderr
    except Exception as exc:
        return 127, "", f"{exc!r}"


def collect_pyright(path: str | None = None) -> TypeSummary | None:
    """
    If pyright/basedpyright is available, run it with JSON output and collect errors per file.
    """
    for exe in ("pyright", "basedpyright"):
        code, out, err = _try_run(f"{exe} --outputjson", cwd=path or ".")
        if code == 0 and out.strip():
            try:
                j = json.loads(out)
            except Exception:
                continue
            summary = TypeSummary()
            for diag in j.get("generalDiagnostics", []):
                f = diag.get("file") or ""
                if not f:
                    continue
                entry = summary.by_file.setdefault(f, TypeFileSummary(file=f))
                entry.error_count += 1
            return summary
    return None


def collect_pyrefly(report_path: str | None) -> TypeSummary | None:
    """
    Parse a Pyrefly JSON/JSONL report if present.
    The CLI invocation can be orchestrated externally (CI) to write this file.
    """
    if not report_path:
        return None
    p = Path(report_path)
    if not p.exists():
        return None
    summary = TypeSummary()
    try:
        if p.suffix == ".jsonl":
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                j = json.loads(line)
                f = j.get("file") or j.get("path") or ""
                if not f:
                    continue
                entry = summary.by_file.setdefault(f, TypeFileSummary(file=f))
                if j.get("severity") == "error":
                    entry.error_count += 1
        else:
            j = json.loads(p.read_text(encoding="utf-8"))
            for item in j.get("results", []):
                f = item.get("file") or item.get("path") or ""
                entry = summary.by_file.setdefault(f, TypeFileSummary(file=f))
                if item.get("severity") == "error":
                    entry.error_count += 1
    except Exception:
        return None
    return summary
