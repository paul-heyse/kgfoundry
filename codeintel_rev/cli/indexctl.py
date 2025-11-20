"""Typer CLI for managing index lifecycle operations."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, cast

import click
import duckdb as duckdb_mod
import numpy as np
import typer

from codeintel_rev.config import AppConfig, load_app_config
from codeintel_rev.config.paths import ResolvedPaths, resolve_application_paths
from codeintel_rev.embeddings import EmbeddingProvider, get_embedding_provider
from codeintel_rev.errors import RuntimeLifecycleError
from codeintel_rev.eval.hybrid_evaluator import EvalConfig, HybridPoolEvaluator
from codeintel_rev.indexing.cast_chunker import Chunk
from codeintel_rev.indexing.index_lifecycle import (
    IndexAssets,
    IndexLifecycleManager,
    collect_asset_attrs,
)
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogConfig
from codeintel_rev.io.duckdb_manager import DuckDBConfig, DuckDBManager
from codeintel_rev.io.faiss_manager import (
    FAISSManager,
    RefineSearchConfig,
    SearchRuntimeOverrides,
)
from codeintel_rev.io.parquet_store import (
    ParquetWriteOptions,
    extract_embeddings,
    read_chunks_parquet,
    write_chunks_parquet,
)
from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.typing import NDArrayF32

try:  # pragma: no cover - optional dependency
    import pyarrow.parquet as pyarrow_parquet
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pyarrow_parquet = None

app = typer.Typer(help="Manage versioned FAISS/DuckDB/SCIP assets.", no_args_is_help=True)
DEFAULT_XTR_ORACLE = False
embeddings_app = typer.Typer(help="Embedding lifecycle commands.", no_args_is_help=True)
app.add_typer(embeddings_app, name="embeddings")


@lru_cache(maxsize=1)
def _cached_app_config() -> AppConfig:
    """Load and cache immutable application configuration.

    Returns
    -------
    AppConfig
        Cached immutable configuration derived from env/file sources.
    """
    return load_app_config(file=os.environ.get("CODEINTEL_CONFIG_FILE"))


def _get_app_config() -> AppConfig:
    """Retrieve application configuration from the CLI context factory.

    Returns
    -------
    AppConfig
        Immutable configuration provided by the CLI context.
    """
    return _cli_context().app_config_factory()


def _default_faiss_manager_factory(
    app_config: AppConfig,
    index_override: Path | None,
) -> FAISSManager:
    """Create and load a FAISS manager instance from AppConfig data.

    This function creates a FAISSManager instance using AppConfig configuration
    and optional index path override. The manager is configured with vector
    dimension and nlist parameters from AppConfig, and the CPU index is loaded
    immediately for use.

    Parameters
    ----------
    app_config : AppConfig
        Immutable configuration containing FAISS vector dimension and nlist
        parameters alongside default index paths.
    index_override : Path | None
        Optional path override for the FAISS index file. If provided, this
        path is used instead of the configured default. The path is expanded and
        resolved to absolute form.

    Returns
    -------
    FAISSManager
        Configured FAISS manager instance with CPU index loaded. The manager
        is ready for search operations and index management.

    Notes
    -----
    FAISS manager creation enables index access for CLI commands that need to
    interact with FAISS indexes. The function handles path resolution and
    index loading, providing a ready-to-use manager instance. The CPU index
    is loaded immediately to ensure it's available for operations.
    """
    index_cfg = app_config.index
    default_index = app_config.faiss.index_path
    index_path = (index_override or default_index).expanduser().resolve()
    nlist = int(index_cfg.nlist or index_cfg.faiss_nlist)
    manager = FAISSManager(
        index_path=index_path,
        vec_dim=index_cfg.vec_dim,
        nlist=nlist,
    )
    manager.load_cpu_index()
    return manager


def _default_duckdb_catalog_factory(
    app_config: AppConfig,
    path_override: Path | None,
) -> DuckDBCatalog:
    """Create and configure a DuckDB catalog instance from AppConfig.

    This function creates a DuckDBCatalog instance using AppConfig configuration
    and optional path override. The catalog is configured with database path,
    vectors directory, repository root, materialization settings, and FAISS
    ID map path.

    Parameters
    ----------
    app_config : AppConfig
        Immutable configuration providing catalog defaults and materialization
        settings.
    path_override : Path | None
        Optional path override for the DuckDB catalog file. If provided, this
        path is used instead of the configured default. The path is expanded and
        resolved to absolute form.

    Returns
    -------
    DuckDBCatalog
        Configured DuckDB catalog instance ready for querying chunk metadata
        and structure annotations. The catalog is configured with all necessary
        paths and options from the application configuration.

    Notes
    -----
    DuckDB catalog creation enables metadata access for CLI commands that need
    to query chunk information, structure annotations, and embedding metadata.
    The function handles path resolution and catalog configuration, providing a
    ready-to-use catalog instance with proper ID map and materialization settings.
    """
    paths = resolve_application_paths(app_config)
    db_path = (path_override or paths.duckdb_path).expanduser().resolve()
    catalog_cfg = DuckDBCatalogConfig(
        db_path=db_path,
        vectors_dir=paths.vectors_dir,
        repo_root=paths.repo_root,
        idmap_path=paths.faiss_idmap_path,
        materialize=app_config.index.duckdb_materialize,
        log_queries=getattr(app_config.duckdb, "log_queries", False),
    )
    catalog = DuckDBCatalog(
        catalog_cfg.db_path,
        catalog_cfg.vectors_dir,
        materialize=catalog_cfg.materialize,
        repo_root=catalog_cfg.repo_root,
    )
    catalog.set_idmap_path(catalog_cfg.idmap_path)
    return catalog


def _duckdb_manager_config(app_config: AppConfig) -> DuckDBConfig:
    """Translate AppConfig DuckDB settings into DuckDBManager configuration.

    Parameters
    ----------
    app_config : AppConfig
        Application configuration containing DuckDB settings.

    Returns
    -------
    DuckDBConfig
        DuckDB manager configuration derived from app_config.
    """
    defaults = DuckDBConfig()
    duck_cfg = app_config.duckdb
    return DuckDBConfig(
        threads=duck_cfg.threads if duck_cfg.threads is not None else defaults.threads,
        enable_object_cache=duck_cfg.object_cache,
        log_queries=defaults.log_queries,
        pool_size=duck_cfg.pool_size,
    )


def _default_duckdb_embedding_dim(catalog: DuckDBCatalog) -> int:
    """Determine embedding dimension from DuckDB catalog.

    This function queries the DuckDB catalog to determine the embedding dimension
    by fetching a sample embedding from the chunks table and computing its length.
    The function handles missing or invalid embeddings gracefully by returning 0.

    Parameters
    ----------
    catalog : DuckDBCatalog
        DuckDB catalog instance to query for embedding dimension. The catalog
        must have a chunks table with an embedding column.

    Returns
    -------
    int
        Embedding dimension (number of elements in embedding vector) if a valid
        embedding is found, otherwise 0. Returns 0 if no chunks exist, embeddings
        are None, or dimension cannot be determined.

    Notes
    -----
    Embedding dimension detection enables validation and compatibility checking
    by determining the expected vector size from stored embeddings. The function
    samples the first chunk's embedding to infer dimension, assuming all embeddings
    have the same dimension. This supports embedding validation and FAISS index
    compatibility checks.
    """
    with catalog.connection() as conn:
        row = conn.execute("SELECT embedding FROM chunks LIMIT 1").fetchone()
    if not row or row[0] is None:
        return 0
    embedding = row[0]
    try:
        return len(embedding)
    except TypeError:
        return 0


def _default_count_idmap_rows(path: Path) -> int:
    """Count rows in FAISS ID map Parquet file.

    This function reads Parquet file metadata to determine the number of rows
    in a FAISS ID map file without loading the entire file. The function
    requires pyarrow to be available for Parquet metadata access.

    Parameters
    ----------
    path : Path
        Path to FAISS ID map Parquet file. The file must exist and be a valid
        Parquet file for row counting to succeed.

    Returns
    -------
    int
        Number of rows in the Parquet file if file exists and metadata is
        available, otherwise 0. Returns 0 if file doesn't exist or metadata
        is None.

    Raises
    ------
    RuntimeError
        Raised when pyarrow is not available, which is required for Parquet
        metadata access. The error message indicates that pyarrow must be
        installed to inspect ID map sidecars.

    Notes
    -----
    ID map row counting enables validation and statistics reporting by determining
    the number of ID mappings without loading the entire file. The function uses
    Parquet metadata for efficient row counting, avoiding full file reads. This
    supports index validation and compatibility checks between FAISS indexes and
    ID maps.
    """
    if not path.exists():
        return 0
    if pyarrow_parquet is None:
        msg = "pyarrow is required to inspect the ID map sidecar"
        raise RuntimeError(msg)
    metadata = pyarrow_parquet.ParquetFile(path).metadata
    return metadata.num_rows if metadata is not None else 0


def _default_embedding_provider_factory(app_config: AppConfig) -> EmbeddingProvider:
    """Create an embedding provider instance from the active configuration.

    Parameters
    ----------
    app_config : AppConfig
        Immutable configuration providing embedding/vLLM parameters and
        index dimensionality.

    Returns
    -------
    EmbeddingProvider
        Configured embedding provider instance ready for generating embeddings.
    """
    index_cfg = app_config.index
    return get_embedding_provider(
        embeddings=app_config.embeddings,
        vec_dim=index_cfg.vec_dim,
        vllm=app_config.vllm,
    )


@dataclass(slots=True, frozen=True)
class IndexctlCliContext:
    """Dependency injection context for the indexctl CLI.

    Attributes
    ----------
    app_config_factory : Callable[[], AppConfig]
        Factory function that returns immutable application configuration.
        Typically uses caching to avoid repeated file I/O.
    faiss_manager_factory : Callable[[AppConfig, Path | None], FAISSManager]
        Factory function that creates FAISS manager instances from AppConfig
        and optional index path override.
    duckdb_catalog_factory : Callable[[AppConfig, Path | None], DuckDBCatalog]
        Factory function that creates DuckDB catalog instances from AppConfig
        and optional path override.
    duckdb_dim_resolver : Callable[[DuckDBCatalog], int]
        Function that determines embedding dimension from a DuckDB catalog
        by querying sample embeddings.
    idmap_row_counter : Callable[[Path], int]
        Function that counts rows in a FAISS ID map Parquet file without
        loading the entire file.
    embedding_provider_factory : Callable[[AppConfig], EmbeddingProvider]
        Factory function that creates embedding provider instances from
        application configuration.
    """

    app_config_factory: Callable[[], AppConfig]
    faiss_manager_factory: Callable[[AppConfig, Path | None], FAISSManager]
    duckdb_catalog_factory: Callable[[AppConfig, Path | None], DuckDBCatalog]
    duckdb_dim_resolver: Callable[[DuckDBCatalog], int]
    idmap_row_counter: Callable[[Path], int]
    embedding_provider_factory: Callable[[AppConfig], EmbeddingProvider]

    @classmethod
    def production(cls) -> IndexctlCliContext:
        """Return the production CLI context.

        Returns
        -------
        IndexctlCliContext
            Context configured with the production factories.
        """
        return cls(
            app_config_factory=_cached_app_config,
            faiss_manager_factory=_default_faiss_manager_factory,
            duckdb_catalog_factory=_default_duckdb_catalog_factory,
            duckdb_dim_resolver=_default_duckdb_embedding_dim,
            idmap_row_counter=_default_count_idmap_rows,
            embedding_provider_factory=_default_embedding_provider_factory,
        )


_DEFAULT_CONTEXT = IndexctlCliContext.production()


def _cli_context(ctx: click.Context | None = None) -> IndexctlCliContext:
    """Retrieve or create indexctl CLI context from Click context.

    This function retrieves the IndexctlCliContext from the Click context state,
    creating and caching it if it doesn't exist. The context provides dependency
    injection for CLI commands, enabling testing with mock factories. The function
    handles both explicit context passing and implicit context retrieval from
    Click's current context.

    Parameters
    ----------
    ctx : click.Context | None, optional
        Optional Click context to retrieve context from. If None, attempts to
        retrieve the current Click context using click.get_current_context.
        If no context is available, returns the default production context.

    Returns
    -------
    IndexctlCliContext
        CLI context object containing factories for FAISS manager, DuckDB catalog,
        embedding provider, and other dependencies. The context is cached in the
        Click context state after first creation, ensuring consistent context
        usage across a command invocation.

    Notes
    -----
    CLI context retrieval enables dependency injection for CLI commands, allowing
    commands to use configurable factories for FAISS managers, DuckDB catalogs,
    and embedding providers. The context is cached in the Click context state to
    avoid repeated creation and ensure consistent behavior throughout command
    execution. The function gracefully handles missing contexts by returning the
    default production context.
    """
    active = ctx or click.get_current_context(silent=True)
    if active is None:
        return _DEFAULT_CONTEXT
    state = active.ensure_object(dict)
    existing = state.get("cli_context")
    if isinstance(existing, IndexctlCliContext):
        return existing
    state["cli_context"] = _DEFAULT_CONTEXT
    return _DEFAULT_CONTEXT


RootOption = Annotated[Path | None, typer.Option("--root", help="Index lifecycle root directory.")]
ExtraOption = Annotated[
    list[str],
    typer.Option(
        "--extra",
        help="Optional channel entry of the form name=/path (e.g., bm25=/tmp/bm25).",
        default_factory=list,
    ),
]
VersionArg = Annotated[str, typer.Argument(help="Version identifier.")]
PathArg = Annotated[Path, typer.Argument(help="Path to an asset on disk.")]
QueriesArg = Annotated[
    Path,
    typer.Argument(help="Path to newline-delimited queries for smoke tests."),
]
IndexOption = Annotated[Path | None, typer.Option("--index", help="Path to FAISS index file.")]
AssetsArg = Annotated[
    tuple[Path, Path, Path],
    typer.Argument(
        ...,
        help="Primary assets (faiss.index catalog.duckdb code.scip).",
        metavar="FAISS_INDEX DUCKDB_PATH SCIP_INDEX",
    ),
]
SidecarOption = Annotated[
    list[str],
    typer.Option(
        "--sidecar",
        help="Optional sidecar entry of the form name=/path (faiss_idmap, tuning).",
        default_factory=list,
    ),
]
VersionOption = Annotated[
    str | None,
    typer.Option("--version", help="Explicit version directory (defaults to CURRENT)."),
]
ParquetOption = Annotated[
    Path | None, typer.Option("--parquet", help="Embeddings Parquet override.")
]
OutputOption = Annotated[Path | None, typer.Option("--output", help="Output Parquet path.")]
ChunkBatchOption = Annotated[
    int,
    typer.Option("--chunk-size", min=1, help="DuckDB rows fetched per embedding batch."),
]
SampleOption = Annotated[int, typer.Option("--samples", min=1, help="Rows sampled for validation.")]
EpsilonOption = Annotated[
    float,
    typer.Option("--epsilon", min=0.0, help="Maximum allowed cosine drift during validation."),
]
SweepMode = Literal["quick", "full"]
_PRIMARY_ASSET_COUNT = 3
_TUNE_OVERRIDE_CASTERS: dict[str, Callable[[str], float | int]] = {
    "nprobe": int,
    "ef_search": int,
    "quantizer_ef_search": int,
    "k_factor": float,
}
_SWEEP_MODE_BY_NAME: dict[str, SweepMode] = {
    "quick": "quick",
    "full": "full",
}


@dataclass(slots=True, frozen=True)
class SearchCommandParams:
    """Typed container for CLI-provided semantic search arguments.

    Attributes
    ----------
    queries : Path
        File path containing queries to search (JSONL format).
    k : int
        Maximum number of results to return per query. Must be positive.
    dry_run : bool
        Whether to perform a dry run without executing searches.
    nprobe : int | None
        Optional FAISS nprobe parameter override. None means use defaults.
        Must be positive if specified.
    index : Path | None
        Optional FAISS index file path override. None means use configured path.
    duckdb : Path | None
        Optional DuckDB catalog file path override. None means use configured path.
    """

    queries: Path
    k: int
    dry_run: bool
    nprobe: int | None
    index: Path | None
    duckdb: Path | None


_SWEEP_FLAG = "--sweep"
SWEEP_OPTION = typer.Option(
    _SWEEP_FLAG,
    case_sensitive=False,
    help="Autotune sweep mode (quick/full).",
)
IdMapOption = Annotated[Path, typer.Option("--idmap", help="Path to FAISS ID map Parquet.")]
DuckOption = Annotated[Path | None, typer.Option("--duckdb", help="Path to DuckDB catalog file.")]
OutOption = Annotated[Path | None, typer.Option("--out", help="Output path override.")]
ParamSpaceArg = Annotated[
    str,
    typer.Argument(help="FAISS ParameterSpace string (e.g. 'nprobe=64')."),
]
EvalTopKOption = Annotated[
    int,
    typer.Option("--k", min=1, help="Top-K for recall computation."),
]
EvalKFactorOption = Annotated[
    float,
    typer.Option("--k-factor", min=1.0, help="Candidate expansion factor for ANN search."),
]
EvalNProbeOption = Annotated[
    int | None,
    typer.Option("--nprobe", help="Override FAISS nprobe."),
]
EvalXtrOracleOption = Annotated[
    bool,
    typer.Option(
        "--xtr-oracle/--no-xtr-oracle",
        help="Also rescore each query using the XTR token index when available.",
    ),
]


@app.callback()
def global_options(ctx: click.Context, root: RootOption = None) -> None:
    """Configure shared CLI options.

    Parameters
    ----------
    ctx : click.Context
        Click context object to store shared state in. The context's obj dict
        is used to store root directory and CLI context.
    root : RootOption, optional
        Optional root directory path to store in context state. If provided,
        overrides default root resolution for subsequent commands.
    """
    state = ctx.ensure_object(dict)
    if root is not None:
        state["root"] = root
    state.setdefault("cli_context", _DEFAULT_CONTEXT)


def _default_root() -> Path:
    """Determine the default index lifecycle root directory.

    This function computes the default root directory for index lifecycle operations
    by checking the CODEINTEL_INDEXES_DIR environment variable. If the environment
    variable is set, it is used; otherwise, the default "indexes" directory is
    returned relative to the current working directory.

    Returns
    -------
    Path
        Default root directory path for index lifecycle operations. The path is
        resolved to absolute form. Returns the value of CODEINTEL_INDEXES_DIR if
        set, otherwise returns "indexes" resolved from the current directory.

    Notes
    -----
    Root directory resolution enables flexible configuration of where index assets
    are stored. The environment variable allows users to override the default
    location without modifying code, supporting different deployment environments
    and user preferences. The path is resolved to absolute form for consistency.
    """
    env = os.getenv("CODEINTEL_INDEXES_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path("indexes").resolve()


def _resolve_root(ctx: click.Context, explicit_root: Path | None = None) -> Path:
    """Resolve index lifecycle root directory from context or defaults.

    This function determines the root directory to use for index lifecycle operations
    by checking explicit parameter, context state, and default values in order of
    precedence. The function handles None contexts gracefully and resolves paths
    to absolute form.

    Parameters
    ----------
    ctx : click.Context
        Click context containing stored root directory state. The context may
        contain a "root" entry from global options.
    explicit_root : Path | None, optional
        Explicit root directory path to use. If provided, takes precedence over
        context state and defaults. The path is resolved to absolute form.

    Returns
    -------
    Path
        Resolved root directory path. Either explicit_root (if provided), root
        from context state (if available), or default root directory. The path
        is guaranteed to be resolved to absolute form.

    Notes
    -----
    Root resolution enables flexible configuration of index lifecycle root directory
    through multiple mechanisms: explicit parameters, context state (from global
    options), and environment-based defaults. The function ensures consistent path
    resolution across all commands, enabling predictable index asset locations.
    """
    root_from_ctx = ctx.obj.get("root") if ctx.obj else None
    resolved_root = explicit_root or root_from_ctx or _default_root()
    return resolved_root.resolve()


def _manager(explicit_root: Path | None = None) -> IndexLifecycleManager:
    """Create an IndexLifecycleManager instance for the resolved root directory.

    This function creates an IndexLifecycleManager instance using the resolved
    root directory from the current Click context and optional explicit override.
    The manager provides operations for staging, publishing, and managing versioned
    index assets.

    Parameters
    ----------
    explicit_root : Path | None, optional
        Optional explicit root directory override. If provided, this path is used
        instead of resolving from context. The path is resolved to absolute form
        before creating the manager.

    Returns
    -------
    IndexLifecycleManager
        Index lifecycle manager instance configured for the resolved root directory.
        The manager provides methods for staging assets, publishing versions, and
        managing index lifecycle operations.

    Notes
    -----
    Manager creation enables index lifecycle operations by providing a manager
    instance configured for the appropriate root directory. The function resolves
    the root directory using _resolve_root, which handles explicit parameters,
    context state, and defaults. This ensures consistent manager configuration
    across CLI commands.
    """
    ctx = click.get_current_context()
    return IndexLifecycleManager(_resolve_root(ctx, explicit_root))


def _build_assets(
    primaries: tuple[Path, Path, Path],
    channels: dict[str, Path],
    sidecars: dict[str, Path],
) -> IndexAssets:
    """Construct IndexAssets object from primary assets, channels, and sidecars.

    This function creates an IndexAssets object by combining primary assets
    (FAISS index, DuckDB catalog, SCIP index), optional channel directories
    (BM25, SPLADE, XTR), and optional sidecar files (FAISS ID map, tuning profile).
    The function maps channel and sidecar dictionaries to the appropriate asset
    fields.

    Parameters
    ----------
    primaries : tuple[Path, Path, Path]
        Tuple containing (faiss_index, duckdb_path, scip_index) paths for the
        three primary index assets. These are required assets for index staging.
    channels : dict[str, Path]
        Dictionary mapping channel names to directory paths. Supported channels
        include "bm25", "splade", and "xtr". Unrecognized channels are ignored.
    sidecars : dict[str, Path]
        Dictionary mapping sidecar names to file paths. Supported sidecars include
        "faiss_idmap" and "tuning". Unrecognized sidecars are ignored.

    Returns
    -------
    IndexAssets
        Complete IndexAssets object containing all primary assets, channel
        directories, and sidecar files. The object is ready for staging and
        publishing operations.

    Notes
    -----
    Asset construction enables index staging by combining all asset types into
    a single IndexAssets object. The function handles optional channels and
    sidecars gracefully by extracting only recognized entries, ensuring robust
    asset construction even when optional components are missing.
    """
    faiss_index, duckdb_path, scip_index = primaries
    return IndexAssets(
        faiss_index=faiss_index,
        duckdb_path=duckdb_path,
        scip_index=scip_index,
        bm25_dir=channels.get("bm25"),
        splade_dir=channels.get("splade"),
        xtr_dir=channels.get("xtr"),
        faiss_idmap=sidecars.get("faiss_idmap"),
        tuning_profile=sidecars.get("tuning"),
    )


def _parse_extras(extras: list[str]) -> dict[str, Path]:
    """Parse channel entries from command-line extra options.

    This function parses a list of channel entry strings in "name=/path" format
    into a dictionary mapping channel names to resolved paths. Entries without
    "=" separators are skipped, and paths are expanded and resolved to absolute
    form.

    Parameters
    ----------
    extras : list[str]
        List of channel entry strings in "name=/path" format (e.g., "bm25=/tmp/bm25").
        Entries are parsed by splitting on "=" and extracting channel name and path.
        Invalid entries (missing "=") are skipped.

    Returns
    -------
    dict[str, Path]
        Dictionary mapping channel names (lowercased, stripped) to resolved Path
        objects. Channel names are normalized to lowercase for consistency. Paths
        are expanded (handling ~) and resolved to absolute form.

    Notes
    -----
    Channel parsing enables flexible specification of optional channel directories
    via command-line options. The function handles malformed entries gracefully by
    skipping them, ensuring robust parsing even when users provide invalid formats.
    Path normalization ensures consistent path handling across different input formats.
    """
    parsed: dict[str, Path] = {}
    for entry in extras:
        if "=" not in entry:
            continue
        key, value = entry.split("=", maxsplit=1)
        parsed[key.strip().lower()] = Path(value).expanduser().resolve()
    return parsed


def _parse_sidecars(entries: list[str]) -> dict[str, Path]:
    """Parse sidecar entries from command-line sidecar options.

    This function parses a list of sidecar entry strings in "name=/path" format
    into a dictionary mapping sidecar names to resolved paths. Only recognized
    sidecars ("faiss_idmap", "tuning") are included, and paths are expanded and
    resolved to absolute form.

    Parameters
    ----------
    entries : list[str]
        List of sidecar entry strings in "name=/path" format (e.g., "faiss_idmap=/tmp/idmap.parquet").
        Entries are parsed by splitting on "=" and extracting sidecar name and path.
        Invalid entries (missing "=") and unrecognized sidecar names are skipped.

    Returns
    -------
    dict[str, Path]
        Dictionary mapping recognized sidecar names (lowercased, stripped) to
        resolved Path objects. Only "faiss_idmap" and "tuning" sidecars are included.
        Paths are expanded (handling ~) and resolved to absolute form.

    Notes
    -----
    Sidecar parsing enables flexible specification of optional sidecar files via
    command-line options. The function validates sidecar names against an allowlist,
    ensuring only recognized sidecars are processed. This prevents errors from
    typos or unsupported sidecar types while maintaining flexibility for future
    extensions.
    """
    parsed: dict[str, Path] = {}
    allowed = {"faiss_idmap", "tuning"}
    for entry in entries:
        if "=" not in entry:
            continue
        key, value = entry.split("=", maxsplit=1)
        normalized = key.strip().lower()
        if normalized not in allowed:
            continue
        parsed[normalized] = Path(value).expanduser().resolve()
    return parsed


def _resolve_version_dir(manager: IndexLifecycleManager, version: str | None) -> Path | None:
    """Resolve version directory path from version identifier or current version.

    This function determines the version directory to use for index operations
    by checking if an explicit version is provided or using the current version
    directory. The function validates that explicit versions exist before returning
    their paths.

    Parameters
    ----------
    manager : IndexLifecycleManager
        Index lifecycle manager instance providing access to versions directory
        and current version resolution. Used to resolve version paths.
    version : str | None
        Optional version identifier string. If provided, the version directory
        is resolved and validated. If None, the current version directory is
        returned.

    Returns
    -------
    Path | None
        Version directory path if version is provided and exists, or current
        version directory if version is None. Returns None if version is None
        and no current version exists.

    Raises
    ------
    typer.BadParameter
        Raised when an explicit version is provided but the version directory
        does not exist. The error message includes the version identifier and
        versions directory path for debugging.

    Notes
    -----
    Version directory resolution enables version-specific index operations by
    determining which version directory to use for staging, publishing, or querying.
    The function validates explicit versions to prevent errors from typos or
    non-existent versions, while gracefully handling None versions by using the
    current version.
    """
    if version:
        candidate = manager.versions_dir / version
        if not candidate.exists():
            msg = f"Version {version!r} does not exist under {manager.versions_dir}"
            raise typer.BadParameter(msg)
        return candidate
    return manager.current_dir()


def _manifest_path_for(output_path: Path) -> Path:
    """Generate manifest file path for an output file.

    This function creates a manifest file path by replacing the output file's
    extension with ".manifest.json". The manifest path is co-located with the
    output file, enabling easy discovery and association.

    Parameters
    ----------
    output_path : Path
        Output file path to generate a manifest path for. The path's extension
        is replaced with ".manifest.json" to create the manifest path.

    Returns
    -------
    Path
        Manifest file path with ".manifest.json" extension. The path is co-located
        with the output file, sharing the same directory and base name.

    Notes
    -----
    Manifest path generation enables consistent manifest file naming by deriving
    manifest paths from output file paths. The function uses pathlib's with_suffix
    to replace extensions, ensuring manifest files are easily discoverable alongside
    their associated output files.
    """
    return output_path.with_suffix(".manifest.json")


def _load_manifest(path: Path) -> dict[str, object]:
    """Load manifest JSON file or return empty dictionary if missing.

    This function attempts to load a manifest JSON file from the specified path,
    returning an empty dictionary if the file doesn't exist or contains invalid
    JSON. The function handles file I/O and JSON parsing errors gracefully.

    Parameters
    ----------
    path : Path
        Path to manifest JSON file to load. The file is read with UTF-8 encoding
        and parsed as JSON.

    Returns
    -------
    dict[str, object]
        Parsed manifest dictionary if file exists and contains valid JSON,
        otherwise empty dictionary. Returns empty dict if file is missing or
        JSON parsing fails.

    Notes
    -----
    Manifest loading enables reading existing manifest metadata for comparison
    and updates. The function handles missing or corrupted manifests gracefully
    by returning empty dictionaries, ensuring robust operation even when manifests
    are not yet created or have been corrupted. This supports incremental manifest
    updates and validation.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    """Write manifest JSON file with pretty-printed formatting.

    This function writes a manifest dictionary to a JSON file with indented
    formatting and sorted keys for readability. The file is written with UTF-8
    encoding, ensuring consistent encoding across platforms.

    Parameters
    ----------
    path : Path
        File path where the manifest should be written. The file is created or
        overwritten with the manifest content.
    payload : dict[str, object]
        Manifest dictionary to serialize to JSON. The dictionary contains metadata
        about generated assets (provider, model, checksums, paths, etc.). Keys
        are sorted alphabetically in the output.

    Notes
    -----
    Manifest writing enables persistence of asset metadata for tracking and
    validation. The function uses pretty-printed JSON with sorted keys for
    readability and version control friendliness. This supports manifest-based
    validation and tracking of asset generation metadata.
    """
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


@dataclass(slots=True, frozen=False)
class _EmbeddingBuildContext:
    """Context object for embedding build operations.

    This dataclass holds configuration and paths needed for embedding generation
    operations, including app_config, lifecycle manager, version information, and
    input/output paths. The context is mutable to allow updates during build
    operations.

    Attributes
    ----------
    app_config : AppConfig
        Immutable application configuration containing embedding provider settings,
        DuckDB parameters, and default paths.
    paths : ResolvedPaths
        Canonical filesystem paths derived from :class:`AppConfig`.
    manager : IndexLifecycleManager
        Index lifecycle manager for accessing version directories and staging
        operations. Used to resolve version-specific paths.
    version : str | None
        Version identifier string if building for a specific version, otherwise
        None for current version. Used to determine version directory.
    version_dir : Path | None
        Resolved version directory path if version is specified, otherwise None.
        Used to locate version-specific assets.
    duck_path : Path
        Path to DuckDB catalog file containing chunks to embed. Used as input
        for embedding generation.
    output_path : Path
        Path where generated embeddings Parquet file should be written. Used as
        output destination for embedding generation.
    manifest_path : Path
        Path where embedding manifest JSON should be written. Used to persist
        metadata about generated embeddings.
    """

    app_config: AppConfig
    paths: ResolvedPaths
    manager: IndexLifecycleManager
    version: str | None
    version_dir: Path | None
    duck_path: Path
    output_path: Path
    manifest_path: Path


def _build_context(
    app_config: AppConfig,
    manager: IndexLifecycleManager,
    *,
    version: str | None,
    duckdb_path: Path | None,
    output: Path | None,
) -> _EmbeddingBuildContext:
    """Construct embedding build context from configuration and parameters.

    This function creates an _EmbeddingBuildContext object by resolving version
    directory, DuckDB catalog path, output path, and manifest path from AppConfig
    and optional overrides. The context provides all paths and configuration
    needed for embedding generation operations.

    Parameters
    ----------
    app_config : AppConfig
        Immutable application configuration providing default paths and settings.
        Used to determine default DuckDB catalog and output paths when overrides
        are not provided.
    manager : IndexLifecycleManager
        Index lifecycle manager for resolving version directories. Used to determine
        version-specific paths when version is specified.
    version : str | None, optional
        Optional version identifier for version-specific builds. If provided,
        version directory is resolved and used for path resolution.
    duckdb_path : Path | None, optional
        Optional DuckDB catalog path override. If provided, this path is used
        instead of resolving from AppConfig defaults or version directory.
    output : Path | None, optional
        Optional output path override for embeddings Parquet file. If provided,
        this path is used instead of resolving from AppConfig defaults or version
        directory.

    Returns
    -------
    _EmbeddingBuildContext
        Complete embedding build context containing all resolved paths and
        configuration. The context is ready for embedding generation operations.

    Notes
    -----
    Context construction enables embedding generation by providing all necessary
    paths and configuration in a single object. The function handles path resolution
    with precedence: explicit overrides > version-specific paths > AppConfig defaults.
    This enables flexible configuration while maintaining sensible defaults.

    The function may propagate typer.BadParameter from _resolve_version_dir when
    explicit version doesn't exist, or from resolve_duck_path when DuckDB catalog
    file is not found.
    """
    paths = resolve_application_paths(app_config)
    version_dir = _resolve_version_dir(manager, version)
    duck_path = resolve_duck_path(paths, version_dir, duckdb_path)
    output_path = _resolve_output_path(
        paths,
        version_dir,
        output,
        ensure_parent=True,
    )
    manifest_path = _manifest_path_for(output_path)
    return _EmbeddingBuildContext(
        app_config=app_config,
        paths=paths,
        manager=manager,
        version=version,
        version_dir=version_dir,
        duck_path=duck_path,
        output_path=output_path,
        manifest_path=manifest_path,
    )


def resolve_duck_path(
    paths: ResolvedPaths,
    version_dir: Path | None,
    override: Path | None,
) -> Path:
    """Resolve DuckDB catalog path from resolved paths, version directory, or override.

    This function determines the DuckDB catalog path to use for embedding operations
    by checking override parameter, version directory, and AppConfig defaults in order
    of precedence. The function validates that the resolved path exists before returning.

    Parameters
    ----------
    paths : ResolvedPaths
        Canonicalized filesystem paths derived from AppConfig. When neither override
        nor version_dir is provided, the DuckDB catalog path falls back to the
        resolved default.
    version_dir : Path | None
        Optional version directory path. If provided and override is None, the
        catalog path is resolved as version_dir / "catalog.duckdb".
    override : Path | None
        Optional explicit path override. If provided, this path takes precedence
        over version directory and AppConfig defaults.

    Returns
    -------
    Path
        Resolved DuckDB catalog path. The path is expanded (handling ~) and
        resolved to absolute form. Path resolution follows precedence: override >
        version_dir / "catalog.duckdb" > AppConfig.duckdb.database.

    Raises
    ------
    typer.BadParameter
        Raised when the resolved DuckDB catalog file does not exist. The error
        message includes the resolved path for debugging.

    Notes
    -----
    DuckDB path resolution enables flexible catalog access by supporting multiple
    path sources: explicit overrides, version-specific catalogs, and AppConfig defaults.
    The function validates path existence to prevent errors from missing catalogs,
    ensuring robust operation even when paths are misconfigured.
    """
    if override is not None:
        duck_path = override.expanduser().resolve()
    elif version_dir is not None:
        duck_path = (version_dir / "catalog.duckdb").resolve()
    else:
        duck_path = paths.duckdb_path
    if not duck_path.exists():
        msg = f"DuckDB catalog not found: {duck_path}"
        raise typer.BadParameter(msg)
    return duck_path


def _resolve_output_path(
    paths: ResolvedPaths,
    version_dir: Path | None,
    override: Path | None,
    *,
    ensure_parent: bool,
) -> Path:
    """Resolve embeddings output path from paths, version directory, or override.

    This function determines the output path for embeddings Parquet file by checking
    override parameter, version directory, and AppConfig defaults in order of precedence.
    The function optionally ensures the parent directory exists before returning.

    Parameters
    ----------
    paths : ResolvedPaths
        Canonicalized filesystem paths containing the default vectors directory. Used when override
        and version_dir are None. The output path is resolved as vectors_dir / "embeddings.parquet".
    version_dir : Path | None
        Optional version directory path. If provided and override is None, the
        output path is resolved as version_dir / "embeddings.parquet".
    override : Path | None
        Optional explicit path override. If provided, this path takes precedence
        over version directory and AppConfig defaults.
    ensure_parent : bool
        Flag indicating whether to create the parent directory if it doesn't exist.
        When True, parent directories are created using mkdir(parents=True, exist_ok=True).

    Returns
    -------
    Path
        Resolved embeddings output path. The path is expanded (handling ~) and
        resolved to absolute form. Path resolution follows precedence: override >
        version_dir / "embeddings.parquet" > paths.vectors_dir / "embeddings.parquet".

    Notes
    -----
    Output path resolution enables flexible embedding storage by supporting multiple
    path sources: explicit overrides, version-specific outputs, and default paths.
    The function optionally ensures parent directories exist, preventing errors
    from missing directories during file writing. This supports both user-specified
    and default output locations.
    """
    if override is not None:
        output_path = override.expanduser().resolve()
    elif version_dir is not None:
        output_path = (version_dir / "embeddings.parquet").resolve()
    else:
        output_path = (paths.vectors_dir / "embeddings.parquet").resolve()
    if ensure_parent:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def _parquet_meta(provider: EmbeddingProvider) -> dict[str, str]:
    """Extract embedding provider metadata for Parquet file metadata.

    This function extracts metadata from an embedding provider and formats it as
    a dictionary of string key-value pairs suitable for inclusion in Parquet file
    metadata. The metadata includes provider type, model name, dimension, dtype,
    normalization, device, and fingerprint.

    Parameters
    ----------
    provider : EmbeddingProvider
        Embedding provider instance to extract metadata from. The provider's
        metadata and fingerprint are accessed to build the metadata dictionary.

    Returns
    -------
    dict[str, str]
        Dictionary containing embedding provider metadata as string key-value
        pairs. Keys include "embedding_provider", "embedding_model", "embedding_dim",
        "embedding_dtype", "embedding_normalize", "embedding_device", and
        "embedding_fingerprint". All values are converted to strings for Parquet
        metadata compatibility.

    Notes
    -----
    Parquet metadata extraction enables embedding provenance tracking by storing
    provider information in Parquet file metadata. This allows downstream tools
    to identify which provider and model generated embeddings without requiring
    separate manifest files. The metadata is stored as strings to ensure Parquet
    compatibility across different metadata systems.
    """
    meta = provider.metadata
    return {
        "embedding_provider": meta.provider,
        "embedding_model": meta.model_name,
        "embedding_dim": str(meta.dimension),
        "embedding_dtype": meta.dtype,
        "embedding_normalize": str(meta.normalize).lower(),
        "embedding_device": meta.device,
        "embedding_fingerprint": provider.fingerprint(),
    }


def _build_embedding_manifest(
    provider: EmbeddingProvider,
    *,
    checksum: str,
    vector_count: int,
    output_path: Path,
    app_config: AppConfig,
) -> dict[str, object]:
    """Build embedding manifest dictionary with generation metadata.

    This function constructs a manifest dictionary containing embedding provider
    metadata, generation parameters, checksum, vector count, output path, and
    generation timestamp. The manifest provides comprehensive metadata about
    generated embeddings for tracking and validation.

    Parameters
    ----------
    provider : EmbeddingProvider
        Embedding provider instance used for generation. Provider metadata and
        fingerprint are included in the manifest.
    checksum : str
        SHA-256 checksum of chunk content used for embedding generation. The
        checksum enables validation of embedding-to-chunk correspondence.
    vector_count : int
        Total number of vectors generated. Included in manifest for statistics
        and validation.
    output_path : Path
        Path where embeddings Parquet file was written. Included in manifest
        for reference and validation.
    app_config : AppConfig
        Immutable application configuration providing embedding batch parameters.

    Returns
    -------
    dict[str, object]
        Complete manifest dictionary containing provider metadata (provider,
        model_name, dimension, dtype, normalize, device, fingerprint), generation
        parameters (checksum, vectors, batch_size, micro_batch_size), output path,
        and generation timestamp. The manifest is ready for JSON serialization.

    Notes
    -----
    Manifest construction enables comprehensive tracking of embedding generation
    by capturing all relevant metadata in a single dictionary. The manifest includes
    provider information, generation parameters, and output details, enabling
    validation, provenance tracking, and reproducibility. The timestamp enables
    tracking of when embeddings were generated.
    """
    meta = provider.metadata
    embeddings_cfg = app_config.embeddings
    return {
        "provider": meta.provider,
        "model_name": meta.model_name,
        "dimension": meta.dimension,
        "dtype": meta.dtype,
        "normalize": meta.normalize,
        "device": meta.device,
        "fingerprint": provider.fingerprint(),
        "checksum": checksum,
        "vectors": vector_count,
        "batch_size": embeddings_cfg.batch_size,
        "micro_batch_size": embeddings_cfg.micro_batch_size,
        "output_path": str(output_path),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _compute_chunk_checksum(manager: DuckDBManager, *, batch_size: int = 2048) -> tuple[str, int]:
    """Compute SHA-256 checksum of chunk IDs and content hashes.

    This function computes a deterministic checksum over all chunks in the DuckDB
    catalog by hashing chunk IDs and content hashes in sorted order. The checksum
    enables detection of changes to chunk content, supporting incremental embedding
    generation and validation.

    Parameters
    ----------
    manager : DuckDBManager
        DuckDB manager instance providing database connection. The manager must
        have a chunks table with id and content_hash columns.
    batch_size : int, optional
        Number of rows to fetch per batch when computing checksum. Defaults to 2048.
        Larger batch sizes reduce database round-trips but increase memory usage.

    Returns
    -------
    tuple[str, int]
        Tuple containing (checksum_hexdigest, total_chunks). The checksum is a
        SHA-256 hex digest computed over all chunk IDs and content hashes in
        sorted order. Total chunks is the number of chunks processed.

    Notes
    -----
    Checksum computation enables change detection by creating a deterministic
    fingerprint of chunk content. The function processes chunks in batches to
    handle large catalogs efficiently, and sorts by ID to ensure deterministic
    checksum computation regardless of database storage order.
    """
    digest = hashlib.sha256()
    total = 0
    with manager.connection() as conn:
        cursor = conn.execute("SELECT id, content_hash FROM chunks ORDER BY id")
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            for chunk_id, content_hash in rows:
                digest.update(f"{int(chunk_id)}:{int(content_hash):016x}".encode())
                total += 1
    return digest.hexdigest(), total


def _collect_chunks_and_embeddings(
    manager: DuckDBManager,
    *,
    provider: EmbeddingProvider,
    batch_rows: int,
) -> tuple[list[Chunk], NDArrayF32]:
    """Collect chunks from DuckDB and generate embeddings in batches.

    This function reads chunks from the DuckDB catalog, generates embeddings
    for chunk text in batches, and returns both chunks and their corresponding
    embeddings. The function processes chunks in batches to manage memory usage
    and enable efficient embedding generation for large catalogs.

    Parameters
    ----------
    manager : DuckDBManager
        DuckDB manager instance providing database connection. The manager must
        have a chunks table with uri, start_byte, end_byte, start_line, end_line,
        content, lang, and symbols columns.
    provider : EmbeddingProvider
        Embedding provider instance for generating embeddings from chunk text.
        The provider must support batch embedding generation via embed_texts.
    batch_rows : int
        Number of chunks to process per batch. Larger batches reduce provider
        overhead but increase memory usage. Must be positive.

    Returns
    -------
    tuple[list[Chunk], NDArrayF32]
        Tuple containing (chunks, embeddings). Chunks is a list of Chunk objects
        with metadata and text. Embeddings is a NumPy array of shape (n_chunks,
        embedding_dim) containing float32 embeddings. Returns empty chunks list
        and empty embeddings array if no chunks exist.

    Notes
    -----
    Batch processing enables efficient embedding generation for large catalogs by
    processing chunks in manageable batches rather than loading all chunks into
    memory. The function preserves chunk metadata (URI, line ranges, symbols,
    language) while generating embeddings, enabling downstream tools to associate
    embeddings with source locations.
    """
    np_module = np
    chunks: list[Chunk] = []
    embeddings_parts: list[NDArrayF32] = []
    sql = """
        SELECT uri, start_byte, end_byte, start_line, end_line, content, lang, symbols
        FROM chunks
        ORDER BY id
    """
    with manager.connection() as conn:
        cursor = conn.execute(sql)
        while True:
            rows = cursor.fetchmany(batch_rows)
            if not rows:
                break
            batch_chunks: list[Chunk] = []
            texts: list[str] = []
            for uri, start_byte, end_byte, start_line, end_line, content, lang, symbols in rows:
                chunk = Chunk(
                    uri=uri,
                    start_byte=int(start_byte),
                    end_byte=int(end_byte),
                    start_line=int(start_line),
                    end_line=int(end_line),
                    text=content,
                    symbols=tuple(symbols) if symbols else (),
                    language=lang or "",
                )
                batch_chunks.append(chunk)
                texts.append(chunk.text)
            if not batch_chunks:
                continue
            vectors = provider.embed_texts(texts)
            embeddings_parts.append(vectors)
            chunks.extend(batch_chunks)
    if embeddings_parts:
        embeddings = np_module.vstack(embeddings_parts)
    else:
        embeddings = np_module.empty((0, provider.metadata.dimension), dtype=np_module.float32)
    return chunks, embeddings


def _deterministic_sample(total_rows: int, sample_size: int) -> list[int]:
    """Return a deterministic pseudo-random selection of indices.

    This function generates a deterministic sample of indices by sorting all
    indices by a hash-based key derived from each index value. The function
    uses SHA-256 hashing to create a stable ordering that appears random but
    is reproducible across runs. This enables consistent sampling for validation
    and testing purposes.

    Parameters
    ----------
    total_rows : int
        Total number of rows/indices available for sampling. The function
        generates indices in the range [0, total_rows). Must be non-negative.
    sample_size : int
        Maximum number of indices to return in the sample. The function returns
        at most sample_size indices, or all indices if total_rows <= sample_size.
        Must be non-negative.

    Returns
    -------
    list[int]
        Ordered list of sampled indices, capped at sample_size. The indices
        are sorted by their hash-based keys, providing a deterministic but
        pseudo-random selection. Empty list if total_rows is 0 or sample_size
        is 0. Contains min(total_rows, sample_size) elements.
    """
    keyed = sorted(
        range(total_rows),
        key=lambda idx: hashlib.sha256(f"validate-{idx}".encode()).digest(),
    )
    return keyed[:sample_size]


def _evaluate_drift(
    *,
    indices: Sequence[int],
    embeddings: NDArrayF32,
    contents: Sequence[str],
    provider: EmbeddingProvider,
    epsilon: float,
) -> tuple[float, float, int]:
    """Evaluate embedding drift by recomputing embeddings and comparing.

    This function evaluates embedding drift by recomputing embeddings for
    sampled chunks and comparing them to stored embeddings using cosine similarity.
    The function computes maximum drift, total drift sum, and failure count
    (drift exceeding epsilon threshold) across all sampled indices.

    Parameters
    ----------
    indices : Sequence[int]
        Sequence of chunk indices to evaluate. Indices correspond to positions
        in embeddings and contents sequences. Used to sample chunks for drift
        evaluation.
    embeddings : NDArrayF32
        Stored embeddings array of shape (n_chunks, embedding_dim) containing
        previously generated embeddings. Used as baseline for drift comparison.
    contents : Sequence[str]
        Sequence of chunk text content corresponding to embeddings. Used to
        recompute embeddings for drift evaluation. Must have same length as
        embeddings first dimension.
    provider : EmbeddingProvider
        Embedding provider instance for recomputing embeddings. The provider
        must match the provider used to generate stored embeddings for meaningful
        drift evaluation.
    epsilon : float
        Maximum allowed drift threshold. Chunks with drift exceeding epsilon are
        counted as failures. Drift is computed as 1 - cosine_similarity, so
        epsilon represents maximum allowed cosine distance.

    Returns
    -------
    tuple[float, float, int]
        Tuple containing (max_drift, drift_sum, failure_count). Max drift is the
        maximum drift value across all sampled chunks. Drift sum is the sum of
        all drift values. Failure count is the number of chunks with drift
        exceeding epsilon threshold.

    Notes
    -----
    Drift evaluation enables validation of stored embeddings by detecting when
    recomputed embeddings differ significantly from stored values. This helps
    identify when embeddings need regeneration due to model changes, configuration
    updates, or data corruption. Cosine similarity is used to measure drift,
    providing a normalized comparison that accounts for embedding magnitude.
    """
    max_drift = 0.0
    drift_sum = 0.0
    failure_count = 0
    for idx in indices:
        text = contents[idx]
        fresh = provider.embed_texts([text])[0]
        stored = embeddings[idx]
        denom = float(np.linalg.norm(stored) * np.linalg.norm(fresh))
        cosine = float(np.dot(stored, fresh) / denom) if denom else 0.0
        drift = max(0.0, 1.0 - cosine)
        drift_sum += drift
        max_drift = max(max_drift, drift)
        if drift > epsilon:
            failure_count += 1
    return max_drift, drift_sum, failure_count


def _execute_embeddings_build(
    *,
    context: _EmbeddingBuildContext,
    chunk_size: int,
    force: bool,
) -> None:
    """Execute embedding generation workflow with checksum validation.

    This function orchestrates the embedding generation workflow by computing
    chunk checksums, checking for existing embeddings, generating embeddings
    if needed, writing Parquet files, and creating manifests. The function
    skips generation if checksums match and force is False, enabling incremental
    updates.

    Parameters
    ----------
    context : _EmbeddingBuildContext
        Embedding build context containing configuration, manager, paths, and version
        information. The context provides all configuration and paths needed
        for embedding generation.
    chunk_size : int
        Number of chunks to process per batch during embedding generation.
        Larger batch sizes reduce provider overhead but increase memory usage.
        Must be positive.
    force : bool
        Flag indicating whether to force regeneration even when checksums match.
        When True, embeddings are regenerated regardless of existing manifests.
        When False, generation is skipped if checksum and fingerprint match.

    Notes
    -----
    Embedding generation workflow enables efficient embedding creation with
    incremental updates. The function checks existing manifests to avoid
    redundant generation when chunk content and provider fingerprint haven't
    changed. This supports fast iteration during development and efficient
    updates in production. The function writes both Parquet files and manifests,
    enabling downstream tools to access embeddings and metadata.
    """
    app_config = context.app_config
    provider = _embedding_provider(app_config)
    duckdb_cfg = _duckdb_manager_config(app_config)
    db_manager = DuckDBManager(context.duck_path, duckdb_cfg)
    try:
        checksum, row_count = _compute_chunk_checksum(db_manager)
        existing_manifest = _load_manifest(context.manifest_path)
        if (
            not force
            and existing_manifest
            and existing_manifest.get("checksum") == checksum
            and existing_manifest.get("fingerprint") == provider.fingerprint()
        ):
            typer.echo(
                "Embeddings already current for checksum="
                f"{checksum[:8]}… and provider {existing_manifest.get('provider')}",
            )
            return

        typer.echo(
            f"Embedding {row_count} chunks from {context.duck_path} → {context.output_path}",
        )
        chunks, embeddings = _collect_chunks_and_embeddings(
            db_manager,
            provider=provider,
            batch_rows=chunk_size,
        )
        write_chunks_parquet(
            context.output_path,
            chunks,
            embeddings,
            options=ParquetWriteOptions(
                vec_dim=provider.metadata.dimension,
                preview_max_chars=app_config.index.preview_max_chars,
                id_strategy="stable_hash",
                table_meta=_parquet_meta(provider),
            ),
        )
        manifest_payload = _build_embedding_manifest(
            provider,
            checksum=checksum,
            vector_count=len(chunks),
            output_path=context.output_path,
            app_config=app_config,
        )
        manifest_payload["row_count"] = row_count
        _write_manifest(context.manifest_path, manifest_payload)
        if context.version_dir is not None:
            _write_embedding_meta(context.manager, manifest_payload, version=context.version)
        typer.echo(
            "Wrote embeddings Parquet "
            f"({len(chunks)} rows) and manifest at {context.manifest_path}",
        )
    finally:
        provider.close()


def _run_embedding_validation(
    *,
    parquet_path: Path,
    samples: int,
    epsilon: float,
) -> None:
    """Run embedding validation by sampling and recomputing embeddings.

    This function validates stored embeddings by reading a Parquet file, sampling
    chunks, recomputing embeddings using the current provider, and comparing
    them to detect drift. The function reports drift statistics and validation
    results, helping identify when embeddings need regeneration.

    Parameters
    ----------
    parquet_path : Path
        Path to Parquet file containing stored chunks and embeddings. The file
        must contain chunks table with content column and embeddings array.
    samples : int
        Number of chunks to sample for validation. The function uses deterministic
        sampling to ensure reproducible results. Must be positive.
    epsilon : float
        Maximum allowed drift threshold for validation. Chunks with drift
        exceeding epsilon are reported as failures. Drift is computed as
        1 - cosine_similarity.

    Raises
    ------
    typer.Exit
        Raised with exit code 1 when validation failures exceed the epsilon
        threshold. This indicates that stored embeddings have drifted beyond
        acceptable limits and may need regeneration.

    Notes
    -----
    Embedding validation enables quality assurance by detecting drift between
    stored and recomputed embeddings. The function uses deterministic sampling
    to ensure reproducible validation results, and reports comprehensive drift
    statistics including maximum drift, average drift, and failure counts. This
    helps identify when embeddings need regeneration due to model changes or
    configuration updates.
    """
    table = read_chunks_parquet(parquet_path)
    embeddings = extract_embeddings(table)
    total_rows = embeddings.shape[0]
    if total_rows == 0:
        typer.echo("Parquet file is empty; nothing to validate.")
        return
    sample_size = min(samples, total_rows)
    contents = cast("list[str]", table.column("content").to_pylist())
    indices = _deterministic_sample(total_rows, sample_size)

    provider = _embedding_provider(_get_app_config())
    try:
        max_drift, drift_sum, failure_count = _evaluate_drift(
            indices=indices,
            embeddings=embeddings,
            contents=contents,
            provider=provider,
            epsilon=epsilon,
        )
        typer.echo(
            f"Validated {sample_size}/{total_rows} rows from {parquet_path} | "
            f"max drift={max_drift:.4f} avg drift={(drift_sum / sample_size):.4f}",
        )
        if failure_count:
            typer.echo(f"{failure_count} samples exceeded epsilon={epsilon:.4f}")
            raise typer.Exit(code=1)
    finally:
        provider.close()


def _write_embedding_meta(
    manager: IndexLifecycleManager,
    payload: Mapping[str, object],
    *,
    version: str | None,
) -> None:
    """Write embedding metadata to version directory.

    This function writes embedding manifest metadata to the version directory
    using the index lifecycle manager. The function suppresses RuntimeLifecycleError
    to handle cases where version directories don't exist or metadata writing
    fails, enabling graceful degradation.

    Parameters
    ----------
    manager : IndexLifecycleManager
        Index lifecycle manager instance for writing metadata. The manager
        provides write_embedding_metadata method for persisting metadata.
    payload : Mapping[str, object]
        Embedding manifest dictionary containing provider metadata, checksums,
        vector counts, and generation parameters. The payload is written to
        version-specific metadata files.
    version : str | None, optional
        Optional version identifier for version-specific metadata writing.
        If None, metadata is written to the current version directory.

    Notes
    -----
    Metadata writing enables version tracking by persisting embedding generation
    metadata alongside versioned index assets. The function suppresses errors
    to handle cases where version directories don't exist or metadata writing
    fails, ensuring embedding generation can complete even when metadata writing
    is unavailable. This supports both versioned and non-versioned workflows.
    """
    with suppress(RuntimeLifecycleError):
        manager.write_embedding_metadata(payload, version=version)


@embeddings_app.command("build")
def embeddings_build_command(
    *,
    force: bool = typer.Option(
        default=False,
        help="Rebuild even when checksum and fingerprint match.",
    ),
    version: VersionOption = None,
    duckdb_path: DuckOption = None,
    output: OutputOption = None,
    chunk_size: ChunkBatchOption = 512,
) -> None:
    """Embed chunks from DuckDB and write Parquet + manifest artifacts.

    Parameters
    ----------
    force : bool, optional
        Whether to rebuild embeddings even when checksum and fingerprint match
        existing artifacts. Defaults to False.
    version : VersionOption, optional
        Optional version identifier for embedding artifacts. If provided, artifacts
        are written to the versioned directory. Defaults to None.
    duckdb_path : DuckOption, optional
        Optional DuckDB catalog path. If None, uses configured default path.
    output : OutputOption, optional
        Optional output directory for Parquet artifacts. If None, uses configured
        default output directory.
    chunk_size : ChunkBatchOption, optional
        Batch size for embedding generation. Defaults to 512.
    """
    app_config = _get_app_config()
    manager = _manager()
    context = _build_context(
        app_config,
        manager,
        version=version,
        duckdb_path=duckdb_path,
        output=output,
    )
    _execute_embeddings_build(context=context, chunk_size=chunk_size, force=force)


@embeddings_app.command("validate")
def embeddings_validate_command(
    parquet: ParquetOption = None,
    version: VersionOption = None,
    samples: SampleOption = 32,
    epsilon: EpsilonOption = 5e-3,
) -> None:
    """Sample stored embeddings, recompute vectors, and detect drift.

    This command validates stored embeddings by sampling vectors from the Parquet
    file, recomputing embeddings for the same texts using the current model,
    and comparing them to detect drift. The command reports drift statistics
    and can help identify when embeddings need to be regenerated due to model
    changes or configuration updates.

    Parameters
    ----------
    parquet : ParquetOption, optional
        Path to the embeddings Parquet file to validate. If None, uses the
        default path from the active index version. The file must exist and
        contain embedding vectors for validation.
    version : VersionOption, optional
        Index version to validate embeddings for. If None, uses the active
        version. Used to locate the embeddings Parquet file when parquet
        path is not explicitly provided.
    samples : SampleOption, optional
        Number of embedding vectors to sample for validation (defaults to 32).
        Larger samples provide more accurate drift detection but take longer
        to compute. The sampled vectors are randomly selected from the Parquet
        file.
    epsilon : EpsilonOption, optional
        Tolerance threshold for drift detection (defaults to 5e-3). Embeddings
        with differences greater than epsilon are considered drifted. Used to
        determine if recomputed embeddings match stored embeddings within the
        specified tolerance.

    Raises
    ------
    typer.BadParameter
        Raised when the embeddings Parquet file is missing or cannot be accessed.
        The error includes the expected path for debugging.
    """
    app_config = _get_app_config()
    paths = resolve_application_paths(app_config)
    manager = _manager()
    version_dir = _resolve_version_dir(manager, version)
    parquet_path = _resolve_output_path(
        paths,
        version_dir,
        parquet,
        ensure_parent=False,
    )
    if not parquet_path.exists():
        msg = f"Embeddings Parquet not found: {parquet_path}"
        raise typer.BadParameter(msg)

    _run_embedding_validation(
        parquet_path=parquet_path,
        samples=samples,
        epsilon=epsilon,
    )


def _parse_tune_overrides(
    raw_args: Sequence[str],
) -> tuple[dict[str, float | int], SweepMode | None]:
    """Parse FAISS tuning override arguments from command-line.

    This function parses command-line arguments for FAISS tuning overrides and
    sweep mode selection. The function validates argument formats, extracts
    override values with type casting, and detects sweep mode flags. Invalid
    arguments raise typer.BadParameter with descriptive error messages.

    Parameters
    ----------
    raw_args : Sequence[str]
        Sequence of command-line argument strings to parse. Arguments must be
        in "--key=value" format for overrides or "--sweep" format for sweep mode.
        Values are parsed and cast to appropriate types (int or float).

    Returns
    -------
    tuple[dict[str, float | int], SweepMode | None]
        Tuple containing (overrides, sweep_mode). Overrides is a dictionary
        mapping parameter names (nprobe, ef_search, quantizer_ef_search, k_factor)
        to their override values. Sweep mode is "quick" or "full" if specified,
        otherwise None.

    Raises
    ------
    typer.BadParameter
        Raised when arguments are malformed (missing "--" prefix, empty option
        names, missing values, invalid value types, conflicting sweep modes, or
        unknown options). Error messages describe the specific validation failure.

    Notes
    -----
    Tuning override parsing enables flexible FAISS parameter configuration via
    command-line arguments. The function validates argument formats and types,
    providing clear error messages for invalid inputs. Supported overrides include
    nprobe, ef_search, quantizer_ef_search, and k_factor, with automatic type
    casting to int or float based on parameter type.
    """
    overrides: dict[str, float | int] = {}
    sweep_mode: SweepMode | None = None
    iterator = iter(raw_args)
    for token in iterator:
        if not token.startswith("--"):
            msg = f"Unknown argument '{token}'."
            raise typer.BadParameter(msg)
        normalized = token.lstrip("-")
        if not normalized:
            msg = "Encountered empty option name."
            raise typer.BadParameter(msg)
        canonical = normalized.replace("-", "_")
        if canonical in _TUNE_OVERRIDE_CASTERS:
            try:
                raw_value = next(iterator)
            except StopIteration as exc:
                msg = f"Missing value for --{normalized}."
                raise typer.BadParameter(msg) from exc
            caster = _TUNE_OVERRIDE_CASTERS[canonical]
            try:
                overrides[canonical] = caster(raw_value)
            except ValueError as exc:
                msg = f"Invalid value '{raw_value}' for --{normalized}."
                raise typer.BadParameter(msg) from exc
            continue
        sweep_candidate = _SWEEP_MODE_BY_NAME.get(canonical)
        if sweep_candidate is not None:
            if sweep_mode is not None and sweep_mode != sweep_candidate:
                msg = "Conflicting sweep modes provided."
                raise typer.BadParameter(msg)
            sweep_mode = sweep_candidate
            continue
        msg = f"Unknown option '--{normalized}'."
        raise typer.BadParameter(msg)
    return overrides, sweep_mode


def _faiss_manager(index_override: Path | None = None) -> FAISSManager:
    """Create FAISS manager instance using CLI context factory.

    This function creates a FAISSManager instance by retrieving AppConfig and
    using the CLI context's FAISS manager factory. The function supports
    optional index path override for flexible index access.

    Parameters
    ----------
    index_override : Path | None, optional
        Optional path override for FAISS index file. If provided, this path
        is used instead of the configured default. The path is expanded and resolved
        to absolute form.

    Returns
    -------
    FAISSManager
        Configured FAISS manager instance with CPU index loaded. The manager
        is ready for search operations and index management.

    Notes
    -----
    FAISS manager creation enables index access for CLI commands that need to
    interact with FAISS indexes. The function uses the CLI context's factory
    method, enabling dependency injection and testing with mock managers. The
    manager is configured with AppConfig data and optional path override, providing
    flexible index access.
    """
    app_config = _get_app_config()
    return _cli_context().faiss_manager_factory(app_config, index_override)


def _duckdb_catalog(path_override: Path | None = None) -> DuckDBCatalog:
    """Create DuckDB catalog instance using CLI context factory.

    This function creates a DuckDBCatalog instance by retrieving AppConfig and
    using the CLI context's DuckDB catalog factory. The function supports
    optional path override for flexible catalog access.

    Parameters
    ----------
    path_override : Path | None, optional
        Optional path override for DuckDB catalog file. If provided, this path
        is used instead of the configured default. The path is expanded and resolved
        to absolute form.

    Returns
    -------
    DuckDBCatalog
        Configured DuckDB catalog instance ready for querying chunk metadata
        and structure annotations. The catalog is configured with all necessary
        paths and configuration from the application configuration.

    Notes
    -----
    DuckDB catalog creation enables metadata access for CLI commands that need
    to query chunk information, structure annotations, and embedding metadata.
    The function uses the CLI context's factory method, enabling dependency
    injection and testing with mock catalogs. The catalog is configured with
    AppConfig data and optional path override, providing flexible catalog access.
    """
    app_config = _get_app_config()
    return _cli_context().duckdb_catalog_factory(app_config, path_override)


def _duckdb_embedding_dim(catalog: DuckDBCatalog) -> int:
    """Return the embedding dimension stored in DuckDB.

    Parameters
    ----------
    catalog : DuckDBCatalog
        DuckDB catalog instance to query for embedding dimension. The catalog
        must have a chunks table with an embedding column.

    Returns
    -------
    int
        The dimension of embeddings stored in the catalog. Returns 0 if no
        embeddings are found or if the embedding column is empty/None.
    """
    return _cli_context().duckdb_dim_resolver(catalog)


def _count_idmap_rows(path: Path) -> int:
    """Return row count for a FAISS idmap sidecar.

    Parameters
    ----------
    path : Path
        Path to the Parquet file containing the FAISS ID map sidecar. The file
        may not exist, in which case 0 is returned.

    Returns
    -------
    int
        Number of rows in the ID map Parquet file, or 0 if the file doesn't
        exist.
    """
    return _cli_context().idmap_row_counter(path)


def _embedding_provider(app_config: AppConfig) -> EmbeddingProvider:
    """Create embedding provider instance using CLI context factory.

    This function creates an EmbeddingProvider instance by using the CLI context's
    embedding provider factory with the provided AppConfig. The function enables
    dependency injection and testing with mock providers.

    Parameters
    ----------
    app_config : AppConfig
        Application configuration containing embedding provider configuration
        (provider type, model name, API keys, etc.). Used to instantiate the
        appropriate embedding provider.

    Returns
    -------
    EmbeddingProvider
        Configured embedding provider instance ready for generating embeddings.
        The provider type and configuration are determined from AppConfig.

    Notes
    -----
    Embedding provider creation enables embedding generation for CLI commands that
    need to create embeddings from text. The function uses the CLI context's
    factory method, enabling dependency injection and testing with mock providers.
    The provider is configured with AppConfig data, supporting multiple provider backends
    (OpenAI, VLLM, local models).
    """
    return _cli_context().embedding_provider_factory(app_config)


def _load_xtr_index(app_config: AppConfig) -> XTRIndex | None:
    """Load XTR index if enabled and available.

    This function attempts to load an XTR index from AppConfig if XTR is enabled.
    The function handles errors gracefully by returning None when the index
    cannot be opened or is not ready, enabling optional XTR functionality.

    Parameters
    ----------
    app_config : AppConfig
        Application configuration containing XTR enablement flag, artifact
        directories, and runtime configuration.

    Returns
    -------
    XTRIndex | None
        Loaded XTR index instance if XTR is enabled and index is available and
        ready, otherwise None. Returns None if XTR is disabled, index cannot
        be opened, or index is not ready.

    Notes
    -----
    XTR index loading enables optional late-interaction rescoring functionality
    when XTR indexes are available. The function handles errors gracefully by
    returning None, ensuring commands can run even when XTR indexes are missing
    or unavailable. This supports both XTR-enabled and XTR-disabled workflows.
    """
    if not app_config.xtr.enable:
        return None
    paths = resolve_application_paths(app_config)
    root = paths.xtr_dir
    index = XTRIndex(root=root, config=app_config.xtr)
    try:
        index.open()
    except (OSError, RuntimeError, ValueError):  # pragma: no cover - defensive logging
        return None
    if not index.ready:
        return None
    return index


def _eval_paths(base_dir: Path) -> tuple[Path, Path]:
    """Generate evaluation output paths with timestamp and run ID.

    This function creates evaluation output paths by combining base directory,
    timestamp, and random run ID. The function creates the output directory
    if it doesn't exist and returns paths for Parquet and JSON output files.

    Parameters
    ----------
    base_dir : Path
        Base directory for evaluation output. Timestamped subdirectories will
        be created within this directory.

    Returns
    -------
    tuple[Path, Path]
        Tuple containing (parquet_path, json_path). Parquet path is the output
        path for evaluation results Parquet file. JSON path is the output path
        for evaluation metrics JSON file. Both paths are in a timestamped
        subdirectory with a random run ID prefix.

    Notes
    -----
    Evaluation path generation enables organized evaluation output by creating
    timestamped directories with unique run IDs. This prevents output file
    conflicts and enables tracking of multiple evaluation runs. The function
    creates directories automatically, ensuring output paths are ready for writing.
    """
    base_dir = Path(base_dir).expanduser().resolve()
    timestamp = datetime.now(UTC).strftime("%y%m%d-%H%M")
    run_id = uuid.uuid4().hex[:8]
    output_dir = base_dir / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{run_id}.parquet", output_dir / f"{run_id}.json"


@app.command("status")
def status_command() -> None:
    """Print the active version and available versions."""
    mgr = _manager()
    current = mgr.current_version() or "<none>"
    typer.echo(f"current: {current}")
    for version in mgr.list_versions():
        typer.echo(f"- {version}")


@app.command("stage")
def stage_command(
    version: VersionArg,
    assets: AssetsArg,
    extras: ExtraOption,
    sidecars: SidecarOption,
) -> None:
    """Stage a new version by copying assets into the lifecycle root.

    This command stages a new index version by copying FAISS, DuckDB, and SCIP
    assets into the lifecycle root directory. The command validates asset paths,
    resolves sidecar files (BM25, SPLADE indices), and prepares the version for
    publishing. Staged versions can be published or rolled back as needed.

    Parameters
    ----------
    version : VersionArg
        Version identifier for the staged index (e.g., "v1.0.0"). The version
        is used to create a versioned directory in the lifecycle root. Must be
        a valid version string.
    assets : AssetsArg
        Tuple of three primary asset paths: (FAISS index, DuckDB catalog, SCIP
        index). These are the required assets for index functionality. Paths
        are resolved to absolute paths before staging.
    extras : ExtraOption
        List of extra channel indices to include (e.g., BM25, SPLADE). Each
        extra is a path to an additional index file that extends the base
        functionality. Extras are optional and can be empty.
    sidecars : SidecarOption
        List of sidecar file paths to include with the staged version. Sidecars
        are additional files (e.g., metadata, configuration) that are staged
        alongside the primary assets. Can be empty if no sidecars are needed.

    Raises
    ------
    typer.BadParameter
        Raised when the primary assets are not provided in the expected order
        or when asset paths cannot be resolved. The error includes details about
        which assets are missing or invalid.
    """
    mgr = _manager()
    channels = _parse_extras(list(extras))
    resolved_assets = tuple(path.expanduser().resolve() for path in assets)
    if len(resolved_assets) != _PRIMARY_ASSET_COUNT:  # defensive: typer should enforce length
        msg = "Provide FAISS, DuckDB, and SCIP asset paths."
        raise typer.BadParameter(msg)
    faiss_index, duckdb_path, scip_index = resolved_assets
    sidecar_paths = _parse_sidecars(list(sidecars))
    staged_assets = _build_assets(
        (faiss_index, duckdb_path, scip_index),
        channels,
        sidecar_paths,
    )
    staging = mgr.prepare(version, staged_assets, attrs=collect_asset_attrs(staged_assets))
    typer.echo(f"Staged assets at {staging}")


@app.command("publish")
def publish_command(
    version: VersionArg,
) -> None:
    """Publish a previously staged version.

    Parameters
    ----------
    version : VersionArg
        Version identifier of the staged version to publish. The version must
        have been previously staged using the stage command. Publishing makes
        the version the active version and updates the CURRENT symlink.
    """
    mgr = _manager()
    final_dir = mgr.publish(version)
    typer.echo(f"Published version {version} -> {final_dir}")


@app.command("rollback")
def rollback_command(
    version: VersionArg,
) -> None:
    """Rollback to a previously published version.

    Parameters
    ----------
    version : VersionArg
        Version identifier to rollback to. The version must have been previously
        published. Rolling back makes the specified version the active version
        and updates the CURRENT symlink.
    """
    mgr = _manager()
    mgr.rollback(version)
    typer.echo(f"Rolled back to {version}")


@app.command("ls")
def list_command() -> None:
    """List all published versions."""
    mgr = _manager()
    versions = mgr.list_versions()
    if not versions:
        typer.echo("No versions published")
        return
    for version in versions:
        typer.echo(version)


@app.command("health")
def health_command(
    index: IndexOption = None,
    duckdb: DuckOption = None,
    idmap: IdMapOption | None = None,
) -> None:
    """Validate FAISS, DuckDB, and ID map invariants.

    Parameters
    ----------
    index : IndexOption, optional
        Path to FAISS index file to validate. If None, uses configured default
        index path.
    duckdb : DuckOption, optional
        Path to DuckDB catalog file to validate. If None, uses configured default
        DuckDB path.
    idmap : IdMapOption | None, optional
        Path to FAISS ID map Parquet file to validate. If None, uses configured
        default ID map path.

    Notes
    -----
    Prints JSON health check results to stdout including dimension matches,
    row count matches, and view validation status.
    """
    app_config = _get_app_config()
    manager = _faiss_manager(index)
    catalog = _duckdb_catalog(duckdb)
    paths = resolve_application_paths(app_config)
    idmap_path = (idmap or Path(paths.faiss_idmap_path)).expanduser().resolve()
    faiss_dim = manager.vec_dim
    duck_dim = _duckdb_embedding_dim(catalog)
    cpu_index = manager.require_cpu_index()
    faiss_rows = getattr(cpu_index, "ntotal", 0)
    checks: dict[str, dict[str, object]] = {}
    checks["faiss_dim_match"] = {
        "ok": faiss_dim == duck_dim,
        "faiss_dim": faiss_dim,
        "duckdb_dim": duck_dim,
    }
    try:
        idmap_rows = _count_idmap_rows(idmap_path)
    except (RuntimeError, OSError, ValueError) as exc:  # pragma: no cover - optional deps
        checks["idmap_size_match"] = {
            "ok": False,
            "error": str(exc),
            "idmap_path": str(idmap_path),
        }
    else:
        checks["idmap_size_match"] = {
            "ok": idmap_rows == faiss_rows,
            "idmap_rows": idmap_rows,
            "faiss_rows": faiss_rows,
        }
    try:
        catalog.ensure_faiss_idmap_views(idmap_path if idmap_path.exists() else None)
        with catalog.connection() as conn:
            conn.execute("SELECT COUNT(*) FROM v_faiss_join LIMIT 1").fetchone()
    except (
        duckdb_mod.Error,
        RuntimeError,
        ValueError,
    ) as exc:  # pragma: no cover - DuckDB failures
        checks["duckdb_views_ok"] = {"ok": False, "error": str(exc)}
    else:
        checks["duckdb_views_ok"] = {"ok": True}
    try:
        chunk_count = catalog.count_chunks()
    except (duckdb_mod.Error, RuntimeError, ValueError) as exc:  # pragma: no cover - schema drift
        checks["duckdb_schema_ok"] = {"ok": False, "error": str(exc)}
    else:
        checks["duckdb_schema_ok"] = {"ok": chunk_count >= 0, "chunks": chunk_count}
    overall = all(entry.get("ok") for entry in checks.values())
    payload = {"ok": overall, "checks": checks, "idmap_path": str(idmap_path)}
    catalog.close()
    typer.echo(json.dumps(payload, indent=2))


@app.command("export-idmap")
def export_idmap_command(
    index: IndexOption = None,
    out: OutOption = None,
    duckdb: DuckOption = None,
) -> None:
    """Export FAISS ID map to Parquet and optionally refresh DuckDB materialization.

    Parameters
    ----------
    index : IndexOption, optional
        Path to FAISS index file to export ID map from. If None, uses configured
        default index path.
    out : OutOption, optional
        Output path for the exported ID map Parquet file. If None, uses configured
        default ID map path.
    duckdb : DuckOption, optional
        Optional DuckDB catalog path. If provided, refreshes the materialized
        FAISS join view after exporting the ID map. If None, only exports the
        ID map without updating DuckDB.
    """
    app_config = _get_app_config()
    manager = _faiss_manager(index)
    paths = resolve_application_paths(app_config)
    destination = (out or Path(paths.faiss_idmap_path)).expanduser().resolve()
    rows = manager.export_idmap(destination)
    typer.echo(f"Exported {rows} FAISS rows -> {destination}")
    if duckdb is not None:
        catalog = _duckdb_catalog(duckdb)
        stats = catalog.register_idmap_parquet(destination, materialize=True)
        typer.echo(
            f"Materialized join rows={stats['rows']} "
            f"checksum={stats['checksum']} refreshed={stats['refreshed']}"
        )


@app.command("materialize-join")
def materialize_join_command(
    idmap: IdMapOption,
    duckdb: DuckOption = None,
) -> None:
    """Refresh DuckDB's materialized FAISS join if the ID map sidecar changed.

    Parameters
    ----------
    idmap : IdMapOption
        Path to FAISS ID map Parquet file. The file is checked for changes, and
        if modified, the materialized join view is refreshed.
    duckdb : DuckOption, optional
        Path to DuckDB catalog file. If None, uses configured default DuckDB path.
    """
    catalog = _duckdb_catalog(duckdb)
    stats = catalog.refresh_faiss_idmap_mat_if_changed(idmap.expanduser().resolve())
    catalog.ensure_faiss_idmap_views(idmap)
    catalog.materialize_faiss_join()
    typer.echo(f"Refreshed={stats['refreshed']} rows={stats['rows']} checksum={stats['checksum']}")


@app.command(
    "tune",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def tune_command(
    ctx: typer.Context,
    index: IndexOption = None,
    sweep: Annotated[
        SweepMode | None,
        SWEEP_OPTION,
    ] = None,
) -> None:
    """Apply FAISS tuning overrides or run an autotune sweep.

    This command applies FAISS search parameter overrides (nprobe, ef_search,
    quantizer_ef_search, k_factor) or runs an autotune sweep to find optimal
    parameters. The command can apply immediate overrides via command-line
    arguments or run a parameter sweep to discover optimal settings. Tuning
    profiles are saved for future use.

    Parameters
    ----------
    ctx : typer.Context
        Typer context object providing access to command-line arguments and
        shared CLI state. Used to parse tuning overrides from ctx.args.
    index : IndexOption, optional
        Path to the FAISS index to tune. If None, uses the active index from
        configuration. The index must exist and be loadable for tuning operations.
    sweep : Annotated[SweepMode | None, SWEEP_OPTION], optional
        Sweep mode to use for autotune (e.g., "quick", "full"). If None, applies
        overrides from command-line arguments instead of running a sweep. When
        provided, runs an autotune sweep to discover optimal parameters. The
        parameter is annotated with SWEEP_OPTION for Typer CLI integration.

    Raises
    ------
    typer.BadParameter
        Raised in the following cases:
        - Conflicting sweep modes: both --sweep flag and inferred sweep mode
          are provided with different values
        - Missing overrides: no tuning overrides provided and no sweep mode
          specified (at least one override or sweep mode is required)
    """
    overrides, inferred_sweep = _parse_tune_overrides(list(ctx.args))
    if sweep is not None and inferred_sweep is not None and sweep != inferred_sweep:
        msg = "Conflicting sweep modes provided via flags."
        raise typer.BadParameter(msg)
    sweep_mode = sweep or inferred_sweep
    manager = _faiss_manager(index)
    if sweep_mode is not None:
        _run_autotune(manager, mode=sweep_mode)
        typer.echo(f"Saved tuning profile -> {manager.autotune_profile_path}")
        return
    if not overrides:
        msg = (
            "Provide at least one override (--nprobe, --ef-search, "
            "--quantizer-ef-search, --k-factor) or specify --sweep."
        )
        raise typer.BadParameter(msg)
    nprobe_override = overrides.get("nprobe")
    ef_override = overrides.get("ef_search")
    quantizer_override = overrides.get("quantizer_ef_search")
    k_factor_override = overrides.get("k_factor")
    tuning = manager.runtime.apply_runtime_tuning(
        nprobe=int(nprobe_override) if nprobe_override is not None else None,
        ef_search=int(ef_override) if ef_override is not None else None,
        quantizer_ef_search=int(quantizer_override) if quantizer_override is not None else None,
        k_factor=float(k_factor_override) if k_factor_override is not None else None,
    )
    audit_path = _write_tuning_audit(manager, tuning)
    typer.echo(f"Wrote runtime tuning snapshot -> {audit_path}")


@app.command("tune-params")
def tune_params_command(
    params: ParamSpaceArg,
    index: IndexOption = None,
) -> None:
    """Apply FAISS ParameterSpace string (nprobe/efSearch/quantizer/k_factor).

    This command applies FAISS search parameters from a ParameterSpace string
    format. The string specifies tuning parameters as key-value pairs (e.g.,
    "nprobe=64,efSearch=128"). The command validates the parameters, applies
    them to the FAISS manager, and writes an audit log of the tuning changes.

    Parameters
    ----------
    params : ParamSpaceArg
        ParameterSpace string containing FAISS tuning parameters in key=value
        format (e.g., "nprobe=64,efSearch=128,quantizer_ef_search=256,k_factor=1.5").
        Supported keys: nprobe, efSearch, quantizer_ef_search, k_factor.
        The string is parsed and validated before application.
    index : IndexOption, optional
        Path to the FAISS index to tune. If None, uses the active index from
        configuration. The index must exist and be loadable for parameter
        application.

    Raises
    ------
    typer.BadParameter
        Raised when the ParameterSpace string includes unsupported keys or
        invalid parameter values. The error includes details about which keys
        are unsupported or which values are invalid. Wraps ValueError from
        FAISS manager parameter validation.
    """
    manager = _faiss_manager(index)
    try:
        tuning = manager.runtime.set_search_parameters(params)
    except ValueError as exc:
        msg = str(exc)
        raise typer.BadParameter(msg) from exc
    audit_path = _write_tuning_audit(manager, tuning)
    typer.echo(f"Wrote runtime tuning snapshot -> {audit_path}")


@app.command("show-profile")
def show_profile_command(index: IndexOption = None) -> None:
    """Print the active tuning profile, overrides, and saved ParameterSpace."""
    manager = _faiss_manager(index)
    typer.echo(json.dumps(manager.runtime.get_runtime_tuning(), indent=2))


def _write_tuning_audit(manager: FAISSManager, tuning: dict[str, object]) -> Path:
    """Write FAISS tuning audit file with JSON formatting.

    This function writes a tuning audit file containing FAISS autotune results
    and parameter configurations. The audit file is co-located with the FAISS
    index file, using the same base name with ".audit.json" extension.

    Parameters
    ----------
    manager : FAISSManager
        FAISS manager instance providing index path for audit file location.
        The audit file is written next to the index file.
    tuning : dict[str, object]
        Tuning dictionary containing autotune results, parameter configurations,
        and performance metrics. The dictionary is serialized to JSON with
        pretty-printed formatting.

    Returns
    -------
    Path
        Path where the audit file was written. The path is resolved to absolute
        form and includes the ".audit.json" extension.

    Notes
    -----
    Tuning audit writing enables tracking of FAISS autotune results and parameter
    configurations. The audit file is co-located with the index file, enabling
    easy discovery and association. The function creates parent directories if
    needed and writes pretty-printed JSON for readability.
    """
    audit_path = manager.index_path.with_suffix(".audit.json").expanduser().resolve()
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(tuning, indent=2) + "\n", encoding="utf-8")
    return audit_path


_AUTOTUNE_SAMPLE_LIMITS = {"quick": 64, "full": 256}
_AUTOTUNE_MIN_SAMPLES = 4


def _run_autotune(manager: FAISSManager, mode: SweepMode) -> None:
    """Run FAISS autotune with query sampling and parameter sweep.

    This function runs FAISS autotune by sampling query vectors from the DuckDB
    catalog, selecting sweep values based on mode, and invoking the manager's
    autotune method. The function validates that sufficient vectors are available
    before running autotune.

    Parameters
    ----------
    manager : FAISSManager
        FAISS manager instance to autotune. The manager must have an active index
        and support autotune operations.
    mode : SweepMode
        Autotune sweep mode ("quick" or "full"). Quick mode uses fewer samples
        and sweep values for faster execution. Full mode uses more samples and
        sweep values for comprehensive tuning.

    Raises
    ------
    typer.BadParameter
        Raised when insufficient vectors are available in the DuckDB catalog for
        autotune. The error message indicates the minimum required vectors and
        the number found.

    Notes
    -----
    Autotune execution enables automatic FAISS parameter optimization by testing
    different parameter combinations and selecting optimal values. The function
    samples query vectors from the catalog to use as autotune queries, ensuring
    realistic performance evaluation. Sweep values are selected based on mode,
    with quick mode using fewer values for faster execution and full mode using
    more values for comprehensive tuning.
    """
    catalog = _duckdb_catalog()
    try:
        samples = catalog.sample_query_vectors(limit=_AUTOTUNE_SAMPLE_LIMITS[mode])
    finally:
        catalog.close()
    if len(samples) < _AUTOTUNE_MIN_SAMPLES:
        msg = (
            f"Need at least {_AUTOTUNE_MIN_SAMPLES} vectors in DuckDB catalog for {mode} "
            f"autotune (found {len(samples)})."
        )
        raise typer.BadParameter(msg)
    vectors = np.stack([vec for _, vec in samples], dtype=np.float32)
    queries = vectors[: min(32, vectors.shape[0])]
    sweep_values = (16, 32, 48, 64, 96, 128) if mode == "quick" else (16, 32, 64, 96, 128, 192, 256)
    sweep = tuple(f"nprobe={value}" for value in sweep_values)
    index_cfg = _get_app_config().index
    manager.autotune(
        queries,
        vectors,
        k=min(int(index_cfg.default_k), queries.shape[0]),
        sweep=sweep,
    )


@app.command("eval")
def eval_command(
    k: EvalTopKOption = 10,
    k_factor: EvalKFactorOption = 2.0,
    nprobe: EvalNProbeOption = None,
    xtr_oracle: EvalXtrOracleOption = DEFAULT_XTR_ORACLE,
) -> None:
    """Run ANN vs Flat evaluation and optionally rescore with XTR."""
    app_config = _get_app_config()
    eval_settings = app_config.eval
    manager = _faiss_manager()
    catalog = _duckdb_catalog()
    xtr_index = _load_xtr_index(app_config) if xtr_oracle else None
    pool_path, metrics_path = _eval_paths(eval_settings.output_dir)
    config = EvalConfig(
        k=k,
        k_factor=k_factor,
        nprobe=nprobe,
        max_queries=eval_settings.max_queries,
        use_xtr_oracle=bool(xtr_index and xtr_oracle),
        pool_path=pool_path,
        metrics_path=metrics_path,
    )
    evaluator = HybridPoolEvaluator(catalog, manager, xtr_index=xtr_index)
    report = evaluator.run(config)
    with suppress(OSError, RuntimeError, ValueError):  # pragma: no cover - defensive logging
        catalog.ensure_pool_views(pool_path)
    typer.echo(json.dumps(report.__dict__, indent=2))


def _execute_search(params: SearchCommandParams) -> None:
    """Execute ANN + refine search for newline-delimited queries.

    Parameters
    ----------
    params : SearchCommandParams
        Search command parameters including queries file path, search options,
        and index/catalog paths.

    Raises
    ------
    typer.BadParameter
        Raised when the queries file cannot be read.
    """
    app_config = _get_app_config()
    manager = _faiss_manager(params.index)
    catalog = _duckdb_catalog(params.duckdb)
    embedder = _embedding_provider(app_config)
    runtime = SearchRuntimeOverrides()
    try:
        try:
            lines = params.queries.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            msg = f"Unable to read queries file: {exc}"
            raise typer.BadParameter(msg) from exc
        summary: list[dict[str, object]] = []

        def _summarize_query(raw_line: str) -> dict[str, object] | None:
            """Summarize search results for a single query.

            This nested function processes a single query line by embedding it,
            performing ANN search, refining results, and computing overlap statistics.
            The function returns a summary dictionary containing query text, ANN results,
            refined results, and overlap metrics.

            Parameters
            ----------
            raw_line : str
                Raw query line from input file. The line is stripped of whitespace
                and used as the search query. Empty lines return None.

            Returns
            -------
            dict[str, object] | None
                Summary dictionary containing query text, ANN IDs and scores, refined
                hits with metadata, and overlap count. Returns None if query line is
                empty after stripping.

            Notes
            -----
            Query summarization enables detailed search result analysis by capturing
            both ANN and refined search results along with overlap metrics. The function
            performs both ANN search and refined search to compare results, enabling
            evaluation of refinement effectiveness. Overlap metrics help quantify
            the agreement between ANN and refined results.
            """
            query = raw_line.strip()
            if not query:
                return None
            vectors = embedder.embed_texts([query])
            ann_dists, ann_ids = manager.search(
                vectors,
                k=params.k,
                nprobe=params.nprobe,
                runtime=runtime,
                catalog=None,
            )
            ann_dist_row = [float(score) for score in ann_dists[0].tolist()]
            ann_ids_row = [int(chunk_id) for chunk_id in ann_ids[0].tolist() if chunk_id >= 0]
            refined_hits = manager.search_with_refine(
                vectors,
                k=params.k,
                catalog=catalog,
                config=RefineSearchConfig(
                    nprobe=params.nprobe,
                    runtime=runtime,
                    source="faiss_refine" if manager.refine_k_factor > 1.0 else "faiss",
                ),
            )
            refined_ids = [int(hit.doc_id) for hit in refined_hits]
            overlap = len(set(ann_ids_row) & set(refined_ids))
            return {
                "query": query,
                "ann_ids": ann_ids_row,
                "ann_scores": ann_dist_row,
                "refined_hits": [
                    {
                        "doc_id": hit.doc_id,
                        "rank": hit.rank,
                        "score": hit.score,
                        "source": hit.source,
                        "faiss_row": hit.faiss_row,
                        "explain": dict(hit.explain),
                    }
                    for hit in refined_hits
                ],
                "overlap": overlap,
            }

        for raw_line in lines:
            entry = _summarize_query(raw_line)
            if entry is not None:
                summary.append(entry)
    finally:
        embedder.close()
        catalog.close()
    typer.echo(json.dumps({"dry_run": params.dry_run, "results": summary}, indent=2))
