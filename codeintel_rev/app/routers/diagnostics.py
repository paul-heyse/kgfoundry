"""Diagnostics endpoints (disabled - observability removed)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


_DIAGNOSTICS_DISABLED_DETAIL = "Diagnostics endpoints disabled - observability removed"


@router.get("/run_report/{run_id}.md", response_class=PlainTextResponse)
def get_run_report_markdown(run_id: str) -> PlainTextResponse:
    """Diagnostics endpoint disabled - observability removed.

    Parameters
    ----------
    run_id : str
        Run identifier (unused, kept for API compatibility).

    Returns
    -------
    PlainTextResponse
        Plain text message describing that the endpoint is unavailable.

    Notes
    -----
    This endpoint is disabled and returns HTTP 501 to signal that telemetry was removed.
    """
    del run_id
    text = f"{_DIAGNOSTICS_DISABLED_DETAIL}\n"
    return PlainTextResponse(text, status_code=501)


@router.get("/run_report/{run_id}")
def get_run_report(run_id: str) -> JSONResponse:
    """Diagnostics endpoint disabled - observability removed.

    Parameters
    ----------
    run_id : str
        Run identifier (unused, kept for API compatibility).

    Returns
    -------
    JSONResponse
        JSON payload describing that the endpoint is unavailable.

    Notes
    -----
    This endpoint is disabled and returns HTTP 501 to signal that telemetry was removed.
    """
    del run_id
    payload = {"available": False, "detail": _DIAGNOSTICS_DISABLED_DETAIL}
    return JSONResponse(payload, status_code=501)
