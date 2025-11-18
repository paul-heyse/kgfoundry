# SPDX-License-Identifier: MIT
"""Typer app for enrichment commands."""

from __future__ import annotations

import typer

from codeintel_rev.cli.enrich import common

app = typer.Typer(add_completion=True, help=common.GLOBAL_OPTIONS_HELP)
common.attach_argv_normalizer(app, common.normalize_global_cli_args)
app.callback()(common.shared_options)


__all__ = ["app"]
