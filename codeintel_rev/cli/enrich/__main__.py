"""CLI entrypoint for enrichment commands."""

from __future__ import annotations

# Import subcommands for registration side-effects.
from codeintel_rev.cli.enrich import analytics as _analytics  # noqa: F401
from codeintel_rev.cli.enrich import app
from codeintel_rev.cli.enrich import audit as _audit  # noqa: F401
from codeintel_rev.cli.enrich import callgraph as _callgraph  # noqa: F401
from codeintel_rev.cli.enrich import cfg as _cfg  # noqa: F401
from codeintel_rev.cli.enrich import exports as _exports  # noqa: F401
from codeintel_rev.cli.enrich import goids as _goids  # noqa: F401
from codeintel_rev.cli.enrich import overlays as _overlays  # noqa: F401
from codeintel_rev.cli.enrich import scan as _scan  # noqa: F401
from codeintel_rev.cli.enrich import to_duckdb as _to_duckdb  # noqa: F401


def main() -> None:  # pragma: no cover - entrypoint
    """Invoke the enrichment Typer app."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
