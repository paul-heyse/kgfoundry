# SPDX-License-Identifier: MIT
"""Tests for stub overlay generation for type stubs."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.enrich.scip_reader import Document, SCIPIndex, SymbolInfo
from codeintel_rev.enrich.stubs_overlay import (
    OverlayInputs,
    OverlayPolicy,
    generate_overlay_for_file,
)

from tests._helpers import assertions


def _scip_symbol(module: str, name: str) -> str:
    """Generate a SCIP symbol identifier.

    Parameters
    ----------
    module : str
        Module name.
    name : str
        Symbol name.

    Returns
    -------
    str
        SCIP symbol identifier.
    """
    return f"scip-python python kgfoundry 0.0.0 `{module}`/{name}#"


def test_generate_overlay_creates_stub_with_reexports(tmp_path: Path) -> None:
    """Verify overlay generation creates stub files with re-exported symbols."""
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

    assertions.expect_true(result.created, reason="overlay should be created")
    assertions.expect_true(result.pyi_path is not None, reason="pyi_path should be set")
    assertions.expect_true(result.pyi_path.exists(), reason="pyi_path should exist")
    assertions.expect_true(
        result.pyi_path.is_relative_to(repo_root / "stubs"), reason="pyi_path should be in stubs"
    )
    assertions.expect_in("codeintel_rev.deps", result.exports_resolved)
    assertions.expect_equal(result.exports_resolved["codeintel_rev.deps"], {"Bar", "Foo"})

    stub_text = result.pyi_path.read_text(encoding="utf-8")
    assertions.expect_in("from codeintel_rev.deps import Bar as Bar, Foo as Foo", stub_text)
    assertions.expect_in("def helper(*args: Any, **kwargs: Any) -> Any", stub_text)
    assertions.expect_in('__all__ = ["Bar", "Foo", "helper"]', stub_text)

    sidecar_data = json.loads(result.pyi_path.with_suffix(".pyi.json").read_text(encoding="utf-8"))
    assertions.expect_equal(sidecar_data["module"], "codeintel_rev.public_api")
    assertions.expect_sequence_equal(
        sidecar_data["exports_resolved"]["codeintel_rev.deps"], ["Bar", "Foo"]
    )


def test_generate_overlay_skips_private_only_module(tmp_path: Path) -> None:
    """Verify overlay generation skips modules with only private symbols."""
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

    assertions.expect_false(result.created, reason="private-only module should not create overlay")
    assertions.expect_equal(result.pyi_path, None)


def test_overlay_hub_threshold_controls_generation(tmp_path: Path) -> None:
    """Verify export hub threshold controls when overlays are generated."""
    repo_root = tmp_path / "repo"
    package_root = repo_root / "pkg"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    module_path = package_root / "hub.py"
    exports = ", ".join(f"'name{i}'" for i in range(5))
    module_path.write_text(f"__all__ = [{exports}]\n", encoding="utf-8")

    result = generate_overlay_for_file(
        module_path,
        package_root,
        policy=OverlayPolicy(export_hub_threshold=5),
        inputs=OverlayInputs(),
    )
    assertions.expect_true(result.created, reason="hub with threshold should create overlay")


def test_overlay_skips_small_export_sets(tmp_path: Path) -> None:
    """Verify overlay generation skips modules with small export sets."""
    repo_root = tmp_path / "repo"
    package_root = repo_root / "pkg"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    module_path = package_root / "helpers.py"
    module_path.write_text("__all__ = ['helper_a', 'helper_b']\n", encoding="utf-8")

    result = generate_overlay_for_file(
        module_path,
        package_root,
        policy=OverlayPolicy(export_hub_threshold=3),
        inputs=OverlayInputs(),
    )
    assertions.expect_false(result.created, reason="small export set should not create overlay")


def test_overlay_needed_tag_forces_generation(tmp_path: Path) -> None:
    """Verify overlay_needed tag forces overlay generation regardless of threshold."""
    repo_root = tmp_path / "repo"
    package_root = repo_root / "pkg"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    module_path = package_root / "feature.py"
    module_path.write_text("VALUE = 1\n", encoding="utf-8")
    rel_key = module_path.relative_to(package_root).as_posix()

    result = generate_overlay_for_file(
        module_path,
        package_root,
        policy=OverlayPolicy(export_hub_threshold=100),
        inputs=OverlayInputs(overlay_tagged_paths=frozenset({rel_key})),
    )
    assertions.expect_true(result.created, reason="tagged path should force overlay creation")
