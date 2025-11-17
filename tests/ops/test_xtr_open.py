"""Tests for the XTR runtime ops CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from codeintel_rev.config.settings import Settings
from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.ops.runtime.xtr_open import APP, XtrOpenContext
from typer.testing import CliRunner

from tests._helpers import assertions

RUNNER = CliRunner(mix_stderr=False)


class _PathsWrapper:
    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def xtr_dir(self) -> Path:
        return self._root


def _settings_factory(*, enabled: bool) -> Callable[[], Settings]:
    settings_ns = SimpleNamespace(xtr=SimpleNamespace(enable=enabled, dtype="float32"))
    settings = cast("Settings", settings_ns)

    def _factory() -> Settings:
        return settings

    return _factory


class _ReadyIndex:
    def __init__(self, *_: object, **__: object) -> None:
        self.ready = True

    @staticmethod
    def open() -> None:
        """No-op open."""

    @staticmethod
    def metadata() -> dict[str, object]:
        return {"doc_count": 1, "total_tokens": 4, "dim": 8, "dtype": "float16"}


class _ExplodingIndex:
    def __init__(self, *_: object, **__: object) -> None:
        self.ready = False

    @staticmethod
    def open() -> None:
        message = "boom"
        raise RuntimeError(message)

    @staticmethod
    def metadata() -> dict[str, object]:
        return {}


def test_xtr_open_disabled_feature(
    tmp_path: Path,
    xtr_cli_context_builder: Callable[..., XtrOpenContext],
) -> None:
    """Verify XTR open returns ready=False when feature is disabled."""
    context = xtr_cli_context_builder(
        settings_factory=_settings_factory(enabled=False),
        paths_resolver=lambda _settings: _PathsWrapper(tmp_path),
    )
    result = RUNNER.invoke(
        APP,
        [],
        obj={"xtr_cli_context": context},
    )
    assertions.expect_equal(result.exit_code, 0, reason=result.stderr or result.stdout)
    payload = json.loads(result.stdout.strip())
    assertions.expect_equal(payload, {"ready": False, "limits": ["xtr disabled"]})


def test_xtr_open_missing_artifacts(
    tmp_path: Path,
    xtr_cli_context_builder: Callable[..., XtrOpenContext],
) -> None:
    """Verify XTR open returns 503 when artifacts are missing."""
    missing_root = tmp_path / "nope"
    context = xtr_cli_context_builder(
        settings_factory=_settings_factory(enabled=True),
        paths_resolver=lambda _settings: _PathsWrapper(missing_root),
    )
    result = RUNNER.invoke(
        APP,
        [],
        obj={"xtr_cli_context": context},
    )
    assertions.expect_equal(result.exit_code, 1, reason=result.stderr or result.stdout)
    problem = json.loads(result.stderr.strip())
    assertions.expect_equal(problem["status"], 503)
    assertions.expect_equal(problem["title"], "XTR artifacts unavailable")


def test_xtr_open_success(
    tmp_path: Path,
    xtr_cli_context_builder: Callable[..., XtrOpenContext],
) -> None:
    """Verify XTR open succeeds when artifacts are present."""
    root = tmp_path / "xtr"
    root.mkdir()
    context = xtr_cli_context_builder(
        settings_factory=_settings_factory(enabled=True),
        paths_resolver=lambda _settings: _PathsWrapper(root),
        index_factory=lambda *_args, **_kwargs: cast("XTRIndex", _ReadyIndex()),
    )
    result = RUNNER.invoke(
        APP,
        ["--root", str(root)],
        obj={"xtr_cli_context": context},
    )
    assertions.expect_equal(result.exit_code, 0, reason=result.stderr or result.stdout)
    payload = json.loads(result.stdout.strip())
    assertions.expect_true(payload["ready"], reason="ready should be True")
    assertions.expect_equal(payload["limits"], [])
    assertions.expect_equal(payload["metadata"]["chunks"], 1)


def test_xtr_open_reports_corruption(
    tmp_path: Path,
    xtr_cli_context_builder: Callable[..., XtrOpenContext],
) -> None:
    """Verify XTR open reports corruption errors correctly."""
    root = tmp_path / "xtr"
    root.mkdir()
    context = xtr_cli_context_builder(
        settings_factory=_settings_factory(enabled=True),
        paths_resolver=lambda _settings: _PathsWrapper(root),
        index_factory=lambda *_args, **_kwargs: cast("XTRIndex", _ExplodingIndex()),
    )
    result = RUNNER.invoke(
        APP,
        [],
        obj={"xtr_cli_context": context},
    )
    assertions.expect_equal(result.exit_code, 1, reason=result.stderr or result.stdout)
    problem = json.loads(result.stderr.strip())
    assertions.expect_equal(problem["title"], "Failed to open XTR artifacts")
