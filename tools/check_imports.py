#!/usr/bin/env python3
"""Run tooling architecture checks built on pytestarch."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, cast

if __package__ in {
    None,
    "",
}:  # pragma: no cover - invoked via script entry instead of module
    message = (
        "Run this command via `python -m tools.check_imports` or install kgfoundry[tools] "
        "so the tooling package is importable."
    )
    raise RuntimeError(message)

from tools import architecture
from tools._shared.cli import CliEnvelopeBuilder, render_cli_envelope
from tools._shared.logging import get_logger

if TYPE_CHECKING:
    from tools._shared.cli import CliEnvelope, CliStatus

LOGGER = get_logger(__name__)


def _build_envelope(result: architecture.ArchitectureResult) -> CliEnvelope:
    status: CliStatus = "success" if result.is_success else "violation"
    builder = CliEnvelopeBuilder.create(command="check_imports", status=status)
    if not result.is_success:
        for violation in result.violations:
            builder = builder.add_error(status="violation", message=violation)
    return builder.finish()


def main() -> int:
    """Execute the tooling architecture checks and emit a CLI envelope.

    Returns
    -------
    int
        Exit code: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write a JSON envelope to stdout with detailed violations.",
    )
    args: argparse.Namespace = parser.parse_args()

    result = architecture.enforce_tooling_layers()
    envelope = _build_envelope(result)

    output_json = cast("bool", getattr(args, "json", False))

    if output_json:
        sys.stdout.write(render_cli_envelope(envelope) + "\n")
    elif result.is_success:
        LOGGER.info("Tooling import layering verified (domain → adapters → io/cli).")
    else:
        for violation in result.violations:
            LOGGER.error(violation)

    return 0 if result.is_success else 1


if __name__ == "__main__":
    sys.exit(main())
