"""Search service endpoints and helper utilities.

This module provides FastAPI endpoints for hybrid search using dense (FAISS),
sparse (BM25/SPLADE), and knowledge graph boosting. All endpoints return
RFC 9457 Problem Details for error responses.

Error Responses
---------------
When search operations fail, the API returns Problem Details JSON responses.
See `schema/examples/problem_details/search-missing-index.json` for an example.

Examples
--------
>>> from search_api.schemas import SearchRequest
>>> from search_api.app import search
>>> req = SearchRequest(query="test query", k=5)
>>> response = search(req, None)
>>> len(response.results) <= 5
True

See Also
--------
- `schema/examples/problem_details/search-missing-index.json` - Example Problem Details response
- `schema/models/search_request.v1.json` - SearchRequest JSON Schema
- `schema/models/search_result.v1.json` - SearchResult JSON Schema
"""

# [nav:section public-api]

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final, cast

from fastapi import FastAPI, Header, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from kgfoundry.embeddings_sparse.bm25 import get_bm25
from kgfoundry.embeddings_sparse.splade import get_splade
from kgfoundry.kg_builder.mock_kg import MockKG
from kgfoundry_common.errors import (
    DeserializationError,
    SerializationError,
    SettingsError,
    VectorSearchError,
)
from kgfoundry_common.errors.http import register_problem_details_handler
from kgfoundry_common.jsonschema_utils import (
    ValidationError as JsonSchemaValidationError,
)
from kgfoundry_common.jsonschema_utils import (
    validate as jsonschema_validate,
)
from kgfoundry_common.logging import get_logger, set_correlation_id, with_fields
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.observability import MetricsProvider, observe_duration
from kgfoundry_common.schema_helpers import load_schema
from kgfoundry_common.settings import RuntimeSettings
from search_api.fastapi_helpers import (
    DEFAULT_TIMEOUT_SECONDS,
    typed_dependency,
    typed_middleware,
)
from search_api.fusion import rrf_fuse
from search_api.schemas import SearchResponse, SearchResult
from search_api.service import apply_kg_boosts

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from starlette.requests import Request as StarletteRequest
    from starlette.responses import Response
    from starlette.types import ASGIApp

    from kgfoundry.embeddings_sparse.bm25 import LuceneBM25, PurePythonBM25
    from kgfoundry_common.jsonschema_utils import (
        ValidationErrorProtocol,
    )
    from kgfoundry_common.problem_details import JsonValue
    from search_api.schemas import SearchRequest

__all__ = [
    "CorrelationIDMiddleware",
    "ResponseValidationMiddleware",
    "app",
    "auth",
    "graph_concepts",
    "healthz",
    "search",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


logger = get_logger(__name__)
metrics = MetricsProvider.default()

MIDDLEWARE_TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS
DEPENDENCY_TIMEOUT_SECONDS = 5.0

AuthorizationHeader = Annotated[str | None, Header(default=None)]

API_KEYS: set[str] = (
    set()
)  # NOTE: load from env SEARCH_API_KEYS when secrets wiring is ready

# [nav:anchor app]
app = FastAPI(title="kgfoundry Search API", version="0.2.0")

# Register Problem Details exception handler
register_problem_details_handler(app)


# Correlation ID middleware
# [nav:anchor CorrelationIDMiddleware]
class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Extract and propagate correlation IDs using the X-Correlation-ID header.

    The middleware reads the ``X-Correlation-ID`` header (using
    :attr:`HEADER_NAME`) or generates a new UUID when absent. The value is stored
    in the request context and appended to the response headers. Base middleware
    attributes such as ``app`` and ``dispatch`` are inherited from
    :class:`BaseHTTPMiddleware` and therefore not re-documented here.
    """

    HEADER_NAME: Final[str] = "X-Correlation-ID"

    async def dispatch(
        self,
        request: StarletteRequest,
        call_next: Callable[[StarletteRequest], Awaitable[Response]],
    ) -> Response:
        """Extract correlation ID from header or generate new one.

        Checks for X-Correlation-ID header in the request. If present, uses it;
        otherwise generates a new UUID. Sets the correlation ID in contextvars
        and includes it in the response headers.

        Parameters
        ----------
        request : StarletteRequest
            HTTP request object containing headers.
        call_next : Callable[[StarletteRequest], Awaitable[Response]]
            Next middleware or route handler in the chain.

        Returns
        -------
        Response
            HTTP response with X-Correlation-ID header set.
        """
        header_name = self.HEADER_NAME
        correlation_id = request.headers.get(header_name)
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
        set_correlation_id(correlation_id)
        response = await call_next(request)
        response.headers[header_name] = correlation_id
        return response


# Response validation middleware
# [nav:anchor ResponseValidationMiddleware]
class ResponseValidationMiddleware(BaseHTTPMiddleware):
    """Middleware to validate JSON responses against schema (dev/staging only).

    Validates responses against search_response.json schema when enabled.
    Logs validation failures and returns Problem Details (RFC 9457) on schema
    mismatch. Only validates JSON responses from the /search endpoint.

    Initializes response validation middleware. Sets up the middleware with optional
    schema validation. Loads the JSON Schema 2020-12 from the provided path or
    default location.

    Parameters
    ----------
    app : FastAPI
        FastAPI application instance to wrap.
    enabled : bool, optional
        Whether to enable response validation. Defaults to False.
    schema_path : Path | None, optional
        Path to search_response.json schema file. If None, searches for
        schema/search/search_response.json relative to repo root. Defaults to None.
    """

    def __init__(
        self,
        app: FastAPI,
        *,
        enabled: bool = False,
        schema_path: Path | None = None,
    ) -> None:
        super().__init__(cast("ASGIApp", app))
        self.enabled = enabled
        if schema_path is None:
            # Default to schema/search/search_response.json relative to repo root
            repo_root = Path(__file__).parent.parent.parent
            schema_path = repo_root / "schema" / "search" / "search_response.json"
        self.schema_path = schema_path
        self.schema: dict[str, JsonValue] | None = None
        if self.enabled and self.schema_path.exists():
            try:
                self.schema = load_schema(self.schema_path)
                logger.info(
                    "Response validation enabled",
                    extra={"schema_path": str(self.schema_path)},
                )
            except (FileNotFoundError, DeserializationError) as exc:
                logger.warning(
                    "Failed to load response schema, validation disabled",
                    extra={"schema_path": str(self.schema_path), "error": str(exc)},
                    exc_info=True,
                )
                self.enabled = False

    async def dispatch(
        self,
        request: StarletteRequest,
        call_next: Callable[[StarletteRequest], Awaitable[Response]],
    ) -> Response:
        """Validate response against schema if enabled.

        Validates JSON responses from the /search endpoint against the loaded
        schema. Logs validation failures and returns Problem Details (RFC 9457)
        if validation fails.

        Parameters
        ----------
        request : StarletteRequest
            HTTP request object.
        call_next : Callable[[StarletteRequest], Awaitable[Response]]
            Next middleware or route handler in the chain.

        Returns
        -------
        Response
            Original response if validation passes or is disabled, or Problem
            Details JSON response if validation fails.
        """
        if not self.enabled or self.schema is None:
            return await call_next(request)

        response = await call_next(request)

        # Only validate JSON responses
        if response.media_type != "application/json":
            return response

        # Only validate /search endpoint responses
        if request.url.path != "/search":
            return response

        # Extract response body from JSONResponse
        try:
            # JSONResponse has a 'body' property that contains the rendered body
            body_buffer = response.body
            if isinstance(body_buffer, memoryview):
                body_bytes = body_buffer.tobytes()
            else:
                body_bytes = bytes(body_buffer)
            response_body: JsonValue = json.loads(body_bytes.decode("utf-8"))
        except (json.JSONDecodeError, AttributeError) as exc:
            with with_fields(logger, operation="response_validation") as log_adapter:
                log_adapter.warning(
                    "Failed to parse response body for validation",
                    extra={"error": str(exc)},
                    exc_info=True,
                )
            # Return original response if parsing fails
            return response

        # Validate against schema
        try:
            jsonschema_validate(instance=response_body, schema=self.schema)
        except JsonSchemaValidationError as exc:
            with with_fields(logger, operation="response_validation") as log_adapter:
                error_details = cast("ValidationErrorProtocol", exc)
                log_adapter.exception(
                    "Response validation failed",
                    extra={
                        "status": "error",
                        "validation_error": error_details.message,
                        "path": "/".join(str(part) for part in error_details.path),
                    },
                )
            # Return Problem Details for validation failure
            error_msg = f"Response validation failed: {error_details.message}"
            problem = SerializationError(
                error_msg,
                cause=exc,
                context={
                    "schema_path": str(self.schema_path),
                    "validation_path": "/".join(
                        str(part) for part in error_details.path
                    ),
                },
            )
            problem_response = JSONResponse(
                content=problem.to_problem_details(),
                status_code=500,
                headers=response.headers,
            )
            return cast("Response", problem_response)

        # Return original response if validation passes
        return response


typed_middleware(
    app,
    CorrelationIDMiddleware,
    name="correlation_id_middleware",
    timeout=MIDDLEWARE_TIMEOUT_SECONDS,
)

# --- bootstrap typed configuration ---
try:
    settings = RuntimeSettings()
except SettingsError:
    logger.exception("Failed to load settings, using defaults")
    from kgfoundry_common.settings import (
        FaissConfig,
        ObservabilityConfig,
        SearchConfig,
        SparseEmbeddingConfig,
    )

    settings = RuntimeSettings(
        search=SearchConfig(),
        sparse_embedding=SparseEmbeddingConfig(),
        faiss=FaissConfig(),
        observability=ObservabilityConfig(),
    )

# Initialize response validation middleware if enabled
if settings.search.validate_responses:
    typed_middleware(
        app,
        ResponseValidationMiddleware,
        name="response_validation_middleware",
        timeout=MIDDLEWARE_TIMEOUT_SECONDS,
        enabled=True,
    )

# --- bootstrap search backends ---
kg = MockKG()
bm25: PurePythonBM25 | LuceneBM25 | None = None
splade = None

try:
    bm25 = get_bm25(
        backend=settings.search.sparse_backend,
        index_dir=settings.sparse_embedding.bm25_index_dir,
        k1=settings.sparse_embedding.bm25_k1,
        b=settings.sparse_embedding.bm25_b,
    )
except (FileNotFoundError, DeserializationError, RuntimeError) as exc:
    logger.warning("BM25 index not available: %s", exc, exc_info=True)

try:
    splade = get_splade(
        backend=settings.search.sparse_backend,
        index_dir=settings.sparse_embedding.splade_index_dir,
        query_encoder=settings.sparse_embedding.splade_query_encoder,
    )
except (FileNotFoundError, DeserializationError, RuntimeError) as exc:
    logger.warning("SPLADE index not available: %s", exc, exc_info=True)


# [nav:anchor auth]
def _validate_authorization_header(authorization: str | None) -> None:
    """Validate bearer token authentication.

    Parameters
    ----------
    authorization : str | None
        Authorization header value.

    Raises
    ------
    HTTPException
        If authorization header is missing, invalid, or API key is invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")
    token = authorization.split(" ", 1)[1]
    if token not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")


async def auth(authorization: AuthorizationHeader) -> None:
    """Validate bearer token authentication."""
    await asyncio.to_thread(_validate_authorization_header, authorization)


# Typed dependency markers -------------------------------------------------

AuthDependency = Annotated[
    None,
    typed_dependency(auth, name="auth", timeout=DEPENDENCY_TIMEOUT_SECONDS),
]


# [nav:anchor healthz]
def healthz() -> dict[str, str | dict[str, str]]:
    """Health check endpoint.

    Returns the health status of the search API and its components (BM25,
    SPLADE, embeddings, knowledge graph). Used for monitoring and readiness
    checks.

    Returns
    -------
    dict[str, str | dict[str, str]]
        Dictionary with "status" key set to "ok" and "components" key containing
        a dictionary mapping component names to their availability status
        ("available", "unavailable", or "mocked").
    """
    return {
        "status": "ok",
        "components": {
            "bm25": "available" if bm25 else "unavailable",
            "splade": "available" if splade else "unavailable",
            "vllm_embeddings": "mocked",
            "neo4j": "mocked",
        },
    }


# [nav:anchor search]
def search(req: SearchRequest, _: AuthDependency = None) -> SearchResponse:
    """Execute hybrid search query.

    Combines dense (FAISS), sparse (BM25/SPLADE), and knowledge graph signals
    using Reciprocal Rank Fusion and KG boosts. Returns ranked results with
    structured logging and metrics.

    Parameters
    ----------
    req : SearchRequest
        Search request containing query text, k (number of results), and
        optional facets for filtering.

    Returns
    -------
    SearchResponse
        Search results with metadata and performance metrics. Results are
        ranked by combined relevance scores from all search channels.

    Raises
    ------
    VectorSearchError
        Returns Problem Details JSON (RFC 9457) on errors such as missing
        indexes, invalid queries, or backend failures.
    RuntimeError
        Raised if the search operation completes without producing a response.

    Examples
    --------
    >>> from search_api.schemas import SearchRequest
    >>> from search_api.app import search
    >>> req = SearchRequest(query="vector store", k=5)
    >>> response = search(req, None)
    >>> len(response.results) <= 5
    True
    """
    # Correlation ID is set by middleware, use with_fields for structured logging
    response: SearchResponse | None = None
    with (
        with_fields(logger, operation="search", query=req.query, k=req.k),
        observe_duration(metrics, "search", component="search_api") as obs,
    ):
        log_adapter = logger  # Use logger directly since with_fields provides context
        log_adapter.info("Search request received", extra={"status": "started"})

        try:
            # Retrieve from each channel
            # We don't have a query embedder here; fallback to empty or demo vector
            dense_hits: list[tuple[str, float]] = []
            # sparse via BM25 (preferred) and SPLADE
            bm25_hits: list[tuple[str, float]] = []
            if bm25:
                try:
                    bm25_hits = bm25.search(
                        req.query, k=settings.search.sparse_candidates
                    )
                except (RuntimeError, ValueError, AttributeError, OSError) as exc:
                    log_adapter.warning(
                        "BM25 search failed, falling back to empty results: %s",
                        exc,
                        extra={"status": "warning"},
                        exc_info=True,
                    )
                    bm25_hits = []
            try:
                splade_hits = (
                    splade.search(req.query, k=settings.search.sparse_candidates)
                    if splade
                    else []
                )
            except (RuntimeError, ValueError, AttributeError, OSError) as exc:
                log_adapter.warning(
                    "SPLADE search failed, falling back to empty results: %s",
                    exc,
                    extra={"status": "warning"},
                    exc_info=True,
                )
                splade_hits = []

            # RRF fusion
            fused = rrf_fuse(
                [dense_hits, bm25_hits, splade_hits], k_rrf=settings.search.rrf_k
            )
            # KG boosts
            boosted = apply_kg_boosts(
                fused,
                req.query,
                direct=settings.search.kg_boosts_direct,
                one_hop=settings.search.kg_boosts_one_hop,
            )

            # Rank and craft results
            def sort_key(item: tuple[str, float]) -> float:
                """Sort key function for ranking results.

                Parameters
                ----------
                item : tuple[str, float]
                    Result tuple containing (chunk_id, score).

                Returns
                -------
                float
                    Score value for sorting.
                """
                return item[1]

            top = sorted(boosted.items(), key=sort_key, reverse=True)[: req.k]
            results: list[SearchResult] = []
            for chunk_id, score in top:
                # In real system we'd hydrate title/section via DuckDB; here we echo ids
                results.append(
                    SearchResult(
                        doc_id=f"doc-of-{chunk_id}",
                        chunk_id=chunk_id,
                        title=f"Title for {chunk_id}",
                        section="Methods",
                        score=float(score),
                        signals={
                            "rrf": float(fused.get(chunk_id, 0.0)),
                            "kg_boost": float(
                                boosted[chunk_id] - fused.get(chunk_id, 0.0)
                            ),
                        },
                        spans={"start_char": 0, "end_char": 50},
                        concepts=[
                            {
                                "concept_id": c,
                                "label": c,
                                "match": ("direct" if c in req.query else "nearby"),
                            }
                            for c in kg.linked_concepts(chunk_id)
                        ],
                    )
                )

            log_adapter.info(
                "Search completed",
                extra={"status": "success", "result_count": len(results)},
            )
            obs.success()

            response = SearchResponse(results=results)
        except (RuntimeError, ValueError, AttributeError, OSError) as exc:
            obs.error()
            # Convert to VectorSearchError for proper Problem Details handling
            error_msg = f"Search operation failed: {exc}"
            # context accepts Mapping[str, object], dict[str, str | int] is compatible
            context_dict: Mapping[str, object] = {"query": req.query, "k": req.k}
            raise VectorSearchError(error_msg, cause=exc, context=context_dict) from exc
    if response is None:
        message = "Search operation completed without producing a response"
        raise RuntimeError(message)
    return response


# [nav:anchor graph_concepts]
def graph_concepts(
    body: Mapping[str, JsonValue],
    _: AuthDependency = None,
) -> dict[str, list[dict[str, str]]]:
    """Retrieve knowledge graph concepts matching query.

    Returns concepts from the knowledge graph that match the query string.
    Searches concept labels for substring matches and returns a limited number
    of results. Includes structured logging and error handling.

    Parameters
    ----------
    body : Mapping[str, JsonValue]
        Request body containing:
        - `q` (str): Query string to match against concept labels (case-insensitive).
        - `limit` (int, optional): Maximum number of concepts to return.
          Defaults to 50.

    Returns
    -------
    dict[str, list[dict[str, str]]]
        Dictionary with "concepts" key containing list of concept dictionaries.
        Each concept has "concept_id" and "label" keys.

    Raises
    ------
    VectorSearchError
        Returns Problem Details JSON (RFC 9457) on errors such as invalid
        request body or backend failures.

    Examples
    --------
    >>> from search_api.app import graph_concepts
    >>> result = graph_concepts({"q": "test", "limit": 10}, None)
    >>> "concepts" in result
    True
    """
    with with_fields(logger, operation="graph_concepts") as log_adapter:
        q: str = ""
        try:
            q = str((body or {}).get("q", "")).lower()
            limit_raw = body.get("limit", 50) if body else 50
            try:
                limit = int(cast("int | float | str", limit_raw))
                if limit < 0:
                    limit = 50
            except (ValueError, TypeError):
                limit = 50

            # toy: return nodes that contain the query substring
            concepts: list[dict[str, str]] = [
                {"concept_id": c, "label": c}
                for c in sorted({c for cs in kg.chunk2concepts.values() for c in cs})
                if q in c.lower()
            ][:limit]

            log_adapter.info(
                "Graph concepts retrieved",
                extra={"status": "success", "count": len(concepts)},
            )
        except (RuntimeError, ValueError, AttributeError, OSError) as exc:
            error_msg = f"Graph concepts operation failed: {exc}"
            # context accepts Mapping[str, object], dict[str, str] is compatible
            context_dict: Mapping[str, object] = {"query": q}
            raise VectorSearchError(error_msg, cause=exc, context=context_dict) from exc
        else:
            return {"concepts": concepts}


app.get("/healthz")(healthz)
app.post("/search", response_model=SearchResponse)(search)
app.post("/graph/concepts", response_model=dict)(graph_concepts)
