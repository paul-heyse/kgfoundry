from __future__ import annotations

from pathlib import Path

import msgspec
import numpy as np
from codeintel_rev.config.settings import EvalConfig, PathsConfig, load_settings
from codeintel_rev.evaluation.scip_coverage import SCIPCoverageEvaluator
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.symbol_catalog import SymbolCatalog, SymbolDefRow


class _StubFAISSManager:
    def search(
        self,
        query: np.ndarray,
        k: int | None = None,
        *,
        nprobe: int | None = None,
        runtime: object | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        del query, nprobe, runtime
        ids = np.array([[101]], dtype=np.int64)
        distances = np.array([[0.9]], dtype=np.float32)
        return distances, ids


class _StubVLLMClient:
    def embed_single(self, text: str) -> list[float]:
        assert text
        return [0.0, 0.0]


def _prepare_catalog(path: Path) -> DuckDBManager:
    manager = DuckDBManager(path)
    catalog = SymbolCatalog(manager)
    catalog.ensure_schema()
    with manager.connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO chunks(id) VALUES (101)")
    catalog.upsert_symbol_defs(
        [
            SymbolDefRow(
                symbol="python://pkg#func",
                display_name="func",
                kind="function",
                language="python",
                uri="src/pkg.py",
                start_line=1,
                start_col=0,
                end_line=3,
                end_col=1,
                chunk_id=101,
            )
        ]
    )
    return manager


def test_scip_coverage_reports_full_metrics(tmp_path: Path) -> None:
    base_settings = load_settings()
    paths = PathsConfig(
        repo_root=str(tmp_path),
        data_dir=str(tmp_path / "data"),
        vectors_dir=str(tmp_path / "vectors"),
        faiss_index=str(tmp_path / "index.faiss"),
        duckdb_path=str(tmp_path / "catalog.duckdb"),
        scip_index=str(tmp_path / "index.scip"),
    )
    settings = msgspec.structs.replace(
        base_settings,
        paths=paths,
        eval=EvalConfig(enabled=True, output_dir=str(tmp_path / "artifacts")),
    )
    duckdb_manager = _prepare_catalog(Path(paths.duckdb_path))
    evaluator = SCIPCoverageEvaluator(
        settings=settings,
        paths=paths,
        duckdb_manager=duckdb_manager,
        faiss_manager=_StubFAISSManager(),
        vllm_client=_StubVLLMClient(),
    )
    summary = evaluator.run(k=5)
    assert summary["chunk_coverage"] == 1.0
    assert summary["index_coverage"] == 1.0
    assert summary["retrieval_coverage"] == 1.0
