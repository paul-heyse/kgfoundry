"""Runtime settings with typed configuration and fail-fast validation.

This module provides RuntimeSettings (pydantic_settings.BaseSettings) with
nested models, environment variable support, and fail-fast Problem Details
on validation errors.

Examples
--------
>>> from kgfoundry_common.settings import RuntimeSettings
>>> # Fails fast if required env vars are missing
>>> settings = RuntimeSettings()  # Raises ConfigurationError if required vars missing
>>> assert settings.search_api_url is not None
"""

# [nav:section public-api]

from __future__ import annotations

from typing import Any, ClassVar, cast

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from kgfoundry_common.errors import SettingsError
from kgfoundry_common.logging import get_logger
from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "FaissConfig",
    "KgFoundrySettings",
    "ObservabilityConfig",
    "RuntimeSettings",
    "SearchConfig",
    "SparseEmbeddingConfig",
    "load_settings",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))

logger = get_logger(__name__)


# [nav:anchor SearchConfig]
class SearchConfig(BaseSettings):
    """Configuration for the hybrid search service (``KGFOUNDRY_SEARCH_*``)."""

    model_config = SettingsConfigDict(env_prefix="KGFOUNDRY_SEARCH_", extra="forbid")

    api_url: str | None = Field(
        default=None,
        description="Search API base URL (required if search features are used)",
    )
    k: int = Field(default=10, description="Default number of results to return")
    dense_candidates: int = Field(
        default=200, description="Number of dense candidates for hybrid search"
    )
    sparse_candidates: int = Field(
        default=200, description="Number of sparse candidates for hybrid search"
    )
    rrf_k: int = Field(default=60, description="Reciprocal Rank Fusion parameter")
    sparse_backend: str = Field(
        default="lucene", description="Sparse backend type ('lucene' or 'pure')"
    )
    kg_boosts_direct: float = Field(default=0.08, description="Direct KG boost weight")
    kg_boosts_one_hop: float = Field(
        default=0.04, description="One-hop KG boost weight"
    )
    validate_responses: bool = Field(
        default=False,
        description="Enable response schema validation (dev/staging only)",
    )


# [nav:anchor ObservabilityConfig]
class ObservabilityConfig(BaseSettings):
    """Logging and telemetry toggles (``KGFOUNDRY_*`` namespace)."""

    model_config = SettingsConfigDict(env_prefix="KGFOUNDRY_", extra="forbid")

    log_level: str = Field(
        default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )
    metrics_enabled: bool = Field(
        default=True, description="Enable Prometheus metrics export"
    )
    traces_enabled: bool = Field(
        default=False, description="Enable OpenTelemetry tracing"
    )
    metrics_port: int = Field(
        default=9090, description="Port for Prometheus metrics endpoint"
    )


# [nav:anchor SparseEmbeddingConfig]
class SparseEmbeddingConfig(BaseSettings):
    """Sparse embedding configuration (``KGFOUNDRY_SPARSE_EMBEDDING_*``)."""

    model_config = SettingsConfigDict(
        env_prefix="KGFOUNDRY_SPARSE_EMBEDDING_", extra="forbid"
    )

    bm25_index_dir: str = Field(
        default="./_indices/bm25", description="BM25 index directory path"
    )
    bm25_k1: float = Field(default=0.9, description="BM25 k1 parameter")
    bm25_b: float = Field(default=0.4, description="BM25 b parameter")
    splade_index_dir: str = Field(
        default="./_indices/splade_impact", description="SPLADE index directory path"
    )
    splade_query_encoder: str = Field(
        default="naver/splade-v3-distilbert",
        description="SPLADE query encoder model name",
    )


# [nav:anchor FaissConfig]
class FaissConfig(BaseSettings):
    """FAISS index configuration (``KGFOUNDRY_FAISS_*`` namespace)."""

    model_config = SettingsConfigDict(env_prefix="KGFOUNDRY_FAISS_", extra="forbid")

    gpu: bool = Field(default=True, description="Enable GPU acceleration")
    cuvs: bool = Field(default=True, description="Enable cuVS support")
    index_factory: str = Field(
        default="OPQ64,IVF8192,PQ64", description="FAISS index factory string"
    )
    nprobe: int = Field(default=64, description="Number of probes for IVF indexes")
    index_path: str = Field(
        default="./_indices/faiss/shard_000.idx", description="FAISS index file path"
    )


# [nav:anchor RuntimeSettings]
class RuntimeSettings(BaseSettings):
    """Aggregate runtime configuration loaded from environment variables.

    Initialises settings with fail-fast validation. Settings are loaded from
    environment variables with the KGFOUNDRY_ prefix and validated according
    to the nested configuration schemas.

    Parameters
    ----------
    **overrides : object
        Settings overrides to apply during initialization.

    Attributes
    ----------
    model_config : ClassVar[SettingsConfigDict]
        Pydantic model configuration dictionary (class variable).
    search : SearchConfig
        Search service configuration.
    observability : ObservabilityConfig
        Observability configuration.
    sparse_embedding : SparseEmbeddingConfig
        Sparse embedding configuration.
    faiss : FaissConfig
        FAISS index configuration.

    Raises
    ------
    SettingsError
        If settings validation fails.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="KGFOUNDRY_",
        env_nested_delimiter="__",
        extra="forbid",
        case_sensitive=False,
    )

    search: SearchConfig = Field(
        default_factory=SearchConfig, description="Search service configuration"
    )
    observability: ObservabilityConfig = Field(
        default_factory=ObservabilityConfig, description="Observability configuration"
    )
    sparse_embedding: SparseEmbeddingConfig = Field(
        default_factory=SparseEmbeddingConfig,
        description="Sparse embedding configuration",
    )
    faiss: FaissConfig = Field(
        default_factory=FaissConfig, description="FAISS index configuration"
    )

    def __init__(self, **overrides: object) -> None:
        try:
            cast_overrides: dict[str, Any] = {
                key: cast("Any", value) for key, value in overrides.items()
            }
            super().__init__(**cast_overrides)
        except Exception as exc:
            # Convert Pydantic validation errors to SettingsError with Problem Details
            msg = f"Configuration validation failed: {exc}"
            logger.exception(
                "Settings validation failed",
                extra={"error": str(exc), "error_type": type(exc).__name__},
            )
            raise SettingsError(
                msg,
                cause=exc,
                context={"validation_error": str(exc)},
            ) from exc


# Type alias for backward compatibility
# [nav:anchor KgFoundrySettings]
KgFoundrySettings = RuntimeSettings


# [nav:anchor load_settings]
def load_settings(**overrides: object) -> KgFoundrySettings:
    """Load :class:`RuntimeSettings` with optional overrides.

    Parameters
    ----------
    **overrides : object
        Settings overrides to apply.

    Returns
    -------
    KgFoundrySettings
        Loaded settings instance.

    Raises
    ------
    SettingsError
        If settings validation fails.
    """
    try:
        return RuntimeSettings(**overrides)
    except SettingsError:
        # Re-raise SettingsError as-is
        raise
    except Exception as exc:
        # Convert any other validation errors to SettingsError
        msg = f"Failed to load settings: {exc}"
        logger.exception(
            "Settings loading failed",
            extra={"error": str(exc), "error_type": type(exc).__name__},
        )
        raise SettingsError(
            msg,
            cause=exc,
            context={"validation_error": str(exc)},
        ) from exc
