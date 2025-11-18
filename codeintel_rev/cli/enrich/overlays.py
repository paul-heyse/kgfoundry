# SPDX-License-Identifier: MIT
"""Overlays command."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import typer

from codeintel_rev.cli.enrich import app, common
from codeintel_rev.enrich.output_writers import write_json
from codeintel_rev.enrich.stubs_overlay import (
    activate_overlays,
    deactivate_all,
    generate_overlay_for_file,
)
from codeintel_rev.services.enrich import overlays as overlay_services
from codeintel_rev.services.enrich.scan import iter_python_files


@app.command("overlays")
def overlays(
    ctx: typer.Context,
    *,
    config_path: Path | None = common.OVERLAYS_CONFIG_OPTION,
    overrides: list[str] | None = common.OVERLAYS_SET_OPTION,
    dry_run: bool = common.DRY_RUN_OPTION,
) -> None:
    """Generate overlays for modules matching overlay-needed heuristics."""
    state = common.ensure_state(ctx)
    pipeline_opts = state.pipeline
    options = overlay_services.load_overlay_options(config_path, list(overrides or ()))
    if dry_run and not options.dry_run:
        options = replace(options, dry_run=True)
    overlay_ctx = overlay_services.build_overlay_context(pipeline_opts, options)
    overlay_ctx.overlays_root.mkdir(parents=True, exist_ok=True)
    overlay_ctx.stubs_root.parent.mkdir(parents=True, exist_ok=True)

    removed = 0
    if options.deactivate_all_first:
        removed = deactivate_all(
            overlays_root=overlay_ctx.overlays_root,
            stubs_root=overlay_ctx.stubs_root,
        )

    generated: list[str] = []
    generated_set: set[str] = set()
    manifest_entries: list[str] = []
    package_overlays: set[str] = set()
    for fp in iter_python_files(overlay_ctx.root):
        rel = Path(fp).relative_to(overlay_ctx.root)
        result = generate_overlay_for_file(
            py_file=fp,
            package_root=overlay_ctx.root,
            policy=overlay_ctx.policy,
            inputs=overlay_ctx.inputs,
        )
        rel_key = str(rel).replace("\\", "/")
        if result.created and rel_key not in generated_set:
            generated.append(rel_key)
            generated_set.add(rel_key)
            manifest_entries.append(f"{overlay_ctx.package_name}/{rel_key}")
            exhausted = overlay_services.ensure_package_overlays(
                rel_path=rel,
                generated=generated,
                generated_set=generated_set,
                manifest_entries=manifest_entries,
                package_name=overlay_ctx.package_name,
                package_overlays=package_overlays,
                root=overlay_ctx.root,
                scip_index=overlay_ctx.scip_index,
                policy=overlay_ctx.policy,
                type_error_counts=overlay_ctx.type_counts,
            )
            if exhausted:
                break
        if len(generated) >= overlay_ctx.policy.max_overlays:
            break

    if options.dry_run:
        typer.echo(
            f"[overlays] DRY RUN: would generate {len(generated)} overlays (removed {removed})."
        )
        return

    typer.echo(
        f"[overlays] Generated {len(generated)} overlays into {options.overlays_root} (removed {removed})."
    )
    if options.activate and generated:
        activated = activate_overlays(
            generated,
            overlays_root=overlay_ctx.overlays_root,
            stubs_root=overlay_ctx.stubs_root,
        )
        typer.echo(f"[overlays] Activated {activated} overlays into {options.stubs_root}.")

    manifest_path = overlay_ctx.overlays_root / "overlays_manifest.json"
    write_json(
        manifest_path,
        {
            "package": overlay_ctx.package_name,
            "generated": manifest_entries,
            "removed": removed,
            "activated": bool(options.activate and generated),
        },
    )
    typer.echo(f"[overlays] Manifest written to {manifest_path}")


def main() -> None:  # pragma: no cover - entrypoint shim
    """Invoke the enrichment CLI (overlays shim)."""
    from codeintel_rev.cli.enrich.__main__ import main as enrich_main

    enrich_main()


__all__ = ["main", "overlays"]
