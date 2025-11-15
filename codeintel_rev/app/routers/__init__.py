"""FastAPI router modules for CodeIntel administrative endpoints."""

from __future__ import annotations

from importlib import import_module

index_admin = import_module("codeintel_rev.app.routers.index_admin")
diagnostics = import_module("codeintel_rev.app.routers.diagnostics")

__all__ = ["diagnostics", "index_admin"]
