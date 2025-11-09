"""Manifest generation helpers for docstring builder runs."""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from tools.docstring_builder.ir import IR_VERSION
from tools.docstring_builder.paths import MANIFEST_PATH

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from tools.docstring_builder.config import ConfigSelection
    from tools.docstring_builder.ir import IRDocstring
    from tools.docstring_builder.models import (
        CacheSummary,
        InputHash,
        PluginReport,
    )
    from tools.docstring_builder.orchestrator import DocstringBuildRequest
    from tools.docstring_builder.pipeline_types import ProcessingOptions


@dataclass(slots=True, frozen=True)
class ManifestContext:
    """Context for manifest generation."""

    request: DocstringBuildRequest
    options: ProcessingOptions
    files: Sequence[Path]
    processed_count: int
    skipped_count: int
    changed_count: int
    cache_summary: CacheSummary
    input_hashes: Mapping[str, InputHash]
    dependency_map: Mapping[str, list[str]]
    diff_links: Mapping[str, str]
    all_ir: Sequence[IRDocstring]
    plugin_report: PluginReport
    selection: object | None


def write_manifest(ctx: ManifestContext) -> Path:
    """Write the manifest file for the docstring builder run.

    Parameters
    ----------
    ctx : ManifestContext
        Context containing run metadata and results.

    Returns
    -------
    Path
        Path to the written manifest file.
    """
    invoked = str(
        ctx.request.invoked_subcommand or ctx.request.subcommand or ctx.request.command or ""
    )
    manifest_payload: dict[str, object] = {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "command": ctx.request.command,
        "subcommand": invoked,
        "options": {
            "module": ctx.request.module,
            "since": ctx.request.since,
            "force": ctx.request.force,
            "changed_only": ctx.request.changed_only,
            "skip_docfacts": ctx.request.skip_docfacts,
        },
        "counts": {
            "considered": len(ctx.files),
            "processed": ctx.processed_count,
            "skipped": ctx.skipped_count,
            "changed": ctx.changed_count,
        },
        "cache": ctx.cache_summary,
        "hashes": dict(ctx.input_hashes),
        "dependencies": dict(ctx.dependency_map),
    }
    if ctx.diff_links:
        manifest_payload["drift_previews"] = dict(ctx.diff_links)
    manifest_payload["ir"] = {
        "version": IR_VERSION,
        "count": len(ctx.all_ir),
        "symbols": [entry.symbol_id for entry in ctx.all_ir],
    }
    manifest_payload["plugins"] = ctx.plugin_report
    if ctx.options.baseline:
        manifest_payload["baseline"] = ctx.options.baseline
    if ctx.selection is not None:
        selection = cast("ConfigSelection", ctx.selection)
        manifest_payload["config_source"] = {
            "path": str(selection.path),
            "source": str(selection.source),
        }

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return MANIFEST_PATH
