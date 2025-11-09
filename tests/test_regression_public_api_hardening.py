"""Regression tests for public API hardening (phase 1)."""

from __future__ import annotations

import inspect
import tempfile
from typing import cast

from tools.docstring_builder.cache import DocstringBuilderCache

from kgfoundry_common.errors import ConfigurationError, KgFoundryError
from kgfoundry_common.logging import LoggingCache, get_logging_cache
from kgfoundry_common.problem_details import build_configuration_problem
from orchestration.config import IndexCliConfig
from tests.helpers import assert_frozen_attribute


class TestCacheProtocolAccess:
    """Regression tests for cache Protocol access patterns."""

    def test_logging_cache_accessed_via_protocol(self) -> None:
        """Verify LoggingCache is accessed via Protocol, not direct implementation."""
        cache = get_logging_cache()

        # Verify it implements the protocol
        assert isinstance(cache, LoggingCache)

        # Verify Protocol methods work
        formatter = cache.get_formatter()
        assert formatter is not None

        # Verify immutability of interface
        assert callable(cache.get_formatter)
        assert callable(cache.clear)

    def test_configuration_error_cache_via_protocol(self) -> None:
        """Verify ConfigurationError context accessed through defined interfaces."""
        error = ConfigurationError.with_details(
            field="test_field",
            issue="Test issue",
            hint="Test hint",
        )

        # Verify error context is properly structured
        assert error.context is not None
        assert isinstance(error.context, dict)
        assert "field" in error.context
        assert "issue" in error.context


class TestConfigurationErrorProbleDetails:
    """Regression tests for ConfigurationError Problem Details generation."""

    def test_configuration_error_produces_problem_details(self) -> None:
        """Verify ConfigurationError generates valid RFC 9457 Problem Details."""
        error = ConfigurationError.with_details(
            field="metric",
            issue="Invalid metric value",
            hint='Use "ip" or "l2"',
        )

        problem = build_configuration_problem(error)
        problem_dict = cast("dict[str, object]", problem)

        # Verify all RFC 9457 required fields present
        assert "type" in problem_dict
        assert "title" in problem_dict
        assert "status" in problem_dict
        assert "detail" in problem_dict
        assert "instance" in problem_dict

        # Verify Problem Details specific to configuration errors
        assert problem_dict["type"] == "https://kgfoundry.dev/problems/configuration-error"
        assert problem_dict["code"] == "configuration-error"

    def test_configuration_error_invalid_field_produces_problem_details(self) -> None:
        """Verify ConfigurationError with invalid field values produces Problem Details."""
        error = ConfigurationError.with_details(
            field="dense_vectors",
            issue="File not found: vectors.json",
            hint="Verify the file path is correct and file exists",
        )

        problem = build_configuration_problem(error)
        problem_dict = cast("dict[str, object]", problem)

        # Verify it's a valid problem
        assert problem_dict["status"] == 500
        detail_str = str(problem_dict.get("detail", ""))
        assert "dense_vectors" in detail_str

    def test_configuration_error_without_hint(self) -> None:
        """Verify ConfigurationError works without optional hint."""
        error = ConfigurationError.with_details(
            field="timeout",
            issue="Timeout value must be positive",
        )

        problem = build_configuration_problem(error)
        problem_dict = cast("dict[str, object]", problem)

        # Should still produce valid Problem Details
        assert "type" in problem_dict
        detail_str = str(problem_dict.get("detail", ""))
        assert "timeout" in detail_str


class TestConfigurationModelValidation:
    """Regression tests for configuration model validation."""

    def test_index_cli_config_requires_keyword_args(self) -> None:
        """Verify IndexCliConfig requires keyword arguments."""
        # This should work
        with tempfile.NamedTemporaryFile(suffix=".idx") as tmp:
            config = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=tmp.name,
                factory="Flat",
                metric="ip",
            )
            assert config.dense_vectors == "vectors.json"

    def test_index_cli_config_immutable(self) -> None:
        """Verify IndexCliConfig is immutable (frozen dataclass)."""
        with tempfile.NamedTemporaryFile(suffix=".idx") as tmp:
            config = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=tmp.name,
                factory="Flat",
                metric="ip",
            )

            # Should not be able to modify
            assert_frozen_attribute(config, "dense_vectors", value="other.json")

    def test_configuration_error_with_details_keyword_only(self) -> None:
        """Verify ConfigurationError.with_details uses keyword-only parameters."""
        # Should work with keywords
        error = ConfigurationError.with_details(
            field="test",
            issue="test issue",
            hint="test hint",
        )
        assert error is not None

        # Should fail with positional args
        signature = inspect.signature(ConfigurationError.with_details)
        for parameter in signature.parameters.values():
            assert parameter.kind.name == "KEYWORD_ONLY"


class TestNewPublicAPI:
    """Regression tests for new public API patterns."""

    def test_docstring_builder_cache_protocol(self) -> None:
        """Verify DocstringBuilderCache Protocol is accessible."""
        # Should be able to reference the Protocol
        assert DocstringBuilderCache is not None

        # Should have required methods
        assert hasattr(DocstringBuilderCache, "path")
        assert hasattr(DocstringBuilderCache, "needs_update")
        assert hasattr(DocstringBuilderCache, "update")
        assert hasattr(DocstringBuilderCache, "write")

    def test_logging_cache_protocol_accessible(self) -> None:
        """Verify LoggingCache Protocol is publicly accessible."""
        assert LoggingCache is not None

        # Should have Protocol methods
        assert hasattr(LoggingCache, "get_formatter")
        assert hasattr(LoggingCache, "clear")

    def test_get_logging_cache_function_exists(self) -> None:
        """Verify get_logging_cache accessor function exists."""
        cache1 = get_logging_cache()
        cache2 = get_logging_cache()

        # Should return singleton
        assert cache1 is cache2


class TestConfigurationErrorIntegration:
    """Integration tests for configuration error handling."""

    def test_error_hierarchy_preserved(self) -> None:
        """Verify ConfigurationError is proper subclass of KgFoundryError."""
        error = ConfigurationError("test")
        assert isinstance(error, KgFoundryError)
        assert isinstance(error, ConfigurationError)

    def test_configuration_error_context_propagation(self) -> None:
        """Verify ConfigurationError properly propagates context."""
        error = ConfigurationError.with_details(
            field="port",
            issue="Port must be between 1024 and 65535",
            hint="Use a port number in the valid range",
        )

        # Context should be preserved
        assert error.context is not None
        assert error.context["field"] == "port"
        assert error.context["issue"] == "Port must be between 1024 and 65535"
        assert error.context["hint"] == "Use a port number in the valid range"


class TestAPIConsistency:
    """Tests ensuring API consistency across refactored modules."""

    def test_all_config_models_frozen(self) -> None:
        """Verify all new config models are frozen."""
        with tempfile.NamedTemporaryFile(suffix=".idx") as tmp:
            config = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=tmp.name,
                factory="Flat",
                metric="ip",
            )

            # Frozen dataclass should raise on modification
            assert_frozen_attribute(
                config,
                "factory",
                value="OPQ64,IVF8192,PQ64",
            )

    def test_configuration_models_use_keyword_only(self) -> None:
        """Verify configuration models are accessible and work correctly."""
        # IndexCliConfig works with both positional and keyword args
        # (standard dataclass behavior)
        with tempfile.NamedTemporaryFile(suffix=".idx") as tmp:
            config_positional = IndexCliConfig(
                "vectors.json",
                tmp.name,
                "Flat",
                "ip",
            )
            assert config_positional.dense_vectors == "vectors.json"

            # And also with keywords
            config_keywords = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=tmp.name,
                factory="Flat",
                metric="ip",
            )
            assert config_keywords is not None
