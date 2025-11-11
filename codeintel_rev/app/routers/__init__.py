"""FastAPI router modules for CodeIntel administrative endpoints."""

from __future__ import annotations

from importlib import import_module

index_admin = import_module("codeintel_rev.app.routers.index_admin")

__all__ = ["index_admin"]
