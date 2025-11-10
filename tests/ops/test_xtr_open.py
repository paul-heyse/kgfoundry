"""Tests for the XTR runtime ops CLI."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from codeintel_rev.ops.runtime.xtr_open import APP
from typer.testing import CliRunner

RUNNER = CliRunner(mix_stderr=False)


def _settings(*, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(xtr=SimpleNamespace(enable=enabled, dtype="float32"))


def _paths(root: Path) -> SimpleNamespace:
    return SimpleNamespace(xtr_dir=root)


def test_xtr_open_disabled_feature(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "codeintel_rev.ops.runtime.xtr_open.load_settings",
        lambda: _settings(enabled=False),
    )
    monkeypatch.setattr(
        "codeintel_rev.ops.runtime.xtr_open.resolve_application_paths",
        lambda _settings: _paths(tmp_path),
    )
    result = RUNNER.invoke(APP, [])
    assert result.exit_code == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload == {"ready": False, "limits": ["xtr disabled"]}


def test_xtr_open_missing_artifacts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing_root = tmp_path / "nope"
    monkeypatch.setattr(
        "codeintel_rev.ops.runtime.xtr_open.load_settings",
        lambda: _settings(enabled=True),
    )
    monkeypatch.setattr(
        "codeintel_rev.ops.runtime.xtr_open.resolve_application_paths",
        lambda _settings: _paths(missing_root),
    )
    result = RUNNER.invoke(APP, [])
    assert result.exit_code == 1, result.stderr or result.stdout
    problem = json.loads(result.stderr.strip())
    assert problem["status"] == 503
    assert problem["title"] == "XTR artifacts unavailable"


def test_xtr_open_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "xtr"
    root.mkdir()
    monkeypatch.setattr(
        "codeintel_rev.ops.runtime.xtr_open.load_settings",
        lambda: _settings(enabled=True),
    )
    monkeypatch.setattr(
        "codeintel_rev.ops.runtime.xtr_open.resolve_application_paths",
        lambda _settings: _paths(root),
    )

    class _StubIndex:
        def __init__(self, *_: object, **__: object) -> None:
            self.ready = True

        def open(self) -> None:
            return None

        def metadata(self) -> dict[str, object]:
            return {"doc_count": 1, "total_tokens": 4, "dim": 8, "dtype": "float16"}

    monkeypatch.setattr("codeintel_rev.ops.runtime.xtr_open.XTRIndex", _StubIndex)
    result = RUNNER.invoke(APP, ["--root", str(root)])
    assert result.exit_code == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip())
    assert payload["ready"] is True
    assert payload["limits"] == []
    assert payload["metadata"]["chunks"] == 1


def test_xtr_open_reports_corruption(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "xtr"
    root.mkdir()
    monkeypatch.setattr(
        "codeintel_rev.ops.runtime.xtr_open.load_settings",
        lambda: _settings(enabled=True),
    )
    monkeypatch.setattr(
        "codeintel_rev.ops.runtime.xtr_open.resolve_application_paths",
        lambda _settings: _paths(root),
    )

    class _ExplodingIndex:
        def __init__(self, *_: object, **__: object) -> None:
            self.ready = False

        def open(self) -> None:
            message = "boom"
            raise RuntimeError(message)

        def metadata(self) -> dict[str, object]:
            return {}

    monkeypatch.setattr("codeintel_rev.ops.runtime.xtr_open.XTRIndex", _ExplodingIndex)
    result = RUNNER.invoke(APP, [])
    assert result.exit_code == 1, result.stderr or result.stdout
    problem = json.loads(result.stderr.strip())
    assert problem["title"] == "Failed to open XTR artifacts"
