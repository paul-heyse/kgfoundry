from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

from codeintel_rev.app.config_context import ApplicationContext, ResolvedPaths

if TYPE_CHECKING:
    from codeintel_rev.config.settings import Settings


_USE_REAL_DATA = os.getenv("KGFOUNDRY_TEST_USE_REAL_DATA", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
_REPO_ROOT_OVERRIDE = os.getenv("KGFOUNDRY_TEST_REPO_ROOT")


def _real_paths(repo_root: Path) -> ResolvedPaths:
    data_dir = repo_root / "data"
    vectors_dir = data_dir / "vectors"
    faiss_dir = data_dir / "faiss"
    coderank_vectors = data_dir / "coderank_vectors"
    warp_dir = repo_root / "indexes" / "warp_xtr"
    xtr_dir = data_dir / "xtr"
    faiss_index = faiss_dir / "code.ivfpq.faiss"
    faiss_idmap = faiss_dir / "faiss_idmap.parquet"
    coderank_index = faiss_dir / "coderank.ivfpq.faiss"
    duckdb_path = data_dir / "catalog.duckdb"
    scip_index = repo_root / "codeintel_rev" / "index.scip.json"

    missing = [
        path
        for path in (
            data_dir,
            vectors_dir,
            faiss_dir,
            faiss_index,
            faiss_idmap,
            duckdb_path,
            scip_index,
        )
        if not path.exists()
    ]
    if missing:
        parts: list[str] = []
        for path in missing:
            try:
                parts.append(str(path.relative_to(repo_root)))
            except ValueError:
                parts.append(str(path))
        formatted = ", ".join(parts)
        message = (
            "Real-data fixtures enabled but missing required artifacts: "
            f"{formatted}. Run the indexing pipeline or set "
            "KGFOUNDRY_TEST_USE_REAL_DATA=0 to fall back to synthetic fixtures."
        )
        raise FileNotFoundError(message)

    return ResolvedPaths(
        repo_root=repo_root,
        data_dir=data_dir,
        vectors_dir=vectors_dir,
        faiss_index=faiss_index,
        faiss_idmap_path=faiss_idmap,
        duckdb_path=duckdb_path,
        scip_index=scip_index,
        coderank_vectors_dir=coderank_vectors,
        coderank_faiss_index=coderank_index,
        warp_index_dir=warp_dir,
        xtr_dir=xtr_dir,
    )


def _synthetic_paths(tmp_path: Path) -> ResolvedPaths:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    data_dir = repo_root / "data"
    vectors_dir = data_dir / "vectors"
    faiss_dir = data_dir / "faiss"
    coderank_vectors = data_dir / "coderank_vectors"
    warp_dir = repo_root / "warp"
    xtr_dir = repo_root / "xtr"

    for directory in (
        data_dir,
        vectors_dir,
        faiss_dir,
        coderank_vectors,
        warp_dir,
        xtr_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    faiss_index = faiss_dir / "code.ivfpq.faiss"
    faiss_idmap = faiss_dir / "faiss_idmap.parquet"
    coderank_index = faiss_dir / "coderank.faiss"
    duckdb_path = data_dir / "catalog.duckdb"
    scip_index = data_dir / "index.scip"

    for path in (
        faiss_index,
        coderank_index,
        duckdb_path,
        scip_index,
        faiss_idmap,
    ):
        path.touch()

    return ResolvedPaths(
        repo_root=repo_root,
        data_dir=data_dir,
        vectors_dir=vectors_dir,
        faiss_index=faiss_index,
        faiss_idmap_path=faiss_idmap,
        duckdb_path=duckdb_path,
        scip_index=scip_index,
        coderank_vectors_dir=coderank_vectors,
        coderank_faiss_index=coderank_index,
        warp_index_dir=warp_dir,
        xtr_dir=xtr_dir,
    )


def _prepare_paths(tmp_path: Path) -> ResolvedPaths:
    """Return ResolvedPaths backed by either real repo data or synthetic fixtures.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory used when creating synthetic fixtures.

    Returns
    -------
    ResolvedPaths
        Paths pointing to either the real repository layout or synthetic test data.

    """
    if _USE_REAL_DATA:
        repo_root = (
            Path(_REPO_ROOT_OVERRIDE).expanduser().resolve()
            if _REPO_ROOT_OVERRIDE
            else Path(__file__).resolve().parents[2]
        )
        return _real_paths(repo_root)
    return _synthetic_paths(tmp_path)


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
    paths = _prepare_paths(tmp_path)
    warp_dir = paths.warp_index_dir

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
