# ruff: noqa: S101 - pytest-style assertions are intentional.
"""CLI tests for the completeness audit command."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from codeintel_rev.cli.enrich.__main__ import app  # noqa: PLC2701
from typer.testing import CliRunner

from tests.enrich._completeness_utils import normalize_payload

FIXTURE_ROOT = Path("tests/golden/enrich/completeness/fixture_repo")
GOLDEN_REPORT = Path("tests/golden/enrich/completeness/expected_report.json")
GOLDEN_MODULES = Path("tests/golden/enrich/completeness/modules.jsonl")


def _prepare_repo(dst: Path) -> Path:
    """Copy the completeness fixture repo into ``dst``.

    Returns
    -------
    Path
        Path to the copied repository.
    """
    shutil.copytree(FIXTURE_ROOT, dst)
    return dst


def test_cli_audit_golden(tmp_path: Path) -> None:
    """CLI audit should match the golden completeness report."""
    runner = CliRunner()
    repo = _prepare_repo(tmp_path / "repo")
    modules_path = tmp_path / "modules.jsonl"
    shutil.copy2(GOLDEN_MODULES, modules_path)
    out_path = tmp_path / "report.json"

    result = runner.invoke(
        app,
        [
            "audit",
            "--repo-root",
            str(repo),
            "--modules-jsonl",
            str(modules_path),
            "--out",
            str(out_path),
        ],
    )

    assert result.exit_code == 0, result.output
    produced = json.loads(out_path.read_text(encoding="utf-8"))
    expected = json.loads(GOLDEN_REPORT.read_text(encoding="utf-8"))
    assert normalize_payload(produced) == normalize_payload(expected)
