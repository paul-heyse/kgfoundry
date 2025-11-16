"""Tests for the XTR runtime ops CLI."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from codeintel_rev.ops.runtime.xtr_open import APP
from typer.testing import CliRunner

from tests._helpers import assertions

RUNNER = CliRunner(mix_stderr=False)


def _settings(*, enabled: bool = True) -> SimpleNamespace:
    """Create mock settings with XTR enabled/disabled.

    Returns
    -------
    SimpleNamespace
        Mock settings object.
    """
    return SimpleNamespace(xtr=SimpleNamespace(enable=enabled, dtype="float32"))


def _paths(root: Path) -> SimpleNamespace:
    """Create mock paths with XTR directory.

    Returns
    -------
    SimpleNamespace
        Mock paths object.
    """
    return SimpleNamespace(xtr_dir=root)


def test_xtr_open_disabled_feature(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify XTR open returns ready=False when feature is disabled."""
    monkeypatch.setattr(
        "codeintel_rev.ops.runtime.xtr_open.load_settings",
        lambda: _settings(enabled=False),
    )
    monkeypatch.setattr(
        "codeintel_rev.ops.runtime.xtr_open.resolve_application_paths",
        lambda _settings: _paths(tmp_path),
    )
    result = RUNNER.invoke(APP, [])
    assertions.expect_equal(result.exit_code, 0, result.stderr or result.stdout)
    payload = json.loads(result.stdout.strip())
    assertions.expect_equal(payload, {"ready": False, "limits": ["xtr disabled"]})


def test_xtr_open_missing_artifacts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify XTR open returns 503 when artifacts are missing."""
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
    assertions.expect_equal(result.exit_code, 1, result.stderr or result.stdout)
    problem = json.loads(result.stderr.strip())
    assertions.expect_equal(problem["status"], 503)
    assertions.expect_equal(problem["title"], "XTR artifacts unavailable")


def test_xtr_open_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify XTR open succeeds when artifacts are present."""
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
    assertions.expect_equal(result.exit_code, 0, result.stderr or result.stdout)
    payload = json.loads(result.stdout.strip())
    assertions.expect_true(payload["ready"], reason="ready should be True")
    assertions.expect_equal(payload["limits"], [])
    assertions.expect_equal(payload["metadata"]["chunks"], 1)


def test_xtr_open_reports_corruption(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify XTR open reports corruption errors correctly."""
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
    assertions.expect_equal(result.exit_code, 1, result.stderr or result.stdout)
    problem = json.loads(result.stderr.strip())
    assertions.expect_equal(problem["title"], "Failed to open XTR artifacts")
