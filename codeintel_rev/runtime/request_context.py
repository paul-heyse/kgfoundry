"""Shared request-scoped context variables for runtime components.

These context variables are defined in the runtime package so that both
middleware layers and lower-level runtime primitives (like :mod:`runtime.cells`)
can exchange session metadata without introducing circular imports between the
``codeintel_rev.app`` and ``codeintel_rev.runtime`` packages.
"""

from __future__ import annotations

import contextvars
from typing import Final

__all__ = ["capability_stamp_var", "session_id_var"]

# Session identifiers are propagated from SessionScopeMiddleware so RuntimeCell
# observers can record which request triggered a heavy initialization.
session_id_var: Final[contextvars.ContextVar[str | None]] = contextvars.ContextVar(
    "codeintel_session_id",
    default=None,
)

# Capability snapshot hash captured per request (see /capz). Runtime telemetry
# attaches this stamp so downstream diagnostics can explain why fallbacks ran.
capability_stamp_var: Final[contextvars.ContextVar[str | None]] = contextvars.ContextVar(
    "codeintel_capability_stamp",
    default=None,
)
