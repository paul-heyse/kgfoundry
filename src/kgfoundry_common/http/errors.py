"""HTTP client exception classes.

This module defines exception classes for HTTP client errors, including status code errors, rate
limiting, timeouts, and connection errors.
"""

from __future__ import annotations


class HttpError(Exception):
    """Base exception for all HTTP client errors."""


class HttpStatusError(HttpError):
    """Exception raised for HTTP error status codes.

    Extended Summary
    ----------------
    Raised when an HTTP response has an error status code (4xx or 5xx).
    Stores the status code, response body excerpt, and headers for debugging
    and error handling. The exception message includes the status code and
    body excerpt.

    Notes
    -----
    Time O(1); memory O(1) aside from message, body_excerpt, and headers storage.
    No I/O, no global state. Thread-safe. After initialization, this exception
    has instance attributes: ``status`` (int) and ``headers`` (dict[str, str],
    defaults to empty dict).

    Examples
    --------
    >>> raise HttpStatusError(404, body_excerpt="Not Found")
    >>> # With headers
    >>> raise HttpStatusError(
    ...     503, body_excerpt="Service Unavailable", headers={"Retry-After": "60"}
    ... )
    """

    def __init__(
        self,
        status: int,
        body_excerpt: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize exception with HTTP status code and optional details.

        Parameters
        ----------
        status : int
            HTTP status code (e.g., 404, 500, 503). Must be >= 400. Stored as
            instance attribute for programmatic error handling and inspection.
        body_excerpt : str | None, optional
            Excerpt from response body for error message. Included in the exception
            message string. Defaults to None. When provided, helps diagnose the
            specific error condition from the server response.
        headers : dict[str, str] | None, optional
            Response headers dictionary. If None, defaults to empty dict. Stored as
            instance attribute for inspection. Useful for extracting rate limit
            information, retry-after headers, or other metadata. Defaults to None.

        Notes
        -----
        Constructs exception message as "HTTP {status}: {body_excerpt or ''}".
        Headers are normalized to empty dict if None is provided. No validation
        is performed on status code range; callers should ensure status >= 400.
        """
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
