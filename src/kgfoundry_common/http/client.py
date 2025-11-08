"""HTTP client with retry strategy support.

This module provides an HttpClient class that supports configurable retry strategies and idempotency
key requirements.
"""

from __future__ import annotations

from dataclasses import dataclass

from kgfoundry_common.http.tenacity_retry import TenacityRetryStrategy
from kgfoundry_common.http.types import RetryStrategy


@dataclass(frozen=True)
class HttpSettings:
    """HTTP client configuration settings.

    Attributes
    ----------
    service : str
        Service name for logging and metrics.
    base_url : str
        Base URL for all requests.
    read_timeout_s : float
        Read timeout in seconds. Defaults to 30.0.
    connect_timeout_s : float
        Connection timeout in seconds. Defaults to 10.0.
    """

    service: str
    base_url: str
    read_timeout_s: float = 30.0
    connect_timeout_s: float = 10.0


class HttpClient:
    """HTTP client with configurable retry strategies.

    This client supports per-method retry policies and enforces idempotency
    key requirements for non-idempotent methods when configured.

    Parameters
    ----------
    settings : HttpSettings
        Client configuration settings.
    retry_strategy : RetryStrategy | None, optional
        Retry strategy to use. If None, requests will be single-attempt.
        Defaults to None.
    """

    def __init__(self, settings: HttpSettings, retry_strategy: RetryStrategy | None = None) -> None:
        self.s = settings
        self.retry_strategy = retry_strategy  # may be None for single-attempt
        # TODO(@http-client): # noqa: TD003, FIX002 Initialize underlying HTTP client (httpx, requests, etc.)

    def _policy_strategy_for(self, method: str) -> RetryStrategy | None:
        """Get retry strategy for a specific HTTP method.

        Parameters
        ----------
        method : str
            HTTP method name.

        Returns
        -------
        RetryStrategy | None
            Retry strategy for the method, or None if no retry should be performed.
        """
        if self.retry_strategy is None:
            return None
        # If strategy supports per-method specialization:
        if hasattr(self.retry_strategy, "for_method"):
            return self.retry_strategy.for_method(method)
        return self.retry_strategy

    def request(  # noqa: PLR0913
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
        data: bytes | None = None,
        timeout_s: float | None = None,
    ) -> object:
        """Make an HTTP request with retry logic.

        Parameters
        ----------
        method : str
            HTTP method (GET, POST, etc.).
        url : str
            Request URL (will be combined with base_url if relative).
        params : dict[str, str] | None, optional
            Query parameters. Defaults to None.
        headers : dict[str, str] | None, optional
            Request headers. Defaults to None.
        json_body : dict[str, object] | None, optional
            JSON body data. Defaults to None.
        data : bytes | None, optional
            Raw body data. Defaults to None.
        timeout_s : float | None, optional
            Request timeout in seconds. Defaults to None (uses settings default).

        Returns
        -------
        object
            HTTP response object.

        Raises
        ------
        NotImplementedError
            If HTTP request implementation is not yet complete.
        """  # noqa: DOC502
        method = method.upper()
        url = self._build_url(url)
        headers = self._merge_headers(headers)
        # Non-idempotent safeguard for policies requiring Idempotency-Key
        if (
            method not in {"GET", "HEAD", "OPTIONS"}
            and isinstance(self.retry_strategy, TenacityRetryStrategy)
            and self.retry_strategy.policy.require_idempotency_key
            and "Idempotency-Key" not in (headers or {})
        ):
            # Force single attempt for safety:
            strategy = None
        else:
            strategy = self._policy_strategy_for(method)

        def _attempt() -> object:
            """Execute a single HTTP request attempt.

            Returns
            -------
            object
                HTTP response object.

            Raises
            ------
            NotImplementedError
                HTTP request implementation is not yet complete.

            Notes
            -----
            This function currently only raises NotImplementedError as a placeholder.
            The Returns section is included because the function signature indicates
            it will return an HTTP response object once implemented.
            """  # noqa: DOC202
            # TODO(@http-client): # noqa: TD003, FIX002 Implement actual HTTP request
            # When implemented, use HttpRateLimitedError and HttpStatusError from
            # kgfoundry_common.http.errors for error handling.
            _ = params, json_body, data, timeout_s  # Placeholder for future use
            msg = "HTTP request not yet implemented"
            raise NotImplementedError(msg)

        if strategy is None:
            return _attempt()
        return strategy.run(_attempt)

    def _build_url(self, url: str) -> str:
        """Build full URL from base URL and relative path.

        Parameters
        ----------
        url : str
            URL or path relative to base_url.

        Returns
        -------
        str
            Full URL.
        """
        # TODO(@http-client): # noqa: TD003, FIX002 Implement URL building logic
        if url.startswith(("http://", "https://")):
            return url
        return f"{self.s.base_url.rstrip('/')}/{url.lstrip('/')}"

    @staticmethod
    def _merge_headers(headers: dict[str, str] | None) -> dict[str, str]:
        """Merge request headers with default headers.

        Parameters
        ----------
        headers : dict[str, str] | None
            Request-specific headers.

        Returns
        -------
        dict[str, str]
            Merged headers dictionary.
        """
        # TODO(@http-client): # noqa: TD003, FIX002 Implement header merging logic
        return headers or {}
