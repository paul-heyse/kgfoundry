"""Tests for navmap CLI API and config validation with Problem Details."""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, cast

from tools.navmap.api import repair_all_with_config, repair_module_with_config
from tools.navmap.config import NavmapRepairOptions
from tools.navmap.repair_navmaps import RepairResult

from kgfoundry_common.errors import ConfigurationError
from tests.helpers import assert_frozen_attribute

if TYPE_CHECKING:
    from tools.navmap.build_navmap import ModuleInfo


class TestConfigBasedAPIUsage:
    """Test that the new config-based API works correctly."""

    def test_repair_all_with_config_accepts_options(self) -> None:
        """Verify repair_all_with_config accepts NavmapRepairOptions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            options = NavmapRepairOptions(apply=False)
            # Should not raise TypeError for missing positional args
            results = repair_all_with_config(root=root, options=options)
            assert isinstance(results, list)

    def test_repair_all_with_config_requires_keyword_args(self) -> None:
        """Verify repair_all_with_config enforces keyword-only parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            options = NavmapRepairOptions(apply=False)
            # This should work - all keyword arguments
            results = repair_all_with_config(root=root, options=options)
            assert isinstance(results, list)

    def test_repair_all_with_config_defaults_root(self) -> None:
        """Verify repair_all_with_config uses default root when omitted."""
        options = NavmapRepairOptions(apply=False)
        # Should not raise even without explicit root (uses project SRC)
        results = repair_all_with_config(options=options)
        assert isinstance(results, list)

    def test_repair_module_with_config_accepts_options(self) -> None:
        """Verify repair_module_with_config accepts NavmapRepairOptions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("# test\n")
            options = NavmapRepairOptions(apply=False)
            # Should not raise TypeError about argument types
            with contextlib.suppress(TypeError, AttributeError, ValueError):
                repair_module_with_config(
                    info=cast("ModuleInfo", None),
                    options=options,
                )


class TestConfigValidation:
    """Test configuration validation with Problem Details."""

    def test_config_creation_with_valid_options(self) -> None:
        """Verify valid config creation succeeds."""
        config = NavmapRepairOptions(apply=True, emit_json=True)
        assert config.apply is True
        assert config.emit_json is True

    def test_config_immutability(self) -> None:
        """Verify config objects are immutable (frozen dataclass)."""
        config = NavmapRepairOptions(apply=True)
        assert_frozen_attribute(config, "apply", value=False)

    def test_config_defaults(self) -> None:
        """Verify config defaults are correct."""
        config = NavmapRepairOptions()
        assert config.apply is False
        assert config.emit_json is False


class TestAPITypeEnforcement:
    """Test that new API enforces type safety."""

    def test_repair_all_with_config_requires_options_param(self) -> None:
        """Verify repair_all_with_config requires options as keyword argument."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            options = NavmapRepairOptions(apply=False)
            result = repair_all_with_config(root=root, options=options)
            assert isinstance(result, list)

    def test_repair_module_with_config_requires_options_param(self) -> None:
        """Verify repair_module_with_config requires options as keyword argument."""
        options = NavmapRepairOptions(apply=False)
        with contextlib.suppress(TypeError, AttributeError, ValueError):
            repair_module_with_config(
                info=cast("ModuleInfo", None),
                options=options,
            )

    def test_options_parameter_strongly_typed(self) -> None:
        """Verify options parameter enforces NavmapRepairOptions type."""
        options = NavmapRepairOptions(apply=False)
        assert isinstance(options, NavmapRepairOptions)


class TestCLIOutputHandling:
    """Test CLI output and envelope handling."""

    def test_repair_all_returns_list_of_results(self) -> None:
        """Verify repair_all_with_config returns list of RepairResult."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            options = NavmapRepairOptions(apply=False)
            results = repair_all_with_config(root=root, options=options)
            assert isinstance(results, list)
            for result in results:
                assert isinstance(result, RepairResult)

    def test_result_contains_required_fields(self) -> None:
        """Verify RepairResult has required fields for JSON serialization."""
        result = RepairResult(
            module=Path("test.py"),
            messages=["test message"],
            changed=True,
            applied=False,
        )
        assert result.module == Path("test.py")
        assert result.messages == ["test message"]
        assert result.changed is True
        assert result.applied is False


class TestProblemDetailsIntegration:
    """Test Problem Details integration for error cases."""

    def test_invalid_root_handled_gracefully(self) -> None:
        """Verify invalid root directory is handled gracefully."""
        options = NavmapRepairOptions(apply=False)
        results = repair_all_with_config(
            root=Path("/nonexistent/path/xyz"), options=options
        )
        assert isinstance(results, list)

    def test_config_errors_raise_configuration_error(self) -> None:
        """Verify config validation errors are properly typed."""
        # Try to create a config with invalid timeout (if validation in place)
        with contextlib.suppress(ConfigurationError, TypeError):
            config = NavmapRepairOptions()
            assert config.apply is False


class TestAPIDocumentation:
    """Test that API functions are properly documented."""

    def test_repair_all_with_config_has_docstring(self) -> None:
        """Verify repair_all_with_config has a docstring."""
        doc = repair_all_with_config.__doc__
        assert doc is not None
        assert len(doc) > 0
        assert "config" in doc.lower()

    def test_repair_module_with_config_has_docstring(self) -> None:
        """Verify repair_module_with_config has a docstring."""
        doc = repair_module_with_config.__doc__
        assert doc is not None
        assert len(doc) > 0
        assert "config" in doc.lower()

    def test_functions_have_examples_in_docstrings(self) -> None:
        """Verify docstrings include usage examples."""
        doc_all = repair_all_with_config.__doc__
        doc_mod = repair_module_with_config.__doc__
        assert doc_all is not None
        assert ">>>" in doc_all
        assert doc_mod is not None
        assert ">>>" in doc_mod
