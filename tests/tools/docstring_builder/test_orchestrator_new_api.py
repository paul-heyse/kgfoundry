"""Tests for the new public API of the docstring builder orchestrator.

This module tests the typed configuration-based API introduced in Phase 1.2 of the public API
hardening, verifying that run_build() and run_legacy() functions work correctly with the new
DocstringBuildConfig and cache interfaces.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import pytest
import tools.docstring_builder.orchestrator as orchestrator_module
from tools.docstring_builder.builder_types import DocstringBuildResult, ExitStatus
from tools.docstring_builder.cache import DocstringBuilderCache
from tools.docstring_builder.config import BuilderConfig, ConfigSelection
from tools.docstring_builder.config_models import CachePolicy, DocstringBuildConfig
from tools.docstring_builder.orchestrator import (
    run_build,
    run_docstring_builder,
    run_legacy,
)


class _AnyCallable(Protocol):
    def __call__(self, *args: object, **kwargs: object) -> object: ...


if TYPE_CHECKING:
    from tools.docstring_builder.builder_types import DocstringBuildRequest


def _call_untyped_run_build(*args: object, **kwargs: object) -> object:
    untyped = cast("_AnyCallable", run_build)
    return untyped(*args, **kwargs)


@dataclass(slots=True, frozen=True)
class _PipelineCapture:
    files: list[Path] = field(default_factory=list)
    request: DocstringBuildRequest | None = None
    config: BuilderConfig | None = None
    selection: ConfigSelection | None = None
    cache: DocstringBuilderCache | None = None
    plugins_enabled: bool | None = None


class RecordingCache(DocstringBuilderCache):
    """Test double implementing :class:`DocstringBuilderCache` for assertions."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self.needs_update_calls: list[tuple[Path, str]] = []
        self.update_calls: list[tuple[Path, str]] = []
        self.write_calls = 0
        self.next_needs_update = False

    @property
    def path(self) -> Path:
        return self._path

    def needs_update(self, file_path: Path, config_hash: str) -> bool:
        self.needs_update_calls.append((file_path, config_hash))
        return self.next_needs_update

    def update(self, file_path: Path, config_hash: str) -> None:
        self.update_calls.append((file_path, config_hash))

    def write(self) -> None:
        self.write_calls += 1


def _install_stubbed_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_PipelineCapture, DocstringBuildResult, BuilderConfig]:
    capture = _PipelineCapture()
    builder_config = BuilderConfig()
    config_selection = ConfigSelection(path=Path("docstring_builder.toml"), source="default")

    monkeypatch.setattr(
        orchestrator_module,
        "load_builder_config",
        lambda _override=None: (builder_config, config_selection),
    )
    monkeypatch.setattr(orchestrator_module, "select_files", lambda *_: [Path("src/module.py")])

    result = DocstringBuildResult(
        exit_status=ExitStatus.SUCCESS,
        errors=[],
        file_reports=[],
        observability_payload={},
        cli_payload=None,
        manifest_path=None,
        problem_details=None,
        config_selection=config_selection,
    )

    def fake_run_pipeline(
        invocation: orchestrator_module._PipelineInvocation,
    ) -> DocstringBuildResult:
        nonlocal capture
        capture = replace(
            capture,
            files=list(invocation.files),
            request=invocation.request,
            config=invocation.config,
            selection=invocation.selection,
            cache=invocation.cache,
            plugins_enabled=invocation.plugins_enabled,
        )
        return result

    monkeypatch.setattr(orchestrator_module, "_run_pipeline", fake_run_pipeline)
    return capture, result, builder_config


class TestRunBuild:
    """Tests for the new run_build() function."""

    def test_run_build_signature_requires_keyword_only(self) -> None:
        """Verify run_build() enforces keyword-only parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DocstringBuildConfig()
            cache = RecordingCache(Path(tmpdir) / "cache.json")

            # Should fail with positional args
            with pytest.raises(TypeError, match="positional argument"):
                _call_untyped_run_build(config, cache)

    def test_run_build_executes_pipeline(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """run_build() should execute the pipeline and return its result."""
        capture, expected_result, _builder_config = _install_stubbed_pipeline(monkeypatch)
        cache = RecordingCache(tmp_path / "cache.json")

        actual = run_build(config=DocstringBuildConfig(), cache=cache)

        assert actual is expected_result
        assert capture.files == [Path("src/module.py")]
        assert capture.request is not None
        assert capture.request.command == "update"
        assert capture.plugins_enabled is True
        assert capture.cache is not None

    def test_run_build_disables_plugins_when_configured(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Setting enable_plugins=False should disable plugin execution."""
        capture, _result, _builder_config = _install_stubbed_pipeline(monkeypatch)
        cache = RecordingCache(tmp_path / "cache.json")

        run_build(config=DocstringBuildConfig(enable_plugins=False), cache=cache)

        assert capture.plugins_enabled is False

    def test_run_build_sets_check_mode_for_diff(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """emit_diff=True should trigger check command with diff previews."""
        capture, _result, _builder_config = _install_stubbed_pipeline(monkeypatch)
        cache = RecordingCache(tmp_path / "cache.json")

        run_build(
            config=DocstringBuildConfig(enable_plugins=True, emit_diff=True),
            cache=cache,
        )

        assert capture.request is not None
        assert capture.request.command == "check"
        assert capture.request.diff is True

    def test_run_build_applies_cache_policy_adapter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Cache policy should wrap the provided cache when needed."""
        capture, _result, _builder_config = _install_stubbed_pipeline(monkeypatch)
        recording_cache = RecordingCache(tmp_path / "cache.json")

        run_build(
            config=DocstringBuildConfig(cache_policy=CachePolicy.DISABLED),
            cache=recording_cache,
        )

        adapted = capture.cache
        assert adapted is not None
        assert adapted is not recording_cache
        assert adapted.needs_update(Path("src/module.py"), "hash") is True
        assert recording_cache.needs_update_calls == []
        adapted.update(Path("src/module.py"), "hash2")
        assert recording_cache.update_calls == []
        adapted.write()
        assert recording_cache.write_calls == 0

    def test_run_build_enforces_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """run_build() should raise TimeoutError when execution exceeds limit."""
        builder_config = BuilderConfig()
        config_selection = ConfigSelection(path=Path("docstring_builder.toml"), source="default")

        monkeypatch.setattr(
            orchestrator_module,
            "load_builder_config",
            lambda _override=None: (builder_config, config_selection),
        )
        monkeypatch.setattr(
            orchestrator_module,
            "select_files",
            lambda *_: [Path("src/module.py")],
        )

        result = DocstringBuildResult(
            exit_status=ExitStatus.SUCCESS,
            errors=[],
            file_reports=[],
            observability_payload={},
            cli_payload=None,
            manifest_path=None,
            problem_details=None,
            config_selection=config_selection,
        )

        timeout_seconds = 1

        def slow_run_pipeline(
            _invocation: orchestrator_module._PipelineInvocation,
        ) -> DocstringBuildResult:
            time.sleep(timeout_seconds + 1)
            return result

        monkeypatch.setattr(orchestrator_module, "_run_pipeline", slow_run_pipeline)

        cache = RecordingCache(tmp_path / "cache.json")
        config = DocstringBuildConfig(timeout_seconds=timeout_seconds)

        with pytest.raises(TimeoutError, match="exceeded timeout"):
            run_build(config=config, cache=cache)


class TestRunLegacy:
    """Tests for the deprecation wrapper run_legacy()."""

    def test_run_legacy_emits_deprecation_warning(self) -> None:
        """Verify run_legacy() emits DeprecationWarning."""
        with (
            pytest.warns(DeprecationWarning, match="run_legacy.*deprecated"),
            pytest.raises(NotImplementedError),
        ):
            run_legacy()

    def test_run_legacy_warning_message_guides_migration(self) -> None:
        """Verify deprecation message guides users to new API."""
        with (
            pytest.warns(DeprecationWarning, match="Use run_build\\(config=.*\\) instead"),
            pytest.raises(NotImplementedError),
        ):
            run_legacy()

    def test_run_legacy_accepts_any_args(self) -> None:
        """Verify run_legacy() accepts arbitrary positional and keyword args."""
        # Should emit warning but not raise TypeError
        with (
            pytest.warns(DeprecationWarning, match="deprecated"),
            pytest.raises(NotImplementedError),
        ):
            run_legacy("arg1", "arg2", kwarg1="value1")

    def test_run_legacy_not_yet_implemented(self) -> None:
        """Verify run_legacy() raises NotImplementedError as placeholder."""
        with (
            pytest.warns(DeprecationWarning, match="deprecated"),
            pytest.raises(NotImplementedError, match="not yet fully implemented"),
        ):
            run_legacy()

    def test_run_legacy_warning_appears_once(self) -> None:
        """Verify deprecation warning appears for each call (not suppressed)."""
        # Each call should emit a warning
        for _ in range(2):
            with (
                pytest.warns(DeprecationWarning, match="deprecated"),
                pytest.raises(NotImplementedError),
            ):
                run_legacy()


class TestPublicAPIMigration:
    """Integration tests for migration from legacy to new API."""

    def test_both_apis_available(self) -> None:
        """Verify both run_docstring_builder and run_build are available."""
        assert callable(run_docstring_builder)
        assert callable(run_build)
        assert callable(run_legacy)

    def test_run_build_and_run_legacy_are_distinct(self) -> None:
        """Verify new and legacy APIs are separate functions."""
        assert run_build != run_legacy
        assert run_build.__doc__ != run_legacy.__doc__
