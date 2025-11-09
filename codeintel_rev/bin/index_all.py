#!/usr/bin/env python3
"""One-shot indexing: SCIP → chunk → embed → Parquet → FAISS.

This script orchestrates the full indexing pipeline:
1. Parse SCIP index for symbol definitions
2. Chunk files using cAST (SCIP-based)
3. Embed chunks with vLLM
4. Write to Parquet with embeddings
5. Build FAISS index with adaptive type selection

The FAISS index type is automatically selected based on corpus size:
- Small (<5K vectors): Flat index (exact search, fast training)
- Medium (5K-50K vectors): IVFFlat (balanced training/recall)
- Large (>50K vectors): IVF-PQ (memory efficient, fast search)
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from codeintel_rev.config.settings import (
    IndexConfig,
    Settings,
    VLLMConfig,
    load_settings,
)
from codeintel_rev.indexing.cast_chunker import Chunk, ChunkOptions, chunk_file
from codeintel_rev.indexing.scip_reader import (
    SCIPIndex,
    SymbolDef,
    extract_definitions,
    get_top_level_definitions,
    parse_scip_json,
)
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.parquet_store import ParquetWriteOptions, write_chunks_parquet
from codeintel_rev.io.symbol_catalog import (  # new
    SymbolCatalog,
    SymbolDefRow,
    SymbolOccurrenceRow,
)
from codeintel_rev.io.vllm_client import VLLMClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EMBED_PREVIEW_CHARS = 1000
TRAINING_LIMIT = 10_000


@dataclass(frozen=True)
class PipelinePaths:
    """Resolved filesystem paths for the indexing pipeline."""

    repo_root: Path
    scip_index: Path
    vectors_dir: Path
    faiss_index: Path
    duckdb_path: Path


def main() -> None:
    """Run the end-to-end indexing pipeline.

    Supports both full rebuild (default) and incremental update modes.
    Use --incremental to add new chunks to an existing index instead of rebuilding.
    """
    parser = argparse.ArgumentParser(
        description="Index repository: SCIP → chunk → embed → Parquet → FAISS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Add new chunks to existing index instead of rebuilding (fast incremental updates)",
    )
    args = parser.parse_args()

    settings = load_settings()
    paths = _resolve_paths(settings)

    logger.info("Starting indexing for repo root %s", paths.repo_root)
    scip_index = _load_scip_index(paths)
    grouped_defs = _group_definitions_by_file(scip_index)
    chunks = _chunk_repository(paths, grouped_defs, settings.index.chunk_budget)

    if not chunks:
        logger.error("No chunks were produced; aborting pipeline")
        return

    embeddings = _embed_chunks(chunks, settings.vllm)
    parquet_path = _write_parquet(
        chunks,
        embeddings,
        paths,
        settings.index.vec_dim,
        settings.index.preview_max_chars,
    )

    if args.incremental:
        _update_faiss_index_incremental(chunks, embeddings, paths, settings.index)
    else:
        _build_faiss_index(embeddings, paths, settings.index)

    catalog_count = _initialize_duckdb(
        paths,
        materialize=settings.index.duckdb_materialize,
    )
    _write_symbols(paths, scip_index, chunks)

    mode_str = "incremental" if args.incremental else "full rebuild"
    logger.info(
        "Indexing pipeline complete (%s); chunks=%s embeddings=%s parquet=%s "
        "faiss_index=%s duckdb_rows=%s",
        mode_str,
        len(chunks),
        len(embeddings),
        parquet_path,
        paths.faiss_index,
        catalog_count,
    )


def _resolve_paths(settings: Settings) -> PipelinePaths:
    """Resolve and normalize key filesystem paths.

    Parameters
    ----------
    settings : Settings
        Application settings containing path configuration.

    Returns
    -------
    PipelinePaths
        Absolute paths for all filesystem locations used by the pipeline.
    """
    repo_root = Path(settings.paths.repo_root).expanduser().resolve()

    def _resolve(path_str: str) -> Path:
        path = Path(path_str)
        if path.is_absolute():
            return path.expanduser().resolve()
        return (repo_root / path).resolve()

    return PipelinePaths(
        repo_root=repo_root,
        scip_index=_resolve(settings.paths.scip_index),
        vectors_dir=_resolve(settings.paths.vectors_dir),
        faiss_index=_resolve(settings.paths.faiss_index),
        duckdb_path=_resolve(settings.paths.duckdb_path),
    )


def _load_scip_index(paths: PipelinePaths) -> SCIPIndex:
    """Load and parse the SCIP index from disk.

    Parameters
    ----------
    paths : PipelinePaths
        Pipeline paths configuration containing SCIP index location.

    Returns
    -------
    SCIPIndex
        Parsed SCIP index containing all documents and occurrences.

    Raises
    ------
    FileNotFoundError
        If the configured SCIP index file does not exist.
    """
    if not paths.scip_index.exists():
        msg = f"SCIP index not found at {paths.scip_index}"
        raise FileNotFoundError(msg)

    index = parse_scip_json(paths.scip_index)
    logger.info("Parsed %s documents from SCIP index", len(index.documents))
    return index


def _group_definitions_by_file(index: SCIPIndex) -> Mapping[str, list[SymbolDef]]:
    """Group symbol definitions by their relative file path.

    Parameters
    ----------
    index : SCIPIndex
        SCIP index containing symbol definitions.

    Returns
    -------
    Mapping[str, list[SymbolDef]]
        Definitions grouped by file path for downstream chunking.
    """
    grouped: dict[str, list[SymbolDef]] = defaultdict(list)
    for definition in extract_definitions(index):
        grouped[definition.path].append(definition)

    logger.info("Found definitions in %s files", len(grouped))
    return grouped


def _chunk_repository(
    paths: PipelinePaths,
    definitions_by_file: Mapping[str, Sequence[SymbolDef]],
    budget: int,
) -> list[Chunk]:
    """Chunk all files referenced by the SCIP index.

    Parameters
    ----------
    paths : PipelinePaths
        Pipeline paths configuration.
    definitions_by_file : Mapping[str, Sequence[SymbolDef]]
        Symbol definitions grouped by file path.
    budget : int
        Character budget per chunk.

    Returns
    -------
    list[Chunk]
        Collection of generated chunks across the repository.
    """
    chunks: list[Chunk] = []
    for relative_path, defs in definitions_by_file.items():
        full_path = paths.repo_root / relative_path
        if not full_path.exists():
            logger.warning("Skipping missing file %s", full_path)
            continue

        try:
            text = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Unable to read %s: %s", full_path, exc)
            continue

        def_list = list(defs)
        top_level_defs = get_top_level_definitions(def_list)
        if not top_level_defs:
            continue

        file_language = top_level_defs[0].language if top_level_defs else ""
        file_chunks = chunk_file(
            full_path,
            text,
            top_level_defs,
            options=ChunkOptions(budget=budget, language=file_language),
        )
        chunks.extend(file_chunks)

    logger.info("Chunked %s files into %s chunks", len(definitions_by_file), len(chunks))
    return chunks


def _embed_chunks(chunks: Sequence[Chunk], config: VLLMConfig) -> np.ndarray:
    """Generate embeddings for the supplied chunks using vLLM.

    Parameters
    ----------
    chunks : Sequence[Chunk]
        Chunks to embed.
    config : VLLMConfig
        vLLM client configuration.

    Returns
    -------
    np.ndarray
        Embedding matrix aligned with the chunk order.
    """
    client = VLLMClient(config)
    texts = [chunk.text[:EMBED_PREVIEW_CHARS] for chunk in chunks]
    vectors = client.embed_chunks(texts, batch_size=config.batch_size)
    logger.info("Generated %s embeddings", len(vectors))
    return vectors


def _write_parquet(
    chunks: Sequence[Chunk],
    embeddings: np.ndarray,
    paths: PipelinePaths,
    vec_dim: int,
    preview_max_chars: int,
) -> Path:
    """Persist chunk metadata and embeddings to Parquet.

    Parameters
    ----------
    chunks : Sequence[Chunk]
        Chunks to persist.
    embeddings : np.ndarray
        Embedding vectors aligned with chunks.
    paths : PipelinePaths
        Pipeline paths configuration.
    vec_dim : int
        Embedding vector dimension.
    preview_max_chars : int
        Maximum number of characters to persist in chunk previews.

    Returns
    -------
    Path
        Path to the written Parquet file containing chunk data.
    """
    output_path = paths.vectors_dir / "part-000.parquet"
    write_chunks_parquet(
        output_path=output_path,
        chunks=chunks,
        embeddings=embeddings,
        options=ParquetWriteOptions(
            start_id=0,
            vec_dim=vec_dim,
            preview_max_chars=preview_max_chars,
        ),
    )
    logger.info("Wrote Parquet dataset to %s", output_path)
    return output_path


def _build_faiss_index(
    embeddings: np.ndarray,
    paths: PipelinePaths,
    index_config: IndexConfig,
) -> None:
    """Train and persist the FAISS index with adaptive type selection.

    The index type is automatically selected based on corpus size for optimal
    performance. Small corpora use flat indexes (fast training), medium corpora
    use IVFFlat (balanced), and large corpora use IVF-PQ (memory efficient).

    Parameters
    ----------
    embeddings : np.ndarray
        Embedding vectors to index.
    paths : PipelinePaths
        Pipeline paths configuration.
    index_config : IndexConfig
        FAISS index configuration.

    Raises
    ------
    RuntimeError
        If embeddings are empty and the index cannot be trained.
    """
    if embeddings.size == 0:
        msg = "No embeddings available to build FAISS index"
        raise RuntimeError(msg)

    n_vectors = len(embeddings)
    logger.info("Building FAISS index for %s vectors (adaptive type selection)", n_vectors)

    faiss_mgr = FAISSManager(
        index_path=paths.faiss_index,
        vec_dim=index_config.vec_dim,
        nlist=index_config.faiss_nlist,
        use_cuvs=index_config.use_cuvs,
    )

    # Log memory estimate before building
    mem_est = faiss_mgr.estimate_memory_usage(n_vectors)
    logger.info(
        "Estimated memory usage: CPU=%.2f GB, GPU=%.2f GB, Total=%.2f GB",
        mem_est["cpu_index_bytes"] / 1e9,
        mem_est["gpu_index_bytes"] / 1e9,
        mem_est["total_bytes"] / 1e9,
    )

    train_limit = min(len(embeddings), TRAINING_LIMIT)
    training_vectors = embeddings[:train_limit]
    faiss_mgr.build_index(training_vectors)
    # Index type and memory estimate are logged by FAISSManager.build_index()

    ids = np.arange(len(embeddings), dtype=np.int64)
    faiss_mgr.add_vectors(embeddings, ids)
    faiss_mgr.save_cpu_index()
    logger.info("Persisted FAISS index to %s", paths.faiss_index)


def _update_faiss_index_incremental(
    chunks: Sequence[Chunk],
    embeddings: np.ndarray,
    paths: PipelinePaths,
    index_config: IndexConfig,
) -> None:
    """Update FAISS index incrementally by adding new chunks to secondary index.

    Loads existing primary index and identifies new chunks that aren't already
    indexed. Adds new chunks to the secondary flat index for fast incremental
    updates without rebuilding the primary index.

    Parameters
    ----------
    chunks : Sequence[Chunk]
        All chunks from the current indexing run.
    embeddings : np.ndarray
        Embedding vectors aligned with chunks.
    paths : PipelinePaths
        Pipeline paths configuration.
    index_config : IndexConfig
        FAISS index configuration.

    Raises
    ------
    FileNotFoundError
        If the primary index does not exist. Use full rebuild mode first.
    RuntimeError
        If embeddings are empty or index loading fails.
    """
    if embeddings.size == 0:
        msg = "No embeddings available for incremental update"
        raise RuntimeError(msg)

    logger.info("Incremental indexing mode: adding new chunks to existing index")

    faiss_mgr = FAISSManager(
        index_path=paths.faiss_index,
        vec_dim=index_config.vec_dim,
        nlist=index_config.faiss_nlist,
        use_cuvs=index_config.use_cuvs,
    )

    # Load existing primary index
    try:
        faiss_mgr.load_cpu_index()
        logger.info("Loaded existing primary index from %s", paths.faiss_index)
    except FileNotFoundError as exc:
        msg = (
            f"Primary index not found at {paths.faiss_index}. "
            "Run without --incremental flag first to create the initial index."
        )
        raise FileNotFoundError(msg) from exc

    # Try to load existing secondary index (if any)
    try:
        faiss_mgr.load_secondary_index()
        logger.info(
            "Loaded existing secondary index with %s vectors",
            len(faiss_mgr.incremental_ids),
        )
    except FileNotFoundError:
        logger.info("No existing secondary index found; will create new one")

    # Identify new chunks (not already in primary or secondary index)
    # For simplicity, we'll use chunk indices as IDs (matching the full rebuild logic)
    chunk_ids = np.arange(len(chunks), dtype=np.int64)
    existing_ids = set(faiss_mgr.incremental_ids)

    # Get IDs from primary index if possible
    if faiss_mgr.cpu_index is not None:
        try:
            primary_n = faiss_mgr.cpu_index.ntotal  # type: ignore[attr-defined]
            if hasattr(faiss_mgr.cpu_index, "id_map"):
                primary_ids = {
                    faiss_mgr.cpu_index.id_map.at(i)  # type: ignore[attr-defined]
                    for i in range(primary_n)
                }
                existing_ids.update(primary_ids)
        except (AttributeError, RuntimeError) as exc:
            logger.warning("Could not extract IDs from primary index: %s", exc)

    # Filter to new chunks only
    new_mask = np.array([chunk_id not in existing_ids for chunk_id in chunk_ids])
    new_indices = np.where(new_mask)[0]

    if len(new_indices) == 0:
        logger.info("All %s chunks already indexed; no incremental update needed", len(chunks))
        return

    new_chunks = [chunks[i] for i in new_indices]
    new_embeddings = embeddings[new_indices]
    new_ids = chunk_ids[new_indices]

    logger.info(
        "Adding %s new chunks to secondary index (%s already indexed)",
        len(new_chunks),
        len(chunks) - len(new_chunks),
    )

    # Add to secondary index
    faiss_mgr.update_index(new_embeddings, new_ids)

    # Save both indexes
    faiss_mgr.save_cpu_index()  # Save primary (unchanged, but ensures consistency)
    faiss_mgr.save_secondary_index()  # Save secondary with new chunks

    logger.info(
        "Incremental update complete: %s new vectors added to secondary index",
        len(new_ids),
    )


def _initialize_duckdb(paths: PipelinePaths, *, materialize: bool) -> int:
    """Create or refresh the DuckDB catalog and return the chunk count.

    Parameters
    ----------
    paths : PipelinePaths
        Pipeline paths configuration.
    materialize : bool
        Whether to materialize Parquet data into a DuckDB table with indexes.

    Returns
    -------
    int
        Number of chunk records registered in the catalog.
    """
    with DuckDBCatalog(
        paths.duckdb_path,
        paths.vectors_dir,
        materialize=materialize,
    ) as catalog:
        count = catalog.count_chunks()
    logger.info(
        "DuckDB catalog initialized at %s (rows=%s, materialize=%s)",
        paths.duckdb_path,
        count,
        materialize,
    )
    return count


def _write_symbols(paths: PipelinePaths, index: SCIPIndex, chunks: Sequence[Chunk]) -> None:
    """Derive symbol tables and persist them into DuckDB."""
    manager = DuckDBManager(paths.duckdb_path)
    sym = SymbolCatalog(manager)
    sym.ensure_schema()

    by_file: dict[str, list[tuple[int, int, int]]] = {}
    for chunk_id, chunk in enumerate(chunks):
        by_file.setdefault(chunk.uri, []).append((chunk_id, chunk.start_line, chunk.end_line))

    def _chunk_for(uri: str, line: int) -> int:
        for cid, start, end in by_file.get(uri, []):
            if start <= line <= end:
                return cid
        return -1

    occ_rows: list[SymbolOccurrenceRow] = []
    def_rows: dict[str, SymbolDefRow] = {}
    chunk_pairs: list[tuple[int, str]] = []

    for doc in index.documents:
        uri = str((paths.repo_root / doc.relative_path).resolve())
        lang = doc.language or ""
        for occ in doc.occurrences:
            sl, sc, el, ec = occ.range
            chunk_id = _chunk_for(uri, sl)
            roles = int(occ.roles or 0)
            occ_rows.append(
                SymbolOccurrenceRow(
                    symbol=occ.symbol,
                    uri=uri,
                    start_line=sl,
                    start_col=sc,
                    end_line=el,
                    end_col=ec,
                    roles=roles,
                    kind=None,
                    language=lang,
                    chunk_id=chunk_id,
                )
            )
            if roles & 1:
                display_name = occ.symbol.split("#")[-1].split(".")[-1]
                def_rows.setdefault(
                    occ.symbol,
                    SymbolDefRow(
                        symbol=occ.symbol,
                        display_name=display_name,
                        kind="symbol",
                        language=lang,
                        uri=uri,
                        start_line=sl,
                        start_col=sc,
                        end_line=el,
                        end_col=ec,
                        chunk_id=chunk_id,
                        docstring=None,
                        signature=None,
                    ),
                )

    for chunk_id, chunk in enumerate(chunks):
        chunk_pairs.extend((chunk_id, symbol) for symbol in chunk.symbols)

    sym.bulk_insert_occurrences(occ_rows)
    sym.upsert_symbol_defs(list(def_rows.values()))
    sym.bulk_insert_chunk_symbols(chunk_pairs)


if __name__ == "__main__":
    main()
