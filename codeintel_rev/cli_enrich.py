"""Compatibility wrapper exporting the enrichment CLI."""

from __future__ import annotations

from codeintel_rev.cli.enrich.__main__ import app, main
from codeintel_rev.cli.enrich_pipeline import (
    ScanInputs,
    ScipContext,
    normalize_global_cli_args,
)
from codeintel_rev.cli.enrich_pipeline import (
    apply_tagging as _apply_tagging,
)
from codeintel_rev.cli.enrich_pipeline import (
    build_module_row as _build_module_row,
)
from codeintel_rev.cli.enrich_pipeline import (
    outline_nodes_for as _outline_nodes_for,
)
from codeintel_rev.cli.enrich_pipeline import (
    type_error_count as _type_error_count,
)

# Preserve historical aliases for importers/tests.
apply_tagging = _apply_tagging
build_module_row = _build_module_row
outline_nodes_for = _outline_nodes_for
type_error_count = _type_error_count


__all__ = [
    "ScanInputs",
    "ScipContext",
    "app",
    "apply_tagging",
    "build_module_row",
    "main",
    "normalize_global_cli_args",
    "outline_nodes_for",
    "type_error_count",
]
