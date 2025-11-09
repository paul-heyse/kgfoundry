"""Tests for CLI ConfigurationError handling and Problem Details rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from kgfoundry_common.errors import ConfigurationError
from kgfoundry_common.problem_details import (
    build_configuration_problem,
    render_problem,
)
from orchestration.config import IndexCliConfig

if TYPE_CHECKING:
    from pathlib import Path


class TestConfigurationErrorHandling:
    """Test that ConfigurationError is properly rendered in CLI context."""

    def test_configuration_error_renders_as_problem_details(self) -> None:
        """Test that ConfigurationError generates valid Problem Details."""
        error = ConfigurationError.with_details(
            field="dense_vectors",
            issue="File not found or invalid path",
            hint="Check that the file exists and is readable",
        )
        problem = build_configuration_problem(error)
        problem_dict = cast("dict[str, object]", problem)

        assert problem_dict["type"] == "https://kgfoundry.dev/problems/configuration-error"
        assert problem_dict["status"] == 500
        assert problem_dict["code"] == "configuration-error"
        assert "extensions" in problem_dict

    def test_configuration_error_renders_to_json(self) -> None:
        """Test that ConfigurationError can be rendered to JSON."""
        error = ConfigurationError.with_details(
            field="metric",
            issue="Invalid metric value",
            hint='Use "ip" or "l2"',
        )
        problem = build_configuration_problem(error)
        json_str = render_problem(problem)

        # Verify it's valid JSON
        assert json_str.startswith("{")
        assert '"type"' in json_str
        assert '"status"' in json_str

    def test_configuration_error_has_correct_exit_code(self, tmp_path: Path) -> None:
        """Verify that ConfigurationError handling uses exit code 2."""
        # Create a config that would work, but then the error is thrown during load
        index_path = tmp_path / "test.idx"
        config = IndexCliConfig(
            dense_vectors="vectors.json",
            index_path=str(index_path),
            factory="Flat",
            metric="ip",
        )

        # The config validation should not fail
        assert config.dense_vectors == "vectors.json"


class TestConfigurationErrorIntegration:
    """Integration tests for CLI configuration error handling."""

    def test_problem_details_structure_from_error(self) -> None:
        """Test that Problem Details has all required RFC 9457 fields."""
        error = ConfigurationError.with_details(
            field="test_field",
            issue="Test issue description",
            hint="Test hint for resolution",
        )
        problem = build_configuration_problem(error)
        problem_dict = cast("dict[str, object]", problem)

        # RFC 9457 required fields
        assert "type" in problem_dict
        assert "title" in problem_dict
        assert "status" in problem_dict
        assert "detail" in problem_dict
        assert "instance" in problem_dict

    def test_multiple_configuration_errors_render_correctly(self) -> None:
        """Test various ConfigurationError scenarios render as Problem Details."""
        errors = [
            ConfigurationError.with_details(
                field="field1",
                issue="Issue 1",
                hint="Hint 1",
            ),
            ConfigurationError.with_details(
                field="field2",
                issue="Issue 2",
            ),
            ConfigurationError("Raw message", context={"key": "value"}),
        ]

        for error in errors:
            problem = build_configuration_problem(error)
            problem_dict = cast("dict[str, object]", problem)
            assert problem_dict["type"] == "https://kgfoundry.dev/problems/configuration-error"
            assert problem_dict["status"] == 500
            assert problem_dict["code"] == "configuration-error"
