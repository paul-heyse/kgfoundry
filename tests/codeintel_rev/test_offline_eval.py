from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from codeintel_rev.config.settings import EvalConfig, PathsConfig, load_settings
from codeintel_rev.evaluation.offline_recall import OfflineRecallEvaluator
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.symbol_catalog import SymbolCatalog, SymbolDefRow
from codeintel_rev.io.vllm_client import VLLMClient
from msgspec import structs


class _StubFAISSManager:
    def __init__(self, chunk_ids: list[int]) -> None:
        self._chunk_ids = chunk_ids

    def search(
        self,
        query: np.ndarray,
        k: int | None = None,
        *,
        nprobe: int | None = None,
        runtime: object | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        del query, nprobe, runtime
        k = k or len(self._chunk_ids)
        hits = self._chunk_ids[:k]
        distances = np.ones((1, len(hits)), dtype=np.float32)
        ids = np.array([hits], dtype=np.int64)
        return distances, ids


class _StubVLLMClient:
    def __init__(self, dim: int) -> None:
        self._dim = dim

    def embed_single(self, text: str) -> list[float]:
        assert text
        return [0.0] * self._dim


def _prepare_symbol_catalog(db_path: Path) -> DuckDBManager:
    manager = DuckDBManager(db_path)
    catalog = SymbolCatalog(manager)
    catalog.ensure_schema()
    row = SymbolDefRow(
        symbol="python://pkg#func",
        display_name="func",
        kind="function",
        language="python",
        uri="src/pkg.py",
        start_line=1,
        start_col=0,
        end_line=5,
        end_col=1,
        chunk_id=101,
    )
    with manager.connection() as conn:
        conn.execute(
            """
            INSERT INTO symbol_defs(
              symbol, display_name, kind, language, uri,
              start_line, start_col, end_line, end_col, chunk_id, docstring, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.symbol,
                row.display_name,
                row.kind,
                row.language,
                row.uri,
                row.start_line,
                row.start_col,
                row.end_line,
                row.end_col,
                row.chunk_id,
                row.docstring,
                row.signature,
            ),
        )
    return manager


def test_offline_eval_synthesizes_queries(tmp_path: Path) -> None:
    base_settings = load_settings()
    paths = PathsConfig(
        repo_root=str(tmp_path),
        data_dir=str(tmp_path / "data"),
        vectors_dir=str(tmp_path / "vectors"),
        faiss_index=str(tmp_path / "index.faiss"),
        duckdb_path=str(tmp_path / "catalog.duckdb"),
        scip_index=str(tmp_path / "index.scip"),
    )
    settings = structs.replace(
        base_settings,
        paths=paths,
        eval=EvalConfig(enabled=True, output_dir=str(tmp_path / "artifacts"), k_values=(5,)),
    )
    duckdb_manager = _prepare_symbol_catalog(Path(paths.duckdb_path))
    evaluator = OfflineRecallEvaluator(
        settings=settings,
        paths=paths,
        faiss_manager=cast("FAISSManager", _StubFAISSManager([101, 202])),
        vllm_client=cast("VLLMClient", _StubVLLMClient(settings.index.vec_dim)),
        duckdb_manager=duckdb_manager,
    )
    result = evaluator.run()
    assert result["queries"] == 1
    summary = cast("Mapping[int, float]", result["summary"])
    assert summary[5] == pytest.approx(1.0)
    summary_path = tmp_path / "artifacts" / "summary.json"
    assert summary_path.exists()
