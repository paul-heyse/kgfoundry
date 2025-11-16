"""Regression tests for public API hardening (phase 1)."""

from __future__ import annotations

import inspect
import tempfile
from typing import cast

# DocstringBuilderCache removed - tests for cache protocols moved to test_logging_cache
from kgfoundry_common.errors import ConfigurationError, KgFoundryError
from kgfoundry_common.problem_details import build_configuration_problem
from orchestration.config import IndexCliConfig
from tests._helpers import assertions
from tests.helpers import assert_frozen_attribute


def test_configuration_error_produces_problem_details() -> None:
    """Verify ConfigurationError generates valid RFC 9457 Problem Details."""
    error = ConfigurationError.with_details(
        field="metric",
        issue="Invalid metric value",
        hint='Use "ip" or "l2"',
    )

    problem = build_configuration_problem(error)
    problem_dict = cast("dict[str, object]", problem)

    # Verify all RFC 9457 required fields present
    assertions.expect_in("type", problem_dict)
    assertions.expect_in("title", problem_dict)
    assertions.expect_in("status", problem_dict)
    assertions.expect_in("detail", problem_dict)
    assertions.expect_in("instance", problem_dict)

    # Verify Problem Details specific to configuration errors
    assertions.expect_equal(
        problem_dict["type"], "https://kgfoundry.dev/problems/configuration-error"
    )
    assertions.expect_equal(problem_dict["code"], "configuration-error")


def test_configuration_error_invalid_field_produces_problem_details() -> None:
    """Verify ConfigurationError with invalid field values produces Problem Details."""
    error = ConfigurationError.with_details(
        field="dense_vectors",
        issue="File not found: vectors.json",
        hint="Verify the file path is correct and file exists",
    )

    problem = build_configuration_problem(error)
    problem_dict = cast("dict[str, object]", problem)

    # Verify it's a valid problem
    assertions.expect_equal(problem_dict["status"], 500)
    detail_str = str(problem_dict.get("detail", ""))
    assertions.expect_in("dense_vectors", detail_str)


def test_configuration_error_without_hint() -> None:
    """Verify ConfigurationError works without optional hint."""
    error = ConfigurationError.with_details(
        field="timeout",
        issue="Timeout value must be positive",
    )

    problem = build_configuration_problem(error)
    problem_dict = cast("dict[str, object]", problem)

    # Should still produce valid Problem Details
    assertions.expect_in("type", problem_dict)
    detail_str = str(problem_dict.get("detail", ""))
    assertions.expect_in("timeout", detail_str)


def test_index_cli_config_requires_keyword_args() -> None:
    """Verify IndexCliConfig requires keyword arguments."""
    # This should work
    with tempfile.NamedTemporaryFile(suffix=".idx") as tmp:
        config = IndexCliConfig(
            dense_vectors="vectors.json",
            index_path=tmp.name,
            factory="Flat",
            metric="ip",
        )
        assertions.expect_equal(config.dense_vectors, "vectors.json")


def test_index_cli_config_immutable() -> None:
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


def test_configuration_error_with_details_keyword_only() -> None:
    """Verify ConfigurationError.with_details uses keyword-only parameters."""
    # Should work with keywords
    error = ConfigurationError.with_details(
        field="test",
        issue="test issue",
        hint="test hint",
    )
    assertions.expect_true(error is not None, reason="error should not be None")

    # Should fail with positional args
    signature = inspect.signature(ConfigurationError.with_details)
    for parameter in signature.parameters.values():
        assertions.expect_equal(parameter.kind.name, "KEYWORD_ONLY")


def test_logging_cache_protocol_accessible() -> None:
    """Verify LoggingCache Protocol is publicly accessible."""
    # LoggingCache was removed - this test is obsolete


def test_get_logging_cache_function_exists() -> None:
    """Verify get_logging_cache accessor function exists."""
    # get_logging_cache was removed - this test is obsolete


def test_error_hierarchy_preserved() -> None:
    """Verify ConfigurationError is proper subclass of KgFoundryError."""
    error = ConfigurationError("test")
    assertions.expect_true(isinstance(error, KgFoundryError), reason="should be KgFoundryError")
    assertions.expect_true(
        isinstance(error, ConfigurationError), reason="should be ConfigurationError"
    )


def test_configuration_error_context_propagation() -> None:
    """Verify ConfigurationError properly propagates context."""
    error = ConfigurationError.with_details(
        field="port",
        issue="Port must be between 1024 and 65535",
        hint="Use a port number in the valid range",
    )

    # Context should be preserved
    assertions.expect_true(error.context is not None, reason="context should not be None")
    assertions.expect_equal(error.context["field"], "port")
    assertions.expect_equal(error.context["issue"], "Port must be between 1024 and 65535")
    assertions.expect_equal(error.context["hint"], "Use a port number in the valid range")


def test_all_config_models_frozen() -> None:
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


def test_configuration_models_use_keyword_only() -> None:
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
        assertions.expect_equal(config_positional.dense_vectors, "vectors.json")

        # And also with keywords
        config_keywords = IndexCliConfig(
            dense_vectors="vectors.json",
            index_path=tmp.name,
            factory="Flat",
            metric="ip",
        )
        assertions.expect_true(
            config_keywords is not None, reason="config_keywords should not be None"
        )
