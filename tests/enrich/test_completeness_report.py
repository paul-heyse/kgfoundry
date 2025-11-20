"""Tests for completeness validation service."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.enrich.output_writers import write_jsonl
from codeintel_rev.enrich.validation.completeness import (
    CompletenessReport,
    report_completeness,
    write_report,
)

from tests._helpers import assertions
from tests.enrich._completeness_utils import normalize_payload


def _emit_modules_jsonl(path: Path, mods: list[str]) -> None:
    """Emit modules JSONL file with test modules.

    Parameters
    ----------
    path : Path
        Output JSONL file path.
    mods : list[str]
        Module names to include.
    """
    rows = [{"module_name": mod, "path": f"{mod.replace('.', '/')}.py"} for mod in mods]
    write_jsonl(path, rows, writer_version="v2")


def test_report_completeness(tmp_path: Path) -> None:
    """Verify completeness report highlights missing/extra modules and issues."""
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text(
        "from ... import outside\nfrom pkg import missing\n", encoding="utf-8"
    )
    (pkg / "b.py").write_text("from pkg import a\n", encoding="utf-8")
    sub = pkg / "sub"
    sub.mkdir()
    (sub / "module.py").write_text("value = 1\n", encoding="utf-8")

    modules_jsonl = tmp_path / "modules.jsonl"
    _emit_modules_jsonl(modules_jsonl, ["pkg.a", "pkg.extra"])

    report = report_completeness(repo, modules_jsonl)

    assertions.expect_true(isinstance(report, CompletenessReport))
    payload = {
        "missing_modules": report.missing_modules,
        "extra_modules": report.extra_modules,
        "unresolved_local_imports": report.unresolved_local_imports,
        "invalid_relative_imports": report.invalid_relative_imports,
        "missing_package_inits": report.missing_package_inits,
        "impacts": report.impacts,
    }
    normalized = normalize_payload(payload)
    golden = Path("tests/golden/enrich/completeness/expected_report.json")
    expected = json.loads(golden.read_text(encoding="utf-8"))
    assertions.expect_equal(normalized, normalize_payload(expected))


def test_write_report(tmp_path: Path) -> None:
    """Ensure completeness reports can be written to disk."""
    target = tmp_path / "report.json"
    report = CompletenessReport(
        missing_modules=["pkg.a"],
        extra_modules=[],
        unresolved_local_imports=[],
        invalid_relative_imports=[],
        missing_package_inits=[],
        impacts={"pkg.a": []},
    )
    write_report(target, report)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assertions.expect_equal(payload["missing_modules"], ["pkg.a"])
