# SPDX-License-Identifier: MIT
"""Typer CLI for building CST datasets."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

import click
import typer

from codeintel_rev.cst_build.cst_collect import CSTCollector
from codeintel_rev.cst_build.cst_resolve import (
    StitchCounters,
    load_modules,
    load_scip_index,
    stitch_nodes,
)
from codeintel_rev.cst_build.cst_schema import CollectorStats
from codeintel_rev.cst_build.cst_serialize import DatasetWriter, write_index, write_join_examples

app = typer.Typer(add_completion=False, help="Build LibCST-backed datasets and stitching audits.")

ROOT_DEFAULT = Path("codeintel_rev")
SCIP_DEFAULT = Path("codeintel_rev/index.scip.json")
MODULES_DEFAULT = Path("build/enrich/modules/modules.jsonl")
OUT_DEFAULT = Path("io/CST")

_DIR_PATH = click.Path(path_type=Path, dir_okay=True, file_okay=False)
_FILE_PATH = click.Path(path_type=Path, dir_okay=False, file_okay=True, writable=False)


@dataclass(slots=True, frozen=True)
class CLIOptions:
    """Materialized CLI arguments after Click parsing."""

    root: Path
    scip: Path | None
    modules: Path | None
    out: Path
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    limit: int | None
    fail_on_parse_error: bool
    debug_joins: bool


def _store_option(ctx: click.Context, param: click.Parameter, value: object) -> object:
    """Store option value in Click context for later retrieval.

    Callback function used by Click decorators to store parsed option values
    in the context object dictionary.

    Parameters
    ----------
    ctx : click.Context
        Click context object containing the option storage dictionary.
    param : click.Parameter
        Click parameter object containing the option name.
    value : Any
        Parsed option value to store.

    Returns
    -------
    Any
        The value passed in, returned unchanged.
    """
    ctx.ensure_object(dict)[param.name] = value
    return value


def _options_from_context(ctx: typer.Context) -> CLIOptions:
    """Extract CLI options from Typer context and construct CLIOptions.

    Parameters
    ----------
    ctx : typer.Context
        Typer context object containing stored option values.

    Returns
    -------
    CLIOptions
        Materialized CLI options dataclass with resolved paths and defaults.
    """
    raw = ctx.ensure_object(dict)
    return CLIOptions(
        root=Path(raw.get("root", ROOT_DEFAULT)).resolve(),
        scip=raw.get("scip"),
        modules=raw.get("modules"),
        out=Path(raw.get("out", OUT_DEFAULT)),
        include=tuple(raw.get("include") or ()),
        exclude=tuple(raw.get("exclude") or ()),
        limit=raw.get("limit"),
        fail_on_parse_error=bool(raw.get("fail_on_parse_error", False)),
        debug_joins=bool(raw.get("debug_joins", False)),
    )


@app.command()
@click.pass_context
@click.option(
    "--root",
    type=_DIR_PATH,
    default=ROOT_DEFAULT,
    show_default=True,
    expose_value=False,
    callback=_store_option,
    help="Repo root to scan.",
)
@click.option(
    "--scip",
    type=_FILE_PATH,
    default=SCIP_DEFAULT,
    show_default=True,
    expose_value=False,
    callback=_store_option,
    help="Path to SCIP index JSON.",
)
@click.option(
    "--modules",
    type=_FILE_PATH,
    default=MODULES_DEFAULT,
    show_default=True,
    expose_value=False,
    callback=_store_option,
    help="Path to modules.jsonl produced by codeintel-enrich.",
)
@click.option(
    "--out",
    type=_DIR_PATH,
    default=OUT_DEFAULT,
    show_default=True,
    expose_value=False,
    callback=_store_option,
    help="Output directory for CST artifacts.",
)
@click.option(
    "--include",
    "include",
    multiple=True,
    expose_value=False,
    callback=_store_option,
    help="Glob pattern(s) limiting files relative to --root (repeatable).",
)
@click.option(
    "--exclude",
    "exclude",
    multiple=True,
    expose_value=False,
    callback=_store_option,
    help="Glob pattern(s) to skip files (repeatable).",
)
@click.option(
    "--limit",
    type=int,
    expose_value=False,
    callback=_store_option,
    help="Maximum number of files to process (debugging).",
)
@click.option(
    "--fail-on-parse-error/--no-fail-on-parse-error",
    default=False,
    expose_value=False,
    callback=_store_option,
    help="Exit with non-zero status when LibCST parsing fails.",
)
@click.option(
    "--debug-joins/--no-debug-joins",
    default=False,
    expose_value=False,
    callback=_store_option,
    help="Capture stitch candidate details for debugging.",
)
def main(ctx: typer.Context) -> None:
    """Entry point invoked by Typer.

    Parameters
    ----------
    ctx : typer.Context
        Typer context object containing parsed CLI options.

    Notes
    -----
    This function delegates to :func:`_run_pipeline`, which may raise
    ``typer.Exit`` if no files match or parse errors occur with
    ``--fail-on-parse-error`` enabled.
    """
    _run_pipeline(_options_from_context(ctx))


def _run_pipeline(options: CLIOptions) -> None:
    """Execute the CST collection and stitching pipeline.

    Parameters
    ----------
    options : CLIOptions
        Materialized CLI options containing root path, output directory,
        filters, and processing flags.

    Raises
    ------
    typer.Exit
        Exit code 1 if no Python files match the provided filters, or if
        parse errors occur and options.fail_on_parse_error is True.
    """
    files = list(_iter_py_files(options.root, options.include, options.exclude))
    if options.limit is not None:
        files = files[: options.limit]
    if not files:
        typer.secho("No Python files matched the provided filters.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)
    module_lookup = load_modules(options.modules)
    if not module_lookup:
        typer.secho(
            "Warning: modules.jsonl not found or empty; module stitching disabled.",
            fg=typer.colors.YELLOW,
        )
    scip_resolver = load_scip_index(options.scip)
    if not scip_resolver:
        typer.secho(
            "Warning: SCIP index not found; SCIP stitching disabled.", fg=typer.colors.YELLOW
        )
    collector = CSTCollector(options.root, files)
    aggregate_stats = CollectorStats()
    stitch_totals = StitchCounters()

    with DatasetWriter(options.out) as writer:
        for idx, file_path in enumerate(files, 1):
            rel_path = file_path.resolve().relative_to(options.root).as_posix()
            typer.secho(f"[{idx}/{len(files)}] indexing {rel_path}", fg=typer.colors.BLUE)
            writer.observe_file(rel_path)
            nodes, file_stats = collector.collect_file(file_path)
            aggregate_stats.merge(file_stats)
            stitched_nodes, file_stitch = stitch_nodes(
                nodes,
                module_lookup=module_lookup,
                scip_resolver=scip_resolver,
                debug=options.debug_joins,
            )
            stitch_totals.merge(file_stitch)
            writer.write_nodes(stitched_nodes)
        write_index(
            options.out,
            root=options.root,
            collector_stats=aggregate_stats,
            stitch_stats=stitch_totals,
            writer=writer,
        )
        samples = writer.samples
        write_join_examples(options.out, samples)
        typer.secho(
            f"codeintel-cst complete: {writer.node_count} nodes across {aggregate_stats.files_indexed} files.",
            fg=typer.colors.GREEN,
        )
        if samples:
            typer.secho("Sample stitched joins:", fg=typer.colors.MAGENTA)
            for sample in samples[:3]:
                span = sample.span.to_dict()
                symbol = sample.stitch.scip_symbol if sample.stitch else ""
                typer.echo(
                    f"- {sample.path} [{span['start']}→{span['end']}] {sample.kind} "
                    f"{sample.name or ''} → {symbol}"
                )
    if options.fail_on_parse_error and aggregate_stats.parse_errors:
        typer.secho(
            f"Encountered {aggregate_stats.parse_errors} parse errors. Failing per --fail-on-parse-error.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)


def _iter_py_files(
    root: Path, include: Iterable[str] | None, exclude: Iterable[str] | None
) -> Iterable[Path]:
    include_patterns = tuple(include or ())
    exclude_patterns = tuple(exclude or ())
    for candidate in sorted(root.rglob("*.py"), key=lambda item: item.as_posix()):
        rel_parts = candidate.resolve().relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        rel = "/".join(rel_parts)
        if include_patterns and not any(fnmatch(rel, pattern) for pattern in include_patterns):
            continue
        if exclude_patterns and any(fnmatch(rel, pattern) for pattern in exclude_patterns):
            continue
        yield candidate


if __name__ == "__main__":  # pragma: no cover
    app()
