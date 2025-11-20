"""Utilities for invoking Typer/CLI entry points in tests."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from click.testing import Result
from typer.main import Typer
from typer.testing import CliRunner

from orchestration.cli import BM25BuildConfig, IndexCliConfig, OrchestrationCliContext

_RUNNER = CliRunner(mix_stderr=False)


class _ArgNormalizer(Protocol):
    def __call__(self, argv: Sequence[str]) -> list[str]: ...


def invoke(
    app: Typer,
    args: Iterable[str],
    *,
    env: Mapping[str, str] | None = None,
    catch_exceptions: bool = False,
    obj: object | None = None,
) -> Result:
    """Invoke ``app`` with ``args`` and return the Typer result.

    Extended Summary
    ----------------
    This helper function provides a convenient way to invoke Typer CLI applications
    in tests. It wraps Typer's CliRunner with a shared instance and provides a
    simple interface for testing CLI commands with various arguments and environment
    variables.

    Parameters
    ----------
    app : Typer
        Typer application instance to invoke.
    args : Iterable[str]
        Command-line arguments to pass to the application. Converted to a list
        before invocation.
    env : Mapping[str, str] | None, optional
        Optional environment variables to set during invocation. None uses the
        current environment (default).
    catch_exceptions : bool, optional
        Whether to catch exceptions during invocation (default: False). When True,
        exceptions are captured in the result object instead of propagating.
    obj : object | None, optional
        Optional Click ``obj`` passed to the CLI context. Defaults to None.
        Pass dictionaries containing CLI-specific contexts (e.g.,
        ``{"splade_cli_context": ctx}``) and ``cli_run_overrides`` entries such as
        ``{"envelope_dir": tmp_path}`` to redirect envelope output without
        touching module globals.

    Returns
    -------
    Result
        Typer test result object containing exit code, stdout, stderr, and
        exception information (if catch_exceptions=True).

    Notes
    -----
        Performance & Side Effects:
            Time complexity O(1) for setup; actual execution time depends on the CLI
            command. Uses a shared CliRunner instance for efficiency. Thread-safe for
            concurrent test invocations (Typer runner handles isolation).
        CLI injection:
            Preferred pattern is to pass dependency contexts and overrides via ``obj``.
            Example::

                context = MyCliContext(...)
                invoke(
                    app,
                    args,
                    obj={
                        "my_cli_context": context,
                        "cli_run_overrides": {"envelope_dir": tmp_path},
                    },
                )
    """
    arg_list = list(args)
    normalizer_obj = getattr(app, "argv_normalizer", None)
    if normalizer_obj is None:
        normalizer_obj = getattr(app, "__kgf_normalize_args__", None)
    if normalizer_obj is not None and callable(normalizer_obj):
        normalizer = cast("_ArgNormalizer", normalizer_obj)
        normalized = normalizer(["cli", *arg_list])
        arg_list = normalized[1:]
    return _RUNNER.invoke(
        app,
        arg_list,
        env=env,
        catch_exceptions=catch_exceptions,
        obj=obj,
    )


def orchestration_cli_context(
    *,
    uuid_factory: Callable[[], str] | None = None,
    bm25_builder: Callable[[BM25BuildConfig, logging.Logger], tuple[str, int]] | None = None,
    faiss_runner: Callable[[IndexCliConfig], dict[str, object]] | None = None,
    artifact_fs: object | None = None,
) -> OrchestrationCliContext:
    """Return an orchestration CLI context with optional overrides.

    Parameters
    ----------
    uuid_factory : Callable[[], str] | None, optional
        Custom UUID factory used for deterministic IDs in tests.
    bm25_builder : Callable[[object, logging.Logger], tuple[str, int]] | None, optional
        Optional BM25 builder override. Accepts the same signature as production.
    faiss_runner : Callable[[object], dict[str, object]] | None, optional
        Optional FAISS runner override returning deterministic metadata.
    artifact_fs : object | None, optional
        Optional ArtifactFS implementation. Defaults to the production filesystem.

    Returns
    -------
    OrchestrationCliContext
        Frozen dataclass instance combining overrides with the production defaults.
    """
    base = OrchestrationCliContext.production()
    return OrchestrationCliContext(
        uuid_factory=uuid_factory or base.uuid_factory,
        bm25_builder=bm25_builder or base.bm25_builder,
        faiss_runner=faiss_runner or base.faiss_runner,
        artifact_fs=artifact_fs or base.artifact_fs,
    )


def orchestration_cli_obj(
    *,
    envelope_dir: Path | None = None,
    artifact_dir: Path | None = None,
    cli_context: OrchestrationCliContext | None = None,
    overrides: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build Typer context object for orchestration CLI invocations.

    Parameters
    ----------
    envelope_dir : Path | None, optional
        Optional override for the CLI envelope directory stored in context state.
    artifact_dir : Path | None, optional
        Optional override for the CLI artifact directory stored in context state.
    cli_context : OrchestrationCliContext | None, optional
        Custom orchestration CLI context (dependency injection container).
    overrides : Mapping[str, object] | None, optional
        Additional key/value pairs to merge into the context object.

    Returns
    -------
    dict[str, object]
        Mutable mapping suitable for passing as ``obj`` to Typer commands.
    """
    state: dict[str, object] = {}
    if overrides:
        state.update(overrides)
    if envelope_dir is not None:
        state["envelope_dir"] = envelope_dir
    if artifact_dir is not None:
        state["artifact_dir"] = artifact_dir
    if cli_context is not None:
        state["orchestration_cli_context"] = cli_context
    return state
