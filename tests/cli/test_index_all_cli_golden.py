"""Golden/help tests for the thin index_all Typer CLI."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from typer.testing import CliRunner

from tests._helpers import assertions
from tests._helpers.process import run_process


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _cli_path() -> Path:
    return _repo_root() / "codeintel_rev" / "bin" / "index_all.py"


def _load_cli_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("index_all_cli", _cli_path())
    if spec is None or spec.loader is None:
        message = "Unable to load CLI module spec."
        raise RuntimeError(message)
    loader = spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["index_all_cli"] = module
    loader.exec_module(module)
    return module


def _read_lines(path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8")
    return [line.rstrip("\n") for line in content.splitlines()]


def test_cli_import_does_not_load_heavy_dependencies() -> None:
    """Importing the CLI module should not pull FAISS/DuckDB/Arrow/Numpy."""
    forbidden = {"numpy", "faiss", "pyarrow", "duckdb"}
    before = set(sys.modules)
    _load_cli_module()
    after = set(sys.modules)
    newly_loaded = after - before
    offenders = sorted(name for name in newly_loaded if name.split(".", 1)[0] in forbidden)
    assertions.expect_equal(offenders, [], reason="CLI import pulled heavy dependencies")


def test_cli_help_matches_golden_markers() -> None:
    """Ensure the `all --help` output retains expected markers."""
    module = _load_cli_module()
    runner = CliRunner()
    result = runner.invoke(module.app, ["all", "--help"])
    assertions.expect_equal(result.exit_code, 0, reason=result.stdout)
    markers = _read_lines(_repo_root() / "tests" / "golden" / "cli" / "index_all_all_help.txt")
    for marker in markers:
        if marker:
            assertions.expect_in(marker, result.stdout, reason="Missing help marker")


def test_script_help_executes() -> None:
    """Running the script via python should emit usage text."""
    output = run_process([sys.executable, str(_cli_path()), "all", "--help"])
    assertions.expect_in("Usage:", output)
