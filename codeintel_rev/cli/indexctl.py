"""Typer CLI for managing index lifecycle operations."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, cast

import click
import duckdb
import numpy as np
import typer

from codeintel_rev.config.settings import Settings, load_settings
from codeintel_rev.embeddings import EmbeddingProvider, get_embedding_provider
from codeintel_rev.errors import RuntimeLifecycleError
from codeintel_rev.eval.hybrid_evaluator import EvalConfig, HybridPoolEvaluator
from codeintel_rev.indexing.cast_chunker import Chunk
from codeintel_rev.indexing.index_lifecycle import (
    IndexAssets,
    IndexLifecycleManager,
    collect_asset_attrs,
)
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager, SearchRuntimeOverrides
from codeintel_rev.io.parquet_store import (
    ParquetWriteOptions,
    extract_embeddings,
    read_chunks_parquet,
    write_chunks_parquet,
)
from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.typing import NDArrayF32
from kgfoundry_common.logging import get_logger

try:  # pragma: no cover - optional dependency
    import pyarrow.parquet as pyarrow_parquet
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pyarrow_parquet = None

LOGGER = get_logger(__name__)
app = typer.Typer(help="Manage versioned FAISS/DuckDB/SCIP assets.", no_args_is_help=True)
DEFAULT_XTR_ORACLE = False
embeddings_app = typer.Typer(help="Embedding lifecycle commands.", no_args_is_help=True)
app.add_typer(embeddings_app, name="embeddings")


@lru_cache(maxsize=1)
def _get_settings() -> Settings:
    """Load settings once and reuse for subsequent commands.

    Returns
    -------
    Settings
        Cached settings object.
    """
    return load_settings()


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
    """Configure shared CLI options."""
    ctx.obj = {"root": root}


def _default_root() -> Path:
    env = os.getenv("CODEINTEL_INDEXES_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path("indexes").resolve()


def _resolve_root(ctx: click.Context, explicit_root: Path | None = None) -> Path:
    root_from_ctx = ctx.obj.get("root") if ctx.obj else None
    resolved_root = explicit_root or root_from_ctx or _default_root()
    return resolved_root.resolve()


def _manager(explicit_root: Path | None = None) -> IndexLifecycleManager:
    ctx = click.get_current_context()
    return IndexLifecycleManager(_resolve_root(ctx, explicit_root))


def _build_assets(
    primaries: tuple[Path, Path, Path],
    channels: dict[str, Path],
    sidecars: dict[str, Path],
) -> IndexAssets:
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
    parsed: dict[str, Path] = {}
    for entry in extras:
        if "=" not in entry:
            LOGGER.warning("Ignoring malformed --extra entry", extra={"entry": entry})
            continue
        key, value = entry.split("=", maxsplit=1)
        parsed[key.strip().lower()] = Path(value).expanduser().resolve()
    return parsed


def _parse_sidecars(entries: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    allowed = {"faiss_idmap", "tuning"}
    for entry in entries:
        if "=" not in entry:
            LOGGER.warning("Ignoring malformed --sidecar entry", extra={"entry": entry})
            continue
        key, value = entry.split("=", maxsplit=1)
        normalized = key.strip().lower()
        if normalized not in allowed:
            LOGGER.warning(
                "Ignoring unsupported sidecar entry",
                extra={"entry": entry, "allowed": sorted(allowed)},
            )
            continue
        parsed[normalized] = Path(value).expanduser().resolve()
    return parsed


def _resolve_version_dir(manager: IndexLifecycleManager, version: str | None) -> Path | None:
    if version:
        candidate = manager.versions_dir / version
        if not candidate.exists():
            msg = f"Version {version!r} does not exist under {manager.versions_dir}"
            raise typer.BadParameter(msg)
        return candidate
    return manager.current_dir()


def _manifest_path_for(output_path: Path) -> Path:
    return output_path.with_suffix(".manifest.json")


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        LOGGER.warning("Malformed manifest file ignored", extra={"path": str(path)})
        return {}


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


@dataclass(slots=True, frozen=False)
class _EmbeddingBuildContext:
    settings: Settings
    manager: IndexLifecycleManager
    version: str | None
    version_dir: Path | None
    duck_path: Path
    output_path: Path
    manifest_path: Path


def _build_context(
    settings: Settings,
    manager: IndexLifecycleManager,
    *,
    version: str | None,
    duckdb_path: Path | None,
    output: Path | None,
) -> _EmbeddingBuildContext:
    version_dir = _resolve_version_dir(manager, version)
    duck_path = _resolve_duck_path(settings, version_dir, duckdb_path)
    output_path = _resolve_output_path(
        settings,
        version_dir,
        output,
        ensure_parent=True,
    )
    manifest_path = _manifest_path_for(output_path)
    return _EmbeddingBuildContext(
        settings=settings,
        manager=manager,
        version=version,
        version_dir=version_dir,
        duck_path=duck_path,
        output_path=output_path,
        manifest_path=manifest_path,
    )


def _resolve_duck_path(
    settings: Settings,
    version_dir: Path | None,
    override: Path | None,
) -> Path:
    if override is not None:
        duck_path = override.expanduser().resolve()
    elif version_dir is not None:
        duck_path = (version_dir / "catalog.duckdb").resolve()
    else:
        duck_path = Path(settings.paths.duckdb_path).expanduser().resolve()
    if not duck_path.exists():
        msg = f"DuckDB catalog not found: {duck_path}"
        raise typer.BadParameter(msg)
    return duck_path


def _resolve_output_path(
    settings: Settings,
    version_dir: Path | None,
    override: Path | None,
    *,
    ensure_parent: bool,
) -> Path:
    if override is not None:
        output_path = override.expanduser().resolve()
    elif version_dir is not None:
        output_path = (version_dir / "embeddings.parquet").resolve()
    else:
        output_path = (
            Path(settings.paths.vectors_dir).expanduser() / "embeddings.parquet"
        ).resolve()
    if ensure_parent:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def _parquet_meta(provider: EmbeddingProvider) -> dict[str, str]:
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
    settings: Settings,
) -> dict[str, object]:
    meta = provider.metadata
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
        "batch_size": settings.embeddings.batch_size,
        "micro_batch_size": settings.embeddings.micro_batch_size,
        "output_path": str(output_path),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _compute_chunk_checksum(manager: DuckDBManager, *, batch_size: int = 2048) -> tuple[str, int]:
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
    settings = context.settings
    provider = get_embedding_provider(settings)
    db_manager = DuckDBManager(context.duck_path, settings.duckdb)
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
                preview_max_chars=settings.index.preview_max_chars,
                id_strategy="stable_hash",
                table_meta=_parquet_meta(provider),
            ),
        )
        manifest_payload = _build_embedding_manifest(
            provider,
            checksum=checksum,
            vector_count=len(chunks),
            output_path=context.output_path,
            settings=settings,
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
    settings: Settings,
) -> None:
    table = read_chunks_parquet(parquet_path)
    embeddings = extract_embeddings(table)
    total_rows = embeddings.shape[0]
    if total_rows == 0:
        typer.echo("Parquet file is empty; nothing to validate.")
        return
    sample_size = min(samples, total_rows)
    contents = cast("list[str]", table.column("content").to_pylist())
    indices = _deterministic_sample(total_rows, sample_size)

    provider = get_embedding_provider(settings)
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
    try:
        manager.write_embedding_metadata(payload, version=version)
    except RuntimeLifecycleError:
        LOGGER.debug(
            "No version directory available for embedding metadata", extra={"version": version}
        )


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
    """Embed chunks from DuckDB and write Parquet + manifest artifacts."""
    settings = _get_settings()
    manager = _manager()
    context = _build_context(
        settings,
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
    settings = _get_settings()
    manager = _manager()
    version_dir = _resolve_version_dir(manager, version)
    parquet_path = _resolve_output_path(
        settings,
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
        settings=settings,
    )


def _parse_tune_overrides(
    raw_args: Sequence[str],
) -> tuple[dict[str, float | int], SweepMode | None]:
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
    settings = _get_settings()
    index_path = (index_override or Path(settings.paths.faiss_index)).expanduser().resolve()
    nlist = int(settings.index.nlist or settings.index.faiss_nlist)
    manager = FAISSManager(
        index_path=index_path,
        vec_dim=settings.index.vec_dim,
        nlist=nlist,
        use_cuvs=settings.index.use_cuvs,
    )
    manager.load_cpu_index()
    return manager


def _duckdb_catalog(path_override: Path | None = None) -> DuckDBCatalog:
    settings = _get_settings()
    db_path = (path_override or Path(settings.paths.duckdb_path)).expanduser().resolve()
    vectors_dir = Path(settings.paths.vectors_dir).expanduser().resolve()
    catalog = DuckDBCatalog(
        db_path=db_path,
        vectors_dir=vectors_dir,
        repo_root=Path(settings.paths.repo_root).expanduser().resolve(),
        materialize=settings.index.duckdb_materialize,
    )
    catalog.set_idmap_path(Path(settings.paths.faiss_idmap_path).expanduser().resolve())
    return catalog


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
    with catalog.connection() as conn:
        row = conn.execute("SELECT embedding FROM chunks LIMIT 1").fetchone()
    if not row or row[0] is None:
        return 0
    embedding = row[0]
    try:
        return len(embedding)
    except TypeError:
        return 0


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

    Raises
    ------
    RuntimeError
        Raised when pyarrow is not installed. pyarrow is required to read
        Parquet metadata and determine the row count.
    """
    if not path.exists():
        return 0
    if pyarrow_parquet is None:
        msg = "pyarrow is required to inspect the ID map sidecar"
        raise RuntimeError(msg)
    metadata = pyarrow_parquet.ParquetFile(path).metadata
    return metadata.num_rows if metadata is not None else 0


def _load_xtr_index(settings: Settings) -> XTRIndex | None:
    if not settings.xtr.enable:
        return None
    root = Path(settings.paths.xtr_dir).expanduser().resolve()
    index = XTRIndex(root=root, config=settings.xtr)
    try:
        index.open()
    except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive logging
        LOGGER.warning("Failed to open XTR index", extra={"root": str(root), "error": str(exc)})
        return None
    if not index.ready:
        LOGGER.warning("XTR index not ready", extra={"root": str(root)})
        return None
    return index


def _eval_paths(settings: Settings) -> tuple[Path, Path]:
    base_dir = Path(settings.eval.output_dir).expanduser().resolve()
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
    """Publish a previously staged version."""
    mgr = _manager()
    final_dir = mgr.publish(version)
    typer.echo(f"Published version {version} -> {final_dir}")


@app.command("rollback")
def rollback_command(
    version: VersionArg,
) -> None:
    """Rollback to a previously published version."""
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
    """Validate FAISS, DuckDB, and ID map invariants."""
    settings = _get_settings()
    manager = _faiss_manager(index)
    catalog = _duckdb_catalog(duckdb)
    idmap_path = (idmap or Path(settings.paths.faiss_idmap_path)).expanduser().resolve()
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
    except (duckdb.Error, RuntimeError, ValueError) as exc:  # pragma: no cover - DuckDB failures
        checks["duckdb_views_ok"] = {"ok": False, "error": str(exc)}
    else:
        checks["duckdb_views_ok"] = {"ok": True}
    try:
        chunk_count = catalog.count_chunks()
    except (duckdb.Error, RuntimeError, ValueError) as exc:  # pragma: no cover - schema drift
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
    """Export FAISS ID map to Parquet and optionally refresh DuckDB materialization."""
    settings = _get_settings()
    manager = _faiss_manager(index)
    destination = (out or Path(settings.paths.faiss_idmap_path)).expanduser().resolve()
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
    """Refresh DuckDB's materialized FAISS join if the ID map sidecar changed."""
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
    tuning = manager.apply_runtime_tuning(
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
        tuning = manager.set_search_parameters(params)
    except ValueError as exc:
        msg = str(exc)
        raise typer.BadParameter(msg) from exc
    audit_path = _write_tuning_audit(manager, tuning)
    typer.echo(f"Wrote runtime tuning snapshot -> {audit_path}")


@app.command("show-profile")
def show_profile_command(index: IndexOption = None) -> None:
    """Print the active tuning profile, overrides, and saved ParameterSpace."""
    manager = _faiss_manager(index)
    typer.echo(json.dumps(manager.get_runtime_tuning(), indent=2))


def _write_tuning_audit(manager: FAISSManager, tuning: dict[str, object]) -> Path:
    audit_path = manager.index_path.with_suffix(".audit.json").expanduser().resolve()
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(tuning, indent=2) + "\n", encoding="utf-8")
    return audit_path


_AUTOTUNE_SAMPLE_LIMITS = {"quick": 64, "full": 256}
_AUTOTUNE_MIN_SAMPLES = 4


def _run_autotune(manager: FAISSManager, mode: SweepMode) -> None:
    settings = _get_settings()
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
    manager.autotune(
        queries,
        vectors,
        k=min(int(settings.index.default_k), queries.shape[0]),
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
    settings = _get_settings()
    manager = _faiss_manager()
    catalog = _duckdb_catalog()
    xtr_index = _load_xtr_index(settings) if xtr_oracle else None
    pool_path, metrics_path = _eval_paths(settings)
    config = EvalConfig(
        k=k,
        k_factor=k_factor,
        nprobe=nprobe,
        max_queries=settings.eval.max_queries,
        use_xtr_oracle=bool(xtr_index and xtr_oracle),
        pool_path=pool_path,
        metrics_path=metrics_path,
    )
    evaluator = HybridPoolEvaluator(catalog, manager, xtr_index=xtr_index)
    report = evaluator.run(config)
    try:
        catalog.ensure_pool_views(pool_path)
    except (OSError, RuntimeError, ValueError) as exc:  # pragma: no cover - defensive logging
        LOGGER.warning(
            "Unable to expose pool coverage views",
            extra={"pool_path": str(pool_path), "error": str(exc)},
        )
    typer.echo(json.dumps(report.__dict__, indent=2))


@app.command("search")
def search_command(
    queries: QueriesArg,
    k: EvalTopKOption = 10,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--write-pool", help="Skip pool artefact creation."),
    ] = True,
    nprobe: EvalNProbeOption = None,
    index: IndexOption = None,
    duckdb: DuckOption = None,
) -> None:
    """Execute ANN + refine search for newline-delimited queries and print a summary.

    Parameters
    ----------
    queries : QueriesArg
        Path to a file containing newline-delimited query strings. Each line
        is treated as a separate query and embedded for search.
    k : EvalTopKOption, optional
        Number of results to return per query (default: 10).
    dry_run : Annotated[bool, typer.Option("--dry-run/--write-pool")], optional
        If True, skip pool artifact creation and only print summary (default: True).
        When False, creates pool artifacts for evaluation.
    nprobe : EvalNProbeOption, optional
        Optional nprobe override for FAISS search (default: None).
    index : IndexOption, optional
        Optional path override for FAISS index (default: None).
    duckdb : DuckOption, optional
        Optional path override for DuckDB catalog (default: None).

    Raises
    ------
    typer.BadParameter
        Raised when the queries file cannot be read. The error includes the
        file path and the underlying I/O error message.
    """
    settings = _get_settings()
    manager = _faiss_manager(index)
    catalog = _duckdb_catalog(duckdb)
    embedder = get_embedding_provider(settings)
    runtime = SearchRuntimeOverrides()
    try:
        try:
            lines = queries.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            msg = f"Unable to read queries file: {exc}"
            raise typer.BadParameter(msg) from exc
        summary: list[dict[str, object]] = []
        for raw_line in lines:
            query = raw_line.strip()
            if not query:
                continue
            vectors = embedder.embed_texts([query])
            ann_dists, ann_ids = manager.search(
                vectors,
                k=k,
                nprobe=nprobe,
                runtime=runtime,
                catalog=None,
            )
            ann_ids_row = [int(chunk_id) for chunk_id in ann_ids[0].tolist() if chunk_id >= 0]
            refined_hits = manager.search_with_refine(
                vectors,
                k=k,
                catalog=catalog,
                nprobe=nprobe,
                runtime=runtime,
                source="faiss_refine" if manager.refine_k_factor > 1.0 else "faiss",
            )
            refined_ids = [hit.id for hit in refined_hits]
            overlap = len(set(ann_ids_row) & set(refined_ids))
            summary.append(
                {
                    "query": query,
                    "ann_ids": ann_ids_row,
                    "refined_hits": [
                        {
                            "id": hit.id,
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
            )
    finally:
        embedder.close()
        catalog.close()
    typer.echo(json.dumps({"dry_run": dry_run, "results": summary}, indent=2))
