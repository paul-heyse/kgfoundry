"""Diagnostics endpoints (disabled - observability removed)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("/run_report/{run_id}")
def get_run_report(run_id: str) -> JSONResponse:  # noqa: ARG001
    """Diagnostics endpoint disabled - observability removed.

    Parameters
    ----------
    run_id : str
        Run identifier (unused, kept for API compatibility).

    Returns
    -------
    JSONResponse
        Never returns normally; always raises HTTPException.

    Raises
    ------
    HTTPException
        Always raised with status 501 to indicate the endpoint is disabled.
    """
    raise HTTPException(
        status_code=501, detail="Diagnostics endpoints disabled - observability removed"
    )


@router.get("/run_report/{run_id}.md", response_class=PlainTextResponse)
def get_run_report_markdown(run_id: str) -> PlainTextResponse:  # noqa: ARG001
    """Diagnostics endpoint disabled - observability removed.

    Parameters
    ----------
    run_id : str
        Run identifier (unused, kept for API compatibility).

    Returns
    -------
    PlainTextResponse
        Never returns normally; always raises HTTPException.

    Raises
    ------
    HTTPException
        Always raised with status 501 to indicate the endpoint is disabled.
    """
    raise HTTPException(
        status_code=501, detail="Diagnostics endpoints disabled - observability removed"
    )
