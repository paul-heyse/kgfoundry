# SPDX-License-Identifier: MIT
"""Tests covering slice builder compatibility with meta payloads."""

from __future__ import annotations

from codeintel_rev.enrich.slices_builder import build_slice_record

from tests._helpers import assertions


def test_build_slice_record_uses_meta_payload() -> None:
    """Ensure slices use meta imports/defs/exports when legacy fields missing."""
    row = {
        "path": "pkg/app.py",
        "module_name": "pkg.app",
        "meta": {
            "imports": [
                {"src_module": "pkg.app", "dst_module": "pkg.utils", "alias": None, "level": 0}
            ],
            "legacy_imports": [
                {
                    "module": "pkg.utils",
                    "names": ["helper"],
                    "aliases": {},
                    "is_star": False,
                    "level": 0,
                }
            ],
            "definitions": [
                {"module": "pkg.app", "name": "run", "kind": "function", "lineno": 5},
            ],
            "exports": [
                {"module": "pkg.app", "name": "Foo", "kind": "class", "via_dunder_all": True},
                {"module": "pkg.app", "name": "run", "kind": "function", "via_dunder_all": False},
            ],
        },
    }
    record = build_slice_record(row)
    assertions.expect_equal(record.exports, ["Foo"])
    assertions.expect_equal(record.imports[0]["module"], "pkg.utils")
    assertions.expect_equal(record.defs[0]["name"], "run")
