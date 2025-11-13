# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.enrich.scip_reader import Document, SCIPIndex, SymbolInfo
from codeintel_rev.enrich.stubs_overlay import (
    OverlayInputs,
    OverlayPolicy,
    generate_overlay_for_file,
)


def _scip_symbol(module: str, name: str) -> str:
    return f"scip-python python kgfoundry 0.0.0 `{module}`/{name}#"


def test_generate_overlay_creates_stub_with_reexports(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    package_root = repo_root / "codeintel_rev"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    module_path = package_root / "public_api.py"
    module_path.write_text(
        "from codeintel_rev.deps import *\n"
        "__all__ = ['Foo']\n"
        "def helper(value):\n"
        "    return value\n"
        "def _internal(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    scip = SCIPIndex(
        documents=[
            Document(
                path="codeintel_rev/deps.py",
                symbols=[
                    SymbolInfo(symbol=_scip_symbol("codeintel_rev.deps", "Foo")),
                    SymbolInfo(symbol=_scip_symbol("codeintel_rev.deps", "Bar")),
                ],
            )
        ]
    )

    result = generate_overlay_for_file(
        module_path,
        package_root,
        policy=OverlayPolicy(),
        inputs=OverlayInputs(scip=scip),
    )

    assert result.created
    assert result.pyi_path is not None
    assert result.pyi_path.exists()
    assert result.pyi_path.is_relative_to(repo_root / "stubs")
    assert "codeintel_rev.deps" in result.exports_resolved
    assert result.exports_resolved["codeintel_rev.deps"] == {"Bar", "Foo"}

    stub_text = result.pyi_path.read_text(encoding="utf-8")
    assert "from codeintel_rev.deps import Bar as Bar, Foo as Foo" in stub_text
    assert "def helper(*args: Any, **kwargs: Any) -> Any" in stub_text
    assert '__all__ = ["Bar", "Foo", "helper"]' in stub_text

    sidecar_data = json.loads(result.pyi_path.with_suffix(".pyi.json").read_text(encoding="utf-8"))
    assert sidecar_data["module"] == "codeintel_rev.public_api"
    assert sidecar_data["exports_resolved"]["codeintel_rev.deps"] == ["Bar", "Foo"]


def test_generate_overlay_skips_private_only_module(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    package_root = repo_root / "codeintel_rev"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    module_path = package_root / "internal.py"
    module_path.write_text(
        "def _helper(value):\n    return value\n",
        encoding="utf-8",
    )

    result = generate_overlay_for_file(
        module_path,
        package_root,
        policy=OverlayPolicy(),
        inputs=OverlayInputs(),
    )

    assert not result.created
    assert result.pyi_path is None
