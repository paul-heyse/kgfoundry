"""HTTP client exception classes.

This module defines exception classes for HTTP client errors, including status code errors, rate
limiting, timeouts, and connection errors.
"""

from __future__ import annotations


class HttpError(Exception):
    """Base exception for all HTTP client errors."""


class HttpStatusError(HttpError):
    """Exception raised for HTTP error status codes.

    Parameters
    ----------
    status : int
        HTTP status code.
    body_excerpt : str | None, optional
        Excerpt from response body. Defaults to None.
    headers : dict[str, str] | None, optional
        Response headers. Defaults to None.

    Notes
    -----
    After initialization, this exception has instance attributes:
    - ``status``: The HTTP status code (int)
    - ``headers``: The response headers (dict[str, str], defaults to empty dict)
    """

    def __init__(
        self,
        status: int,
        body_excerpt: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize the exception. See class docstring for full details."""
        super().__init__(f"HTTP {status}: {body_excerpt or ''}")
        self.status = status
        self.headers = headers or {}


class HttpRateLimitedError(HttpStatusError):
    """Exception raised when rate limited (HTTP 429)."""


class HttpTimeoutError(HttpError):
    """Exception raised when request times out."""


class HttpConnectionError(HttpError):
    """Exception raised when connection fails."""


class HttpTlsError(HttpError):
    """Exception raised when TLS/SSL error occurs."""


class HttpTooManyRedirectsError(HttpError):
    """Exception raised when too many redirects occur."""


class HttpRequestError(HttpError):
    """Exception raised for general request errors."""


# Backward compatibility aliases
HttpRateLimited = HttpRateLimitedError
HttpTimeout = HttpTimeoutError
HttpTooManyRedirects = HttpTooManyRedirectsError
