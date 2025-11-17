"""Overlay-focused CLI for enrichment tooling."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import typer

import codeintel_rev.cli.enrich_pipeline as pipeline
from codeintel_rev.enrich.stubs_overlay import (
    activate_overlays,
    deactivate_all,
    generate_overlay_for_file,
)

app = typer.Typer(add_completion=True, help="Overlay generation commands.")
pipeline.attach_argv_normalizer(app, pipeline.normalize_global_cli_args)
app.callback()(pipeline.shared_options)


def overlays(
    ctx: typer.Context,
    *,
    config_path: Path | None = pipeline.OVERLAYS_CONFIG_OPTION,
    overrides: list[str] | None = pipeline.OVERLAYS_SET_OPTION,
    dry_run: bool = pipeline.DRY_RUN_OPTION,
) -> None:
    state = pipeline.ensure_state(ctx)
    pipeline_opts = state.pipeline
    if pipeline_opts.scip is None:
        message = "The --scip option is required for overlay generation."
        raise typer.BadParameter(message)
    options = pipeline.load_overlay_options(config_path, list(overrides or ()))
    if dry_run and not options.dry_run:
        options = replace(options, dry_run=True)
    overlay_ctx = pipeline.build_overlay_context(pipeline_opts, options)
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
    for fp in pipeline.iter_files(overlay_ctx.root):
        rel = pipeline.normalized_rel_path(fp, overlay_ctx.root)
        result = generate_overlay_for_file(
            py_file=fp,
            package_root=overlay_ctx.root,
            policy=overlay_ctx.policy,
            inputs=overlay_ctx.inputs,
        )
        if result.created and rel not in generated_set:
            generated.append(rel)
            generated_set.add(rel)
            manifest_entries.append(f"{overlay_ctx.package_name}/{rel}")
            if len(generated) >= overlay_ctx.policy.max_overlays or pipeline.ensure_package_overlays(
                rel_path=Path(rel),
                generated=generated,
                generated_set=generated_set,
                manifest_entries=manifest_entries,
                package_name=overlay_ctx.package_name,
                package_overlays=package_overlays,
                root=overlay_ctx.root,
                scip_index=overlay_ctx.scip_index,
                policy=overlay_ctx.policy,
                type_error_counts=overlay_ctx.type_counts,
            ):
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
    pipeline.write_json(
        manifest_path,
        {
            "package": overlay_ctx.package_name,
            "generated": manifest_entries,
            "removed": removed,
            "activated": bool(options.activate and generated),
        },
    )
    typer.echo(f"[overlays] Manifest written to {manifest_path}")


app.command("overlays")(overlays)


def main() -> None:  # pragma: no cover - entrypoint
    app()


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["app"]
