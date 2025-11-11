from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

from codeintel_rev.app.config_context import ApplicationContext, ResolvedPaths

if TYPE_CHECKING:
    from codeintel_rev.config.settings import Settings


def build_application_context(
    tmp_path: Path,
    *,
    xtr_enabled: bool = False,
    enable_bm25: bool = False,
    enable_splade: bool = False,
) -> ApplicationContext:
    """Create a lightweight ApplicationContext for unit tests.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path for creating test repository structure.
    xtr_enabled : bool, optional
        Whether to enable XTR (extraction) features, by default False.
    enable_bm25 : bool, optional
        Whether to enable BM25 search channel, by default False.
    enable_splade : bool, optional
        Whether to enable SPLADE search channel, by default False.

    Returns
    -------
    ApplicationContext
        Configured application context with mocked dependencies for testing.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    data_dir = repo_root / "data"
    vectors_dir = data_dir / "vectors"
    faiss_index = data_dir / "faiss" / "code.ivfpq.faiss"
    coderank_index = data_dir / "faiss" / "coderank.faiss"
    duckdb_path = data_dir / "catalog.duckdb"
    scip_index = data_dir / "index.scip"
    coderank_vectors = data_dir / "coderank_vectors"
    warp_dir = repo_root / "warp"
    xtr_dir = repo_root / "xtr"

    for directory in (
        data_dir,
        vectors_dir,
        faiss_index.parent,
        coderank_vectors,
        warp_dir,
        xtr_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    faiss_index.touch()
    coderank_index.touch()
    duckdb_path.touch()
    scip_index.touch()

    paths = ResolvedPaths(
        repo_root=repo_root,
        data_dir=data_dir,
        vectors_dir=vectors_dir,
        faiss_index=faiss_index,
        duckdb_path=duckdb_path,
        scip_index=scip_index,
        coderank_vectors_dir=coderank_vectors,
        coderank_faiss_index=coderank_index,
        warp_index_dir=warp_dir,
        xtr_dir=xtr_dir,
    )

    index_cfg = SimpleNamespace(
        faiss_nlist=64,
        use_cuvs=False,
        enable_bm25_channel=enable_bm25,
        enable_splade_channel=enable_splade,
        vec_dim=2,
        default_k=50,
        default_nprobe=32,
        hnsw_ef_search=64,
        refine_k_factor=1.0,
    )
    xtr_cfg = SimpleNamespace(
        enable=xtr_enabled,
        mode="narrow",
        max_query_tokens=32,
        candidate_k=32,
        dim=2,
        dtype="float16",
    )
    settings = SimpleNamespace(
        index=index_cfg,
        xtr=xtr_cfg,
        bm25=SimpleNamespace(index_dir=str(warp_dir / "bm25")),
        splade=SimpleNamespace(
            model_dir=str(warp_dir / "splade-model"),
            onnx_dir=str(warp_dir / "splade-onnx"),
            index_dir=str(warp_dir / "splade-index"),
            onnx_file="splade.onnx",
            provider="cpu",
            quantization="int8",
            max_terms=32,
        ),
        warp=SimpleNamespace(budget_ms=200, enabled=True, device="cpu", top_k=5),
    )

    typed_settings = cast("Settings", settings)
    return ApplicationContext(
        settings=typed_settings,
        paths=paths,
        vllm_client=MagicMock(),
        faiss_manager=MagicMock(),
        scope_store=MagicMock(),
        duckdb_manager=MagicMock(),
        git_client=MagicMock(),
        async_git_client=MagicMock(),
    )
