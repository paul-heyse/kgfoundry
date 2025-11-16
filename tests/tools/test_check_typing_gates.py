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
    HEAVY_MODULES,
    check_file,
    format_violations,
    main,
)

from tests._helpers import assertions

# Test constants
_MIN_EXPECTED_OUTPUT_PARTS = 4


def test_detect_heavy_import_numpy(tmp_path: Path) -> None:
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

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_equal(violations[0].violation_type, "heavy_import")
    assertions.expect_equal(violations[0].module_name, "numpy")
    assertions.expect_in("numpy", violations[0].suggestion)


def test_detect_heavy_import_from_fastapi(tmp_path: Path) -> None:
    """Verify detection of unguarded fastapi imports."""
    test_file = tmp_path / "test.py"
    test_file.write_text(
        """

from fastapi import FastAPI

app: FastAPI = None
""",
        encoding="utf-8",
    )

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_equal(violations[0].violation_type, "heavy_import")
    assertions.expect_equal(violations[0].module_name, "fastapi")
    assertions.expect_in("TYPE_CHECKING", violations[0].suggestion)


def test_detect_private_module_docs_types(tmp_path: Path) -> None:
    """Verify detection of private docs._types imports."""
    test_file = tmp_path / "test.py"
    test_file.write_text(
        """

from docs._types.symbol import SymbolDefinition
""",
        encoding="utf-8",
    )

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_equal(violations[0].violation_type, "private_module")
    assertions.expect_equal(violations[0].module_name, "docs._types.symbol")
    assertions.expect_in("public façade", violations[0].suggestion)


def test_detect_private_module_docs_cache(tmp_path: Path) -> None:
    """Verify detection of private docs._cache imports."""
    test_file = tmp_path / "test.py"
    test_file.write_text(
        """

from docs._cache import get_cached_symbols
""",
        encoding="utf-8",
    )

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_equal(violations[0].violation_type, "private_module")
    assertions.expect_in("docs._cache", violations[0].module_name)


def test_detect_deprecated_resolve_numpy_shim(tmp_path: Path) -> None:
    """Verify detection of deprecated resolve_numpy shim usage."""
    test_file = tmp_path / "test.py"
    test_file.write_text(
        """

from kgfoundry_common.typing import resolve_numpy
""",
        encoding="utf-8",
    )

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_equal(violations[0].violation_type, "deprecated_shim")
    assertions.expect_in("resolve_numpy", violations[0].module_name)
    assertions.expect_in("gate_import", violations[0].suggestion)


def test_detect_deprecated_resolve_fastapi_shim(tmp_path: Path) -> None:
    """Verify detection of deprecated resolve_fastapi shim usage."""
    test_file = tmp_path / "test.py"
    test_file.write_text(
        """

from kgfoundry_common.typing import resolve_fastapi
""",
        encoding="utf-8",
    )

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_equal(violations[0].violation_type, "deprecated_shim")
    assertions.expect_in("resolve_fastapi", violations[0].module_name)


def test_detect_deprecated_resolve_faiss_shim(tmp_path: Path) -> None:
    """Verify detection of deprecated resolve_faiss shim usage."""
    test_file = tmp_path / "test.py"
    test_file.write_text(
        """

from kgfoundry_common.typing import resolve_faiss
""",
        encoding="utf-8",
    )

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_equal(violations[0].violation_type, "deprecated_shim")
    assertions.expect_in("resolve_faiss", violations[0].module_name)


def test_no_violation_for_type_checking_guarded(tmp_path: Path) -> None:
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

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 0)


def test_no_violation_for_stdlib(tmp_path: Path) -> None:
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

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 0)


def test_heavy_import_suggestion_includes_type_checking(tmp_path: Path) -> None:
    """Verify heavy import suggestion mentions TYPE_CHECKING."""
    test_file = tmp_path / "test.py"
    test_file.write_text("import torch\n", encoding="utf-8")

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_in("TYPE_CHECKING", violations[0].suggestion)


def test_heavy_import_suggestion_includes_gate_import(tmp_path: Path) -> None:
    """Verify heavy import suggestion mentions gate_import."""
    test_file = tmp_path / "test.py"
    test_file.write_text("import tensorflow\n", encoding="utf-8")

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_in("gate_import", violations[0].suggestion)


def test_private_module_suggestion_references_facade(tmp_path: Path) -> None:
    """Verify private module suggestion references public façade."""
    test_file = tmp_path / "test.py"
    test_file.write_text("from docs._types.symbol import Symbol\n", encoding="utf-8")

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_in("façade", violations[0].suggestion.lower())
    assertions.expect_in("docs.types", violations[0].suggestion)


def test_deprecated_shim_suggestion_references_gate_import(tmp_path: Path) -> None:
    """Verify deprecated shim suggestion mentions gate_import."""
    test_file = tmp_path / "test.py"
    test_file.write_text("from kgfoundry_common.typing import resolve_numpy\n", encoding="utf-8")

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_in("gate_import", violations[0].suggestion)


def test_json_output_format(tmp_path: Path) -> None:
    """Verify JSON output contains all required fields."""
    test_file = tmp_path / "test.py"
    test_file.write_text("import numpy as np\n", encoding="utf-8")

    violations = check_file(test_file, HEAVY_MODULES)
    json_output = format_violations(violations, json_output=True)
    data = cast("list[dict[str, Any]]", json.loads(json_output))

    assertions.expect_true(isinstance(data, list), reason="data should be list")
    assertions.expect_equal(len(data), 1)
    assertions.expect_equal(data[0]["violation_type"], "heavy_import")
    assertions.expect_true(bool(data[0]["suggestion"]), reason="suggestion should be truthy")
    assertions.expect_true(bool(data[0]["filepath"]), reason="filepath should be truthy")
    assertions.expect_true(bool(data[0]["lineno"]), reason="lineno should be truthy")


def test_list_output_format(tmp_path: Path) -> None:
    """Verify --list output format for codemod integration."""
    test_file = tmp_path / "test.py"
    test_file.write_text("import numpy as np\n", encoding="utf-8")

    violations = check_file(test_file, HEAVY_MODULES)
    list_output = format_violations(violations, list_output=True)
    lines = list_output.strip().split("\n")

    assertions.expect_equal(len(lines), 1)
    # Format: filepath:lineno:violation_type:module_name
    parts = lines[0].split(":")
    assertions.expect_true(
        len(parts) >= _MIN_EXPECTED_OUTPUT_PARTS,
        reason=f"should have at least {_MIN_EXPECTED_OUTPUT_PARTS} parts",
    )
    assertions.expect_equal(parts[2], "heavy_import")
    assertions.expect_equal(parts[3], "numpy")


def test_default_output_includes_suggestions(tmp_path: Path) -> None:
    """Verify default output format includes fix suggestions."""
    test_file = tmp_path / "test.py"
    test_file.write_text("from docs._types import Symbol\n", encoding="utf-8")

    violations = check_file(test_file, HEAVY_MODULES)
    output = format_violations(violations)

    assertions.expect_in("Fix:", output)
    assertions.expect_in("façade", output.lower())
    assertions.expect_in(violations[0].suggestion, output)


def test_empty_violations_output(tmp_path: Path) -> None:
    """Verify output for clean files."""
    test_file = tmp_path / "test.py"
    test_file.write_text("import sys\n", encoding="utf-8")

    violations = check_file(test_file, HEAVY_MODULES)
    output = format_violations(violations)

    assertions.expect_in("✓ No typing gate violations found", output)


def test_main_with_json_flag(tmp_path: Path) -> None:
    """Verify --json flag works via main()."""
    test_file = tmp_path / "test.py"
    test_file.write_text("import numpy\n", encoding="utf-8")

    exit_code = main(["--json", str(tmp_path)])
    assertions.expect_equal(exit_code, 1)  # Exit 1 when violations found


def test_main_with_list_flag(tmp_path: Path) -> None:
    """Verify --list flag works via main()."""
    test_file = tmp_path / "test.py"
    test_file.write_text("from docs._types import X\n", encoding="utf-8")

    exit_code = main(["--list", str(tmp_path)])
    assertions.expect_equal(exit_code, 1)  # Exit 1 when violations found


def test_main_with_clean_directory(tmp_path: Path) -> None:
    """Verify main returns 0 for clean directory."""
    test_file = tmp_path / "test.py"
    test_file.write_text("import sys\n", encoding="utf-8")

    exit_code = main([str(tmp_path)])
    assertions.expect_equal(exit_code, 0)  # Exit 0 when no violations


def test_nested_type_checking_blocks(tmp_path: Path) -> None:
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

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 0)


def test_faiss_submodule_import(tmp_path: Path) -> None:
    """Verify detection of faiss submodule imports."""
    test_file = tmp_path / "test.py"
    test_file.write_text("from faiss.swigfaiss import IndexFlat\n", encoding="utf-8")

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_equal(violations[0].violation_type, "heavy_import")
    assertions.expect_in("faiss", violations[0].module_name)


def test_multiple_violations_in_one_file(tmp_path: Path) -> None:
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

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 4)
    violation_types = {v.violation_type for v in violations}
    assertions.expect_equal(violation_types, {"heavy_import", "private_module", "deprecated_shim"})


def test_syntactic_errors_are_handled(tmp_path: Path) -> None:
    """Verify graceful handling of syntax errors."""
    test_file = tmp_path / "test.py"
    test_file.write_text("import numpy\nthis is not valid python\n", encoding="utf-8")

    violations = check_file(test_file, HEAVY_MODULES)
    # Should return empty list for files with syntax errors
    assertions.expect_true(isinstance(violations, list), reason="violations should be list")


def test_violation_line_numbers_are_accurate(tmp_path: Path) -> None:
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

    violations = check_file(test_file, HEAVY_MODULES)
    assertions.expect_equal(len(violations), 1)
    assertions.expect_equal(violations[0].lineno, 4)  # 1-indexed, counting blank line at start
