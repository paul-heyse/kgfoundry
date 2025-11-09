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
from kgfoundry_common.logging import get_logger
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.problem_details import build_problem_details

if TYPE_CHECKING:
    from kgfoundry_common.problem_details import JsonValue, ProblemDetails

logger = get_logger(__name__)

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
    if config is not None:
        if legacy_kwargs:
            unexpected = ", ".join(sorted(legacy_kwargs))
            message = f"KgFoundryError received both 'config' and legacy keyword arguments: {unexpected}"
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

    Provides structured fields (code, http_status, log_level) and RFC 9457
    Problem Details mapping. All kgfoundry exceptions inherit from this
    base class and can be converted to Problem Details JSON for HTTP responses.

    Creates a new KgFoundryError instance with the provided message
    and configuration. Resolves configuration from either the config
    parameter or legacy keyword arguments.

    Parameters
    ----------
    message : str
        Human-readable error message.
    config : KgFoundryErrorConfig | None, optional
        Structured configuration for the error including code, http_status,
        log_level, cause and context. When omitted, these fields fall back
        to sensible defaults. Defaults to None.
    **legacy_kwargs : object
        Backwards-compatible keyword arguments mirroring the fields of
        KgFoundryErrorConfig. Cannot be combined with config.

    Examples
    --------
    >>> from kgfoundry_common.errors import KgFoundryError, ErrorCode
    >>> error = KgFoundryError("Operation failed", code=ErrorCode.RUNTIME_ERROR)
    >>> assert error.code == ErrorCode.RUNTIME_ERROR
    >>> details = error.to_problem_details(instance="/api/operation")
    >>> assert details["status"] == 500
    """

    def __init__(
        self,
        message: str,
        *,
        config: KgFoundryErrorConfig | None = None,
        **legacy_kwargs: object,
    ) -> None:
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
            Formatted error string (e.g., "DownloadError[download-failed]: Failed to fetch resource").
        """
        base = f"{self.__class__.__name__}[{self.code.value}]: {self.message}"
        if self.__cause__:
            base += f" (caused by: {type(self.__cause__).__name__})"
        return base


# [nav:anchor DownloadError]
class DownloadError(KgFoundryError):
    """Error during download or resource fetch operations.

    Raised when download or resource fetch operations fail. Uses error code
    DOWNLOAD_FAILED and HTTP status 503 (Service Unavailable).

    Creates a DownloadError with DOWNLOAD_FAILED error code and HTTP status 503.

    Parameters
    ----------
    message : str
        Human-readable error message describing the download failure.
    cause : Exception | None, optional
        Underlying exception that caused the download failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise DownloadError("Failed to download PDF", cause=IOError("Connection refused"))
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when a file or resource has an unsupported MIME type. Uses error
    code UNSUPPORTED_MIME and HTTP status 415 (Unsupported Media Type).

    Creates an UnsupportedMIMEError with UNSUPPORTED_MIME error code
    and HTTP status 415.

    Parameters
    ----------
    message : str
        Human-readable error message describing the unsupported MIME type.
    cause : Exception | None, optional
        Underlying exception that caused the error. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise UnsupportedMIMEError("application/x-unknown is not supported")
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when document processing operations fail in Docling. Uses error
    code DOCLING_ERROR and HTTP status 422 (Unprocessable Entity).

    Creates a DoclingError with DOCLING_ERROR error code and HTTP status 422.

    Parameters
    ----------
    message : str
        Human-readable error message describing the processing failure.
    cause : Exception | None, optional
        Underlying exception that caused the processing failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise DoclingError("Failed to parse document", cause=ValueError("Invalid format"))
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when OCR (Optical Character Recognition) operations exceed their
    timeout limit. Uses error code OCR_TIMEOUT and HTTP status 504 (Gateway Timeout).

    Creates an OCRTimeoutError with OCR_TIMEOUT error code and HTTP status 504.

    Parameters
    ----------
    message : str
        Human-readable error message describing the timeout.
    cause : Exception | None, optional
        Underlying exception that caused the timeout. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise OCRTimeoutError("OCR timed out after 30s")
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when text chunking operations fail. Uses error code CHUNKING_ERROR
    and HTTP status 422 (Unprocessable Entity).

    Creates a ChunkingError with CHUNKING_ERROR error code and HTTP status 422.

    Parameters
    ----------
    message : str
        Human-readable error message describing the chunking failure.
    cause : Exception | None, optional
        Underlying exception that caused the chunking failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise ChunkingError("Failed to chunk document", cause=ValueError("Empty text"))
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when embedding generation operations fail. Uses error code
    EMBEDDING_ERROR and HTTP status 503 (Service Unavailable).

    Creates an EmbeddingError with EMBEDDING_ERROR error code and HTTP status 503.

    Parameters
    ----------
    message : str
        Human-readable error message describing the embedding failure.
    cause : Exception | None, optional
        Underlying exception that caused the embedding failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise EmbeddingError("Failed to generate embeddings", cause=RuntimeError("GPU unavailable"))
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when SPLADE (Sparse Lexical and Expansion) operations exceed
    available memory. Uses error code SPLADE_OOM and HTTP status 507
    (Insufficient Storage).

    Creates a SpladeOOMError with SPLADE_OOM error code and HTTP status 507.

    Parameters
    ----------
    message : str
        Human-readable error message describing the out-of-memory condition.
    cause : Exception | None, optional
        Underlying exception that caused the OOM. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise SpladeOOMError("SPLADE OOM during inference")
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when index construction operations fail (e.g., FAISS index build).
    Uses error code INDEX_BUILD_ERROR and HTTP status 500 (Internal Server Error).

    Creates an IndexBuildError with INDEX_BUILD_ERROR error code and HTTP status 500.

    Parameters
    ----------
    message : str
        Human-readable error message describing the index build failure.
    cause : Exception | None, optional
        Underlying exception that caused the build failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise IndexBuildError("Failed to build FAISS index", cause=IOError("Disk full"))
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when ontology parsing operations fail (e.g., OWL file parsing).
    Uses error code ONTOLOGY_PARSE_ERROR and HTTP status 422 (Unprocessable Entity).

    Creates an OntologyParseError with ONTOLOGY_PARSE_ERROR error code
    and HTTP status 422.

    Parameters
    ----------
    message : str
        Human-readable error message describing the parsing failure.
    cause : Exception | None, optional
        Underlying exception that caused the parsing failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise OntologyParseError("Failed to parse OWL file", cause=XMLSyntaxError("Invalid XML"))
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when linker calibration operations fail. Uses error code
    LINKER_CALIBRATION_ERROR and HTTP status 500 (Internal Server Error).

    Creates a LinkerCalibrationError with LINKER_CALIBRATION_ERROR error
    code and HTTP status 500.

    Parameters
    ----------
    message : str
        Human-readable error message describing the calibration failure.
    cause : Exception | None, optional
        Underlying exception that caused the calibration failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise LinkerCalibrationError("Calibration failed", cause=ValueError("Invalid parameters"))
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when Neo4j database operations fail. Uses error code NEO4J_ERROR
    and HTTP status 503 (Service Unavailable).

    Creates a Neo4jError with NEO4J_ERROR error code and HTTP status 503.

    Parameters
    ----------
    message : str
        Human-readable error message describing the Neo4j operation failure.
    cause : Exception | None, optional
        Underlying exception that caused the Neo4j failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise Neo4jError("Neo4j query failed", cause=ConnectionError("Database unreachable"))
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when configuration validation or loading fails. Uses error code
    CONFIGURATION_ERROR and HTTP status 500 (Internal Server Error) with
    CRITICAL log level.

    Creates a ConfigurationError with CONFIGURATION_ERROR error code,
    HTTP status 500, and CRITICAL log level.

    Parameters
    ----------
    message : str
        Human-readable error message describing the configuration failure.
    cause : Exception | None, optional
        Underlying exception that caused the configuration failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise ConfigurationError("Missing required env var: KGFOUNDRY_API_KEY")
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when runtime settings validation fails. Similar to ConfigurationError
    but includes structured validation error details. Uses error code
    CONFIGURATION_ERROR and HTTP status 500.

    Creates a SettingsError with CONFIGURATION_ERROR error code and
    HTTP status 500. Merges validation errors into context if provided.

    Parameters
    ----------
    message : str
        Human-readable error message describing the settings validation failure.
    errors : list[dict[str, object]] | None, optional
        List of validation error dictionaries with field/issue details.
        Defaults to None.
    cause : Exception | None, optional
        Underlying exception that caused the validation failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.
    """

    def __init__(
        self,
        message: str,
        *,
        errors: list[dict[str, object]] | None = None,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when JSON serialization or schema validation fails. Uses error
    code SERIALIZATION_ERROR and HTTP status 500 (Internal Server Error).

    Creates a SerializationError with SERIALIZATION_ERROR error code
    and HTTP status 500.

    Parameters
    ----------
    message : str
        Human-readable error message describing the serialization failure.
    cause : Exception | None, optional
        Underlying exception that caused the serialization failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise SerializationError("Schema validation failed", cause=ValueError("Invalid type"))
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when registry or DuckDB database operations fail. Uses error code
    REGISTRY_ERROR and HTTP status 500 (Internal Server Error).

    Creates a RegistryError with REGISTRY_ERROR error code and HTTP status 500.

    Parameters
    ----------
    message : str
        Human-readable error message describing the registry operation failure.
    cause : Exception | None, optional
        Underlying exception that caused the registry failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise RegistryError("Failed to write to registry")
    """

    def __init__(
        self,
        message: str,
        *,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when JSON deserialization, schema validation, or checksum verification
    fails. Uses error code DESERIALIZATION_ERROR and HTTP status 500 (Internal Server Error).

    Creates a DeserializationError with DESERIALIZATION_ERROR error code
    and HTTP status 500.

    Parameters
    ----------
    message : str
        Human-readable error message describing the deserialization failure.
    cause : Exception | None, optional
        Underlying exception that caused the deserialization failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise DeserializationError("Checksum mismatch", cause=ValueError("Corrupted data"))
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when schema validation fails. Includes structured validation error
    details. Uses error code SCHEMA_VALIDATION_ERROR and HTTP status 422
    (Unprocessable Entity).

    Creates a SchemaValidationError with SCHEMA_VALIDATION_ERROR error
    code and HTTP status 422. Merges validation errors into context if provided.

    Parameters
    ----------
    message : str
        Human-readable error message describing the validation failure.
    errors : list[str] | None, optional
        List of validation error messages with path and constraint details.
        Defaults to None.
    cause : Exception | None, optional
        Underlying exception that caused the validation failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise SchemaValidationError("Invalid schema", errors=["Missing field: name"])
    """

    def __init__(
        self,
        message: str,
        *,
        errors: list[str] | None = None,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    This exception indicates that a retryable operation has exhausted all
    retry attempts and should surface Problem Details with retry guidance
    information. Uses error code RETRY_EXHAUSTED and HTTP status 503.

    Creates a RetryExhaustedError with RETRY_EXHAUSTED error code and
    HTTP status 503. Stores retry metadata for Problem Details conversion.

    Parameters
    ----------
    message : str
        Human-readable error message describing the retry exhaustion.
    operation : str | None, optional
        Name of the operation that failed. Defaults to None.
    attempts : int | None, optional
        Number of retry attempts that were made. Defaults to None.
    last_error : Exception | None, optional
        The last exception that occurred before retries were exhausted.
        Defaults to None.
    retry_after_seconds : int | None, optional
        Suggested retry delay in seconds. Defaults to None.
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
            extensions=cast(
                "Mapping[str, JsonValue] | None", extensions if extensions else None
            ),
        )


# [nav:anchor VectorSearchError]
class VectorSearchError(KgFoundryError):
    """Error during vector search operations.

    Raised when vector search operations fail. Uses error code VECTOR_SEARCH_ERROR
    and HTTP status 503 (Service Unavailable).

    Creates a VectorSearchError with VECTOR_SEARCH_ERROR error code and HTTP status 503.

    Parameters
    ----------
    message : str
        Human-readable error message describing the search failure.
    cause : Exception | None, optional
        Underlying exception that caused the search failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise VectorSearchError("Search failed", cause=RuntimeError("Index not loaded"))
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when agent catalog search operations fail. Uses error code
    AGENT_CATALOG_SEARCH_ERROR and HTTP status 503 (Service Unavailable).

    Creates an AgentCatalogSearchError with AGENT_CATALOG_SEARCH_ERROR error
    code and HTTP status 503.

    Parameters
    ----------
    message : str
        Human-readable error message describing the catalog search failure.
    cause : Exception | None, optional
        Underlying exception that caused the catalog search failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise AgentCatalogSearchError(
    ...     "Catalog search failed", cause=RuntimeError("Index not loaded")
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when catalog session operations fail (e.g., JSON-RPC or subprocess
    spawning). Uses error code SESSION_ERROR and HTTP status 500 (Internal Server Error).

    Creates a CatalogSessionError with SESSION_ERROR error code and HTTP status 500.

    Parameters
    ----------
    message : str
        Human-readable error message describing the session operation failure.
    cause : Exception | None, optional
        Underlying exception that caused the session failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise CatalogSessionError("Session spawn failed", cause=OSError("Command not found"))
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when catalog payload loading or parsing fails. Uses error code
    CATALOG_LOAD_ERROR and HTTP status 422 (Unprocessable Entity).

    Creates a CatalogLoadError with CATALOG_LOAD_ERROR error code and HTTP status 422.

    Parameters
    ----------
    message : str
        Human-readable error message describing the catalog load failure.
    cause : Exception | None, optional
        Underlying exception that caused the catalog load failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise CatalogLoadError(
    ...     "Failed to parse catalog JSON", cause=json.JSONDecodeError("Invalid JSON")
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when symbol attachment to modules in the catalog fails. Uses error
    code SYMBOL_ATTACHMENT_ERROR and HTTP status 500 (Internal Server Error).

    Creates a SymbolAttachmentError with SYMBOL_ATTACHMENT_ERROR error
    code and HTTP status 500.

    Parameters
    ----------
    message : str
        Human-readable error message describing the symbol attachment failure.
    cause : Exception | None, optional
        Underlying exception that caused the attachment failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise SymbolAttachmentError(
    ...     "Failed to attach symbols to module", cause=sqlite3.DatabaseError("Database error")
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when artifact model loading or validation fails. Uses error code
    ARTIFACT_MODEL_ERROR and HTTP status 500 (Internal Server Error).

    Creates an ArtifactModelError with ARTIFACT_MODEL_ERROR error code
    and HTTP status 500.

    Parameters
    ----------
    message : str
        Human-readable error message describing the model loading failure.
    cause : Exception | None, optional
        Underlying exception that caused the model loading failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise ArtifactModelError(
    ...     "Failed to load artifact model", cause=FileNotFoundError("Model file missing")
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when artifact validation fails. Uses error code ARTIFACT_VALIDATION_ERROR
    and HTTP status 422 (Unprocessable Entity).

    Creates an ArtifactValidationError with ARTIFACT_VALIDATION_ERROR error
    code and HTTP status 422.

    Parameters
    ----------
    message : str
        Human-readable error message describing the validation failure.
    cause : Exception | None, optional
        Underlying exception that caused the validation failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise ArtifactValidationError(
    ...     "Artifact validation failed", cause=json.JSONDecodeError("Invalid JSON")
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when artifact serialization fails. Uses error code
    ARTIFACT_SERIALIZATION_ERROR and HTTP status 500 (Internal Server Error).

    Creates an ArtifactSerializationError with ARTIFACT_SERIALIZATION_ERROR
    error code and HTTP status 500.

    Parameters
    ----------
    message : str
        Human-readable error message describing the serialization failure.
    cause : Exception | None, optional
        Underlying exception that caused the serialization failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise ArtifactSerializationError(
    ...     "Failed to serialize artifact", cause=json.JSONDecodeError("Invalid JSON")
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when artifact deserialization fails. Uses error code
    ARTIFACT_DESERIALIZATION_ERROR and HTTP status 500 (Internal Server Error).

    Creates an ArtifactDeserializationError with ARTIFACT_DESERIALIZATION_ERROR
    error code and HTTP status 500.

    Parameters
    ----------
    message : str
        Human-readable error message describing the deserialization failure.
    cause : Exception | None, optional
        Underlying exception that caused the deserialization failure. Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise ArtifactDeserializationError(
    ...     "Failed to deserialize artifact", cause=json.JSONDecodeError("Invalid JSON")
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
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

    Raised when artifact dependency resolution fails. Uses error code
    ARTIFACT_DEPENDENCY_ERROR and HTTP status 500 (Internal Server Error).

    Creates an ArtifactDependencyError with ARTIFACT_DEPENDENCY_ERROR error
    code and HTTP status 500.

    Parameters
    ----------
    message : str
        Human-readable error message describing the dependency resolution failure.
    cause : Exception | None, optional
        Underlying exception that caused the dependency resolution failure.
        Defaults to None.
    context : Mapping[str, object] | None, optional
        Additional context dictionary for error details. Defaults to None.

    Examples
    --------
    >>> raise ArtifactDependencyError(
    ...     "Failed to resolve artifact dependency", cause=ImportError("Module not found")
    ... )
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(
            message,
            code=ErrorCode.ARTIFACT_DEPENDENCY_ERROR,
            http_status=500,
            cause=cause,
            context=context,
        )
