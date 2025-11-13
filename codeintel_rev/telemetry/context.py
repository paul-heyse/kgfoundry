"""Context variable helpers for telemetry metadata."""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from codeintel_rev.runtime.request_context import (
    capability_stamp_var as _capability_stamp_var,
)
from codeintel_rev.runtime.request_context import (
    session_id_var as _session_id_var,
)
from kgfoundry_common.logging import set_correlation_id

session_id_var = _session_id_var
capability_stamp_var = _capability_stamp_var
run_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "codeintel_run_id",
    default=None,
)
request_tool_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "codeintel_request_tool",
    default=None,
)
stage_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "codeintel_request_stage",
    default=None,
)

__all__ = [
    "attach_context_attrs",
    "capability_stamp_var",
    "current_run_id",
    "current_session",
    "current_stage",
    "request_tool_var",
    "run_id_var",
    "session_id_var",
    "set_request_stage",
    "telemetry_context",
    "telemetry_metadata",
]


def current_session() -> str | None:
    """Return the session identifier stored in context.

    Returns
    -------
    str | None
        Session ID when bound, otherwise ``None``.
    """
    return session_id_var.get()


def current_run_id() -> str | None:
    """Return the active run identifier (alias of the current trace ID).

    Returns
    -------
    str | None
        Run identifier when telemetry has been initialised, otherwise ``None``.
    """
    return run_id_var.get()


def _set_run_id(run_id: str | None) -> contextvars.Token[str | None]:
    token = run_id_var.set(run_id)
    set_correlation_id(run_id)
    return token


def set_request_stage(stage: str | None) -> contextvars.Token[str | None]:
    """Bind the current pipeline stage to the context.

    Parameters
    ----------
    stage : str | None
        Stage label to store (``None`` clears the stage).

    Returns
    -------
    contextvars.Token[str | None]
        Token used to restore the previous stage.
    """
    return stage_var.set(stage)


def current_stage() -> str | None:
    """Return the stage currently executing within the request.

    Returns
    -------
    str | None
        Stage label or ``None`` when unset.
    """
    return stage_var.get()


@contextmanager
def telemetry_context(
    *,
    session_id: str | None,
    run_id: str | None,
    capability_stamp: str | None = None,
    tool_name: str | None = None,
) -> Iterator[None]:
    """Bind telemetry identifiers to the current context."""
    token_stack: list[contextvars.Token[object]] = []
    token_stack.append(session_id_var.set(session_id))
    token_stack.append(capability_stamp_var.set(capability_stamp))
    token_stack.append(_set_run_id(run_id))
    token_stack.append(request_tool_var.set(tool_name))
    try:
        yield
    finally:
        while token_stack:
            token = token_stack.pop()
            token.var.reset(token)
        set_correlation_id(None)


def attach_context_attrs(base: Mapping[str, Any] | None = None) -> dict[str, object]:
    """Return attributes merged with current telemetry identifiers.

    Parameters
    ----------
    base : Mapping[str, Any] | None
        Optional attributes to copy before telemetry keys are injected.

    Returns
    -------
    dict[str, object]
        Attribute dictionary containing telemetry metadata.
    """
    merged: dict[str, object] = dict(base or {})
    session_id = current_session()
    run_id = current_run_id()
    tool = request_tool_var.get()
    stage = current_stage()
    if session_id is not None:
        merged.setdefault("session_id", session_id)
    if run_id is not None:
        merged.setdefault("run_id", run_id)
    if tool:
        merged.setdefault("request_tool", tool)
    if stage:
        merged.setdefault("request_stage", stage)
    capability_stamp = capability_stamp_var.get()
    if capability_stamp:
        merged.setdefault("capability_stamp", capability_stamp)
    return merged


def telemetry_metadata() -> dict[str, str] | None:
    """Return telemetry metadata (session/run IDs) for response envelopes.

    Returns
    -------
    dict[str, str] | None
        ``{"session_id": "...", "run_id": "..."}`` when telemetry is active, else ``None``.
    """
    session_id = current_session()
    run_id = current_run_id()
    if session_id is None and run_id is None:
        return None
    payload: dict[str, str] = {}
    if run_id is not None:
        payload["run_id"] = run_id
    if session_id is not None:
        payload["session_id"] = session_id
    return payload
