from __future__ import annotations

from pathlib import Path

import pytest
from tools.repo_scan_libcst import CSTImports, collect_imports_with_libcst

from tests._helpers import assertions


def test_collect_imports_with_libcst(tmp_path: Path) -> None:
    pytest.importorskip("libcst")
    module = tmp_path / "package" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        """from __future__ import annotations\n\nimport os as operating_system\nfrom typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from pkg.internal import TypeOnly\n\nfrom ..shared import helpers\nfrom .local import value as local_value\nfrom vendor import toolkit, extras as ex\nfrom vendor import *\n\n__all__ = [\"EXPORTED\", \"CONSTANT\"]\n""",
        encoding="utf-8",
    )

    result = collect_imports_with_libcst(module, "package.mod")
    assertions.expect_true(isinstance(result, CSTImports), reason="result should be CSTImports")
    assertions.expect_false(result.has_parse_errors, reason="should not have parse errors")
    assertions.expect_true(
        any(name.startswith("operating_system") for name in result.imports),
        reason="should have operating_system import",
    )
    assertions.expect_true(
        any(name.startswith("vendor") for name in result.imports),
        reason="should have vendor import",
    )
    assertions.expect_true(
        any(name.startswith("pkg.internal") for name in result.tc_imports),
        reason="should have pkg.internal in tc_imports",
    )
    assertions.expect_sequence_equal(result.exports, ("CONSTANT", "EXPORTED"))
    assertions.expect_in("vendor", result.star_imports)


def test_collect_imports_with_parse_error(tmp_path: Path) -> None:
    pytest.importorskip("libcst")
    faulty = tmp_path / "broken.py"
    faulty.write_text("def f(:\n", encoding="utf-8")

    info = collect_imports_with_libcst(faulty, "broken")
    assertions.expect_true(info.has_parse_errors, reason="should have parse errors")
    assertions.expect_sequence_equal(info.imports, ())
