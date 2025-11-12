# SPDX-License-Identifier: MIT
"""CLI entrypoint for CST dataset builds."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

import click

from codeintel_rev.cst_build.cst_collect import CSTCollector
from codeintel_rev.cst_build.cst_resolve import (
    StitchCounters,
    load_modules,
    load_scip_index,
    stitch_nodes,
)
from codeintel_rev.cst_build.cst_schema import CollectorStats
from codeintel_rev.cst_build.cst_serialize import DatasetWriter, write_index, write_join_examples


@dataclass(slots=True, frozen=True)
class CLIOptions:
    """Normalized command-line options."""

    root: Path
    scip: Path
    modules: Path
    out: Path
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    limit: int | None
    fail_on_parse_error: bool
    debug_joins: bool


ROOT_DEFAULT = Path("codeintel_rev")
SCIP_DEFAULT = Path("codeintel_rev/index.scip.json")
MODULES_DEFAULT = Path("build/enrich/modules/modules.jsonl")
OUT_DEFAULT = Path("io/CST")


def _build_options(ctx: click.Context) -> CLIOptions:
    """Extract and normalize CLI options from Click context.

    Parameters
    ----------
    ctx : click.Context
        Click context object containing parsed command-line parameters.

    Returns
    -------
    CLIOptions
        Normalized dataclass instance containing all CLI options with resolved paths.
    """
    params = ctx.params
    return CLIOptions(
        root=Path(params["root"]).resolve(),
        scip=Path(params["scip"]).resolve(),
        modules=Path(params["modules"]).resolve(),
        out=Path(params["out"]).resolve(),
        include=tuple(params.get("include") or ()),
        exclude=tuple(params.get("exclude") or ()),
        limit=params.get("limit"),
        fail_on_parse_error=bool(params.get("fail_on_parse_error")),
        debug_joins=bool(params.get("debug_joins")),
    )


@click.command()
@click.pass_context
@click.option(
    "--root",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=ROOT_DEFAULT,
    show_default=True,
    help="Repo root to scan.",
)
@click.option(
    "--scip",
    type=click.Path(file_okay=True, dir_okay=False, exists=True, path_type=Path),
    default=SCIP_DEFAULT,
    show_default=True,
    help="Path to SCIP index JSON.",
)
@click.option(
    "--modules",
    type=click.Path(file_okay=True, dir_okay=False, exists=True, path_type=Path),
    default=MODULES_DEFAULT,
    show_default=True,
    help="Path to modules.jsonl produced by codeintel-enrich.",
)
@click.option(
    "--out",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=OUT_DEFAULT,
    show_default=True,
    help="Output directory for CST artifacts.",
)
@click.option(
    "--include",
    "include",
    multiple=True,
    show_default=False,
    help="Glob pattern(s) limiting files relative to --root (repeatable).",
)
@click.option(
    "--exclude",
    "exclude",
    multiple=True,
    show_default=False,
    help="Glob pattern(s) to skip files (repeatable).",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    show_default=False,
    help="Maximum number of files to process (debugging).",
)
@click.option(
    "--fail-on-parse-error/--no-fail-on-parse-error",
    default=False,
    show_default=True,
    help="Exit with non-zero status when LibCST parsing fails.",
)
@click.option(
    "--debug-joins/--no-debug-joins",
    default=False,
    show_default=True,
    help="Capture stitch candidate details for debugging.",
)
def main(ctx: click.Context, **_: object) -> None:
    """Entry point invoked by the console script.

    Scans the repository root for Python files, collects CST nodes, stitches them
    to module and SCIP symbols, and writes dataset artifacts to the output directory.

    Parameters
    ----------
    ctx : click.Context
        Click context object containing parsed command-line options.
    **_
        Additional keyword arguments (unused, required by Click decorator).
        Type: object

    Raises
    ------
    click.exceptions.Exit
        Exit code 1 when no files match or when parse errors occur while
        ``--fail-on-parse-error`` is enabled.
    """
    options = _build_options(ctx)
    files = list(_iter_py_files(options.root, options.include, options.exclude))
    if options.limit is not None:
        files = files[: options.limit]
    if not files:
        click.secho("No Python files matched the provided filters.", fg="yellow")
        raise click.exceptions.Exit(1)
    module_lookup = load_modules(options.modules)
    if not module_lookup:
        click.secho(
            "Warning: modules.jsonl not found or empty; module stitching disabled.",
            fg="yellow",
        )
    scip_resolver = load_scip_index(options.scip)
    if not scip_resolver:
        click.secho(
            "Warning: SCIP index not found; SCIP stitching disabled.",
            fg="yellow",
        )
    collector = CSTCollector(options.root, files)
    aggregate_stats = CollectorStats()
    stitch_totals = StitchCounters()

    with DatasetWriter(options.out) as writer:
        for idx, file_path in enumerate(files, 1):
            rel_path = file_path.resolve().relative_to(options.root).as_posix()
            click.secho(f"[{idx}/{len(files)}] indexing {rel_path}", fg="blue")
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
        click.secho(
            f"codeintel-cst complete: {writer.node_count} nodes across {aggregate_stats.files_indexed} files.",
            fg="green",
        )
        if samples:
            click.secho("Sample stitched joins:", fg="magenta")
            for sample in samples[:3]:
                span = sample.span.to_dict()
                symbol = sample.stitch.scip_symbol if sample.stitch else ""
                click.echo(
                    f"- {sample.path} [{span['start']}→{span['end']}] {sample.kind} "
                    f"{sample.name or ''} → {symbol}"
                )
    if options.fail_on_parse_error and aggregate_stats.parse_errors:
        click.secho(
            "Encountered parse errors. Failing per --fail-on-parse-error.",
            fg="red",
        )
        raise click.exceptions.Exit(1)


def _iter_py_files(root: Path, include: Sequence[str], exclude: Sequence[str]) -> list[Path]:
    """Discover Python files matching include/exclude glob patterns.

    Recursively scans the root directory for .py files and filters them based on
    include and exclude glob patterns. Patterns are matched against relative paths
    from the root directory.

    Parameters
    ----------
    root : Path
        Root directory to scan for Python files.
    include : Sequence[str]
        Glob patterns that files must match to be included. Empty sequence means
        all files are included (subject to exclude patterns).
    exclude : Sequence[str]
        Glob patterns that exclude files from the result set.

    Returns
    -------
    list[Path]
        Sorted list of absolute paths to Python files matching the filters.
    """
    include_patterns = tuple(include or ())
    exclude_patterns = tuple(exclude or ())
    files: list[Path] = []
    for candidate in sorted(root.rglob("*.py"), key=lambda item: item.as_posix()):
        rel_parts = candidate.resolve().relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        rel = "/".join(rel_parts)
        if include_patterns and not any(fnmatch(rel, pattern) for pattern in include_patterns):
            continue
        if exclude_patterns and any(fnmatch(rel, pattern) for pattern in exclude_patterns):
            continue
        files.append(candidate)
    return files


if __name__ == "__main__":  # pragma: no cover
    main()
