"""Exception hierarchy and Problem Details support.

This module provides typed exceptions with RFC 9457 Problem Details
mapping and structured error handling.

Examples
--------
>>> from kgfoundry_common.errors import KgFoundryError, ErrorCode
>>> try:
...     raise KgFoundryError("Operation failed", ErrorCode.RUNTIME_ERROR)
... except KgFoundryError as e:
...     details = e.to_problem_details(instance="/api/search")
...     assert details["type"] == "https://kgfoundry.dev/problems/runtime-error"
"""

# [nav:section public-api]

from __future__ import annotations

from typing import NoReturn, Protocol, cast

from kgfoundry_common.errors.codes import BASE_TYPE_URI, ErrorCode, get_type_uri
from kgfoundry_common.errors.exceptions import (
    AgentCatalogSearchError,
    ArtifactDependencyError,
    ArtifactDeserializationError,
    ArtifactModelError,
    ArtifactSerializationError,
    ArtifactValidationError,
    CatalogLoadError,
    CatalogSessionError,
    ChunkingError,
    ConfigurationError,
    DeserializationError,
    DoclingError,
    DownloadError,
    EmbeddingError,
    IndexBuildError,
    KgFoundryError,
    LinkerCalibrationError,
    Neo4jError,
    OCRTimeoutError,
    OntologyParseError,
    RegistryError,
    RetryExhaustedError,
    SchemaValidationError,
    SerializationError,
    SettingsError,
    SpladeOOMError,
    SymbolAttachmentError,
    UnsupportedMIMEError,
    VectorSearchError,
)
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.navmap_types import NavMap as _NavMap

NavMap = _NavMap


# Structural protocols for optional FastAPI integration. We keep the
# expectations minimal so the package does not need FastAPI installed for
# static analysis while preserving typed call signatures.


def _protocol_stub(method: str, *args: object, **kwargs: object) -> NoReturn:
    """Raise ``NotImplementedError`` when a structural protocol leaks to runtime."""
    message = (
        f"FastAPI protocol method '{method}' must be implemented by the concrete app. "
        f"Received args={args!r}, kwargs={kwargs!r}."
    )
    raise NotImplementedError(message)


class RequestProtocol(Protocol):
    """Structural type for FastAPI's Request object."""


class JSONResponseProtocol(Protocol):
    """Structural type for FastAPI's JSONResponse."""

    status_code: int


class ExceptionHandlerProtocol(Protocol):
    """Structural type for FastAPI exception handlers."""

    def __call__(self, *args: object, **kwargs: object) -> object:
        """Process an exception raised within the FastAPI request lifecycle."""
        ...


class FastAPIProtocol(Protocol):
    """Structural type for FastAPI application instances."""

    def add_exception_handler(
        self,
        exception_class: type[BaseException],
        handler: ExceptionHandlerProtocol,
        *,
        name: str | None = None,
    ) -> None:
        """Register an exception handler."""
        _protocol_stub("add_exception_handler", self, exception_class, handler, name=name)


class ProblemDetailsResponse(Protocol):
    """Callable protocol for Problem Details response helpers."""

    def __call__(
        self,
        error: KgFoundryError,
        request: RequestProtocol | None = None,
    ) -> JSONResponseProtocol:
        """Convert a KgFoundryError into a JSON-response payload."""
        ...


class RegisterProblemDetailsHandler(Protocol):
    """Callable protocol for registering Problem Details handlers."""

    def __call__(self, app: FastAPIProtocol) -> None:
        """Attach the Problem Details handler to a FastAPI-like application."""
        ...


# HTTP adapters are optional (require fastapi)
_problem_details_response: ProblemDetailsResponse
_register_problem_details_handler: RegisterProblemDetailsHandler

try:
    from kgfoundry_common.errors.http import (
        problem_details_response as _http_problem_details_response,
    )
    from kgfoundry_common.errors.http import (
        register_problem_details_handler as _http_register_problem_details_handler,
    )
except ImportError:  # pragma: no cover - optional dependency

    def _missing_problem_details_response(
        error: KgFoundryError,
        request: RequestProtocol | None = None,
    ) -> JSONResponseProtocol:
        """Raise ``RuntimeError`` when FastAPI support is unavailable.

        Parameters
        ----------
        error : KgFoundryError
            Error instance (unused, for signature compatibility).
        request : RequestProtocol | None, optional
            Request instance (unused, for signature compatibility).

        Returns
        -------
        JSONResponseProtocol
            This helper never returns; the return type is declared for signature
            compatibility with the FastAPI-enabled variant.

        Raises
        ------
        RuntimeError
            Always raised to indicate missing FastAPI dependency.
        """
        del error, request
        message = (
            "FastAPI support is not installed. Install kgfoundry[api] to enable "
            "problem details response helpers."
        )
        raise RuntimeError(message)
        return cast("JSONResponseProtocol", None)  # pragma: no cover

    _problem_details_response = _missing_problem_details_response

    def _missing_register_problem_details_handler(app: FastAPIProtocol) -> None:
        """Raise ``RuntimeError`` when FastAPI support is unavailable.

        Parameters
        ----------
        app : FastAPIProtocol
            FastAPI app instance (unused, for signature compatibility).

        Raises
        ------
        RuntimeError
            Always raised to indicate missing FastAPI dependency.
        """
        del app
        message = (
            "FastAPI support is not installed. Install kgfoundry[api] to enable "
            "Problem Details handlers."
        )
        raise RuntimeError(message)

    _register_problem_details_handler = _missing_register_problem_details_handler
else:
    _problem_details_response = cast(
        "ProblemDetailsResponse",
        _http_problem_details_response,
    )
    _register_problem_details_handler = cast(
        "RegisterProblemDetailsHandler",
        _http_register_problem_details_handler,
    )


# [nav:anchor problem_details_response]
def problem_details_response(
    error: KgFoundryError,
    request: RequestProtocol | None = None,
) -> JSONResponseProtocol:
    """Convert ``KgFoundryError`` to a Problem Details response.

    This wrapper preserves the optional FastAPI dependency while exposing a
    typed interface that accepts the structural ``RequestProtocol`` defined in
    this module. When FastAPI support is installed, the helper delegates to the
    implementation in ``kgfoundry_common.errors.http``. Otherwise it raises an
    informative ``RuntimeError`` describing the missing optional dependency.

    Parameters
    ----------
    error : KgFoundryError
        Error instance to convert.
    request : RequestProtocol | None, optional
        Optional request instance for context.

    Returns
    -------
    JSONResponseProtocol
        Problem Details HTTP response.
    """
    return _problem_details_response(error, request)


# [nav:anchor register_problem_details_handler]
def register_problem_details_handler(app: FastAPIProtocol) -> None:
    """Register the KgFoundry Problem Details handler on a FastAPI app."""
    _register_problem_details_handler(app)


__all__ = [
    "BASE_TYPE_URI",
    "AgentCatalogSearchError",
    "ArtifactDependencyError",
    "ArtifactDeserializationError",
    "ArtifactModelError",
    "ArtifactSerializationError",
    "ArtifactValidationError",
    "CatalogLoadError",
    "CatalogSessionError",
    "ChunkingError",
    "ConfigurationError",
    "DeserializationError",
    "DoclingError",
    "DownloadError",
    "EmbeddingError",
    "ErrorCode",
    "IndexBuildError",
    "KgFoundryError",
    "LinkerCalibrationError",
    "NavMap",
    "Neo4jError",
    "OCRTimeoutError",
    "OntologyParseError",
    "RegistryError",
    "RetryExhaustedError",
    "SchemaValidationError",
    "SerializationError",
    "SettingsError",
    "SpladeOOMError",
    "SymbolAttachmentError",
    "UnsupportedMIMEError",
    "VectorSearchError",
    "get_type_uri",
    "problem_details_response",
    "register_problem_details_handler",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
