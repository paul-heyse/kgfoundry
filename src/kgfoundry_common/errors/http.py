"""HTTP adapters for Problem Details exception handling.

This module provides FastAPI exception handlers and helpers for converting
KgFoundryError exceptions to RFC 9457 Problem Details responses.

Examples
--------
>>> from fastapi import FastAPI
>>> from kgfoundry_common.errors.http import register_problem_details_handler
>>> app = FastAPI()
>>> register_problem_details_handler(app)
"""

# [nav:section public-api]

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

from kgfoundry_common.errors.exceptions import KgFoundryError
from kgfoundry_common.fastapi_helpers import typed_exception_handler
from kgfoundry_common.logging import get_logger
from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

    from kgfoundry_common.problem_details import ProblemDetails


__all__ = [
    "problem_details_response",
    "register_problem_details_handler",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


logger = get_logger(__name__)


# [nav:anchor problem_details_response]
def problem_details_response(
    error: KgFoundryError,
    request: Request | None = None,
) -> JSONResponse:
    """Convert KgFoundryError to RFC 9457 Problem Details JSONResponse.

    Converts a KgFoundryError exception into a FastAPI JSONResponse
    conforming to RFC 9457 Problem Details format, including appropriate
    HTTP status code and content type headers.

    Parameters
    ----------
    error : KgFoundryError
        Exception to convert to Problem Details response.
    request : Request | None, optional
        FastAPI request object for generating instance URI. Defaults to None.

    Returns
    -------
    JSONResponse
        Problem Details JSON response with appropriate status code and
        Content-Type header.

    Examples
    --------
    >>> from kgfoundry_common.errors import DownloadError
    >>> from kgfoundry_common.errors.http import problem_details_response
    >>> error = DownloadError("Download failed")
    >>> response = problem_details_response(error)
    >>> assert response.status_code == 503
    >>> assert "type" in response.body.decode()
    """
    instance = None
    if request:
        instance = str(request.url.path)
        if request.url.query:
            instance += f"?{request.url.query}"

    details: ProblemDetails = error.to_problem_details(instance=instance)

    # Log the error at appropriate level
    logger.log(error.log_level, "Error: %s", error.message, exc_info=error.__cause__)

    return JSONResponse(
        status_code=error.http_status,
        content=details,
        headers={
            "Content-Type": "application/problem+json",
        },
    )


# [nav:anchor register_problem_details_handler]
def register_problem_details_handler(app: FastAPI) -> None:
    """Register FastAPI exception handler for KgFoundryError."""

    async def _handler(request: Request, exc: KgFoundryError) -> JSONResponse:
        return await asyncio.to_thread(problem_details_response, exc, request)

    typed_exception_handler(
        app,
        KgFoundryError,
        _handler,
        name="kgfoundry_error_handler",
    )
