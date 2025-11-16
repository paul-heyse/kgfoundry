"""Tests for subprocess utilities with timeout and safety features."""

from __future__ import annotations

from collections import UserDict
from typing import TYPE_CHECKING

import pytest

from kgfoundry_common.subprocess_utils import (
    SubprocessError,
    SubprocessTimeoutError,
    run_subprocess,
)
from tests._helpers import assertions

if TYPE_CHECKING:
    from pathlib import Path


class TestSubprocessExecution:
    """Test suite for subprocess execution."""

    def test_simple_command_success(self) -> None:
        """Test successful simple command execution."""
        result = run_subprocess(["echo", "hello"], timeout=5)
        assertions.expect_true("hello" in result, reason="result should contain hello")

    def test_command_with_output(self) -> None:
        """Test command that produces output."""
        result = run_subprocess(
            ["python", "-c", "print('test output')"],
            timeout=10,
        )
        assertions.expect_true("test output" in result, reason="result should contain test output")

    def test_command_failure_raises_error(self) -> None:
        """Test that failed command raises SubprocessError."""
        with pytest.raises(SubprocessError) as exc_info:
            run_subprocess(
                ["python", "-c", "import sys; sys.exit(1)"],
                timeout=5,
            )
        assertions.expect_equal(exc_info.value.returncode, 1)

    def test_command_with_stderr(self) -> None:
        """Test that stderr is captured in error."""
        with pytest.raises(SubprocessError) as exc_info:
            run_subprocess(
                ["python", "-c", "import sys; sys.stderr.write('error'); sys.exit(1)"],
                timeout=5,
            )
        assertions.expect_true(
            exc_info.value.stderr is not None, reason="stderr should be captured"
        )

    def test_timeout_enforcement(self) -> None:
        """Test that timeout is enforced."""
        with pytest.raises(SubprocessTimeoutError):
            run_subprocess(
                ["python", "-c", "import time; time.sleep(10)"],
                timeout=1,
            )

    def test_timeout_error_has_details(self) -> None:
        """Test that timeout error contains useful details."""
        with pytest.raises(SubprocessTimeoutError) as exc_info:
            run_subprocess(
                ["sleep", "10"],
                timeout=1,
            )
        assertions.expect_equal(exc_info.value.timeout_seconds, 1)
        assertions.expect_true(exc_info.value.command is not None, reason="command should be set")

    def test_invalid_timeout_too_low(self) -> None:
        """Test that timeout < 1 is rejected."""
        with pytest.raises(ValueError, match="between"):
            run_subprocess(["echo", "test"], timeout=0)

    def test_invalid_timeout_too_high(self) -> None:
        """Test that timeout > 3600 is rejected."""
        with pytest.raises(ValueError, match="between"):
            run_subprocess(["echo", "test"], timeout=3601)

    def test_valid_timeout_boundaries(self) -> None:
        """Test that boundary timeout values are accepted."""
        # Minimum valid timeout
        result = run_subprocess(["echo", "test"], timeout=1)
        assertions.expect_true("test" in result, reason="result should contain test")

        # Maximum valid timeout
        result = run_subprocess(["echo", "test"], timeout=3600)
        assertions.expect_true("test" in result, reason="result should contain test")

    def test_timeout_none_uses_default(self) -> None:
        """Test that None timeout uses default."""
        result = run_subprocess(["echo", "test"], timeout=None)
        assertions.expect_true("test" in result, reason="result should contain test")


class TestWorkingDirectory:
    """Test suite for working directory handling."""

    def test_cwd_is_used(self, tmp_path: Path) -> None:
        """Test that cwd parameter is used."""
        # Create a test file in tmp_path
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        # List files in that directory
        result = run_subprocess(
            ["ls", "test.txt"],
            timeout=5,
            cwd=tmp_path,
        )
        assertions.expect_true("test.txt" in result, reason="result should contain test.txt")

    def test_cwd_resolved_to_absolute_path(self, tmp_path: Path) -> None:
        """Test that cwd is resolved to absolute path."""
        # Pass a relative-looking path (after resolution it's absolute)
        result = run_subprocess(
            ["pwd"],
            timeout=5,
            cwd=tmp_path,
        )
        # Should contain the absolute path
        assertions.expect_true(
            str(tmp_path.resolve()) in result or str(tmp_path) in result,
            reason="result should contain path",
        )

    def test_cwd_none_works(self) -> None:
        """Test that cwd=None (inherit parent cwd) works."""
        result = run_subprocess(["pwd"], timeout=5, cwd=None)
        assertions.expect_true(
            "/" in result, reason="result should contain path"
        )  # Should output a path


class TestEnvironmentVariables:
    """Test suite for environment variable handling."""

    def test_env_dict_passed(self) -> None:
        """Test that environment dict is passed to subprocess."""
        env = {"TEST_VAR": "test_value", "PATH": "/usr/bin:/bin"}
        result = run_subprocess(
            ["python", "-c", "import os; print(os.environ.get('TEST_VAR'))"],
            timeout=5,
            env=env,
        )
        assertions.expect_true("test_value" in result, reason="result should contain test_value")

    def test_env_none_inherits_parent(self) -> None:
        """Test that env=None inherits parent environment."""
        result = run_subprocess(
            ["python", "-c", "import os; print(bool(os.environ.get('PATH')))"],
            timeout=5,
            env=None,
        )
        assertions.expect_true("True" in result, reason="result should contain True")

    def test_env_dict_mapping(self) -> None:
        """Test that env can be any Mapping."""
        env = UserDict({"CUSTOM": "value", "PATH": "/bin"})
        result = run_subprocess(
            ["python", "-c", "import os; print(os.environ.get('CUSTOM'))"],
            timeout=5,
            env=env,
        )
        assertions.expect_true("value" in result, reason="result should contain value")


class TestErrorReporting:
    """Test suite for error messages."""

    def test_subprocess_error_message_includes_command(self) -> None:
        """Test that error message includes command."""
        with pytest.raises(SubprocessError) as exc_info:
            run_subprocess(["false"], timeout=5)
        assertions.expect_true(
            "false" in str(exc_info.value), reason="error should mention command"
        )

    def test_timeout_error_message_includes_command(self) -> None:
        """Test that timeout error includes command."""
        with pytest.raises(SubprocessTimeoutError) as exc_info:
            run_subprocess(["sleep", "10"], timeout=1)
        assertions.expect_true(
            "sleep" in str(exc_info.value), reason="error should mention command"
        )


class TestComplexCommands:
    """Test suite for complex command scenarios."""

    def test_python_script_with_args(self) -> None:
        """Test Python script with arguments."""
        result = run_subprocess(
            [
                "python",
                "-c",
                "import sys; print(f'{len(sys.argv)} {sys.argv[1]}')",
                "arg1",
            ],
            timeout=5,
        )
        assertions.expect_true("arg1" in result, reason="result should contain arg1")

    def test_shell_command_via_python(self) -> None:
        """Test shell-like commands via Python."""
        result = run_subprocess(
            [
                "python",
                "-c",
                ("data = [1, 2, 3]; print(','.join(map(str, data)))"),
            ],
            timeout=5,
        )
        assertions.expect_true("1,2,3" in result, reason="result should contain 1,2,3")

    @pytest.mark.parametrize(
        "value",
        ["test", "hello world", "123", ""],
    )
    def test_echo_various_inputs(self, value: str) -> None:
        """Test echo command with various inputs."""
        result = run_subprocess(["echo", value], timeout=5)
        if value:
            assertions.expect_true(value in result, reason=f"result should contain {value}")
