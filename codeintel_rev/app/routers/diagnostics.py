"""Diagnostics endpoints for runtime execution ledger reports."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from codeintel_rev.observability import execution_ledger

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("/run_report/{run_id}")
def get_run_report(run_id: str) -> JSONResponse:
    """Return the execution ledger report for ``run_id`` as JSON.

    Parameters
    ----------
    run_id : str
        Unique identifier for the execution run to retrieve.

    Returns
    -------
    JSONResponse
        Response containing the run report payload.

    Raises
    ------
    HTTPException
        Raised when the requested run identifier is not present in the ledger.
    """
    try:
        payload = execution_ledger.build_run_report(run_id)
    except KeyError as exc:  # pragma: no cover - FastAPI converts to 404
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(payload)


@router.get("/run_report/{run_id}.md", response_class=PlainTextResponse)
def get_run_report_markdown(run_id: str) -> PlainTextResponse:
    """Return execution ledger report rendered as Markdown.

    Parameters
    ----------
    run_id : str
        Unique identifier for the execution run to retrieve.

    Returns
    -------
    PlainTextResponse
        Response containing the Markdown version of the run report.

    Raises
    ------
    HTTPException
        Raised when the requested run identifier is not present in the ledger.
    """
    try:
        payload = execution_ledger.build_run_report(run_id)
    except KeyError as exc:  # pragma: no cover - FastAPI converts to 404
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    markdown = execution_ledger.report_to_markdown(payload)
    return PlainTextResponse(markdown)
