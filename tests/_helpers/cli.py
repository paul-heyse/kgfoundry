"""Utilities for invoking Typer/CLI entry points in tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from typer.main import Typer
from typer.testing import CliRunner, Result

_RUNNER = CliRunner(mix_stderr=False)


def invoke(
    app: Typer,
    args: Iterable[str],
    *,
    env: Mapping[str, str] | None = None,
    catch_exceptions: bool = False,
) -> Result:
    """Invoke ``app`` with ``args`` and return the Typer result."""
    result = _RUNNER.invoke(app, list(args), env=env, catch_exceptions=catch_exceptions)
    return result
