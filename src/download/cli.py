"""Download CLI adopted onto the shared tooling metadata contracts."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Protocol

import click
import typer
from tools import (
    CliEnvelope,
    CliEnvelopeBuilder,
    ProblemDetailsDict,
    ProblemDetailsParams,
    build_problem_details,
    render_cli_envelope,
)

from download import cli_context
from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "DownloadCliContext",
    "HarvestRequest",
    "app",
    "harvest",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


CLI_COMMAND = cli_context.CLI_COMMAND
CLI_OPERATION_IDS = cli_context.CLI_OPERATION_IDS
CLI_TITLE = cli_context.CLI_TITLE
CLI_INTERFACE_ID = cli_context.CLI_INTERFACE_ID

CLI_SETTINGS = cli_context.get_cli_settings()
CLI_CONFIG = cli_context.get_cli_config()

REPO_ROOT = cli_context.REPO_ROOT
CLI_ENVELOPE_DIR = REPO_ROOT / "site" / "_build" / "cli"

HARVEST_OVERRIDE = cli_context.get_operation_override("harvest")
if HARVEST_OVERRIDE and HARVEST_OVERRIDE.description:
    HARVEST_DESCRIPTION = HARVEST_OVERRIDE.description
else:
    HARVEST_DESCRIPTION = "Harvest documents from OpenAlex matching query parameters."

DEFAULT_YEARS = ">=2018"
DEFAULT_MAX_WORKS = 20_000


@dataclass(slots=True, frozen=True)
class HarvestRequest:
    """Structured request describing a harvest invocation."""

    topic: str
    years: str
    max_works: int


class HarvestHandler(Protocol):
    """Protocol describing harvest handler callables."""

    def __call__(self, request: HarvestRequest) -> str: ...


def _default_harvest_handler(request: HarvestRequest) -> str:
    return (
        "[dry-run] would harvest "
        f"topic={request.topic!r} years={request.years!r} max_works={request.max_works}"
    )


@dataclass(slots=True, frozen=True)
class DownloadCliContext:
    """Dependency injection context for download CLI operations."""

    harvest_handler: HarvestHandler

    @classmethod
    def production(cls) -> DownloadCliContext:
        """Return the production CLI context with default handler.

        Returns
        -------
        DownloadCliContext
            Context configured with the default harvest handler.
        """
        return cls(harvest_handler=_default_harvest_handler)


def _resolve_cli_help() -> str:
    title = CLI_CONFIG.title or CLI_TITLE
    version = CLI_CONFIG.version
    return f"{title} ({version})"


app = typer.Typer(help=_resolve_cli_help(), no_args_is_help=True, add_completion=False)
download_app = typer.Typer(help=HARVEST_DESCRIPTION, no_args_is_help=True, add_completion=False)
app.add_typer(download_app, name=CLI_COMMAND, help=HARVEST_DESCRIPTION)

_DEFAULT_CONTEXT = DownloadCliContext.production()


EnvelopeDirOption = Annotated[
    Path,
    typer.Option(
        "--envelope-dir",
        help="Directory where CLI envelopes are written.",
        dir_okay=True,
        file_okay=False,
        show_default=True,
    ),
]


def _store_cli_state(ctx: typer.Context, envelope_dir: Path) -> None:
    state = ctx.ensure_object(dict)
    state["envelope_dir"] = envelope_dir


def _resolve_envelope_dir(ctx: typer.Context | None) -> Path:
    if ctx is None or ctx.obj is None:
        return CLI_ENVELOPE_DIR
    state = ctx.ensure_object(dict)
    directory = state.get("envelope_dir")
    if directory is None:
        return CLI_ENVELOPE_DIR
    return Path(directory)


def _cli_context(ctx: typer.Context | None = None) -> DownloadCliContext:
    active = ctx or click.get_current_context(silent=True)
    if active is None:
        return _DEFAULT_CONTEXT
    state = active.ensure_object(dict)
    existing = state.get("cli_context")
    if isinstance(existing, DownloadCliContext):
        return existing
    state["cli_context"] = _DEFAULT_CONTEXT
    return _DEFAULT_CONTEXT


@app.callback()
def main_callback(
    ctx: typer.Context,
    envelope_dir: EnvelopeDirOption = CLI_ENVELOPE_DIR,
) -> None:
    """Configure shared CLI options applicable to all subcommands."""
    _store_cli_state(ctx, envelope_dir)
    state = ctx.ensure_object(dict)
    state.setdefault("cli_context", _DEFAULT_CONTEXT)


def _envelope_path(subcommand: str, *, envelope_dir: Path) -> Path:
    safe_subcommand = subcommand or "root"
    filename = f"{CLI_SETTINGS.bin_name}-{CLI_COMMAND}-{safe_subcommand.replace('/', '-')}.json"
    return envelope_dir / filename


def _emit_envelope(
    envelope: CliEnvelope,
    *,
    subcommand: str,
    envelope_dir: Path,
) -> Path:
    path = _envelope_path(subcommand, envelope_dir=envelope_dir)
    envelope_dir.mkdir(parents=True, exist_ok=True)
    rendered = render_cli_envelope(envelope)
    path.write_text(rendered + "\n", encoding="utf-8")
    return path


def _harvest_problem(
    detail: str, *, status: int = 500, extras: dict[str, Any] | None = None
) -> ProblemDetailsDict:
    return build_problem_details(
        ProblemDetailsParams(
            type="https://kgfoundry.dev/problems/download/harvest-error",
            title="Download harvest command failed",
            status=status,
            detail=detail,
            instance=f"urn:cli:download:{CLI_INTERFACE_ID}",
            extensions=extras,
        )
    )


@download_app.command(help=HARVEST_DESCRIPTION)
def harvest(
    ctx: typer.Context,
    topic: str = typer.Argument(..., help="Topic query string to harvest."),
    years: str = typer.Option(
        DEFAULT_YEARS,
        "--years",
        "-y",
        help="Year filter expression (e.g., '>=2018').",
        metavar="EXPR",
        show_default=True,
    ),
    max_works: int = typer.Option(
        DEFAULT_MAX_WORKS,
        "--max-works",
        "-m",
        help="Maximum number of works to harvest.",
        metavar="COUNT",
        show_default=True,
    ),
) -> None:
    """Harvest documents from OpenAlex using the shared CLI tooling context.

    Parameters
    ----------
    ctx : typer.Context
        Typer context object providing access to CLI state and shared options.
    topic : str
        Topic query string to harvest.
    years : str
        Year filter expression (e.g., '>=2018'). Defaults to ``DEFAULT_YEARS``.
    max_works : int
        Maximum number of works to harvest. Defaults to ``DEFAULT_MAX_WORKS``.

    Raises
    ------
    typer.Exit
        Raised with a non-zero exit code when the command fails.
    """
    start = time.monotonic()
    builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND,
        status="success",
        subcommand="harvest",
    )
    envelope_dir = _resolve_envelope_dir(ctx)
    download_context = _cli_context(ctx)
    try:
        message = download_context.harvest_handler(
            HarvestRequest(topic=topic, years=years, max_works=max_works)
        )
        builder = builder.add_file(path="openalex", status="success", message=message)
        typer.echo(message)
    except Exception as exc:  # pragma: no cover - defensive catch for future integrations
        problem = _harvest_problem(str(exc))
        failure_builder = CliEnvelopeBuilder.create(
            command=CLI_COMMAND,
            status="error",
            subcommand="harvest",
        )
        failure_builder = failure_builder.add_error(
            status="error",
            message=str(exc),
            problem=problem,
        )
        failure_builder = failure_builder.set_problem(problem)
        envelope = failure_builder.finish(duration_seconds=time.monotonic() - start)
        path = _emit_envelope(envelope, subcommand="harvest", envelope_dir=envelope_dir)
        typer.echo(
            f"Harvest command failed; envelope saved to {path}",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    envelope = builder.finish(duration_seconds=time.monotonic() - start)
    path = _emit_envelope(envelope, subcommand="harvest", envelope_dir=envelope_dir)
    typer.echo(f"Harvest command completed; envelope saved to {path}")


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    app()
