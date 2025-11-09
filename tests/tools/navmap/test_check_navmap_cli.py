from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from tools.navmap import check_navmap


def _read_envelope(path: Path) -> dict[str, Any]:
    payload = path.read_text(encoding="utf-8")
    return cast("dict[str, Any]", json.loads(payload))


@pytest.fixture(name="index_path")
def _index_path_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(check_navmap, "CLI_ENVELOPE_DIR", tmp_path)
    index_path = tmp_path / "navmap.json"
    monkeypatch.setattr(check_navmap, "INDEX", index_path)
    return index_path


def test_main_emits_success_envelope(
    monkeypatch: pytest.MonkeyPatch, index_path: Path
) -> None:
    def fake_collect() -> list[str]:
        return []

    def fake_build_index(*, json_path: Path | None = None) -> dict[str, object]:
        target = json_path or index_path
        target.write_text("{}", encoding="utf-8")
        return {"modules": {}}

    def fake_round_trip(_index: dict[str, object]) -> list[str]:
        return []

    monkeypatch.setattr(check_navmap, "_collect_module_errors", fake_collect)
    monkeypatch.setattr(check_navmap, "build_index", fake_build_index)
    monkeypatch.setattr(check_navmap, "_round_trip_errors", fake_round_trip)

    exit_code = check_navmap.main([])

    assert exit_code == 0
    envelope_path = check_navmap.CLI_ENVELOPE_DIR / "tools-navmap-navmap-check.json"
    envelope = _read_envelope(envelope_path)
    assert envelope["status"] == "success"
    files = cast("list[dict[str, Any]]", envelope["files"])
    assert any(entry.get("path") == str(index_path) for entry in files)


def test_main_records_validation_failure(
    monkeypatch: pytest.MonkeyPatch, index_path: Path
) -> None:
    def fake_collect() -> list[str]:
        return ["module.py: missing __navmap__"]

    monkeypatch.setattr(check_navmap, "_collect_module_errors", fake_collect)

    exit_code = check_navmap.main([])

    assert exit_code == 1
    envelope_path = check_navmap.CLI_ENVELOPE_DIR / "tools-navmap-navmap-check.json"
    envelope = _read_envelope(envelope_path)
    assert envelope["status"] == "violation"
    problem = cast("dict[str, Any]", envelope["problem"])
    assert problem["type"] == "https://kgfoundry.dev/problems/navmap/check"
    assert problem["status"] == 422
    assert problem["error_count"] == 1
    assert problem["errors"] == ["module.py: missing __navmap__"]
    assert problem["index_path"] == str(index_path)
