"""Thin HTTP client for interacting with the kgfoundry Search API."""

# [nav:section public-api]

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol, cast

import requests

from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kgfoundry_common.problem_details import JsonValue

__all__ = [
    "KGFoundryClient",
    "RequestsHttp",
    "SupportsHttp",
    "SupportsResponse",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor SupportsResponse]
class SupportsResponse(Protocol):
    """Protocol describing the minimal HTTP response surface used by the client.

    This protocol defines the minimal interface required for HTTP responses
    used by KGFoundryClient. Implementations should mirror the behavior of
    `requests.Response` for the provided methods.

    Notes
    -----
    Implementations are expected to mirror :class:`requests.Response` for the provided
    methods so callers can work with a small shared interface.
    """

    def raise_for_status(self) -> None:
        """Raise an HTTP error if the response indicates failure.

        Raises an exception if the HTTP status code indicates an error (4xx or 5xx). Should mirror
        the behavior of `requests.Response.raise_for_status()`.
        """

    def json(self) -> JsonValue:
        """Return the response payload as JSON.

        Parses the response body as JSON and returns the decoded value.
        Should mirror the behavior of `requests.Response.json()`.

        Returns
        -------
        JsonValue
            Decoded JSON body returned by the HTTP service. Can be a dict, list,
            str, int, float, bool, or None.
        """
        ...


# [nav:anchor SupportsHttp]
class SupportsHttp(Protocol):
    """Protocol describing the HTTP verbs required by :class:`KGFoundryClient`.

    This protocol defines the minimal HTTP interface required by KGFoundryClient.
    Implementations only need to provide `get` and `post` methods that mirror
    the behavior of the `requests` library.

    Notes
    -----
    Implementations only need to provide ``get`` and ``post`` methods that mirror the
    behaviour of :mod:`requests`.
    """

    def get(
        self,
        url: str,
        *,
        timeout: float | tuple[float | None, float | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> SupportsResponse:
        """Issue an HTTP ``GET`` request.

        Sends a GET request to the specified URL with optional timeout and headers.

        Parameters
        ----------
        url : str
            Target URL for the GET request.
        timeout : float | tuple[float | None, float | None] | None, optional
            Request timeout in seconds or (connect, read) tuple. Defaults to None
            (no timeout).
        headers : Mapping[str, str] | None, optional
            HTTP headers to include with the request. Defaults to None.

        Returns
        -------
        SupportsResponse
            Response wrapper produced by the HTTP implementation.
        """
        ...

    def post(
        self,
        url: str,
        *,
        json: JsonValue | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | tuple[float | None, float | None] | None = None,
    ) -> SupportsResponse:
        """Issue an HTTP ``POST`` request.

        Sends a POST request to the specified URL with optional JSON payload,
        headers, and timeout.

        Parameters
        ----------
        url : str
            Target URL for the POST request.
        json : JsonValue | None, optional
            JSON payload to include in the request body. Defaults to None.
        headers : Mapping[str, str] | None, optional
            HTTP headers to include with the request. Defaults to None.
        timeout : float | tuple[float | None, float | None] | None, optional
            Request timeout in seconds or (connect, read) tuple. Defaults to None
            (no timeout).

        Returns
        -------
        SupportsResponse
            Response wrapper produced by the HTTP implementation.
        """
        ...


# [nav:anchor RequestsHttp]
class RequestsHttp(SupportsHttp):
    """HTTP adapter that delegates HTTP verbs to :mod:`requests`.

    Thin wrapper around the `requests` library that implements the SupportsHttp
    protocol. This adapter exists to make the high-level client easy to test
    by swapping in alternative transports.

    Notes
    -----
    This thin wrapper exists to make the high-level client easy to test by swapping
    in alternative transports.
    """

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def get(
        self,
        url: str,
        *,
        timeout: float | tuple[float | None, float | None] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> SupportsResponse:
        """Send a ``GET`` request using :func:`requests.get`.

        Delegates to the underlying requests.Session.get() method.

        Parameters
        ----------
        url : str
            Target URL for the GET request.
        timeout : float | tuple[float | None, float | None] | None, optional
            Request timeout in seconds or (connect, read) tuple. Defaults to None
            (no timeout).
        headers : Mapping[str, str] | None, optional
            HTTP headers to include with the request. Defaults to None.

        Returns
        -------
        SupportsResponse
            Response returned by :mod:`requests`.
        """
        response = self._session.get(url, timeout=timeout, headers=headers)
        return cast("SupportsResponse", response)

    def post(
        self,
        url: str,
        *,
        json: JsonValue | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | tuple[float | None, float | None] | None = None,
    ) -> SupportsResponse:
        """Send a ``POST`` request using :func:`requests.post`.

        Delegates to the underlying requests.Session.post() method.

        Parameters
        ----------
        url : str
            Target URL for the POST request.
        json : JsonValue | None, optional
            JSON body to send with the request. Defaults to None.
        headers : Mapping[str, str] | None, optional
            HTTP headers to include with the request. Defaults to None.
        timeout : float | tuple[float | None, float | None] | None, optional
            Request timeout in seconds or (connect, read) tuple. Defaults to None
            (no timeout).

        Returns
        -------
        SupportsResponse
            Response returned by :mod:`requests`.
        """
        response = self._session.post(url, json=json, headers=headers, timeout=timeout)
        return cast("SupportsResponse", response)


_DEFAULT_HTTP: Final[SupportsHttp] = RequestsHttp()


# [nav:anchor KGFoundryClient]
class KGFoundryClient:
    """High-level client for the kgfoundry Search API.

    Provides a convenient interface for interacting with the kgfoundry Search API,
    including search, health checks, and knowledge graph concept queries. Supports
    authentication via API keys and configurable timeouts.

    Instantiates the client with connection details. Initializes the client with
    API endpoint, authentication, and timeout configuration. The base_url is
    normalized by removing trailing slashes.

    Parameters
    ----------
    base_url : str, optional
        Base URL of the Search API service. Defaults to "http://localhost:8080".
    api_key : str | None, optional
        API key for Bearer token authentication. Defaults to None (no auth).
    timeout : float, optional
        Default request timeout in seconds. Defaults to 30.0.
    http : SupportsHttp | None, optional
        HTTP adapter implementation. If None, uses RequestsHttp. Defaults to None.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_key: str | None = None,
        timeout: float = 30.0,
        http: SupportsHttp | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._http: SupportsHttp = http or _DEFAULT_HTTP

    def _headers(self) -> dict[str, str]:
        """Build default headers for authenticated requests.

        Constructs HTTP headers for requests, including Content-Type and
        Authorization (if API key is configured).

        Returns
        -------
        dict[str, str]
            Header dictionary including Content-Type and Authorization (if API key
            is configured).
        """
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def healthz(self) -> JsonValue:
        """Fetch the service health endpoint.

        Queries the /healthz endpoint to check service availability and
        component status.

        Returns
        -------
        JsonValue
            JSON payload describing service health, including component
            availability status.

        Notes
        -----
        Propagates :class:`requests.HTTPError` when the API responds with a
        non-success status code.
        """
        response = self._http.get(f"{self.base_url}/healthz", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def search(
        self,
        query: str,
        k: int = 10,
        filters: dict[str, JsonValue] | None = None,
        *,
        explain: bool = False,
    ) -> JsonValue:
        """Execute a semantic search request.

        Performs a hybrid search query combining dense (FAISS), sparse (BM25/SPLADE),
        and knowledge graph signals. Returns ranked results with optional explanation
        metadata.

        Parameters
        ----------
        query : str
            Search query text.
        k : int, optional
            Maximum number of results to return. Defaults to 10.
        filters : dict[str, JsonValue] | None, optional
            Optional facet filters for narrowing search results. Defaults to None.
        explain : bool, optional
            Whether to include explanation metadata in results. Defaults to False.

        Returns
        -------
        JsonValue
            JSON response containing the ranked search results with metadata.

        Notes
        -----
        Propagates :class:`requests.HTTPError` when the API responds with a
        non-success status code.
        """
        filters_payload: dict[str, JsonValue] = (
            filters.copy() if filters is not None else {}
        )
        payload: dict[str, JsonValue] = {
            "query": query,
            "k": k,
            "filters": filters_payload,
            "explain": explain,
        }
        response = self._http.post(
            f"{self.base_url}/search",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def concepts(self, q: str, limit: int = 50) -> JsonValue:
        """Retrieve graph concepts that match the provided query string.

        Queries the knowledge graph for concepts matching the query string.
        Returns concept IDs and labels.

        Parameters
        ----------
        q : str
            Query string to match against concept labels (case-insensitive).
        limit : int, optional
            Maximum number of concepts to return. Defaults to 50.

        Returns
        -------
        JsonValue
            JSON response containing matching concepts with concept_id and label
            fields.

        Notes
        -----
        Propagates :class:`requests.HTTPError` when the API responds with a
        non-success status code.
        """
        body: dict[str, JsonValue] = {"q": q, "limit": limit}
        response = self._http.post(
            f"{self.base_url}/graph/concepts",
            json=body,
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
