# SPDX-License-Identifier: MIT
"""Compatibility shim exposing the legacy enrich pipeline API."""

from __future__ import annotations

import sys
from collections.abc import Sequence

import typer

from codeintel_rev.cli.enrich import app as _enrich_app
from codeintel_rev.cli.enrich import common as _common
from codeintel_rev.enrich.errors import StageError
from codeintel_rev.enrich.output_writers import write_json as _write_json
from codeintel_rev.enrich.pipeline_helpers import apply_tagging as _apply_tagging
from codeintel_rev.enrich.pipeline_helpers import build_module_row as _build_module_row
from codeintel_rev.enrich.pipeline_helpers import normalized_rel_path as _normalized_rel_path
from codeintel_rev.enrich.pipeline_helpers import outline_nodes_for as _outline_nodes_for
from codeintel_rev.enrich.pipeline_helpers import type_error_count as _type_error_count
from codeintel_rev.services.enrich import exports as export_service
from codeintel_rev.services.enrich import overlays as overlay_service
from codeintel_rev.services.enrich import scan as scan_service
from codeintel_rev.services.enrich.context import (
    AnalyticsOptions,
    CLIContextState,
    OverlayCLIOptions,
    OverlayContext,
    PipelineOptions,
    PipelineResult,
    ScanInputs,
    ScipContext,
)

app = _enrich_app

# Legacy helper re-exports
attach_argv_normalizer = _common.attach_argv_normalizer
normalize_global_cli_args = _common.normalize_global_cli_args
shared_options = _common.shared_options
ensure_state = _common.ensure_state
handle_dry_run = _common.handle_dry_run
write_graph_outputs = export_service.write_graph_outputs
write_uses_output = export_service.write_uses_output
write_typedness_output = export_service.write_typedness_output
write_doc_output = export_service.write_doc_output
write_coverage_output = export_service.write_coverage_output
write_config_output = export_service.write_config_output
write_hotspot_output = export_service.write_hotspot_output
write_exports_outputs = export_service.write_exports_outputs
write_ast_outputs = export_service.write_ast_outputs
write_slices_output = export_service.write_slices_output
apply_ownership = export_service.apply_ownership
load_overlay_options = overlay_service.load_overlay_options
build_overlay_context = overlay_service.build_overlay_context
ensure_package_overlays = overlay_service.ensure_package_overlays
iter_files = scan_service.iter_python_files
build_module_row = _build_module_row
outline_nodes_for = _outline_nodes_for
type_error_count = _type_error_count
apply_tagging = _apply_tagging
normalized_rel_path = _normalized_rel_path
DRY_RUN_OPTION = _common.DRY_RUN_OPTION
OVERLAYS_CONFIG_OPTION = _common.OVERLAYS_CONFIG_OPTION
OVERLAYS_SET_OPTION = _common.OVERLAYS_SET_OPTION
write_json = _write_json


def execute_pipeline_or_exit(ctx: typer.Context) -> tuple[PipelineResult, CLIContextState]:
    """Execute the enrichment pipeline or exit with a diagnostic on failure.

    Returns
    -------
    tuple[PipelineResult, CLIContextState]
        Pipeline output plus the current CLI state.
    """
    state = _common.ensure_state(ctx)
    try:
        return _common.execute_pipeline(state), state
    except StageError as exc:  # pragma: no cover - defensive
        _common.handle_stage_error(exc)


def main(argv: Sequence[str] | None = None) -> None:
    """Invoke the compatibility CLI app."""
    if argv is None:
        argv = tuple(sys.argv)
    sys.argv = _common.normalize_global_cli_args(tuple(argv))
    app()


__all__ = [
    "AnalyticsOptions",
    "CLIContextState",
    "OverlayCLIOptions",
    "OverlayContext",
    "PipelineOptions",
    "PipelineResult",
    "ScanInputs",
    "ScipContext",
    "app",
    "apply_ownership",
    "apply_tagging",
    "attach_argv_normalizer",
    "build_module_row",
    "build_overlay_context",
    "ensure_package_overlays",
    "ensure_state",
    "execute_pipeline_or_exit",
    "handle_dry_run",
    "iter_files",
    "load_overlay_options",
    "main",
    "normalize_global_cli_args",
    "normalized_rel_path",
    "outline_nodes_for",
    "shared_options",
    "type_error_count",
    "write_ast_outputs",
    "write_config_output",
    "write_coverage_output",
    "write_doc_output",
    "write_exports_outputs",
    "write_graph_outputs",
    "write_hotspot_output",
    "write_slices_output",
    "write_typedness_output",
    "write_uses_output",
]
