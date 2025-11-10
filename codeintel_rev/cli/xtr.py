"""Backward-compatible entrypoint for the XTR Typer CLI."""

from __future__ import annotations

from codeintel_rev.mcp_server.retrieval.xtr_cli import app, main

__all__ = ["app", "main"]
