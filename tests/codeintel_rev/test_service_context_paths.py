"""Tests for service context path resolution helpers."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from codeintel_rev.app.config_context import (
    ApplicationContext,
    ApplicationContextOverrides,
    merge_paths_with_app_config,
)
from codeintel_rev.config.api import (
    CONFIG_API_VERSION,
    AppConfig,
    BM25Settings,
    EmbeddingsSettings,
    FAISSSettings,
    LoggingSettings,
    SearchSettings,
    SpladeSettings,
    VLLMSettings,
    XTRSettings,
)
from codeintel_rev.config.api import (
    DuckDBSettings as ApiDuckDBSettings,
)
from codeintel_rev.config.api import (
    PathsConfig as ApiPathsConfig,
)
from codeintel_rev.config.paths import ResolvedPaths
from codeintel_rev.config.settings import Settings
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.vllm_client import VLLMClient
from codeintel_rev.mcp_server import service_context

from tests._helpers import assertions
from tests._helpers.settings import build_settings_for_repo


class RecordingFAISSManager:
    """Stub FAISS manager capturing constructor arguments."""

    def __init__(
        self,
        *,
        index_path: Path,
        vec_dim: int,
        nlist: int,
        runtime: object | None = None,
    ) -> None:
        """Initialize recording FAISS manager.

        Parameters
        ----------
        index_path : Path
            Path to FAISS index file.
        vec_dim : int
            Vector dimension.
        nlist : int
            Number of clusters for IVF index.
        runtime : object | None, optional
            Optional runtime object.
        """
        self.index_path = index_path
        self.vec_dim = vec_dim
        self.nlist = nlist
        self.cpu_index = None
        self.load_calls = 0
        self.runtime = runtime
        self.autotune_profile_path = index_path.with_name("tuning.json")

    def load_cpu_index(self, *_: object, **__: object) -> None:
        """Record CPU index load attempts."""
        self.load_calls += 1

    @staticmethod
    def get_compile_options() -> dict[str, str]:
        """Return fake compile options for logging.

        Returns
        -------
        dict[str, str]
            Static compile option payload for assertions.
        """
        return {"arch": "stub"}


class RecordingDuckDBCatalog:
    """Stub DuckDB catalog capturing constructor arguments."""

    def __init__(self, db_path: Path, vectors_dir: Path, **_: object) -> None:
        """Initialize recording DuckDB catalog.

        Parameters
        ----------
        db_path : Path
            Path to DuckDB database file.
        vectors_dir : Path
            Directory containing vector files.
        **_
            Additional keyword arguments (ignored).
        """
        self.db_path = db_path
        self.vectors_dir = vectors_dir
        self.open_called = False
        self.closed = False
        self.idmap_path: Path | None = None

    def open(self) -> None:  # pragma: no cover - trivial shim
        """Record catalog opening."""
        self.open_called = True

    def close(self) -> None:  # pragma: no cover - trivial shim
        """Record catalog closing."""
        self.closed = True

    def set_idmap_path(self, path: Path) -> None:
        """Record configured FAISS ID map path."""
        self.idmap_path = path


class DummyVLLMClient:
    """Minimal vLLM client placeholder used for dependency injection."""

    def __init__(self, _config: object) -> None:  # pragma: no cover - trivial shim
        """Initialize dummy vLLM client.

        Parameters
        ----------
        _config : object
            Configuration object (ignored).
        """
        return


def test_service_context_resolves_paths(tmp_path: Path) -> None:
    """Relative configuration paths resolve against ``REPO_ROOT``."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config_dir = repo_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "app.yml").write_text("tests: true")
    for relative in ("logs", ".cache", ".tmp", "plugins"):
        (repo_root / relative).mkdir(parents=True, exist_ok=True)
    default_data_dir = repo_root / "data"
    default_data_dir.mkdir(parents=True, exist_ok=True)
    (default_data_dir / "vectors").mkdir(parents=True, exist_ok=True)
    faiss_rel = "indexes/code.ivfpq.faiss"
    duckdb_rel = "catalog/catalog.duckdb"
    vectors_rel = "artifacts/vectors"

    expected_faiss_path = (repo_root / faiss_rel).resolve()
    expected_duckdb_path = (repo_root / duckdb_rel).resolve()
    expected_vectors_dir = (repo_root / vectors_rel).resolve()

    expected_faiss_path.parent.mkdir(parents=True, exist_ok=True)
    expected_faiss_path.touch()
    expected_vectors_dir.mkdir(parents=True, exist_ok=True)

    settings = build_settings_for_repo(
        repo_root,
        paths_overrides={
            "faiss_index": faiss_rel,
            "duckdb_path": duckdb_rel,
            "vectors_dir": vectors_rel,
        },
    )
    app_config = AppConfig(
        version=CONFIG_API_VERSION,
        paths=ApiPathsConfig(
            repo_root=repo_root,
            data_dir=repo_root / "data",
            cache_dir=repo_root / ".cache",
            logs_dir=repo_root / "logs",
        ),
        duckdb=ApiDuckDBSettings(database=expected_duckdb_path),
        faiss=FAISSSettings(index_path=expected_faiss_path),
        bm25=BM25Settings(
            corpus_json_dir=repo_root / "data" / "bm25_json",
            index_dir=repo_root / "indexes" / "bm25",
        ),
        splade=SpladeSettings(
            model_id="naver/splade-v3",
            model_dir=repo_root / "models" / "splade",
            onnx_dir=repo_root / "models" / "splade" / "onnx",
            onnx_file="model.onnx",
            vectors_dir=repo_root / "vectors",
            index_dir=repo_root / "indexes" / "splade",
            provider="CPUExecutionProvider",
            quantization=100,
            max_terms=1000,
            max_clause_count=4096,
            batch_size=16,
            threads=4,
            enabled=False,
            max_query_terms=32,
            prune_below=0.0,
            analyzer="wordpiece",
            static_prune_pct=0.0,
        ),
        xtr=XTRSettings(
            model_id="nomic-ai/CodeRankEmbed",
            device="cuda",
            max_query_tokens=256,
            candidate_k=200,
            dim=768,
            dtype="float16",
            enable=False,
            mode="narrow",
        ),
        embeddings=EmbeddingsSettings(),
        vllm=VLLMSettings(),
        search=SearchSettings(),
        logging=LoggingSettings(),
        index=IndexSettings(),
    )

    service_context.reset_service_context()

    def _faiss_factory(cfg: Settings, resolved: ResolvedPaths) -> FAISSManager:
        nlist_value = cfg.index.nlist or 1
        return cast(
            "FAISSManager",
            RecordingFAISSManager(
                index_path=resolved.faiss_index,
                vec_dim=cfg.index.vec_dim,
                nlist=nlist_value,
                runtime=None,
            ),
        )

    def _catalog_factory(
        resolved: ResolvedPaths,
        cfg: Settings,
        manager: DuckDBManager,
    ) -> DuckDBCatalog:
        _ = cfg, manager
        catalog = RecordingDuckDBCatalog(resolved.duckdb_path, resolved.vectors_dir)
        catalog.set_idmap_path(resolved.faiss_idmap_path)
        return cast("DuckDBCatalog", catalog)

    overrides = ApplicationContextOverrides(
        vllm_client=cast("VLLMClient", DummyVLLMClient(settings.vllm)),
        faiss_manager_factory=_faiss_factory,
        duckdb_catalog_factory=_catalog_factory,
    )
    custom_context = ApplicationContext.create(
        settings=settings,
        overrides=overrides,
        app_config=app_config,
    )
    service_context.set_service_context(custom_context)
    context = service_context.get_service_context()

    _assert_faiss_manager(context.faiss_manager, expected_faiss_path)
    _assert_faiss_ready(context)

    with context.open_catalog() as catalog_obj:
        catalog = cast("RecordingDuckDBCatalog", catalog_obj)
        _assert_catalog(catalog, expected_duckdb_path, expected_vectors_dir)

    assertions.expect_true(catalog.closed, reason="catalog should be closed")

    service_context.reset_service_context()


def test_merge_paths_with_app_config_overrides_duckdb_and_faiss(tmp_path: Path) -> None:
    """merge_paths_with_app_config should reflect AppConfig overrides."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    base_paths = _stub_paths(repo_root)
    custom_duckdb = tmp_path / "custom.duckdb"
    custom_faiss = tmp_path / "custom.index"
    app_config = AppConfig(
        version=CONFIG_API_VERSION,
        paths=ApiPathsConfig(
            repo_root=repo_root,
            data_dir=repo_root / "data",
            cache_dir=repo_root / ".cache",
            logs_dir=repo_root / "logs",
        ),
        duckdb=ApiDuckDBSettings(database=custom_duckdb),
        faiss=FAISSSettings(index_path=custom_faiss),
        bm25=BM25Settings(
            corpus_json_dir=repo_root / "data" / "bm25_json",
            index_dir=repo_root / "indexes" / "bm25",
        ),
        splade=SpladeSettings(
            model_id="naver/splade-v3",
            model_dir=repo_root / "models" / "splade",
            onnx_dir=repo_root / "models" / "splade" / "onnx",
            onnx_file="model.onnx",
            vectors_dir=repo_root / "vectors",
            index_dir=repo_root / "indexes" / "splade",
            provider="CPUExecutionProvider",
            quantization=100,
            max_terms=1000,
            max_clause_count=4096,
            batch_size=16,
            threads=4,
            enabled=False,
            max_query_terms=32,
            prune_below=0.0,
            analyzer="wordpiece",
            static_prune_pct=0.0,
        ),
        xtr=XTRSettings(
            model_id="nomic-ai/CodeRankEmbed",
            device="cuda",
            max_query_tokens=256,
            candidate_k=200,
            dim=768,
            dtype="float16",
            enable=False,
            mode="narrow",
        ),
        embeddings=EmbeddingsSettings(),
        vllm=VLLMSettings(),
        search=SearchSettings(),
        logging=LoggingSettings(),
        index=IndexSettings(),
    )
    merged = merge_paths_with_app_config(base_paths, app_config)
    assertions.expect_equal(merged.duckdb_path, custom_duckdb)
    assertions.expect_equal(merged.faiss_index, custom_faiss)


def _stub_paths(repo_root: Path) -> ResolvedPaths:
    """Return ResolvedPaths populated with deterministic locations for tests.

    Parameters
    ----------
    repo_root : Path
        Base path used to derive deterministic locations.

    Returns
    -------
    ResolvedPaths
        Stubbed resolved paths instance referencing ``repo_root``.
    """
    return ResolvedPaths(
        repo_root=repo_root,
        config_dir=repo_root / "config",
        config_file=repo_root / "config" / "app.yml",
        data_dir=repo_root / "data",
        vectors_dir=repo_root / "data" / "vectors",
        faiss_index=repo_root / "indexes" / "code.ivfpq.faiss",
        faiss_idmap_path=repo_root / "indexes" / "faiss_idmap.parquet",
        lucene_dir=repo_root / "indexes" / "lucene",
        splade_dir=repo_root / "indexes" / "splade",
        duckdb_path=repo_root / "data" / "catalog.duckdb",
        scip_index=repo_root / "index.scip",
        coderank_vectors_dir=repo_root / "coderank" / "vectors",
        coderank_faiss_index=repo_root / "coderank" / "coderank.faiss",
        warp_index_dir=repo_root / "indexes" / "warp",
        xtr_dir=repo_root / "indexes" / "xtr",
        logs_dir=repo_root / "logs",
        cache_dir=repo_root / ".cache",
        tmp_dir=repo_root / ".tmp",
        plugins_dir=repo_root / "plugins",
    )


def _assert_faiss_manager(manager: object, expected_path: Path) -> None:
    assertions.expect_true(
        isinstance(manager, RecordingFAISSManager), reason="manager should be RecordingFAISSManager"
    )
    if isinstance(manager, RecordingFAISSManager):
        assertions.expect_equal(manager.index_path, expected_path)


def _assert_faiss_ready(context: ApplicationContext) -> None:
    ready, limits, error = context.ensure_faiss_ready()
    assertions.expect_true(ready, reason="faiss should be ready")
    assertions.expect_equal(limits, [])
    assertions.expect_equal(error, None)
    manager = cast("RecordingFAISSManager", context.faiss_manager)
    assertions.expect_equal(manager.load_calls, 1)


def _assert_catalog(
    catalog: RecordingDuckDBCatalog, expected_db: Path, expected_vectors: Path
) -> None:
    assertions.expect_true(
        isinstance(catalog, RecordingDuckDBCatalog),
        reason="catalog should be RecordingDuckDBCatalog",
    )
    assertions.expect_equal(catalog.db_path, expected_db)
    assertions.expect_equal(catalog.vectors_dir, expected_vectors)
    assertions.expect_true(catalog.open_called, reason="catalog.open should have been called")
