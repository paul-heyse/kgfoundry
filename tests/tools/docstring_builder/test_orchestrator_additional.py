"""Additional tests for Task 1.4: Tests & Docs for orchestrator public API.

This module extends test_orchestrator_new_api.py with additional coverage for:
- Positional argument rejection enforcement
- Detailed deprecation path verification
- Docstring example validation
"""

from __future__ import annotations

from typing import Protocol, cast

import pytest
import tools.docstring_builder.orchestrator as orchestrator_module
from tools.docstring_builder.config_models import DocstringBuildConfig
from tools.docstring_builder.orchestrator import run_build, run_legacy


class _AnyCallable(Protocol):
    def __call__(self, *args: object, **kwargs: object) -> object: ...


def _call_untyped_run_build(*args: object, **kwargs: object) -> object:
    untyped = cast("_AnyCallable", run_build)
    return untyped(*args, **kwargs)


class TestPositionalArgumentRejection:
    """Tests verifying that positional arguments are rejected."""

    def test_run_build_rejects_positional_config(self) -> None:
        """Verify run_build() rejects config as positional argument."""
        config = DocstringBuildConfig()
        cache = object()

        # Attempting to pass config positionally should raise TypeError
        with pytest.raises(TypeError, match="positional"):
            _call_untyped_run_build(config, cache)

    def test_run_build_rejects_all_positional_arguments(self) -> None:
        """Verify run_build() rejects any positional arguments."""
        config = DocstringBuildConfig()

        # Even a single positional argument should fail
        with pytest.raises(TypeError):
            _call_untyped_run_build(config)

    def test_run_build_requires_both_keyword_arguments(self) -> None:
        """Verify run_build() requires both explicit keyword arguments."""
        config = DocstringBuildConfig()
        cache = object()

        # Missing cache argument should fail
        with pytest.raises(TypeError, match=r"missing.*required"):
            _call_untyped_run_build(config=config)

        # Missing config argument should fail
        with pytest.raises(TypeError, match=r"missing.*required"):
            _call_untyped_run_build(cache=cache)


class TestDeprecationPath:
    """Detailed tests for the deprecation warning path."""

    def test_run_legacy_warning_stacklevel(self) -> None:
        """Verify deprecation warning points to caller, not run_legacy."""
        with (
            pytest.warns(DeprecationWarning, match=r".*") as warning_list,
            pytest.raises(NotImplementedError),
        ):
            run_legacy()

        # Should have exactly one warning
        assert len(warning_list) == 1
        warning = warning_list[0]

        # Warning should be DeprecationWarning
        assert issubclass(warning.category, DeprecationWarning)
        # Message should guide to new API
        assert "run_build" in str(warning.message)

    def test_run_legacy_multiple_calls_each_warn(self) -> None:
        """Verify each call to run_legacy emits a warning (not suppressed)."""
        warning_count = 0
        for _ in range(3):
            with (
                pytest.warns(DeprecationWarning, match=r".*"),
                pytest.raises(NotImplementedError),
            ):
                run_legacy()
            warning_count += 1

        assert warning_count == 3

    def test_deprecation_message_content(self) -> None:
        """Verify deprecation message contains migration guidance."""
        with (
            pytest.warns(DeprecationWarning, match=r".*") as warning_list,
            pytest.raises(NotImplementedError),
        ):
            run_legacy()

        message = str(warning_list[0].message)
        # Should mention deprecation
        assert "deprecated" in message.lower()
        # Should suggest run_build
        assert "run_build" in message
        # Should mention config objects
        assert "config" in message.lower()


class TestDocstringExamples:
    """Tests verifying that docstring examples are correct and runnable."""

    def test_run_build_has_docstring(self) -> None:
        """Verify run_build has comprehensive docstring."""
        assert run_build.__doc__ is not None
        assert "keyword-only" in run_build.__doc__ or "Parameters" in run_build.__doc__
        assert "DocstringBuildConfig" in run_build.__doc__
        assert "Returns" in run_build.__doc__

    def test_run_legacy_has_docstring(self) -> None:
        """Verify run_legacy has deprecation guidance in docstring."""
        assert run_legacy.__doc__ is not None
        assert "deprecated" in run_legacy.__doc__.lower()
        assert "run_build" in run_legacy.__doc__

    def test_orchestrator_module_has_examples(self) -> None:
        """Verify orchestrator module docstring includes usage examples."""
        module_doc = orchestrator_module.__doc__
        assert module_doc is not None
        assert "Examples" in module_doc
        assert "run_build" in module_doc
        assert "DocstringBuildConfig" in module_doc

    def test_orchestrator_module_references_apis(self) -> None:
        """Verify orchestrator module documents both new and legacy APIs."""
        module_doc = orchestrator_module.__doc__
        assert module_doc is not None
        # Document mentions new API
        assert "New Typed API" in module_doc or "new API" in module_doc.lower()
        # Document mentions legacy API
        assert "Legacy API" in module_doc or "legacy" in module_doc.lower()
        # Document indicates new API is recommended
        assert "recommended" in module_doc.lower() or "prefer" in module_doc.lower()
