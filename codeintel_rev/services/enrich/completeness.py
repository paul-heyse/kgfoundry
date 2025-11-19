"""Service wrapper for completeness validation."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.enrich.validation.completeness import (
    report_completeness,
    write_report,
)


def run_completeness_audit(
    repo_root: Path,
    modules_jsonl: Path,
    out_path: Path,
) -> Path:
    """Run completeness validation and write the JSON report.

    Parameters
    ----------
    repo_root : Path
        Repository root directory path.
    modules_jsonl : Path
        Path to the modules JSONL file to analyze.
    out_path : Path
        Output file path for the JSON report.

    Returns
    -------
    Path
        The resolved output path that was written.
    """
    repo_root = repo_root.resolve()
    modules_jsonl = modules_jsonl.resolve()
    out_path = out_path.resolve()
    report = report_completeness(repo_root, modules_jsonl)
    write_report(out_path, report)
    return out_path


__all__ = ["run_completeness_audit"]
