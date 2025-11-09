from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from tools.navmap import build_navmap


def _read_envelope(path: Path) -> dict[str, Any]:
    payload = path.read_text(encoding="utf-8")
    return cast("dict[str, Any]", json.loads(payload))


@pytest.fixture(name="_reset_paths")
def _reset_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(build_navmap, "CLI_ENVELOPE_DIR", tmp_path)
    monkeypatch.setattr(build_navmap, "NAVMAP_DIFF_PATH", tmp_path / "navmap.html")
    monkeypatch.setattr(build_navmap, "DRIFT_DIR", tmp_path)


@pytest.mark.usefixtures("_reset_paths")
def test_main_emits_success_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "navmap.json"

    def fake_build_index(
        *, _root: Path = build_navmap.SRC, json_path: Path | None = None
    ) -> dict[str, object]:
        target = json_path or destination
        target.write_text("{}", encoding="utf-8")
        return {"modules": {}}

    monkeypatch.setattr(build_navmap, "build_index", fake_build_index)
    monkeypatch.setattr(build_navmap, "_git_sha", lambda: "deadbeef")

    exit_code = build_navmap.main(["--write", str(destination)])

    assert exit_code == 0
    envelope_path = build_navmap.CLI_ENVELOPE_DIR / "tools-navmap-navmap-build.json"
    envelope = _read_envelope(envelope_path)
    assert envelope["status"] == "success"
    files = cast("list[dict[str, Any]]", envelope["files"])
    assert any(entry.get("path") == str(destination) for entry in files)


@pytest.mark.usefixtures("_reset_paths")
def test_main_records_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_build_index(
        *, _root: Path = build_navmap.SRC, json_path: Path | None = None
    ) -> dict[str, object]:
        _ = json_path
        message = "boom"
        raise RuntimeError(message)

    monkeypatch.setattr(build_navmap, "build_index", fake_build_index)
    monkeypatch.setattr(build_navmap, "_git_sha", lambda: "deadbeef")

    exit_code = build_navmap.main(["--write", str(tmp_path / "navmap.json")])

    assert exit_code == 1
    envelope_path = build_navmap.CLI_ENVELOPE_DIR / "tools-navmap-navmap-build.json"
    envelope = _read_envelope(envelope_path)
    assert envelope["status"] == "error"
    problem = cast("dict[str, Any]", envelope["problem"])
    assert problem["type"] == "https://kgfoundry.dev/problems/navmap/build"
