# SPDX-License-Identifier: MIT
"""CLI entrypoint for enrichment commands."""

from __future__ import annotations

from codeintel_rev.cli.enrich import app


def main() -> None:  # pragma: no cover - entrypoint
    """Invoke the enrichment Typer app."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
