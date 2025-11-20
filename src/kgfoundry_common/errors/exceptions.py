"""Typed exception hierarchy with Problem Details support.

All kgfoundry exceptions inherit from KgFoundryError, which provides
structured fields and RFC 9457 Problem Details mapping.

Examples
--------
>>> from kgfoundry_common.errors import DownloadError, ErrorCode
>>> try:
...     raise DownloadError("Failed to fetch resource", cause=IOError("Connection refused"))
... except DownloadError as e:
...     assert e.code == ErrorCode.DOWNLOAD_FAILED
...     assert e.http_status == 503
...     details = e.to_problem_details(instance="/api/download")
"""

# [nav:section public-api]

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from kgfoundry_common.errors.codes import ErrorCode, get_type_uri
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.problem_details import build_problem_details

if TYPE_CHECKING:
    from kgfoundry_common.problem_details import JsonValue, ProblemDetails

__all__ = [
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
    "IndexBuildError",
    "KgFoundryError",
    "KgFoundryErrorConfig",
    "LinkerCalibrationError",
    "Neo4jError",
    "OCRTimeoutError",
    "OntologyParseError",
    "RegistryError",
    "RetryExhaustedError",
    "SchemaValidationError",
    "SerializationError",
    "SpladeOOMError",
    "SymbolAttachmentError",
    "UnsupportedMIMEError",
    "VectorSearchError",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


@dataclass(slots=True, frozen=True)
# [nav:anchor KgFoundryErrorConfig]
class KgFoundryErrorConfig:
    """Configuration options used when instantiating :class:`KgFoundryError`."""

    code: ErrorCode = ErrorCode.RUNTIME_ERROR
    http_status: int = 500
    log_level: int = logging.ERROR
    cause: Exception | None = None
    context: Mapping[str, object] | None = None


_KNOWN_CONFIG_KEYS = frozenset({"code", "http_status", "log_level", "cause", "context"})


def _coerce_error_config(
    config: KgFoundryErrorConfig | None,
    legacy_kwargs: dict[str, object],
) -> KgFoundryErrorConfig:
    """Coerce error configuration from config object or legacy keyword arguments.

    Validates and resolves error configuration from either a structured config
    object or legacy keyword arguments. Ensures mutual exclusivity and type
    safety for all configuration fields.

    Parameters
    ----------
    config : KgFoundryErrorConfig | None
        Structured configuration object. If provided, legacy_kwargs must be empty.
    legacy_kwargs : dict[str, object]
        Dictionary of legacy keyword arguments mirroring KgFoundryErrorConfig
        fields. Ignored if config is provided.

    Returns
    -------
    KgFoundryErrorConfig
        Validated and resolved configuration object.

    Raises
    ------
    TypeError
        If both config and legacy_kwargs are provided, or if legacy_kwargs
        contains unknown keys, or if any field has an invalid type.

    Examples
    --------
    >>> from kgfoundry_common.errors import ErrorCode
    >>> config = _coerce_error_config(None, {"code": ErrorCode.RUNTIME_ERROR})
    >>> assert config.code == ErrorCode.RUNTIME_ERROR
    """
    if config is not None:
        if legacy_kwargs:
            unexpected = ", ".join(sorted(legacy_kwargs))
            message = (
                f"KgFoundryError received both 'config' and legacy keyword arguments: {unexpected}"
            )
            raise TypeError(message)
        return config

    unexpected_keys = set(legacy_kwargs) - set(_KNOWN_CONFIG_KEYS)
    if unexpected_keys:
        unexpected = ", ".join(sorted(unexpected_keys))
        message = f"KgFoundryError got unexpected keyword arguments: {unexpected}"
        raise TypeError(message)

    code = legacy_kwargs.get("code", ErrorCode.RUNTIME_ERROR)
    http_status = legacy_kwargs.get("http_status", 500)
    log_level = legacy_kwargs.get("log_level", logging.ERROR)
    cause = legacy_kwargs.get("cause")
    context = legacy_kwargs.get("context")

    context_mapping: Mapping[str, object] | None
    if context is None:
        context_mapping = None
    elif isinstance(context, Mapping):
        context_mapping = context
    else:
        message = "context must be a mapping when provided"
        raise TypeError(message)

    if not isinstance(code, ErrorCode):
        message = "code must be an instance of ErrorCode"
        raise TypeError(message)
    if not isinstance(http_status, int):
        message = "http_status must be an int"
        raise TypeError(message)
    if not isinstance(log_level, int):
        message = "log_level must be an int"
        raise TypeError(message)
    if cause is not None and not isinstance(cause, Exception):
        message = "cause must be an Exception when provided"
        raise TypeError(message)

    return KgFoundryErrorConfig(
        code=code,
        http_status=http_status,
        log_level=log_level,
        cause=cause,
        context=context_mapping,
    )


# [nav:anchor KgFoundryError]
class KgFoundryError(Exception):
    """Base exception for all kgfoundry errors.

    Extended Summary
    ----------------
    Provides structured fields (code, http_status, log_level) and RFC 9457
    Problem Details mapping. All kgfoundry exceptions inherit from this
    base class and can be converted to Problem Details JSON for HTTP responses.
    Resolves configuration from either a structured config object or legacy
    keyword arguments, ensuring type safety and mutual exclusivity.

    Parameters
    ----------
    message : str
        Human-readable error message describing the failure condition.
    config : KgFoundryErrorConfig | None, optional
        Structured configuration object containing code, http_status,
        log_level, cause, and context fields. When provided, legacy_kwargs
        must be empty. Defaults to None, which triggers legacy keyword
        argument resolution.
    **legacy_kwargs : object
        Backwards-compatible keyword arguments mirroring KgFoundryErrorConfig
        fields (code, http_status, log_level, cause, context). Cannot be
        combined with config parameter. Allowed keys are validated against
        known configuration fields.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe for construction. The error code defaults to
    RUNTIME_ERROR, HTTP status defaults to 500, and log level defaults to
    ERROR if not specified via config or legacy_kwargs.

    The constructor raises TypeError indirectly via _coerce_error_config() when
    validation fails (e.g., both config and legacy_kwargs provided, unknown keys,
    or invalid field types). This is documented in the Notes section rather than
    Raises because the raise occurs in a helper function, not directly in __init__.

    Examples
    --------
    >>> from kgfoundry_common.errors import KgFoundryError, ErrorCode
    >>> error = KgFoundryError("Operation failed", code=ErrorCode.RUNTIME_ERROR)
    >>> assert error.code == ErrorCode.RUNTIME_ERROR
    >>> details = error.to_problem_details(instance="/api/operation")
    >>> assert details["status"] == 500
    >>> # Using config object
    >>> from kgfoundry_common.errors import KgFoundryErrorConfig
    >>> config = KgFoundryErrorConfig(code=ErrorCode.RUNTIME_ERROR, http_status=404)
    >>> error2 = KgFoundryError("Not found", config=config)
    >>> assert error2.http_status == 404
    """

    def __init__(
        self,
        message: str,
        *,
        config: KgFoundryErrorConfig | None = None,
        **legacy_kwargs: object,
    ) -> None:
        """Initialize exception with message and configuration.

        See class docstring for detailed parameter documentation.
        """
        resolved_config = _coerce_error_config(config, dict(legacy_kwargs))
        self.message = message
        self.code = resolved_config.code
        self.http_status = resolved_config.http_status
        self.log_level = resolved_config.log_level
        self.context = dict(resolved_config.context) if resolved_config.context else {}
        if resolved_config.cause is not None:
            self.__cause__ = resolved_config.cause

    def to_problem_details(
        self,
        instance: str | None = None,
        title: str | None = None,
    ) -> ProblemDetails:
        """Convert to RFC 9457 Problem Details JSON.

        Converts the exception to a Problem Details JSON structure suitable
        for HTTP error responses. Includes type URI, title, status, detail,
        instance, code, and optional context extensions.

        Parameters
        ----------
        instance : str | None, optional
            URI identifying the specific occurrence. Defaults to None.
        title : str | None, optional
            Short summary. Defaults to the exception class name.
            Defaults to None.

        Returns
        -------
        ProblemDetails
            Problem Details object with type, title, status, detail, code,
            instance, and optional errors fields.

        Examples
        --------
        >>> error = KgFoundryError(
        ...     "Not found", code=ErrorCode.RESOURCE_UNAVAILABLE, http_status=404
        ... )
        >>> details = error.to_problem_details(instance="/api/resource/123")
        >>> assert details["type"] == "https://kgfoundry.dev/problems/resource-unavailable"
        >>> assert details["status"] == 404
        >>> assert details["code"] == "resource-unavailable"
        """
        return build_problem_details(
            problem_type=get_type_uri(self.code),
            title=title or self.__class__.__name__,
            status=self.http_status,
            detail=self.message,
            instance=instance or "urn:kgfoundry:error",
            code=self.code.value,
            extensions=cast(
                "Mapping[str, JsonValue] | None", self.context if self.context else None
            ),
        )

    def __str__(self) -> str:
        """Return formatted error string.

        Returns a string representation of the error including the class
        name, error code, and message. If a cause exception is present,
        includes information about the cause.

        Returns
        -------
        str
            Formatted error string
            (e.g., "DownloadError[download-failed]: Failed to fetch resource").
        """
        base = f"{self.__class__.__name__}[{self.code.value}]: {self.message}"
        if self.__cause__:
            base += f" (caused by: {type(self.__cause__).__name__})"
        return base


# [nav:anchor DownloadError]
class DownloadError(KgFoundryError):
    """Error during download or resource fetch operations.

    Extended Summary
    ----------------
    Raised when download or resource fetch operations fail. Uses error code
    DOWNLOAD_FAILED and HTTP status 503 (Service Unavailable). Inherits
    structured error handling and Problem Details mapping from KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the download failure (e.g.,
        "Failed to fetch resource from URL").
    cause : Exception | None, optional
        Underlying exception that caused the download failure (e.g., IOError,
        ConnectionError, TimeoutError). Stored as exception cause for
        chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., URL, retry count,
        response headers). Merged into Problem Details extensions. Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to DOWNLOAD_FAILED
    and HTTP status is fixed to 503.

    Examples
    --------
    >>> raise DownloadError("Failed to download PDF", cause=IOError("Connection refused"))
    >>> # With context
    >>> raise DownloadError(
    ...     "Download timeout",
    ...     cause=TimeoutError("30s exceeded"),
    ...     context={"url": "https://example.com/file.pdf", "timeout_seconds": 30},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message, optional cause, and context.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.DOWNLOAD_FAILED,
            http_status=503,
            cause=cause,
            context=context,
        )


# [nav:anchor UnsupportedMIMEError]
class UnsupportedMIMEError(KgFoundryError):
    """Error for unsupported MIME types.

    Extended Summary
    ----------------
    Raised when a file or resource has an unsupported MIME type. Uses error
    code UNSUPPORTED_MIME and HTTP status 415 (Unsupported Media Type).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the unsupported MIME type
        (e.g., "application/x-unknown is not supported").
    cause : Exception | None, optional
        Underlying exception that caused the error (e.g., ValueError from
        MIME type detection). Stored as exception cause for chained exception
        handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., detected MIME
        type, file path, supported types list). Merged into Problem Details
        extensions. Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to UNSUPPORTED_MIME
    and HTTP status is fixed to 415.

    Examples
    --------
    >>> raise UnsupportedMIMEError("application/x-unknown is not supported")
    >>> # With context
    >>> raise UnsupportedMIMEError(
    ...     "Unsupported MIME type",
    ...     context={"detected_mime": "application/x-unknown", "supported": ["application/pdf"]},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.UNSUPPORTED_MIME,
            http_status=415,
            cause=cause,
            context=context,
        )


# [nav:anchor DoclingError]
class DoclingError(KgFoundryError):
    """Error during document processing with Docling.

    Extended Summary
    ----------------
    Raised when document processing operations fail in Docling. Uses error
    code DOCLING_ERROR and HTTP status 422 (Unprocessable Entity). Inherits
    structured error handling and Problem Details mapping from KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the processing failure
        (e.g., "Failed to parse document structure").
    cause : Exception | None, optional
        Underlying exception that caused the processing failure (e.g., ValueError
        from invalid format, IOError from file access). Stored as exception cause
        for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., document path,
        processing stage, format type). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to DOCLING_ERROR
    and HTTP status is fixed to 422.

    Examples
    --------
    >>> raise DoclingError("Failed to parse document", cause=ValueError("Invalid format"))
    >>> # With context
    >>> raise DoclingError(
    ...     "Processing failed",
    ...     cause=IOError("File not found"),
    ...     context={"document_path": "/path/to/doc.pdf", "stage": "parsing"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.DOCLING_ERROR,
            http_status=422,
            cause=cause,
            context=context,
        )


# [nav:anchor OCRTimeoutError]
class OCRTimeoutError(KgFoundryError):
    """Error when OCR operation times out.

    Extended Summary
    ----------------
    Raised when OCR (Optical Character Recognition) operations exceed their
    timeout limit. Uses error code OCR_TIMEOUT and HTTP status 504 (Gateway Timeout).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the timeout (e.g., "OCR timed
        out after 30s").
    cause : Exception | None, optional
        Underlying exception that caused the timeout (e.g., TimeoutError from
        OCR backend). Stored as exception cause for chained exception handling.
        Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., timeout_seconds,
        document_path, processing stage). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to OCR_TIMEOUT
    and HTTP status is fixed to 504.

    Examples
    --------
    >>> raise OCRTimeoutError("OCR timed out after 30s")
    >>> # With context
    >>> raise OCRTimeoutError(
    ...     "OCR timeout",
    ...     cause=TimeoutError("30s exceeded"),
    ...     context={"timeout_seconds": 30, "document_path": "/path/to/image.png"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.OCR_TIMEOUT,
            http_status=504,
            cause=cause,
            context=context,
        )


# [nav:anchor ChunkingError]
class ChunkingError(KgFoundryError):
    """Error during text chunking operations.

    Extended Summary
    ----------------
    Raised when text chunking operations fail. Uses error code CHUNKING_ERROR
    and HTTP status 422 (Unprocessable Entity). Inherits structured error
    handling and Problem Details mapping from KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the chunking failure (e.g.,
        "Failed to chunk document").
    cause : Exception | None, optional
        Underlying exception that caused the chunking failure (e.g., ValueError
        from empty text, IndexError from invalid chunk size). Stored as exception
        cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., chunk_size,
        document_length, chunking_strategy). Merged into Problem Details
        extensions. Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to CHUNKING_ERROR
    and HTTP status is fixed to 422.

    Examples
    --------
    >>> raise ChunkingError("Failed to chunk document", cause=ValueError("Empty text"))
    >>> # With context
    >>> raise ChunkingError(
    ...     "Chunking failed",
    ...     cause=ValueError("Invalid chunk size"),
    ...     context={"chunk_size": 0, "document_length": 1000},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.CHUNKING_ERROR,
            http_status=422,
            cause=cause,
            context=context,
        )


# [nav:anchor EmbeddingError]
class EmbeddingError(KgFoundryError):
    """Error during embedding generation.

    Extended Summary
    ----------------
    Raised when embedding generation operations fail. Uses error code
    EMBEDDING_ERROR and HTTP status 503 (Service Unavailable). Inherits
    structured error handling and Problem Details mapping from KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the embedding failure (e.g.,
        "Failed to generate embeddings").
    cause : Exception | None, optional
        Underlying exception that caused the embedding failure (e.g., RuntimeError
        from backend unavailable, MemoryError from OOM). Stored as exception cause
        for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., model_name,
        input_length, backend_type). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to EMBEDDING_ERROR
    and HTTP status is fixed to 503.

    Examples
    --------
    >>> raise EmbeddingError(
    ...     "Failed to generate embeddings", cause=RuntimeError("backend unavailable")
    ... )
    >>> # With context
    >>> raise EmbeddingError(
    ...     "Embedding generation failed",
    ...     cause=MemoryError("Out of memory"),
    ...     context={"model_name": "bert-base", "input_length": 10000},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.EMBEDDING_ERROR,
            http_status=503,
            cause=cause,
            context=context,
        )


# [nav:anchor SpladeOOMError]
class SpladeOOMError(KgFoundryError):
    """Error when SPLADE operation runs out of memory.

    Extended Summary
    ----------------
    Raised when SPLADE (Sparse Lexical and Expansion) operations exceed
    available memory. Uses error code SPLADE_OOM and HTTP status 507
    (Insufficient Storage). Inherits structured error handling and Problem
    Details mapping from KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the out-of-memory condition
        (e.g., "SPLADE OOM during inference").
    cause : Exception | None, optional
        Underlying exception that caused the OOM (e.g., MemoryError from Python
        runtime, OSError from system memory exhaustion). Stored as exception cause
        for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., input_length,
        memory_limit_bytes, batch_size). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to SPLADE_OOM
    and HTTP status is fixed to 507.

    Examples
    --------
    >>> raise SpladeOOMError("SPLADE OOM during inference")
    >>> # With context
    >>> raise SpladeOOMError(
    ...     "SPLADE out of memory",
    ...     cause=MemoryError("Cannot allocate array"),
    ...     context={"input_length": 1000000, "memory_limit_bytes": 1073741824},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.SPLADE_OOM,
            http_status=507,
            cause=cause,
            context=context,
        )


# [nav:anchor IndexBuildError]
class IndexBuildError(KgFoundryError):
    """Error during index construction.

    Extended Summary
    ----------------
    Raised when index construction operations fail (e.g., FAISS index build).
    Uses error code INDEX_BUILD_ERROR and HTTP status 500 (Internal Server Error).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the index build failure
        (e.g., "Failed to build FAISS index").
    cause : Exception | None, optional
        Underlying exception that caused the build failure (e.g., IOError from
        disk full, ValueError from invalid parameters). Stored as exception cause
        for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., index_type,
        vector_count, index_path). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to INDEX_BUILD_ERROR
    and HTTP status is fixed to 500.

    Examples
    --------
    >>> raise IndexBuildError("Failed to build FAISS index", cause=IOError("Disk full"))
    >>> # With context
    >>> raise IndexBuildError(
    ...     "Index build failed",
    ...     cause=ValueError("Invalid dimension"),
    ...     context={"index_type": "faiss", "vector_count": 1000000, "dimension": 768},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.INDEX_BUILD_ERROR,
            http_status=500,
            cause=cause,
            context=context,
        )


# [nav:anchor OntologyParseError]
class OntologyParseError(KgFoundryError):
    """Error during ontology parsing.

    Extended Summary
    ----------------
    Raised when ontology parsing operations fail (e.g., OWL file parsing).
    Uses error code ONTOLOGY_PARSE_ERROR and HTTP status 422 (Unprocessable Entity).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the parsing failure (e.g.,
        "Failed to parse OWL file").
    cause : Exception | None, optional
        Underlying exception that caused the parsing failure (e.g., XMLSyntaxError
        from invalid XML, SyntaxError from malformed OWL). Stored as exception
        cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., ontology_path,
        format_type, line_number). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to ONTOLOGY_PARSE_ERROR
    and HTTP status is fixed to 422.

    Examples
    --------
    >>> raise OntologyParseError("Failed to parse OWL file", cause=XMLSyntaxError("Invalid XML"))
    >>> # With context
    >>> raise OntologyParseError(
    ...     "Parsing failed",
    ...     cause=XMLSyntaxError("Invalid syntax"),
    ...     context={"ontology_path": "/path/to/ontology.owl", "line_number": 42},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.ONTOLOGY_PARSE_ERROR,
            http_status=422,
            cause=cause,
            context=context,
        )


# [nav:anchor LinkerCalibrationError]
class LinkerCalibrationError(KgFoundryError):
    """Error during linker calibration.

    Extended Summary
    ----------------
    Raised when linker calibration operations fail. Uses error code
    LINKER_CALIBRATION_ERROR and HTTP status 500 (Internal Server Error).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the calibration failure
        (e.g., "Calibration failed").
    cause : Exception | None, optional
        Underlying exception that caused the calibration failure (e.g., ValueError
        from invalid parameters, RuntimeError from convergence failure). Stored as
        exception cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., calibration_stage,
        parameter_values, iteration_count). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to LINKER_CALIBRATION_ERROR
    and HTTP status is fixed to 500.

    Examples
    --------
    >>> raise LinkerCalibrationError("Calibration failed", cause=ValueError("Invalid parameters"))
    >>> # With context
    >>> raise LinkerCalibrationError(
    ...     "Calibration convergence failed",
    ...     cause=RuntimeError("Max iterations exceeded"),
    ...     context={"calibration_stage": "threshold_tuning", "iteration_count": 1000},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.LINKER_CALIBRATION_ERROR,
            http_status=500,
            cause=cause,
            context=context,
        )


# [nav:anchor Neo4jError]
class Neo4jError(KgFoundryError):
    """Error during Neo4j operations.

    Extended Summary
    ----------------
    Raised when Neo4j database operations fail. Uses error code NEO4J_ERROR
    and HTTP status 503 (Service Unavailable). Inherits structured error
    handling and Problem Details mapping from KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the Neo4j operation failure
        (e.g., "Neo4j query failed").
    cause : Exception | None, optional
        Underlying exception that caused the Neo4j failure (e.g., ConnectionError
        from database unreachable, QueryError from Cypher syntax error). Stored as
        exception cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., query_text,
        operation_type, node_count). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to NEO4J_ERROR
    and HTTP status is fixed to 503.

    Examples
    --------
    >>> raise Neo4jError("Neo4j query failed", cause=ConnectionError("Database unreachable"))
    >>> # With context
    >>> raise Neo4jError(
    ...     "Query execution failed",
    ...     cause=QueryError("Syntax error"),
    ...     context={"query_text": "MATCH (n) RETURN n", "operation_type": "read"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.NEO4J_ERROR,
            http_status=503,
            cause=cause,
            context=context,
        )


# [nav:anchor ConfigurationError]
class ConfigurationError(KgFoundryError):
    """Error during configuration validation or loading.

    Extended Summary
    ----------------
    Raised when configuration validation or loading fails. Uses error code
    CONFIGURATION_ERROR and HTTP status 500 (Internal Server Error) with
    CRITICAL log level. Inherits structured error handling and Problem Details
    mapping from KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the configuration failure
        (e.g., "Missing required env var: KGFOUNDRY_API_KEY").
    cause : Exception | None, optional
        Underlying exception that caused the configuration failure (e.g., ValueError
        from invalid value, KeyError from missing key). Stored as exception cause
        for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., config_file_path,
        env_var_name, validation_errors). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to CONFIGURATION_ERROR,
    HTTP status is fixed to 500, and log level is fixed to CRITICAL.

    Examples
    --------
    >>> raise ConfigurationError("Missing required env var: KGFOUNDRY_API_KEY")
    >>> # With context
    >>> raise ConfigurationError(
    ...     "Invalid configuration",
    ...     cause=ValueError("Invalid port number"),
    ...     context={"config_file": "config.yaml", "field": "server.port"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.CONFIGURATION_ERROR,
            http_status=500,
            log_level=logging.CRITICAL,
            cause=cause,
            context=context,
        )

    @classmethod
    def with_details(
        cls,
        *,
        field: str,
        issue: str,
        hint: str | None = None,
    ) -> ConfigurationError:
        """Create a ConfigurationError with structured validation details.

        Parameters
        ----------
        field : str
            Name of the configuration field that failed validation.
        issue : str
            Description of the validation issue (e.g., "Must be > 0", "Invalid format").
        hint : str | None, optional
            Optional hint for resolving the issue (e.g., "Use ISO 8601 format").
            Defaults to ``None``.

        Returns
        -------
        ConfigurationError
            New instance with details captured in context.

        Examples
        --------
        >>> error = ConfigurationError.with_details(
        ...     field="timeout_seconds",
        ...     issue="Must be > 0",
        ...     hint="Provide a positive integer",
        ... )
        >>> assert "timeout_seconds" in str(error.context)
        """
        details: dict[str, object] = {
            "field": field,
            "issue": issue,
        }
        if hint is not None:
            details["hint"] = hint

        message = f"Configuration validation failed for field '{field}': {issue}"
        return cls(message, context=details)


class SettingsError(KgFoundryError):
    """Error raised when runtime settings validation fails.

    Extended Summary
    ----------------
    Raised when runtime settings validation fails. Similar to ConfigurationError
    but includes structured validation error details. Uses error code
    CONFIGURATION_ERROR and HTTP status 500. Inherits structured error handling
    and Problem Details mapping from KgFoundryError. Merges validation errors
    into context if provided.

    Parameters
    ----------
    message : str
        Human-readable error message describing the settings validation failure
        (e.g., "Settings validation failed").
    errors : list[dict[str, object]] | None, optional
        List of validation error dictionaries with field/issue details. Each
        dictionary should contain keys like "field", "issue", and optionally
        "hint". Merged into context["validation_errors"]. Defaults to None.
    cause : Exception | None, optional
        Underlying exception that caused the validation failure (e.g., ValueError
        from invalid type, ValidationError from Pydantic). Stored as exception cause
        for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., settings_file_path,
        validated_fields). Merged with validation_errors into Problem Details
        extensions. Defaults to None.

    Notes
    -----
    Time O(n) where n is the number of validation errors; memory O(n) for error
    storage. No I/O, no global state. Thread-safe. The error code is fixed to
    CONFIGURATION_ERROR and HTTP status is fixed to 500.

    Examples
    --------
    >>> raise SettingsError(
    ...     "Settings validation failed", errors=[{"field": "timeout", "issue": "Must be > 0"}]
    ... )
    >>> # With cause and context
    >>> raise SettingsError(
    ...     "Invalid settings",
    ...     errors=[{"field": "port", "issue": "Must be between 1 and 65535"}],
    ...     cause=ValueError("Port out of range"),
    ...     context={"settings_file": "settings.yaml"},
    ... )
    """

    def __init__(
        self,
        message: str,
        *,
        errors: list[dict[str, object]] | None = None,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        combined_context: dict[str, object] = dict(context or {})
        if errors:
            combined_context.setdefault(
                "validation_errors",
                [dict(error) for error in errors],
            )
        super().__init__(
            message,
            code=ErrorCode.CONFIGURATION_ERROR,
            http_status=500,
            cause=cause,
            context=combined_context,
        )


# [nav:anchor SerializationError]
class SerializationError(KgFoundryError):
    """Error during JSON serialization or schema validation.

    Extended Summary
    ----------------
    Raised when JSON serialization or schema validation fails. Uses error
    code SERIALIZATION_ERROR and HTTP status 500 (Internal Server Error).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the serialization failure
        (e.g., "Schema validation failed").
    cause : Exception | None, optional
        Underlying exception that caused the serialization failure (e.g., ValueError
        from invalid type, TypeError from non-serializable object). Stored as exception
        cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., schema_path,
        object_type, field_name). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to SERIALIZATION_ERROR
    and HTTP status is fixed to 500.

    Examples
    --------
    >>> raise SerializationError("Schema validation failed", cause=ValueError("Invalid type"))
    >>> # With context
    >>> raise SerializationError(
    ...     "Serialization failed",
    ...     cause=TypeError("Object not JSON serializable"),
    ...     context={"object_type": "MyClass", "field": "data"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.SERIALIZATION_ERROR,
            http_status=500,
            cause=cause,
            context=context,
        )


# [nav:anchor RegistryError]
class RegistryError(KgFoundryError):
    """Errors raised during registry or DuckDB operations.

    Extended Summary
    ----------------
    Raised when registry or DuckDB database operations fail. Uses error code
    REGISTRY_ERROR and HTTP status 500 (Internal Server Error). Inherits
    structured error handling and Problem Details mapping from KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the registry operation failure
        (e.g., "Failed to write to registry").
    cause : Exception | None, optional
        Underlying exception that caused the registry failure (e.g., DatabaseError
        from DuckDB, IOError from file access). Stored as exception cause for
        chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., registry_path,
        operation_type, table_name). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to REGISTRY_ERROR
    and HTTP status is fixed to 500.

    Examples
    --------
    >>> raise RegistryError("Failed to write to registry")
    >>> # With context
    >>> raise RegistryError(
    ...     "Registry operation failed",
    ...     cause=DatabaseError("Connection lost"),
    ...     context={"registry_path": "/path/to/registry", "operation": "write"},
    ... )
    """

    def __init__(
        self,
        message: str,
        *,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.REGISTRY_ERROR,
            http_status=500,
            cause=cause,
            context=context,
        )


# [nav:anchor DeserializationError]
class DeserializationError(KgFoundryError):
    """Error during JSON deserialization, schema validation, or checksum verification.

    Extended Summary
    ----------------
    Raised when JSON deserialization, schema validation, or checksum verification
    fails. Uses error code DESERIALIZATION_ERROR and HTTP status 500 (Internal Server Error).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the deserialization failure
        (e.g., "Checksum mismatch").
    cause : Exception | None, optional
        Underlying exception that caused the deserialization failure (e.g., ValueError
        from corrupted data, JSONDecodeError from invalid JSON, ValidationError from
        schema mismatch). Stored as exception cause for chained exception handling.
        Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., expected_checksum,
        actual_checksum, schema_path). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to DESERIALIZATION_ERROR
    and HTTP status is fixed to 500.

    Examples
    --------
    >>> raise DeserializationError("Checksum mismatch", cause=ValueError("Corrupted data"))
    >>> # With context
    >>> raise DeserializationError(
    ...     "Deserialization failed",
    ...     cause=JSONDecodeError("Invalid JSON"),
    ...     context={"expected_checksum": "abc123", "actual_checksum": "def456"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.DESERIALIZATION_ERROR,
            http_status=500,
            cause=cause,
            context=context,
        )


# [nav:anchor SchemaValidationError]
class SchemaValidationError(KgFoundryError):
    """Error raised when schema validation fails.

    Extended Summary
    ----------------
    Raised when schema validation fails. Includes structured validation error
    details. Uses error code SCHEMA_VALIDATION_ERROR and HTTP status 422
    (Unprocessable Entity). Inherits structured error handling and Problem
    Details mapping from KgFoundryError. Merges validation errors into context
    if provided.

    Parameters
    ----------
    message : str
        Human-readable error message describing the validation failure
        (e.g., "Invalid schema").
    errors : list[str] | None, optional
        List of validation error messages with path and constraint details
        (e.g., ["Missing field: name", "Field 'age' must be >= 0"]). Merged
        into context["validation_errors"]. Defaults to None.
    cause : Exception | None, optional
        Underlying exception that caused the validation failure (e.g., ValidationError
        from jsonschema, ValueError from constraint violation). Stored as exception
        cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., schema_path,
        validated_object_type). Merged with validation_errors into Problem Details
        extensions. Defaults to None.

    Notes
    -----
    Time O(n) where n is the number of validation errors; memory O(n) for error
    storage. No I/O, no global state. Thread-safe. The error code is fixed to
    SCHEMA_VALIDATION_ERROR and HTTP status is fixed to 422.

    Examples
    --------
    >>> raise SchemaValidationError("Invalid schema", errors=["Missing field: name"])
    >>> # With cause and context
    >>> raise SchemaValidationError(
    ...     "Validation failed",
    ...     errors=["Field 'age' must be >= 0", "Field 'email' must be valid email"],
    ...     cause=ValidationError("Schema mismatch"),
    ...     context={"schema_path": "/schemas/user.json"},
    ... )
    """

    def __init__(
        self,
        message: str,
        *,
        errors: list[str] | None = None,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        combined_context: dict[str, object] = dict(context or {})
        if errors:
            combined_context.setdefault("validation_errors", list(errors))
        super().__init__(
            message,
            code=ErrorCode.SCHEMA_VALIDATION_ERROR,
            http_status=422,
            cause=cause,
            context=combined_context,
        )


# [nav:anchor RetryExhaustedError]
class RetryExhaustedError(KgFoundryError):
    """Raised when retry logic exhausts all attempts.

    Extended Summary
    ----------------
    This exception indicates that a retryable operation has exhausted all
    retry attempts and should surface Problem Details with retry guidance
    information. Uses error code RETRY_EXHAUSTED and HTTP status 503.
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError. Stores retry metadata (operation, attempts, retry_after_seconds)
    as instance attributes for Problem Details conversion.

    Parameters
    ----------
    message : str
        Human-readable error message describing the retry exhaustion
        (e.g., "Retry attempts exhausted").
    operation : str | None, optional
        Name of the operation that failed (e.g., "http_request", "database_query").
        Stored as instance attribute and included in Problem Details extensions.
        Defaults to None.
    attempts : int | None, optional
        Number of retry attempts that were made. Must be >= 0 if provided.
        Stored as instance attribute and included in Problem Details extensions.
        Defaults to None.
    last_error : Exception | None, optional
        The last exception that occurred before retries were exhausted. Stored
        as instance attribute for debugging. Not automatically chained as cause.
        Defaults to None.
    retry_after_seconds : int | None, optional
        Suggested retry delay in seconds. Must be >= 0 if provided. Stored as
        instance attribute and included in Problem Details extensions as
        "retry_after_seconds". Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and attribute storage. No I/O,
    no global state. Thread-safe. The error code is fixed to RETRY_EXHAUSTED,
    HTTP status is fixed to 503, and log level is fixed to ERROR. Overrides
    to_problem_details() to include retry metadata in extensions.

    Examples
    --------
    >>> raise RetryExhaustedError(
    ...     "Retry attempts exhausted", operation="http_request", attempts=3, retry_after_seconds=60
    ... )
    >>> # With last_error
    >>> raise RetryExhaustedError(
    ...     "Retries exhausted",
    ...     operation="database_query",
    ...     attempts=5,
    ...     last_error=ConnectionError("Connection lost"),
    ...     retry_after_seconds=30,
    ... )
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        attempts: int | None = None,
        last_error: Exception | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.RETRY_EXHAUSTED,
            http_status=503,
            log_level=logging.ERROR,
        )
        self.operation = operation
        self.attempts = attempts
        self.last_error = last_error
        self.retry_after_seconds = retry_after_seconds

    def to_problem_details(
        self,
        instance: str | None = None,
        title: str | None = None,
    ) -> ProblemDetails:
        """Convert to RFC 9457 Problem Details JSON.

        Converts the exception to a Problem Details JSON structure including
        retry metadata (operation, attempts, retry_after_seconds) in extensions.

        Parameters
        ----------
        instance : str | None, optional
            Instance URI for the specific error occurrence. Defaults to None.
        title : str | None, optional
            Short summary. Defaults to the exception class name.
            Defaults to None.

        Returns
        -------
        ProblemDetails
            Problem Details JSON structure with retry metadata in extensions.
        """
        extensions: dict[str, object] = {}
        if self.operation:
            extensions["operation"] = self.operation
        if self.attempts is not None:
            extensions["attempts"] = self.attempts
        if self.retry_after_seconds is not None:
            extensions["retry_after_seconds"] = self.retry_after_seconds

        return build_problem_details(
            problem_type=get_type_uri(self.code),
            title=title or self.__class__.__name__,
            status=self.http_status,
            detail=self.message,
            instance=instance or "urn:kgfoundry:error",
            code=self.code.value,
            extensions=cast("Mapping[str, JsonValue] | None", extensions if extensions else None),
        )


# [nav:anchor VectorSearchError]
class VectorSearchError(KgFoundryError):
    """Error during vector search operations.

    Extended Summary
    ----------------
    Raised when vector search operations fail. Uses error code VECTOR_SEARCH_ERROR
    and HTTP status 503 (Service Unavailable). Inherits structured error handling
    and Problem Details mapping from KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the search failure (e.g.,
        "Search failed").
    cause : Exception | None, optional
        Underlying exception that caused the search failure (e.g., RuntimeError
        from index not loaded, ValueError from invalid query vector). Stored as
        exception cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., index_type,
        query_dimension, top_k). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to VECTOR_SEARCH_ERROR
    and HTTP status is fixed to 503.

    Examples
    --------
    >>> raise VectorSearchError("Search failed", cause=RuntimeError("Index not loaded"))
    >>> # With context
    >>> raise VectorSearchError(
    ...     "Vector search failed",
    ...     cause=ValueError("Invalid query dimension"),
    ...     context={"index_type": "faiss", "query_dimension": 768, "expected_dimension": 512},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.VECTOR_SEARCH_ERROR,
            http_status=503,
            cause=cause,
            context=context,
        )


# [nav:anchor AgentCatalogSearchError]
class AgentCatalogSearchError(KgFoundryError):
    """Error during agent catalog search operations.

    Extended Summary
    ----------------
    Raised when agent catalog search operations fail. Uses error code
    AGENT_CATALOG_SEARCH_ERROR and HTTP status 503 (Service Unavailable).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the catalog search failure
        (e.g., "Catalog search failed").
    cause : Exception | None, optional
        Underlying exception that caused the catalog search failure (e.g., RuntimeError
        from index not loaded, ValueError from invalid query). Stored as exception
        cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., catalog_path,
        query_string, search_type). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to AGENT_CATALOG_SEARCH_ERROR
    and HTTP status is fixed to 503.

    Examples
    --------
    >>> raise AgentCatalogSearchError(
    ...     "Catalog search failed", cause=RuntimeError("Index not loaded")
    ... )
    >>> # With context
    >>> raise AgentCatalogSearchError(
    ...     "Search failed",
    ...     cause=ValueError("Invalid query"),
    ...     context={"catalog_path": "/path/to/catalog", "query": "test"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.AGENT_CATALOG_SEARCH_ERROR,
            http_status=503,
            cause=cause,
            context=context,
        )


# [nav:anchor CatalogSessionError]
class CatalogSessionError(KgFoundryError):
    """Error during catalog session operations (JSON-RPC, subprocess).

    Extended Summary
    ----------------
    Raised when catalog session operations fail (e.g., JSON-RPC or subprocess
    spawning). Uses error code SESSION_ERROR and HTTP status 500 (Internal Server Error).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the session operation failure
        (e.g., "Session spawn failed").
    cause : Exception | None, optional
        Underlying exception that caused the session failure (e.g., OSError from
        command not found, ProcessError from subprocess failure). Stored as exception
        cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., command_path,
        session_id, operation_type). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to SESSION_ERROR
    and HTTP status is fixed to 500.

    Examples
    --------
    >>> raise CatalogSessionError("Session spawn failed", cause=OSError("Command not found"))
    >>> # With context
    >>> raise CatalogSessionError(
    ...     "Session error",
    ...     cause=ProcessError("Subprocess failed"),
    ...     context={"command_path": "/usr/bin/catalog", "session_id": "abc123"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.SESSION_ERROR,
            http_status=500,
            cause=cause,
            context=context,
        )


# [nav:anchor CatalogLoadError]
class CatalogLoadError(KgFoundryError):
    """Error during catalog payload loading or parsing.

    Extended Summary
    ----------------
    Raised when catalog payload loading or parsing fails. Uses error code
    CATALOG_LOAD_ERROR and HTTP status 422 (Unprocessable Entity). Inherits
    structured error handling and Problem Details mapping from KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the catalog load failure
        (e.g., "Failed to parse catalog JSON").
    cause : Exception | None, optional
        Underlying exception that caused the catalog load failure (e.g., JSONDecodeError
        from invalid JSON, FileNotFoundError from missing file). Stored as exception
        cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., catalog_path,
        file_format, line_number). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to CATALOG_LOAD_ERROR
    and HTTP status is fixed to 422.

    Examples
    --------
    >>> raise CatalogLoadError(
    ...     "Failed to parse catalog JSON", cause=json.JSONDecodeError("Invalid JSON")
    ... )
    >>> # With context
    >>> raise CatalogLoadError(
    ...     "Load failed",
    ...     cause=FileNotFoundError("Catalog file missing"),
    ...     context={"catalog_path": "/path/to/catalog.json", "file_format": "json"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.CATALOG_LOAD_ERROR,
            http_status=422,
            cause=cause,
            context=context,
        )


# [nav:anchor SymbolAttachmentError]
class SymbolAttachmentError(KgFoundryError):
    """Error during symbol attachment to modules in catalog.

    Extended Summary
    ----------------
    Raised when symbol attachment to modules in the catalog fails. Uses error
    code SYMBOL_ATTACHMENT_ERROR and HTTP status 500 (Internal Server Error).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the symbol attachment failure
        (e.g., "Failed to attach symbols to module").
    cause : Exception | None, optional
        Underlying exception that caused the attachment failure (e.g., DatabaseError
        from database error, AttributeError from missing module). Stored as exception
        cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., module_name,
        symbol_count, attachment_stage). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to SYMBOL_ATTACHMENT_ERROR
    and HTTP status is fixed to 500.

    Examples
    --------
    >>> raise SymbolAttachmentError(
    ...     "Failed to attach symbols to module", cause=sqlite3.DatabaseError("Database error")
    ... )
    >>> # With context
    >>> raise SymbolAttachmentError(
    ...     "Attachment failed",
    ...     cause=AttributeError("Module not found"),
    ...     context={"module_name": "my_module", "symbol_count": 42},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.SYMBOL_ATTACHMENT_ERROR,
            http_status=500,
            cause=cause,
            context=context,
        )


# [nav:anchor ArtifactModelError]
class ArtifactModelError(KgFoundryError):
    """Error during artifact model loading or validation.

    Extended Summary
    ----------------
    Raised when artifact model loading or validation fails. Uses error code
    ARTIFACT_MODEL_ERROR and HTTP status 500 (Internal Server Error). Inherits
    structured error handling and Problem Details mapping from KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the model loading failure
        (e.g., "Failed to load artifact model").
    cause : Exception | None, optional
        Underlying exception that caused the model loading failure (e.g., FileNotFoundError
        from missing file, ImportError from missing dependency). Stored as exception
        cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., model_path,
        model_type, version). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to ARTIFACT_MODEL_ERROR
    and HTTP status is fixed to 500.

    Examples
    --------
    >>> raise ArtifactModelError(
    ...     "Failed to load artifact model", cause=FileNotFoundError("Model file missing")
    ... )
    >>> # With context
    >>> raise ArtifactModelError(
    ...     "Model load failed",
    ...     cause=ImportError("Missing dependency"),
    ...     context={"model_path": "/path/to/model.pkl", "model_type": "pydantic"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.ARTIFACT_MODEL_ERROR,
            http_status=500,
            cause=cause,
            context=context,
        )


# [nav:anchor ArtifactValidationError]
class ArtifactValidationError(KgFoundryError):
    """Error during artifact validation.

    Extended Summary
    ----------------
    Raised when artifact validation fails. Uses error code ARTIFACT_VALIDATION_ERROR
    and HTTP status 422 (Unprocessable Entity). Inherits structured error handling
    and Problem Details mapping from KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the validation failure
        (e.g., "Artifact validation failed").
    cause : Exception | None, optional
        Underlying exception that caused the validation failure (e.g., JSONDecodeError
        from invalid JSON, ValidationError from schema mismatch). Stored as exception
        cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., artifact_type,
        validation_rules, field_path). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to ARTIFACT_VALIDATION_ERROR
    and HTTP status is fixed to 422.

    Examples
    --------
    >>> raise ArtifactValidationError(
    ...     "Artifact validation failed", cause=json.JSONDecodeError("Invalid JSON")
    ... )
    >>> # With context
    >>> raise ArtifactValidationError(
    ...     "Validation failed",
    ...     cause=ValidationError("Schema mismatch"),
    ...     context={"artifact_type": "document", "field_path": "metadata.author"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.ARTIFACT_VALIDATION_ERROR,
            http_status=422,
            cause=cause,
            context=context,
        )


# [nav:anchor ArtifactSerializationError]
class ArtifactSerializationError(KgFoundryError):
    """Error during artifact serialization.

    Extended Summary
    ----------------
    Raised when artifact serialization fails. Uses error code
    ARTIFACT_SERIALIZATION_ERROR and HTTP status 500 (Internal Server Error).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the serialization failure
        (e.g., "Failed to serialize artifact").
    cause : Exception | None, optional
        Underlying exception that caused the serialization failure (e.g., TypeError
        from non-serializable object, JSONEncodeError from encoding error). Stored
        as exception cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., artifact_type,
        serialization_format, field_name). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to ARTIFACT_SERIALIZATION_ERROR
    and HTTP status is fixed to 500.

    Examples
    --------
    >>> raise ArtifactSerializationError(
    ...     "Failed to serialize artifact", cause=json.JSONDecodeError("Invalid JSON")
    ... )
    >>> # With context
    >>> raise ArtifactSerializationError(
    ...     "Serialization failed",
    ...     cause=TypeError("Object not serializable"),
    ...     context={"artifact_type": "document", "format": "json"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.ARTIFACT_SERIALIZATION_ERROR,
            http_status=500,
            cause=cause,
            context=context,
        )


# [nav:anchor ArtifactDeserializationError]
class ArtifactDeserializationError(KgFoundryError):
    """Error during artifact deserialization.

    Extended Summary
    ----------------
    Raised when artifact deserialization fails. Uses error code
    ARTIFACT_DESERIALIZATION_ERROR and HTTP status 500 (Internal Server Error).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the deserialization failure
        (e.g., "Failed to deserialize artifact").
    cause : Exception | None, optional
        Underlying exception that caused the deserialization failure (e.g., JSONDecodeError
        from invalid JSON, ValueError from corrupted data). Stored as exception cause
        for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., artifact_type,
        deserialization_format, data_source). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to ARTIFACT_DESERIALIZATION_ERROR
    and HTTP status is fixed to 500.

    Examples
    --------
    >>> raise ArtifactDeserializationError(
    ...     "Failed to deserialize artifact", cause=json.JSONDecodeError("Invalid JSON")
    ... )
    >>> # With context
    >>> raise ArtifactDeserializationError(
    ...     "Deserialization failed",
    ...     cause=ValueError("Corrupted data"),
    ...     context={"artifact_type": "document", "format": "json", "data_source": "file"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.ARTIFACT_DESERIALIZATION_ERROR,
            http_status=500,
            cause=cause,
            context=context,
        )


# [nav:anchor ArtifactDependencyError]
class ArtifactDependencyError(KgFoundryError):
    """Error during artifact dependency resolution.

    Extended Summary
    ----------------
    Raised when artifact dependency resolution fails. Uses error code
    ARTIFACT_DEPENDENCY_ERROR and HTTP status 500 (Internal Server Error).
    Inherits structured error handling and Problem Details mapping from
    KgFoundryError.

    Parameters
    ----------
    message : str
        Human-readable error message describing the dependency resolution failure
        (e.g., "Failed to resolve artifact dependency").
    cause : Exception | None, optional
        Underlying exception that caused the dependency resolution failure (e.g., ImportError
        from missing module, VersionConflictError from incompatible versions). Stored as
        exception cause for chained exception handling. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details (e.g., dependency_name,
        required_version, available_versions). Merged into Problem Details extensions.
        Defaults to None.

    Notes
    -----
    Time O(1); memory O(1) aside from message and context storage. No I/O,
    no global state. Thread-safe. The error code is fixed to ARTIFACT_DEPENDENCY_ERROR
    and HTTP status is fixed to 500.

    Examples
    --------
    >>> raise ArtifactDependencyError(
    ...     "Failed to resolve artifact dependency", cause=ImportError("Module not found")
    ... )
    >>> # With context
    >>> raise ArtifactDependencyError(
    ...     "Dependency resolution failed",
    ...     cause=ImportError("Package not installed"),
    ...     context={"dependency_name": "numpy", "required_version": ">=1.20.0"},
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize exception with message and optional parameters.

        See class docstring for detailed parameter documentation.
        """
        super().__init__(
            message,
            code=ErrorCode.ARTIFACT_DEPENDENCY_ERROR,
            http_status=500,
            cause=cause,
            context=context,
        )
