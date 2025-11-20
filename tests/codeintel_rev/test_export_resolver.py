# SPDX-License-Identifier: MIT
"""Tests for export resolver helpers using meta payloads."""

from __future__ import annotations

from codeintel_rev.export_resolver import (
    build_module_name_map,
    is_reexport_hub,
    resolve_exports,
)

from tests._helpers import assertions


def _row_with_meta(path: str, meta: dict[str, object]) -> dict[str, object]:
    """Create test row dictionary with path and metadata.

    Parameters
    ----------
    path : str
        File path.
    meta : dict[str, object]
        Metadata dictionary.

    Returns
    -------
    dict[str, object]
        Row dictionary with path and meta keys.
    """
    return {"path": path, "meta": meta}


def test_resolve_exports_uses_meta_legacy_imports() -> None:
    """Ensure resolve_exports reads compatibility imports from meta payloads."""
    origin = _row_with_meta(
        "pkg/origin.py",
        {
            "exports": [
                {"module": "pkg.origin", "name": "Foo", "kind": "class", "via_dunder_all": True}
            ],
            "definitions": [
                {"module": "pkg.origin", "name": "Foo", "kind": "class", "lineno": 1},
            ],
            "legacy_imports": [],
        },
    )
    reexport = _row_with_meta(
        "pkg/reexport.py",
        {
            "legacy_imports": [
                {
                    "module": "pkg.origin",
                    "names": [],
                    "aliases": {},
                    "is_star": True,
                    "level": 0,
                }
            ],
            "definitions": [],
        },
    )
    modules_by_name = build_module_name_map([origin, reexport])
    resolved, reexports = resolve_exports(reexport, modules_by_name)
    assertions.expect_equal(resolved, {"pkg.origin": ["Foo"]})
    assertions.expect_equal(reexports, {"Foo": {"from": "pkg.origin", "symbol": "pkg.origin.Foo"}})


def test_is_reexport_hub_detects_meta_star_imports() -> None:
    """Star imports stored in meta payloads should mark re-export hubs."""
    row = _row_with_meta(
        "pkg/hub.py",
        {
            "legacy_imports": [
                {"module": "pkg.other", "names": [], "aliases": {}, "is_star": True, "level": 0}
            ],
            "exports": [],
            "definitions": [],
        },
    )
    assertions.expect_true(is_reexport_hub(row))
