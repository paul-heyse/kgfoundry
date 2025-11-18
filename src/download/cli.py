"""Download CLI adopted onto the shared tooling metadata contracts."""

from __future__ import annotations

import re
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
HARVEST_OVERRIDE = cli_context.get_operation_override("harvest")
if HARVEST_OVERRIDE and HARVEST_OVERRIDE.description:
    HARVEST_DESCRIPTION = HARVEST_OVERRIDE.description
else:
    HARVEST_DESCRIPTION = "Harvest documents from OpenAlex matching query parameters."

DEFAULT_YEARS = ">=2018"
DEFAULT_MAX_WORKS = 20_000


@dataclass(slots=True, frozen=True)
class HarvestRequest:
    """Structured request describing a harvest invocation.

    Attributes
    ----------
    topic : str
        Topic query string to harvest from OpenAlex.
    years : str
        Year filter expression (e.g., '>=2018').
    max_works : int
        Maximum number of works to harvest.
    """

    topic: str
    years: str
    max_works: int


class HarvestHandler(Protocol):
    """Protocol describing harvest handler callables."""

    def __call__(self, request: HarvestRequest) -> str: ...


class ArtifactFS(Protocol):
    """Protocol describing filesystem interactions for CLI artifacts."""

    def ensure_dir(self, directory: Path) -> None:
        """Ensure the specified directory exists.

        Parameters
        ----------
        directory : Path
            Directory path to create if it doesn't exist.
        """
        ...

    def write_text(self, path: Path, content: str, *, encoding: str = "utf-8") -> None:
        """Write text content to a file.

        Parameters
        ----------
        path : Path
            File path to write to.
        content : str
            Text content to write.
        encoding : str, optional
            Text encoding to use. Defaults to "utf-8".
        """
        ...


def _default_harvest_handler(request: HarvestRequest) -> str:
    """Return a dry-run message describing the harvest request.

    Parameters
    ----------
    request : HarvestRequest
        Harvest request parameters.

    Returns
    -------
    str
        Dry-run message describing what would be harvested.
    """
    return (
        "[dry-run] would harvest "
        f"topic={request.topic!r} years={request.years!r} max_works={request.max_works}"
    )


@dataclass(slots=True, frozen=True)
class DownloadCliContext:
    """Dependency injection context for download CLI operations.

    Attributes
    ----------
    harvest_handler : HarvestHandler
        Callable handler function for executing harvest operations.
    artifact_dir : Path
        Directory path where harvested artifacts are written.
    artifact_fs : ArtifactFS
        Filesystem interface for writing artifact files.
    """

    harvest_handler: HarvestHandler
    artifact_dir: Path
    artifact_fs: ArtifactFS

    @classmethod
    def production(cls) -> DownloadCliContext:
        """Return the production CLI context with default handler.

        Returns
        -------
        DownloadCliContext
            Context configured with the default harvest handler.
        """
        return cls(
            harvest_handler=_default_harvest_handler,
            artifact_dir=REPO_ROOT / "data" / "download_artifacts",
            artifact_fs=_LocalArtifactFS(),
        )


class _LocalArtifactFS:
    """Filesystem implementation that writes to disk.

    Methods
    -------
    ensure_dir(directory)
        Create the directory and all parent directories if they don't exist.
    write_text(path, content, *, encoding)
        Write text content to a file, creating parent directories if needed.
    """

    def ensure_dir(self, directory: Path) -> None:
        """Ensure the specified directory exists.

        Parameters
        ----------
        directory : Path
            Directory path to create.
        """
        _ = self
        directory.mkdir(parents=True, exist_ok=True)

    def write_text(self, path: Path, content: str, *, encoding: str = "utf-8") -> None:
        """Write text content to a file.

        Parameters
        ----------
        path : Path
            File path where content will be written.
        content : str
            Text content to write.
        encoding : str, optional
            Text encoding to use (default: "utf-8").
        """
        _ = self
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)


def _resolve_cli_help() -> str:
    """Resolve the CLI help text from configuration.

    Returns
    -------
    str
        Formatted help text combining title and version.
    """
    title = CLI_CONFIG.title or CLI_TITLE
    version = CLI_CONFIG.version
    return f"{title} ({version})"


app = typer.Typer(help=_resolve_cli_help(), no_args_is_help=True, add_completion=False)
download_app = typer.Typer(help=HARVEST_DESCRIPTION, no_args_is_help=True, add_completion=False)
app.add_typer(download_app, name=CLI_COMMAND, help=HARVEST_DESCRIPTION)

_DEFAULT_CONTEXT = DownloadCliContext.production()


def _default_envelope_dir() -> Path:
    """Return the default directory for CLI envelope files.

    Returns
    -------
    Path
        Default envelope directory path.
    """
    return REPO_ROOT / "site" / "_build" / "cli"


EnvelopeDirOption = Annotated[
    Path | None,
    typer.Option(
        "--envelope-dir",
        help="Directory where CLI envelopes are written.",
        dir_okay=True,
        file_okay=False,
    ),
]


ArtifactDirOption = Annotated[
    Path | None,
    typer.Option(
        "--artifact-dir",
        help="Directory where harvested artifacts are written.",
        dir_okay=True,
        file_okay=False,
    ),
]


def _store_cli_state(
    ctx: typer.Context,
    *,
    envelope_dir: Path | None,
    artifact_dir: Path | None,
) -> None:
    """Store CLI state in the Typer context.

    Parameters
    ----------
    ctx : typer.Context
        Typer context object.
    envelope_dir : Path | None
        Optional directory path for envelope files.
    artifact_dir : Path | None
        Optional directory path for artifact files.
    """
    state = ctx.ensure_object(dict)
    state["envelope_dir"] = envelope_dir
    state["artifact_dir"] = artifact_dir


def _resolve_envelope_dir(ctx: typer.Context | None) -> Path:
    """Resolve the envelope directory from context or return default.

    Parameters
    ----------
    ctx : typer.Context | None
        Optional Typer context object.

    Returns
    -------
    Path
        Envelope directory path from context or default.
    """
    default_dir = _default_envelope_dir()
    if ctx is None or ctx.obj is None:
        return default_dir
    state = ctx.ensure_object(dict)
    directory = state.get("envelope_dir")
    if directory is None:
        return default_dir
    return Path(directory)


def _cli_context(ctx: typer.Context | None = None) -> DownloadCliContext:
    """Resolve the CLI context from Typer or Click context.

    Parameters
    ----------
    ctx : typer.Context | None, optional
        Optional Typer context object. If None, attempts to get Click context.

    Returns
    -------
    DownloadCliContext
        CLI context instance, either from context state or default.
    """
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
    envelope_dir: EnvelopeDirOption = None,
    artifact_dir: ArtifactDirOption = None,
) -> None:
    """Configure shared CLI options applicable to all subcommands."""
    _store_cli_state(ctx, envelope_dir=envelope_dir, artifact_dir=artifact_dir)
    state = ctx.ensure_object(dict)
    context = state.setdefault("cli_context", _DEFAULT_CONTEXT)
    if artifact_dir is not None and isinstance(context, DownloadCliContext):
        state["cli_context"] = DownloadCliContext(
            harvest_handler=context.harvest_handler,
            artifact_dir=artifact_dir,
            artifact_fs=context.artifact_fs,
        )


def _envelope_path(subcommand: str, *, envelope_dir: Path) -> Path:
    """Generate the file path for a CLI envelope.

    Parameters
    ----------
    subcommand : str
        Subcommand name (e.g., "harvest").
    envelope_dir : Path
        Directory where envelope files are stored.

    Returns
    -------
    Path
        Full path to the envelope JSON file.
    """
    safe_subcommand = subcommand or "root"
    filename = f"{CLI_SETTINGS.bin_name}-{CLI_COMMAND}-{safe_subcommand.replace('/', '-')}.json"
    return envelope_dir / filename


def _emit_envelope(
    envelope: CliEnvelope,
    *,
    subcommand: str,
    envelope_dir: Path,
) -> Path:
    """Write a CLI envelope to disk.

    Parameters
    ----------
    envelope : CliEnvelope
        Envelope object to serialize and write.
    subcommand : str
        Subcommand name for filename generation.
    envelope_dir : Path
        Directory where envelope files are stored.

    Returns
    -------
    Path
        Path to the written envelope file.
    """
    path = _envelope_path(subcommand, envelope_dir=envelope_dir)
    envelope_dir.mkdir(parents=True, exist_ok=True)
    rendered = render_cli_envelope(envelope)
    path.write_text(rendered + "\n", encoding="utf-8")
    return path


def _harvest_problem(
    detail: str, *, status: int = 500, extras: dict[str, Any] | None = None
) -> ProblemDetailsDict:
    """Build a Problem Details dictionary for harvest command errors.

    Parameters
    ----------
    detail : str
        Human-readable error detail message.
    status : int, optional
        HTTP status code (default: 500).
    extras : dict[str, Any] | None, optional
        Optional additional error context.

    Returns
    -------
    ProblemDetailsDict
        RFC 9457 Problem Details dictionary.
    """
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


def _artifact_filename(topic: str) -> str:
    """Generate a safe filename from a topic string.

    Parameters
    ----------
    topic : str
        Topic query string to convert to filename.

    Returns
    -------
    str
        Safe filename with topic slug and "-artifacts.txt" suffix.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    safe = slug or "harvest"
    return f"{safe}-artifacts.txt"


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

    artifact_dir = download_context.artifact_dir
    artifact_fs = download_context.artifact_fs
    artifact_fs.ensure_dir(artifact_dir)
    artifact_path = artifact_dir / _artifact_filename(topic)
    artifact_fs.write_text(artifact_path, message + "\n", encoding="utf-8")
    builder = builder.add_file(path=str(artifact_path), status="success", message=message)
    envelope = builder.finish(duration_seconds=time.monotonic() - start)
    path = _emit_envelope(
        envelope,
        subcommand="harvest",
        envelope_dir=envelope_dir,
    )
    typer.echo(f"Harvest command completed; envelope saved to {path}")


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    app()
