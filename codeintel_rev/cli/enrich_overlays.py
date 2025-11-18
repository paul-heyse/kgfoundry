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
    """Generate type stub overlays for Python files with type errors.

    This command generates type stub overlays (.pyi files) for Python files that
    have type errors, creating overlay files that provide correct type annotations
    without modifying the original source files. The command processes files in
    the repository, generates overlays up to a configured maximum, optionally
    activates them into the stubs directory, and writes a manifest of generated
    overlays.

    Parameters
    ----------
    ctx : typer.Context
        Typer context containing shared CLI state and pipeline options. Used to
        access pipeline configuration (root, scip index path) and build overlay
        context.
    config_path : Path | None, optional
        Optional path to overlay configuration file. If None, uses default
        configuration. The config file specifies overlay generation policy,
        maximum overlays, and activation settings.
    overrides : list[str] | None, optional
        Optional list of configuration overrides in key=value format. Overrides
        are applied on top of config file settings, enabling command-line
        customization of overlay generation behavior.
    dry_run : bool, optional
        Flag indicating whether to perform a dry run without actually generating
        or activating overlays. When True, the command reports what would be
        generated without making changes.

    Raises
    ------
    typer.BadParameter
        Raised when the --scip option is missing, which is required for overlay
        generation. The SCIP index is needed to analyze type errors and generate
        appropriate overlays.

    Notes
    -----
    Overlay generation enables type error correction without modifying source files
    by creating companion stub files (.pyi) that provide correct type annotations.
    The command iterates through Python files in the repository, generates overlays
    for files with type errors, optionally activates them into the stubs directory,
    and writes a manifest tracking generated overlays. The process respects maximum
    overlay limits and can deactivate existing overlays before generation.
    """
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
            if len(
                generated
            ) >= overlay_ctx.policy.max_overlays or pipeline.ensure_package_overlays(
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
    """Entry point for the overlay CLI application.

    This function serves as the main entry point for the overlay generation CLI,
    invoking the Typer application to process command-line arguments and execute
    overlay generation commands.

    Notes
    -----
    The function delegates to the Typer app instance, which handles argument
    parsing, command routing, and execution. This entry point is used when the
    module is executed directly or invoked as a CLI command.
    """
    app()


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["app"]
