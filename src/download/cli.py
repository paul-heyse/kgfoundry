"""Download CLI adopted onto the shared tooling metadata contracts."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import typer
from tools import (
    CliEnvelope,
    CliEnvelopeBuilder,
    ProblemDetailsDict,
    ProblemDetailsParams,
    build_problem_details,
    get_logger,
    render_cli_envelope,
    with_fields,
)

from download import cli_context
from kgfoundry_common.logging import LoggerAdapter as KGFLoggerAdapter
from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
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

HARVEST_OPERATION_ID = CLI_OPERATION_IDS["harvest"]
HARVEST_OVERRIDE = cli_context.get_operation_override("harvest")
if HARVEST_OVERRIDE and HARVEST_OVERRIDE.description:
    HARVEST_DESCRIPTION = HARVEST_OVERRIDE.description
else:
    HARVEST_DESCRIPTION = "Harvest documents from OpenAlex matching query parameters."
LOGGER = get_logger(__name__)

DEFAULT_YEARS = ">=2018"
DEFAULT_MAX_WORKS = 20_000


def _resolve_cli_help() -> str:
    title = CLI_CONFIG.title or CLI_TITLE
    version = CLI_CONFIG.version
    return f"{title} ({version})"


app = typer.Typer(help=_resolve_cli_help(), no_args_is_help=True, add_completion=False)
download_app = typer.Typer(
    help=HARVEST_DESCRIPTION, no_args_is_help=True, add_completion=False
)
app.add_typer(download_app, name=CLI_COMMAND, help=HARVEST_DESCRIPTION)


def _envelope_path(subcommand: str) -> Path:
    safe_subcommand = subcommand or "root"
    filename = f"{CLI_SETTINGS.bin_name}-{CLI_COMMAND}-{safe_subcommand.replace('/', '-')}.json"
    return CLI_ENVELOPE_DIR / filename


def _emit_envelope(
    envelope: CliEnvelope,
    *,
    subcommand: str,
    logger: logging.Logger | KGFLoggerAdapter,
) -> Path:
    path = _envelope_path(subcommand)
    CLI_ENVELOPE_DIR.mkdir(parents=True, exist_ok=True)
    rendered = render_cli_envelope(envelope)
    path.write_text(rendered + "\n", encoding="utf-8")
    logger.debug(
        "CLI envelope written",
        extra={"status": envelope.status, "cli_envelope": str(path)},
    )
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
    logger = with_fields(
        LOGGER,
        correlation_id=str(uuid4()),
        operation_id=HARVEST_OPERATION_ID,
        topic=topic,
        years=years,
        max_works=max_works,
    )

    logger.info("Harvest command started", extra={"status": "start"})
    try:
        message = f"[dry-run] would harvest topic={topic!r} years={years!r} max_works={max_works}"
        builder = builder.add_file(path="openalex", status="success", message=message)
        typer.echo(message)
    except (
        Exception
    ) as exc:  # pragma: no cover - defensive catch for future integrations
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
        path = _emit_envelope(envelope, subcommand="harvest", logger=logger)
        logger.exception(
            "Harvest command failed",
            extra={
                "status": "error",
                "cli_envelope": str(path),
                "duration_seconds": envelope.duration_seconds,
            },
        )
        raise typer.Exit(code=1) from exc

    envelope = builder.finish(duration_seconds=time.monotonic() - start)
    path = _emit_envelope(envelope, subcommand="harvest", logger=logger)
    logger.info(
        "Harvest command completed",
        extra={
            "status": "success",
            "cli_envelope": str(path),
            "duration_seconds": envelope.duration_seconds,
        },
    )


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    app()
