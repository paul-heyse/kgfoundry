"""Tests for module_analysis_to_meta helper."""

from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.enrich.meta_compat import module_meta
from codeintel_rev.enrich.module_meta import module_analysis_to_meta
from codeintel_rev.enrich.types import (
    DefinitionInfo,
    DocInfo,
    ExportItem,
    ImportEdge,
    LegacyImportRecord,
    ModuleAnalysis,
    ModuleMetrics,
)

from tests._helpers import assertions


def test_module_analysis_to_meta_serializes_expected_fields() -> None:
    """Ensure module_analysis_to_meta emits JSON-friendly records."""
    analysis = ModuleAnalysis(
        path=Path("pkg/mod.py"),
        module="pkg.mod",
        imports=[
            ImportEdge(src_module="pkg.mod", dst_module="pkg.other", alias="other", level=0),
        ],
        exports=[
            ExportItem(module="pkg.mod", name="Foo", kind="class", via_dunder_all=True),
        ],
        docs=DocInfo(
            module="pkg.mod",
            module_docstring="Doc",
            module_has_doc=True,
            classes_with_doc=1,
            classes_total=1,
            functions_with_doc=0,
            functions_total=0,
        ),
        metrics=ModuleMetrics(
            module="pkg.mod",
            annotated_defs=1,
            defs_total=2,
            annotation_ratio=0.5,
            has_top_level_side_effects=False,
        ),
        definitions=[
            DefinitionInfo(module="pkg.mod", name="Foo", kind="class", lineno=3),
        ],
        legacy_imports=[
            LegacyImportRecord(
                module="pkg.utils",
                names=("helper",),
                aliases={"helper": "helper_alias"},
                is_star=False,
                level=0,
            )
        ],
    )
    meta = module_analysis_to_meta(analysis)
    assertions.expect_equal(meta["module"], "pkg.mod")
    assertions.expect_equal(meta["path"], "pkg/mod.py")
    assertions.expect_equal(meta["imports"][0]["alias"], "other")
    assertions.expect_equal(meta["exports"][0]["name"], "Foo")
    assertions.expect_equal(meta["docs"]["module_docstring"], "Doc")
    assertions.expect_equal(meta["metrics"]["annotation_ratio"], 0.5)
    assertions.expect_equal(meta["definitions"][0]["lineno"], 3)
    assertions.expect_equal(meta["legacy_imports"][0]["aliases"]["helper"], "helper_alias")


def test_module_meta_helper_deserializes_payload() -> None:
    """Verify module_meta returns a typed ModuleMeta instance."""
    row = {
        "meta": {
            "module": "pkg.mod",
            "path": "pkg/mod.py",
            "imports": [
                {"src_module": "pkg.mod", "dst_module": "pkg.other", "alias": None, "level": 0}
            ],
            "exports": [
                {"module": "pkg.mod", "name": "Foo", "kind": "class", "via_dunder_all": True}
            ],
            "docs": {
                "module": "pkg.mod",
                "module_docstring": "Doc",
                "module_has_doc": True,
                "classes_with_doc": 1,
                "classes_total": 1,
                "functions_with_doc": 0,
                "functions_total": 0,
            },
            "metrics": {
                "module": "pkg.mod",
                "annotated_defs": 1,
                "defs_total": 1,
                "annotation_ratio": 1.0,
                "has_top_level_side_effects": False,
            },
            "definitions": [{"name": "Foo", "kind": "class", "lineno": 10}],
            "legacy_imports": [
                {
                    "module": "pkg.other",
                    "names": ["alias"],
                    "aliases": {"alias": "alias"},
                    "is_star": False,
                    "level": 0,
                }
            ],
        }
    }
    meta = module_meta(row)
    assertions.expect_true(meta is not None, reason="module_meta should parse meta payload")
    if meta is None:  # pragma: no cover - defensive
        pytest.fail("module_meta returned None")
    assertions.expect_equal(meta.module, "pkg.mod")
    assertions.expect_equal(meta.docs.module_docstring, "Doc")
    assertions.expect_equal(meta.metrics.annotation_ratio, 1.0)
    assertions.expect_equal(meta.legacy_imports[0].module, "pkg.other")
