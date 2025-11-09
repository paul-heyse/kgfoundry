"""Error code registry and type URIs for Problem Details.

This module defines stable error codes and type URIs used in RFC 9457
Problem Details responses. Codes and URIs are frozen after initial release
to maintain backward compatibility.

Examples
--------
>>> from kgfoundry_common.errors.codes import ErrorCode, get_type_uri
>>> code = ErrorCode.DOWNLOAD_FAILED
>>> type_uri = get_type_uri(code)
>>> assert type_uri == "https://kgfoundry.dev/problems/download-failed"
"""

# [nav:section public-api]

from __future__ import annotations

from enum import StrEnum
from typing import Final

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "BASE_TYPE_URI",
    "ErrorCode",
    "get_type_uri",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor BASE_TYPE_URI]
BASE_TYPE_URI: Final[str] = "https://kgfoundry.dev/problems"


# [nav:anchor ErrorCode]
class ErrorCode(StrEnum):
    """Stable error codes for kgfoundry exceptions.

    Enumeration of error codes used in RFC 9457 Problem Details responses.
    Codes follow kebab-case naming and remain stable across releases to ensure
    backward compatibility.

    Error codes are organized by category:
    - 1xx: Download & Ingestion
    - 2xx: Document Processing
    - 3xx: Embedding & Indexing
    - 4xx: Search & Retrieval
    - 5xx: Configuration & Runtime
    - 6xx: Knowledge Graph & Ontology
    - 7xx: Serialization & Persistence

    Attributes
    ----------
    DOWNLOAD_FAILED
        Download operation failed.
    UNSUPPORTED_MIME
        Unsupported MIME type encountered.
    INVALID_INPUT
        Invalid input provided.
    DOCLING_ERROR
        Document processing error via Docling.
    OCR_TIMEOUT
        OCR operation timed out.
    CHUNKING_ERROR
        Document chunking failed.
    EMBEDDING_ERROR
        Embedding generation failed.
    INDEX_BUILD_ERROR
        Index construction failed.
    SPLADE_OOM
        SPLADE encoding out of memory.
    RETRY_EXHAUSTED
        All retry attempts exhausted.
    SEARCH_INDEX_MISSING
        Search index not found.
    SEARCH_QUERY_INVALID
        Invalid search query.
    SEARCH_TIMEOUT
        Search operation timed out.
    VECTOR_SEARCH_ERROR
        Vector search operation failed.
    AGENT_CATALOG_SEARCH_ERROR
        Agent catalog search failed.
    CATALOG_LOAD_ERROR
        Catalog loading failed.
    SYMBOL_ATTACHMENT_ERROR
        Symbol attachment failed.
    CONFIGURATION_ERROR
        Configuration error.
    RUNTIME_ERROR
        Runtime error occurred.
    RESOURCE_UNAVAILABLE
        Required resource unavailable.
    SESSION_ERROR
        Session management error.
    FILE_OPERATION_ERROR
        File operation failed.
    GIT_OPERATION_ERROR
        Git operation failed.
    INVALID_PARAMETER
        Invalid parameter value provided.
    PATH_OUTSIDE_REPOSITORY
        Path is outside the repository root.
    PATH_NOT_DIRECTORY
        Path does not refer to a directory.
    PATH_NOT_FOUND
        Path does not exist.
    NOT_IMPLEMENTED
        Feature is not implemented.
    ONTOLOGY_PARSE_ERROR
        Ontology parsing failed.
    LINKER_CALIBRATION_ERROR
        Linker calibration failed.
    NEO4J_ERROR
        Neo4j database error.
    SERIALIZATION_ERROR
        Data serialization failed.
    DESERIALIZATION_ERROR
        Data deserialization failed.
    SCHEMA_VALIDATION_ERROR
        Schema validation failed.
    REGISTRY_ERROR
        Registry operation failed.
    ARTIFACT_MODEL_ERROR
        Artifact model error.
    ARTIFACT_VALIDATION_ERROR
        Artifact validation failed.
    ARTIFACT_SERIALIZATION_ERROR
        Artifact serialization failed.
    ARTIFACT_DESERIALIZATION_ERROR
        Artifact deserialization failed.
    ARTIFACT_DEPENDENCY_ERROR
        Artifact dependency error.

    Notes
    -----
    Enum members are instances of ErrorCode and can be used as string values
    (since ErrorCode inherits from StrEnum). Common enum members include:
    DOWNLOAD_FAILED, DOCLING_ERROR, EMBEDDING_ERROR, SEARCH_INDEX_MISSING,
    CONFIGURATION_ERROR, SERIALIZATION_ERROR, and others.

    Examples
    --------
    >>> code = ErrorCode.DOWNLOAD_FAILED
    >>> assert code == "download-failed"
    >>> assert isinstance(code, ErrorCode)
    """

    # Download & Ingestion (1xx)
    DOWNLOAD_FAILED = "download-failed"
    UNSUPPORTED_MIME = "unsupported-mime"
    INVALID_INPUT = "invalid-input"

    # Document Processing (2xx)
    DOCLING_ERROR = "docling-error"
    OCR_TIMEOUT = "ocr-timeout"
    CHUNKING_ERROR = "chunking-error"

    # Embedding & Indexing (3xx)
    EMBEDDING_ERROR = "embedding-error"
    INDEX_BUILD_ERROR = "index-build-error"
    SPLADE_OOM = "splade-oom"
    RETRY_EXHAUSTED = "retry-exhausted"

    # Search & Retrieval (4xx)
    SEARCH_INDEX_MISSING = "search-index-missing"
    SEARCH_QUERY_INVALID = "search-query-invalid"
    SEARCH_TIMEOUT = "search-timeout"
    VECTOR_SEARCH_ERROR = "vector-search-error"
    AGENT_CATALOG_SEARCH_ERROR = "agent-catalog-search-error"
    CATALOG_LOAD_ERROR = "catalog-load-error"
    SYMBOL_ATTACHMENT_ERROR = "symbol-attachment-error"

    # Configuration & Runtime (5xx)
    CONFIGURATION_ERROR = "configuration-error"
    RUNTIME_ERROR = "runtime-error"
    RESOURCE_UNAVAILABLE = "resource-unavailable"
    SESSION_ERROR = "session-error"
    FILE_OPERATION_ERROR = "file-operation-error"
    GIT_OPERATION_ERROR = "git-operation-error"
    INVALID_PARAMETER = "invalid-parameter"
    PATH_OUTSIDE_REPOSITORY = "path-outside-repo"
    PATH_NOT_DIRECTORY = "path-not-directory"
    PATH_NOT_FOUND = "path-not-found"
    NOT_IMPLEMENTED = "not-implemented"

    # Knowledge Graph & Ontology (6xx)
    ONTOLOGY_PARSE_ERROR = "ontology-parse-error"
    LINKER_CALIBRATION_ERROR = "linker-calibration-error"
    NEO4J_ERROR = "neo4j-error"

    # Serialization & Persistence (7xx)
    SERIALIZATION_ERROR = "serialization-error"
    DESERIALIZATION_ERROR = "deserialization-error"
    SCHEMA_VALIDATION_ERROR = "schema-validation-error"
    REGISTRY_ERROR = "registry-error"
    ARTIFACT_MODEL_ERROR = "artifact-model-error"
    ARTIFACT_VALIDATION_ERROR = "artifact-validation-error"
    ARTIFACT_SERIALIZATION_ERROR = "artifact-serialization-error"
    ARTIFACT_DESERIALIZATION_ERROR = "artifact-deserialization-error"
    ARTIFACT_DEPENDENCY_ERROR = "artifact-dependency-error"

    def __str__(self) -> str:
        """Return the code value as a string.

        Returns
        -------
        str
            The error code value (e.g., "download-failed").
        """
        return self.value


# [nav:anchor get_type_uri]
def get_type_uri(code: ErrorCode) -> str:
    """Get the RFC 9457 type URI for an error code.

    Constructs a complete type URI by combining BASE_TYPE_URI with the
    error code value. Type URIs are used in Problem Details responses
    to uniquely identify error types.

    Parameters
    ----------
    code : ErrorCode
        Error code enum value.

    Returns
    -------
    str
        Complete type URI (e.g., "https://kgfoundry.dev/problems/download-failed").

    Examples
    --------
    >>> get_type_uri(ErrorCode.DOWNLOAD_FAILED)
    'https://kgfoundry.dev/problems/download-failed'
    """
    return f"{BASE_TYPE_URI}/{code.value}"
