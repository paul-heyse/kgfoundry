from __future__ import annotations

from pathlib import Path

import pytest
from tools.repo_scan_libcst import CSTImports, collect_imports_with_libcst


def test_collect_imports_with_libcst(tmp_path: Path) -> None:
    pytest.importorskip("libcst")
    module = tmp_path / "package" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        """from __future__ import annotations\n\nimport os as operating_system\nfrom typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from pkg.internal import TypeOnly\n\nfrom ..shared import helpers\nfrom .local import value as local_value\nfrom vendor import toolkit, extras as ex\nfrom vendor import *\n\n__all__ = [\"EXPORTED\", \"CONSTANT\"]\n""",
        encoding="utf-8",
    )

    result = collect_imports_with_libcst(module, "package.mod")
    assert isinstance(result, CSTImports)
    assert not result.has_parse_errors
    assert any(name.startswith("operating_system") for name in result.imports)
    assert any(name.startswith("vendor") for name in result.imports)
    assert any(name.startswith("pkg.internal") for name in result.tc_imports)
    assert result.exports == ("CONSTANT", "EXPORTED")
    assert "vendor" in result.star_imports


def test_collect_imports_with_parse_error(tmp_path: Path) -> None:
    pytest.importorskip("libcst")
    faulty = tmp_path / "broken.py"
    faulty.write_text("def f(:\n", encoding="utf-8")

    info = collect_imports_with_libcst(faulty, "broken")
    assert info.has_parse_errors
    assert info.imports == ()
