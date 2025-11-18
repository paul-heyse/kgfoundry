# SPDX-License-Identifier: MIT
"""Shared enrichment pipeline contexts and dataclasses."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from codeintel_rev.config.paths import ResolvedPaths
from codeintel_rev.enrich.errors import StageError
from codeintel_rev.enrich.graph_builder import ImportGraph
from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.enrich.scip_reader import Document, SCIPIndex
from codeintel_rev.enrich.stubs_overlay import OverlayInputs, OverlayPolicy
from codeintel_rev.typedness import FileTypeSignals
from codeintel_rev.uses_builder import UseGraph

try:  # pragma: no cover - optional dependency
    import duckdb  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    duckdb = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from duckdb import DuckDBPyConnection
else:  # pragma: no cover - fallback when duckdb missing at runtime
    DuckDBPyConnection = Any

LOGGER = logging.getLogger(__name__)

EXPORT_HUB_THRESHOLD = 10
OVERLAY_PARAM_THRESHOLD = 0.8
OVERLAY_FAN_IN_THRESHOLD = 3
OVERLAY_ERROR_THRESHOLD = 5

DEFAULT_MIN_ERRORS = 25
DEFAULT_MAX_OVERLAYS = 200
DEFAULT_INCLUDE_PUBLIC_DEFS = False
DEFAULT_INJECT_GETATTR_ANY = True
DEFAULT_DRY_RUN = False
DEFAULT_ACTIVATE = True
DEFAULT_DEACTIVATE = False
DEFAULT_USE_TYPE_ERROR_OVERLAYS = False
DEFAULT_MAX_FILE_BYTES = 2_000_000
DEFAULT_OWNER_HISTORY_DAYS = 90
DEFAULT_COMMITS_WINDOW = 50
DEFAULT_ENABLE_OWNERS = True
DEFAULT_EMIT_SLICES_FLAG = False


def _format_stage_meta(metadata: Mapping[str, object]) -> str:
    """Return deterministic key-sorted metadata formatting.

    Extended Summary
    ----------------
    Formats metadata dictionary into a deterministic string representation
    sorted by key. Used for consistent logging and tracing of stage metadata
    throughout the enrichment pipeline.

    Parameters
    ----------
    metadata : Mapping[str, object]
        Metadata dictionary to format. Keys are sorted alphabetically for
        deterministic output.

    Returns
    -------
    str
        Stringified metadata payload sorted by key, formatted as "key=value"
        pairs separated by spaces.
    """
    parts = [f"{key}={metadata[key]}" for key in sorted(metadata)]
    return " ".join(parts)


@contextmanager
def _stage_span(stage: str, **start_meta: object) -> Iterator[dict[str, object]]:
    """Context manager logging structured stage timings.

    Extended Summary
    ----------------
    Provides a context manager that logs structured timing and metadata for
    enrichment pipeline stages. Logs start, finish, and error events with
    consistent formatting. Automatically tracks duration and propagates stage
    errors with context.

    Parameters
    ----------
    stage : str
        Stage name identifier for logging and error reporting.
    **start_meta : object
        Additional metadata key-value pairs to include in stage logs.

    Yields
    ------
    dict[str, object]
        Mutable payload dictionary for downstream metadata. Callers can add
        metrics or context that will be included in the finish log event.

    Raises
    ------
    StageError
        Raised when the wrapped block fails unexpectedly. Original exceptions
        are wrapped with stage context.
    """
    start = time.perf_counter()
    LOGGER.debug("stage=%s event=start %s", stage, _format_stage_meta(start_meta))
    outcome: dict[str, Any] = {}
    try:
        yield outcome
    except StageError as stage_exc:
        error_meta = {**start_meta, **stage_exc.log_extra()}
        LOGGER.exception("stage=%s event=error %s", stage, _format_stage_meta(error_meta))
        raise
    except Exception as exc:
        LOGGER.exception("stage=%s event=error %s", stage, _format_stage_meta(start_meta))
        detail = str(exc)
        raise StageError(
            stage,
            "unexpected-error",
            detail=detail,
            data=dict(start_meta),
        ) from exc
    finally:
        outcome.setdefault("duration_sec", round(time.perf_counter() - start, 3))
        LOGGER.info(
            "stage=%s event=finish %s",
            stage,
            _format_stage_meta({**start_meta, **outcome}),
        )


@dataclass(slots=True, frozen=True)
class StageMeta:
    """Structured metadata describing a stage run."""

    name: str
    start: Mapping[str, object] = field(default_factory=dict)


@contextmanager
def _stage(meta: StageMeta) -> Iterator[dict[str, object]]:
    """Run a stage using the shared span helper.

    Extended Summary
    ----------------
    Convenience wrapper around _stage_span that accepts a StageMeta dataclass.
    Provides the same structured logging and error handling for enrichment
    pipeline stages.

    Parameters
    ----------
    meta : StageMeta
        Stage metadata containing name and initial metadata dictionary.

    Yields
    ------
    dict[str, object]
        Mutable payload dictionary reflecting stage metrics. Callers can add
        metrics that will be included in the finish log event.
    """
    with _stage_span(meta.name, **meta.start) as payload:
        yield payload


@dataclass(slots=True, frozen=True)
class PipelineOptions:
    """Resolved paths and filters required for pipeline execution."""

    root: Path = Path()
    scip: Path | None = None
    out: Path = Path("codeintel_rev/io/ENRICHED")
    pyrefly_json: Path | None = None
    tags_yaml: Path | None = None
    coverage_xml: Path = Path("coverage.xml")
    only: tuple[str, ...] = ()
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES


@dataclass(slots=True, frozen=True)
class AnalyticsOptions:
    """Optional analytics toggles shared across commands."""

    owners: bool = DEFAULT_ENABLE_OWNERS
    history_window_days: int = DEFAULT_OWNER_HISTORY_DAYS
    commits_window: int = DEFAULT_COMMITS_WINDOW
    emit_slices: bool = DEFAULT_EMIT_SLICES_FLAG
    slices_filter: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class CLIContextState:
    """CLI-scoped state shared between commands."""

    pipeline: PipelineOptions = field(default_factory=PipelineOptions)
    analytics: AnalyticsOptions = field(default_factory=AnalyticsOptions)


@dataclass(slots=True)
class OverlayCLIOptions:
    """Mutable overlay generation options parsed from CLI/config."""

    stubs_root: Path = Path("stubs")
    overlays_root: Path = Path("stubs/overlays")
    min_errors: int = DEFAULT_MIN_ERRORS
    max_overlays: int = DEFAULT_MAX_OVERLAYS
    include_public_defs: bool = DEFAULT_INCLUDE_PUBLIC_DEFS
    inject_getattr_any: bool = DEFAULT_INJECT_GETATTR_ANY
    dry_run: bool = DEFAULT_DRY_RUN
    activate: bool = DEFAULT_ACTIVATE
    deactivate_all_first: bool = DEFAULT_DEACTIVATE
    type_error_overlays: bool = DEFAULT_USE_TYPE_ERROR_OVERLAYS


@dataclass(slots=True, frozen=True)
class OverlayContext:
    """Aggregated context used during overlay generation."""

    root: Path
    package_name: str
    overlays_root: Path
    stubs_root: Path
    scip_index: SCIPIndex
    type_counts: Mapping[str, int]
    policy: OverlayPolicy
    inputs: OverlayInputs


@dataclass(frozen=True)
class ScipContext:
    """Cache of SCIP lookups used during scanning."""

    index: SCIPIndex
    by_file: Mapping[str, Document]


@dataclass(frozen=True)
class ScanInputs:
    """Bundle of contextual inputs used during module row construction."""

    scip_ctx: ScipContext
    type_signals: Mapping[str, FileTypeSignals]
    coverage_map: Mapping[str, Mapping[str, float]]
    tagging_rules: Mapping[str, Any]
    repo_root: Path
    max_file_bytes: int
    package_prefix: str | None


@dataclass(slots=True, frozen=True)
class LegacyPipelineContext:
    """Aggregated context derived from CLI inputs and repo state."""

    root: Path
    repo_root: Path
    scip_index: SCIPIndex
    scip_ctx: ScipContext
    type_signals: Mapping[str, FileTypeSignals]
    coverage_map: Mapping[str, Mapping[str, float]]
    config_records: list[dict[str, Any]]
    tagging_rules: Mapping[str, Any]
    package_prefix: str | None


@dataclass(slots=True, frozen=True)
class PipelineResult:
    """Aggregate artifact bundle produced by a pipeline run."""

    root: Path
    repo_root: Path
    module_rows: list[ModuleRecord]
    symbol_edges: list[tuple[str, str]]
    import_graph: ImportGraph
    use_graph: UseGraph
    config_index: list[dict[str, Any]]
    coverage_rows: list[dict[str, Any]]
    hotspot_rows: list[dict[str, Any]]
    tag_index: dict[str, list[str]]


@dataclass(slots=True, frozen=True)
class PreparedPipeline:
    """Resolved pipeline context plus discovered files."""

    context: LegacyPipelineContext
    files: list[Path]


@dataclass(slots=True, frozen=True)
class AnalyticsArtifacts:
    """Derived analytics products emitted after scanning modules."""

    import_graph: ImportGraph
    use_graph: UseGraph
    config_index: list[dict[str, Any]]
    coverage_rows: list[dict[str, Any]]
    hotspot_rows: list[dict[str, Any]]
    tag_index: dict[str, list[str]]


@dataclass(slots=True, frozen=True)
class ConfigReferenceState:
    """Intermediate config reference tracking used during augmentation."""

    records: list[dict[str, Any]]
    by_dir: Mapping[str, tuple[str, ...]]
    references: dict[str, set[str]]


@dataclass(slots=True)
class PipelineContext:
    """Thin context used by the refactored enrich CLI."""

    paths: ResolvedPaths
    config: Mapping[str, Any]
    logger: logging.Logger
    db: DuckDBPyConnection | None = None

    @classmethod
    def from_paths(
        cls,
        paths: ResolvedPaths,
        *,
        config: Mapping[str, Any] | None = None,
        enable_db: bool = False,
        duckdb_path: str | None = None,
    ) -> PipelineContext:
        """Build a context from resolved application paths.

        Returns
        -------
        PipelineContext
            Newly constructed context.

        Raises
        ------
        RuntimeError
            Raised when ``enable_db`` is ``True`` but DuckDB is unavailable.
        """
        logger = logging.getLogger("enrich")
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
        conn = None
        if enable_db:
            if duckdb is None:  # pragma: no cover - optional dependency
                message = "DuckDB not available; install the duckdb extra."
                raise RuntimeError(message)
            target = duckdb_path or str(paths.data_dir / "enrich.duckdb")
            conn = duckdb.connect(target)
        return cls(paths=paths, config=config or {}, logger=logger, db=conn)

    def close(self) -> None:
        """Close the optional DuckDB connection."""
        if self.db is not None:
            self.db.close()


__all__ = [
    "DEFAULT_ACTIVATE",
    "DEFAULT_COMMITS_WINDOW",
    "DEFAULT_DEACTIVATE",
    "DEFAULT_DRY_RUN",
    "DEFAULT_EMIT_SLICES_FLAG",
    "DEFAULT_ENABLE_OWNERS",
    "DEFAULT_INCLUDE_PUBLIC_DEFS",
    "DEFAULT_INJECT_GETATTR_ANY",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_OVERLAYS",
    "DEFAULT_MIN_ERRORS",
    "DEFAULT_OWNER_HISTORY_DAYS",
    "DEFAULT_USE_TYPE_ERROR_OVERLAYS",
    "EXPORT_HUB_THRESHOLD",
    "OVERLAY_ERROR_THRESHOLD",
    "OVERLAY_FAN_IN_THRESHOLD",
    "OVERLAY_PARAM_THRESHOLD",
    "AnalyticsArtifacts",
    "AnalyticsOptions",
    "CLIContextState",
    "ConfigReferenceState",
    "LegacyPipelineContext",
    "OverlayCLIOptions",
    "OverlayContext",
    "PipelineContext",
    "PipelineOptions",
    "PipelineResult",
    "PreparedPipeline",
    "ScanInputs",
    "ScipContext",
    "StageMeta",
    "_format_stage_meta",
    "_stage",
    "_stage_span",
]
