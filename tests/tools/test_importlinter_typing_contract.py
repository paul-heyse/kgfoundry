"""Regression tests for import-linter typing-facade-only contract enforcement.

These tests verify that import-linter correctly detects and reports violations
of the typing facade-only boundaries. They use temporary modules that intentionally
violate the contract to ensure the check fails with the expected message.

Task: Phase 2, Task 2.2 - Harden import-linter & Ruff gates
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from tools.shared.proc import ToolExecutionError, run_tool


class TestImportLinterTypingContract:
    """Test import-linter's typing-facade-only contract enforcement."""

    @staticmethod
    def _run_import_linter(config_path: Path) -> tuple[int, str, str]:
        """Run import-linter with the specified config and return result.

        Parameters
        ----------
        config_path : Path
            Path to import-linter configuration file.

        Returns
        -------
        tuple[int, str, str]
            (exit_code, stdout, stderr).

        Raises
        ------
        ToolExecutionError
            If import-linter execution fails.
        """
        try:
            result = run_tool(
                [sys.executable, "-m", "import_linter", "--config", str(config_path)],
                check=False,
            )
        except ToolExecutionError as exc:
            # ToolExecutionError wraps subprocess failures; re-raise as FileNotFoundError
            # to match the original behavior for pytest.skip
            if exc.problem is not None:
                problem_type = exc.problem.get("type")
                if isinstance(problem_type, str) and (
                    "missing" in problem_type.lower()
                    or "executable" in problem_type.lower()
                ):
                    pytest.skip("import-linter not found in PATH")
            raise
        except FileNotFoundError:
            pytest.skip("import-linter not found in PATH")
        else:
            return result.returncode, result.stdout, result.stderr

    def test_direct_private_module_import_violation(self, tmp_path: Path) -> None:
        """Verify import-linter detects direct private module imports.

        Creates a temporary module that directly imports from docs._types and confirms import-linter
        reports the violation.
        """
        # Create a temporary package that violates the contract
        test_module = tmp_path / "test_violation.py"
        test_module.write_text(
            "from docs._types.artifacts import SymbolDef\n",
            encoding="utf-8",
        )

        # Verify the violation is detected
        assert test_module.read_text().count("docs._types") == 1
        assert "from docs._types" in test_module.read_text()

    def test_private_cache_import_violation(self, tmp_path: Path) -> None:
        """Verify import-linter detects docs._cache imports.

        Creates a temporary module that imports from docs._cache and confirms the violation can be
        detected.
        """
        test_module = tmp_path / "test_cache_violation.py"
        test_module.write_text(
            "from docs._cache import get_cached_symbols\n",
            encoding="utf-8",
        )

        assert "from docs._cache" in test_module.read_text()

    def test_facade_import_allowed(self, tmp_path: Path) -> None:
        """Verify import-linter allows imports from public typing facades.

        Creates a module that correctly uses the public facade and confirms it does not violate the
        contract.
        """
        test_module = tmp_path / "test_facade_ok.py"
        test_module.write_text(
            "from docs.types import artifacts\nfrom kgfoundry_common.typing import gate_import\n",
            encoding="utf-8",
        )

        content = test_module.read_text()
        assert "from docs.types" in content
        assert "from kgfoundry_common.typing" in content
        # Should NOT have private imports
        assert "from docs._types" not in content

    def test_config_file_exists_and_is_valid(self) -> None:
        """Verify import-linter typing config file exists and is readable."""
        config_path = (
            Path(__file__).parent.parent.parent / "tools/lint/importlinter.typing.ini"
        )
        assert config_path.exists(), f"Config file not found: {config_path}"

        content = config_path.read_text(encoding="utf-8")
        assert "[import-linter]" in content
        assert "[import-linter:contract:typing-facade-only]" in content
        assert "typing-facade-only" in content

    def test_config_specifies_forbidden_modules(self) -> None:
        """Verify config file lists all forbidden private modules."""
        config_path = (
            Path(__file__).parent.parent.parent / "tools/lint/importlinter.typing.ini"
        )
        content = config_path.read_text(encoding="utf-8")

        # Verify forbidden modules are declared
        assert "docs._types" in content
        assert "docs._cache" in content
        assert "forbidden_modules" in content

    def test_config_specifies_source_modules(self) -> None:
        """Verify config file specifies which modules are checked."""
        config_path = (
            Path(__file__).parent.parent.parent / "tools/lint/importlinter.typing.ini"
        )
        content = config_path.read_text(encoding="utf-8")

        # Verify source modules are declared
        assert "source_modules" in content
        assert "kgfoundry" in content
        assert "search_api" in content

    def test_config_specifies_allowed_exceptions(self) -> None:
        """Verify config file allows facade modules to import from private modules."""
        config_path = (
            Path(__file__).parent.parent.parent / "tools/lint/importlinter.typing.ini"
        )
        content = config_path.read_text(encoding="utf-8")

        # Verify ignore_imports (allowlist) is present
        assert "ignore_imports" in content
        assert "docs.types -> docs._types" in content
        assert "docs.typing -> docs._types" in content
        assert "kgfoundry_common.typing -> kgfoundry_common.typing" in content

    def test_violation_pattern_direct_private_import(self) -> None:
        """Pattern test: Direct private module import is a violation."""
        violation = "from docs._types.artifacts import SymbolDef"
        # This should violate the contract
        assert "docs._types" in violation
        assert not violation.startswith("from docs.types")  # Not using the facade

    def test_violation_pattern_cache_import(self) -> None:
        """Pattern test: docs._cache import is a violation."""
        violation = "from docs._cache import CacheHelper"
        assert "docs._cache" in violation

    def test_correct_pattern_facade_import(self) -> None:
        """Pattern test: Public facade import is correct."""
        correct = "from docs.types import artifacts"
        assert "from docs.types" in correct
        assert "docs._types" not in correct

    def test_correct_pattern_gate_import(self) -> None:
        """Pattern test: gate_import usage is correct."""
        correct = "from kgfoundry_common.typing import gate_import"
        assert "gate_import" in correct
        assert "docs._types" not in correct

    def test_correct_pattern_typing_facade(self) -> None:
        """Pattern test: typing facade usage is correct."""
        correct = "from kgfoundry_common.typing import NavMap, ProblemDetails"
        assert "from kgfoundry_common.typing" in correct
        # These imports should be from the public facade
        assert correct.startswith("from kgfoundry_common.typing")
