"""Integration test harness for spinning up service layers without patching."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.scope_store import ScopeStore
from codeintel_rev.config.paths import resolve_application_paths
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogConfig
from codeintel_rev.io.duckdb_manager import DuckDBConfig, DuckDBManager
from codeintel_rev.io.vllm_client import VLLMClient

from tests._helpers.adapters import InMemoryScopeStore
from tests._helpers.ml import FakeEmbeddingClient
from tests._helpers.settings import build_app_config_for_repo


@dataclass(slots=True)
class FakeAsyncGitClient:
    """Async Git stub returning deterministic blame/history payloads."""

    blame_payload: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "line": 1,
                "commit": "abc1234",
                "author": "Test Author",
                "date": "2024-01-01T00:00:00Z",
                "message": "Test commit",
            }
        ]
    )
    history_payload: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "sha": "abc1234",
                "full_sha": "abc1234abcdef",
                "author": "Test Author",
                "email": "test@example.com",
                "date": "2024-01-01T00:00:00Z",
                "message": "Test commit",
            }
        ]
    )

    async def blame_range(self, *_: object, **__: object) -> list[dict[str, Any]]:
        """Return pre-configured blame payload.

        Parameters
        ----------
        *_ : Any
            Positional arguments (ignored).
        **__ : Any
            Keyword arguments (ignored).

        Returns
        -------
        list[dict[str, Any]]
            List of blame entry dictionaries.
        """
        return list(self.blame_payload)

    async def file_history(self, *_: object, **__: object) -> list[dict[str, Any]]:
        """Return pre-configured file history payload.

        Parameters
        ----------
        *_ : Any
            Positional arguments (ignored).
        **__ : Any
            Keyword arguments (ignored).

        Returns
        -------
        list[dict[str, Any]]
            List of file history commit dictionaries.
        """
        return list(self.history_payload)


@dataclass(slots=True)
class FakeGitClient:
    """Synchronous Git stub; not currently exercised by smoke tests."""

    def __getattr__(self, name: str) -> Callable[..., Any]:  # pragma: no cover - defensive
        def _missing(*_: Any, **__: Any) -> None:
            message = f"GitClient method {name} not implemented in fake"
            raise NotImplementedError(message)

        return _missing


@dataclass(slots=True)
class DictScopeStore:
    """Minimal async scope store returning dictionaries."""

    _data: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def get(self, name: str) -> dict[str, Any] | None:
        """Get scope dictionary for session ID.

        Parameters
        ----------
        name : str
            Session ID to look up.

        Returns
        -------
        dict[str, Any] | None
            Scope dictionary if found, None otherwise.
        """
        return self._data.get(name)

    async def set(self, name: str, value: dict[str, Any]) -> bool:
        """Set scope dictionary for session ID.

        Parameters
        ----------
        name : str
            Session ID to store scope for.
        value : dict[str, Any]
            Scope dictionary to store.

        Returns
        -------
        bool
            Always True on success.
        """
        self._data[name] = value
        return True

    async def delete(self, name: str) -> int:
        """Delete scope dictionary for session ID.

        Parameters
        ----------
        name : str
            Session ID to delete scope for.

        Returns
        -------
        int
            1 if scope was deleted, 0 if not found.
        """
        return 1 if self._data.pop(name, None) is not None else 0


@dataclass(slots=True)
class IntegrationHarness:
    """Bundle of initialized services for integration/smoke tests."""

    context: ApplicationContext
    repo_root: Path
    cleanup_callbacks: list[Callable[[], None]] = field(default_factory=list)

    def close(self) -> None:
        """Run registered cleanup callbacks in LIFO order."""
        for callback in reversed(self.cleanup_callbacks):
            callback()


@dataclass
class FakeFAISSManager:
    """Minimal FAISS manager stub satisfying readiness/search paths."""

    results: list[Any] = field(default_factory=list)
    search_side_effect: Exception | None = None
    autotune_profile_path: Path = (
        Path(__file__).resolve().parent / "faiss-tuning.json"
    )
    vec_dim: int = 128
    active_runtime: dict[str, Any] = field(default_factory=lambda: {"nprobe": 32})

    @staticmethod
    def load_cpu_index(*, export_idmap: Path, profile_path: Path) -> None:
        """No-op load hook to satisfy readiness checks."""
        _ = export_idmap, profile_path

    def search(self, *_: object, **__: object) -> list[Any]:
        """Return pre-configured search results or raise side effect exception.

        Parameters
        ----------
        *_ : Any
            Positional arguments (ignored).
        **__ : Any
            Keyword arguments (ignored).

        Returns
        -------
        list[Any]
            List of pre-configured search results.

        Notes
        -----
        If search_side_effect is set, raises that exception instead of returning results.
        """
        if self.search_side_effect is not None:
            raise self.search_side_effect
        return list(self.results)

    @property
    def runtime(self) -> Any:
        """Return runtime tuning stub instance.

        Returns
        -------
        _Runtime
            Runtime instance with get_runtime_tuning and set_runtime_tuning methods.
        """

        class _Runtime:
            def __init__(self, parent: FakeFAISSManager) -> None:
                self._parent = parent

            def get_runtime_tuning(self) -> dict[str, Any]:
                """Return current runtime tuning parameters.

                Returns
                -------
                dict[str, Any]
                    Dictionary with "active" key containing current tuning parameters.
                """
                return {"active": dict(self._parent.active_runtime)}

            def set_runtime_tuning(self, params: dict[str, Any]) -> dict[str, Any]:
                """Update runtime tuning parameters.

                Parameters
                ----------
                params : dict[str, Any]
                    Parameters to merge into active runtime tuning.

                Returns
                -------
                dict[str, Any]
                    Updated tuning parameters dictionary.
                """
                self._parent.active_runtime.update(params)
                return self.get_runtime_tuning()

        return _Runtime(self)


def _default_catalog_factory(
    catalog_cfg: DuckDBCatalogConfig,
    manager: DuckDBManager,
) -> DuckDBCatalog:
    catalog = DuckDBCatalog(
        catalog_cfg.db_path,
        catalog_cfg.vectors_dir,
        materialize=catalog_cfg.materialize,
        manager=manager,
        log_queries=catalog_cfg.log_queries,
        repo_root=catalog_cfg.repo_root,
    )
    catalog.set_idmap_path(catalog_cfg.idmap_path)
    return catalog


def build_integration_harness(
    base_dir: Path,
    *,
    populate_repo: bool = True,
    seed_files: dict[str, str] | None = None,
) -> IntegrationHarness:
    """Create an ApplicationContext with in-memory fakes suitable for integration tests.

    Parameters
    ----------
    base_dir : Path
        Base directory for creating test repository structure.
    populate_repo : bool, optional
        Whether to create default test files, by default True.
    seed_files : dict[str, str] | None, optional
        Additional files to create (relpath -> content), by default None.

    Returns
    -------
    IntegrationHarness
        Integration test harness with configured ApplicationContext.
    """
    repo_root = base_dir / "repo"
    repo_root.mkdir()
    if populate_repo:
        (repo_root / "README.md").write_text("sample integration content\n", encoding="utf-8")
        (repo_root / "module.py").write_text("def sample():\n    return 1\n", encoding="utf-8")
    for relpath, content in (seed_files or {}).items():
        target = repo_root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    app_config = build_app_config_for_repo(repo_root)
    paths = resolve_application_paths(app_config)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.vectors_dir.mkdir(parents=True, exist_ok=True)
    paths.faiss_index.parent.mkdir(parents=True, exist_ok=True)
    paths.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    paths.xtr_dir.mkdir(parents=True, exist_ok=True)
    paths.faiss_index.touch()
    paths.faiss_idmap_path.parent.mkdir(parents=True, exist_ok=True)

    catalog_cfg = DuckDBCatalogConfig(
        db_path=paths.duckdb_path,
        vectors_dir=paths.vectors_dir,
        repo_root=paths.repo_root,
        idmap_path=paths.faiss_idmap_path,
        materialize=app_config.index.duckdb_materialize,
        log_queries=False,
    )

    with duckdb.connect(str(paths.duckdb_path)):
        pass

    vllm_client: VLLMClient = FakeEmbeddingClient(
        embedding_dim=app_config.vllm.embedding_dim,
        batch_size=app_config.vllm.batch_size,
    )
    faiss_manager = FakeFAISSManager(vec_dim=app_config.index.vec_dim)
    faiss_manager.autotune_profile_path = paths.faiss_index.with_name("tuning.json")
    scope_backend = InMemoryScopeStore()
    scope_store = ScopeStore(
        scope_backend,
        l1_maxsize=app_config.redis.scope_l1_size,
        l1_ttl_seconds=app_config.redis.scope_l1_ttl_seconds,
        l2_ttl_seconds=app_config.redis.scope_l2_ttl_seconds,
    )
    duckdb_manager = DuckDBManager(paths.duckdb_path, DuckDBConfig())

    context = ApplicationContext(
        app_config=app_config,
        paths=paths,
        vllm_client=vllm_client,
        faiss_manager=faiss_manager,
        scope_store=scope_store,
        duckdb_manager=duckdb_manager,
        catalog_config=catalog_cfg,
        duckdb_catalog_factory=_default_catalog_factory,
        git_client=FakeGitClient(),
        async_git_client=FakeAsyncGitClient(),
    )

    harness = IntegrationHarness(
        context=context,
        repo_root=repo_root,
        cleanup_callbacks=[duckdb_manager.close],
    )
    return harness


def integration_harness_fixture(tmp_path: Path) -> Iterator[IntegrationHarness]:
    """Pytest-style fixture factory for integration harness usage.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path provided by pytest fixture.

    Yields
    ------
    IntegrationHarness
        Integration test harness instance, automatically closed after test.
    """
    harness = build_integration_harness(tmp_path)
    try:
        yield harness
    finally:
        harness.close()
