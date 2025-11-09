from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

build_graphs = importlib.import_module("tools.docs.build_graphs")


def _read_envelope(path: Path) -> dict[str, Any]:
    payload = path.read_text(encoding="utf-8")
    return cast("dict[str, Any]", json.loads(payload))


@pytest.fixture(name="cli_paths")
def _cli_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    envelope_dir = tmp_path / "cli"
    monkeypatch.setattr(build_graphs, "CLI_ENVELOPE_DIR", envelope_dir)
    graph_dir = tmp_path / "graphs"
    monkeypatch.setattr(build_graphs, "OUT", graph_dir)
    graph_dir.mkdir(parents=True, exist_ok=True)
    return envelope_dir


def test_main_emits_success_envelope(monkeypatch: pytest.MonkeyPatch, cli_paths: Path) -> None:
    monkeypatch.setattr(build_graphs, "_validate_runtime_dependencies", lambda: None)
    monkeypatch.setattr(build_graphs, "_resolve_packages", lambda _args: ["pkg1"])
    monkeypatch.setattr(
        build_graphs,
        "_prepare_cache",
        lambda _args: (cli_paths / "cache", True),
    )
    monkeypatch.setattr(build_graphs, "_log_configuration", lambda **_: None)
    monkeypatch.setattr(
        build_graphs,
        "_build_per_package_graphs",
        lambda _packages, _config, _max_workers: [("pkg1", False, True, True)],
    )
    monkeypatch.setattr(build_graphs, "_report_package_failures", lambda _results: None)
    monkeypatch.setattr(build_graphs, "_build_global_graph", lambda *_: object())
    monkeypatch.setattr(build_graphs, "_load_layers_config", lambda _: {})
    monkeypatch.setattr(build_graphs, "_load_allowlist", lambda _: {})
    monkeypatch.setattr(build_graphs, "analyze_graph", lambda *_, **__: {})
    monkeypatch.setattr(build_graphs, "_write_global_artifacts", lambda *_, **__: None)
    monkeypatch.setattr(build_graphs, "enforce_policy", lambda *_, **__: None)
    monkeypatch.setattr(build_graphs, "_log_run_summary", lambda **_: None)

    exit_code = build_graphs.main([])

    assert exit_code == 0
    envelope_path = cli_paths / (
        f"{build_graphs.CLI_SETTINGS.bin_name}-{build_graphs.CLI_COMMAND}-{build_graphs.SUBCOMMAND_BUILD_GRAPHS}.json"
    )
    envelope = _read_envelope(envelope_path)
    assert envelope["status"] == "success"
    files = cast("list[dict[str, Any]]", envelope["files"])
    assert any(entry.get("path") == str(build_graphs.OUT) for entry in files)


def test_main_records_validation_failure(monkeypatch: pytest.MonkeyPatch, cli_paths: Path) -> None:
    monkeypatch.setattr(build_graphs, "_validate_runtime_dependencies", lambda: None)
    monkeypatch.setattr(build_graphs, "_resolve_packages", lambda _args: ["pkg1"])

    def fake_prepare_cache(_args: Any) -> tuple[Path, bool]:
        message = "cache directory invalid"
        raise build_graphs.ValidationError(message)

    monkeypatch.setattr(build_graphs, "_prepare_cache", fake_prepare_cache)

    exit_code = build_graphs.main([])

    assert exit_code == 2
    envelope_path = cli_paths / (
        f"{build_graphs.CLI_SETTINGS.bin_name}-{build_graphs.CLI_COMMAND}-{build_graphs.SUBCOMMAND_BUILD_GRAPHS}.json"
    )
    envelope = _read_envelope(envelope_path)
    assert envelope["status"] == "config"
    problem = cast("dict[str, Any]", envelope["problem"])
    assert problem["status"] == 422
    assert "cache directory invalid" in cast("str", problem["detail"])
