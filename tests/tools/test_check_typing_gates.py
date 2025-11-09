"""Tests for enhanced typing gate checker with autofix guidance.

Tests cover:
- Detection of heavy imports (numpy, fastapi, faiss, etc.)
- Detection of private module imports (docs._types, docs._cache)
- Detection of deprecated shim usage (resolve_numpy, resolve_fastapi, resolve_faiss)
- Actionable autofix suggestions for each violation type
- Output formats (default, JSON, --list for codemods)
- TYPE_CHECKING guard detection
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

from tools.lint.check_typing_gates import (
    check_file,
    format_violations,
    main,
)


class TestTypeGateViolationTypes:
    """Test detection of different violation types."""

    def test_detect_heavy_import_numpy(self, tmp_path: Path) -> None:
        """Verify detection of unguarded numpy imports."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """
import numpy as np

def process(arr: np.ndarray) -> None:
    pass
""",
            encoding="utf-8",
        )

        violations = check_file(test_file)
        assert len(violations) == 1
        assert violations[0].violation_type == "heavy_import"
        assert violations[0].module_name == "numpy"
        assert "numpy" in violations[0].suggestion

    def test_detect_heavy_import_from_fastapi(self, tmp_path: Path) -> None:
        """Verify detection of unguarded fastapi imports."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """
from fastapi import FastAPI

app: FastAPI = None
""",
            encoding="utf-8",
        )

        violations = check_file(test_file)
        assert len(violations) == 1
        assert violations[0].violation_type == "heavy_import"
        assert violations[0].module_name == "fastapi"
        assert "TYPE_CHECKING" in violations[0].suggestion

    def test_detect_private_module_docs_types(self, tmp_path: Path) -> None:
        """Verify detection of private docs._types imports."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """
from docs._types.symbol import SymbolDefinition
""",
            encoding="utf-8",
        )

        violations = check_file(test_file)
        assert len(violations) == 1
        assert violations[0].violation_type == "private_module"
        assert violations[0].module_name == "docs._types.symbol"
        assert "public façade" in violations[0].suggestion

    def test_detect_private_module_docs_cache(self, tmp_path: Path) -> None:
        """Verify detection of private docs._cache imports."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """
from docs._cache import get_cached_symbols
""",
            encoding="utf-8",
        )

        violations = check_file(test_file)
        assert len(violations) == 1
        assert violations[0].violation_type == "private_module"
        assert "docs._cache" in violations[0].module_name

    def test_detect_deprecated_resolve_numpy_shim(self, tmp_path: Path) -> None:
        """Verify detection of deprecated resolve_numpy shim usage."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """
from kgfoundry_common.typing import resolve_numpy
""",
            encoding="utf-8",
        )

        violations = check_file(test_file)
        assert len(violations) == 1
        assert violations[0].violation_type == "deprecated_shim"
        assert "resolve_numpy" in violations[0].module_name
        assert "gate_import" in violations[0].suggestion

    def test_detect_deprecated_resolve_fastapi_shim(self, tmp_path: Path) -> None:
        """Verify detection of deprecated resolve_fastapi shim usage."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """
from kgfoundry_common.typing import resolve_fastapi
""",
            encoding="utf-8",
        )

        violations = check_file(test_file)
        assert len(violations) == 1
        assert violations[0].violation_type == "deprecated_shim"
        assert "resolve_fastapi" in violations[0].module_name

    def test_detect_deprecated_resolve_faiss_shim(self, tmp_path: Path) -> None:
        """Verify detection of deprecated resolve_faiss shim usage."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """
from kgfoundry_common.typing import resolve_faiss
""",
            encoding="utf-8",
        )

        violations = check_file(test_file)
        assert len(violations) == 1
        assert violations[0].violation_type == "deprecated_shim"
        assert "resolve_faiss" in violations[0].module_name

    def test_no_violation_for_type_checking_guarded(self, tmp_path: Path) -> None:
        """Verify no violation for TYPE_CHECKING-guarded imports."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

def process(arr: np.ndarray) -> None:
    pass
""",
            encoding="utf-8",
        )

        violations = check_file(test_file)
        assert len(violations) == 0

    def test_no_violation_for_stdlib(self, tmp_path: Path) -> None:
        """Verify no violations for stdlib imports."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """
import json
from pathlib import Path

def process(p: Path) -> None:
    pass
""",
            encoding="utf-8",
        )

        violations = check_file(test_file)
        assert len(violations) == 0


class TestAutoFixSuggestions:
    """Test that suggestions are actionable and specific."""

    def test_heavy_import_suggestion_includes_type_checking(self, tmp_path: Path) -> None:
        """Verify heavy import suggestion mentions TYPE_CHECKING."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import torch\n", encoding="utf-8")

        violations = check_file(test_file)
        assert len(violations) == 1
        assert "TYPE_CHECKING" in violations[0].suggestion

    def test_heavy_import_suggestion_includes_gate_import(self, tmp_path: Path) -> None:
        """Verify heavy import suggestion mentions gate_import."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import tensorflow\n", encoding="utf-8")

        violations = check_file(test_file)
        assert len(violations) == 1
        assert "gate_import" in violations[0].suggestion

    def test_private_module_suggestion_references_facade(self, tmp_path: Path) -> None:
        """Verify private module suggestion references public façade."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from docs._types.symbol import Symbol\n", encoding="utf-8")

        violations = check_file(test_file)
        assert len(violations) == 1
        assert "façade" in violations[0].suggestion.lower()
        assert "docs.types" in violations[0].suggestion

    def test_deprecated_shim_suggestion_references_gate_import(self, tmp_path: Path) -> None:
        """Verify deprecated shim suggestion mentions gate_import."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            "from kgfoundry_common.typing import resolve_numpy\n", encoding="utf-8"
        )

        violations = check_file(test_file)
        assert len(violations) == 1
        assert "gate_import" in violations[0].suggestion


class TestOutputFormats:
    """Test different output formats."""

    def test_json_output_format(self, tmp_path: Path) -> None:
        """Verify JSON output contains all required fields."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import numpy as np\n", encoding="utf-8")

        violations = check_file(test_file)
        json_output = format_violations(violations, json_output=True)
        data = cast("list[dict[str, Any]]", json.loads(json_output))

        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["violation_type"] == "heavy_import"
        assert data[0]["suggestion"]
        assert data[0]["filepath"]
        assert data[0]["lineno"]

    def test_list_output_format(self, tmp_path: Path) -> None:
        """Verify --list output format for codemod integration."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import numpy as np\n", encoding="utf-8")

        violations = check_file(test_file)
        list_output = format_violations(violations, list_output=True)
        lines = list_output.strip().split("\n")

        assert len(lines) == 1
        # Format: filepath:lineno:violation_type:module_name
        parts = lines[0].split(":")
        assert len(parts) >= 4
        assert parts[2] == "heavy_import"
        assert parts[3] == "numpy"

    def test_default_output_includes_suggestions(self, tmp_path: Path) -> None:
        """Verify default output format includes fix suggestions."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from docs._types import Symbol\n", encoding="utf-8")

        violations = check_file(test_file)
        output = format_violations(violations)

        assert "Fix:" in output
        assert "façade" in output.lower()
        assert violations[0].suggestion in output

    def test_empty_violations_output(self, tmp_path: Path) -> None:
        """Verify output for clean files."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import sys\n", encoding="utf-8")

        violations = check_file(test_file)
        output = format_violations(violations)

        assert "✓ No typing gate violations found" in output


class TestMainCommand:
    """Test command-line interface."""

    def test_main_with_json_flag(self, tmp_path: Path) -> None:
        """Verify --json flag works via main()."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import numpy\n", encoding="utf-8")

        exit_code = main(["--json", str(tmp_path)])
        assert exit_code == 1  # Exit 1 when violations found

    def test_main_with_list_flag(self, tmp_path: Path) -> None:
        """Verify --list flag works via main()."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from docs._types import X\n", encoding="utf-8")

        exit_code = main(["--list", str(tmp_path)])
        assert exit_code == 1  # Exit 1 when violations found

    def test_main_with_clean_directory(self, tmp_path: Path) -> None:
        """Verify main returns 0 for clean directory."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import sys\n", encoding="utf-8")

        exit_code = main([str(tmp_path)])
        assert exit_code == 0  # Exit 0 when no violations


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_nested_type_checking_blocks(self, tmp_path: Path) -> None:
        """Verify handling of nested TYPE_CHECKING blocks."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    if True:
        import numpy as np
""",
            encoding="utf-8",
        )

        violations = check_file(test_file)
        assert len(violations) == 0

    def test_faiss_submodule_import(self, tmp_path: Path) -> None:
        """Verify detection of faiss submodule imports."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from faiss.swigfaiss import IndexFlat\n", encoding="utf-8")

        violations = check_file(test_file)
        assert len(violations) == 1
        assert violations[0].violation_type == "heavy_import"
        assert "faiss" in violations[0].module_name

    def test_multiple_violations_in_one_file(self, tmp_path: Path) -> None:
        """Verify detection of multiple violations in single file."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """
import numpy as np
from fastapi import FastAPI
from docs._types import Symbol
from kgfoundry_common.typing import resolve_numpy
""",
            encoding="utf-8",
        )

        violations = check_file(test_file)
        assert len(violations) == 4
        violation_types = {v.violation_type for v in violations}
        assert violation_types == {"heavy_import", "private_module", "deprecated_shim"}

    def test_syntactic_errors_are_handled(self, tmp_path: Path) -> None:
        """Verify graceful handling of syntax errors."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import numpy\nthis is not valid python\n", encoding="utf-8")

        violations = check_file(test_file)
        # Should return empty list for files with syntax errors
        assert isinstance(violations, list)

    def test_violation_line_numbers_are_accurate(self, tmp_path: Path) -> None:
        """Verify line numbers in violations are accurate."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            """
# Line 1
# Line 2
import numpy  # Line 3
""",
            encoding="utf-8",
        )

        violations = check_file(test_file)
        assert len(violations) == 1
        assert violations[0].lineno == 4  # 1-indexed, counting blank line at start
