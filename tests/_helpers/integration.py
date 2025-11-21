"""Integration test harness for spinning up service layers without patching."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

import duckdb
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.scope_store import ScopeStore
from codeintel_rev.config.paths import resolve_application_paths
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogConfig
from codeintel_rev.io.duckdb_manager import DuckDBConfig, DuckDBManager
from codeintel_rev.io.faiss_compat import load_faiss_module
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.git_client import AsyncGitClient, GitClient
from codeintel_rev.io.vllm_client import VLLMClient

from tests._helpers.adapters import (
    InMemoryCommit,
    InMemoryFileAdapter,
    InMemoryHistoryAdapter,
    InMemoryScopeStore,
)
from tests._helpers.ml import FakeEmbeddingClient
from tests._helpers.settings import build_app_config_for_repo


class FakeRuntimeProtocol(Protocol):
    """Runtime tuning protocol used by FakeFAISSManager runtime stub."""

    def get_runtime_tuning(self) -> dict[str, Any]:
        """Get current runtime tuning parameters.

        Returns
        -------
        dict[str, Any]
            Current tuning parameters dictionary.
        """
        ...

    def set_runtime_tuning(self, params: dict[str, Any]) -> dict[str, Any]:
        """Set runtime tuning parameters.

        Parameters
        ----------
        params : dict[str, Any]
            Tuning parameters to set.

        Returns
        -------
        dict[str, Any]
            Updated tuning parameters dictionary.
        """
        ...


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

    def __getattr__(self, name: str) -> Callable[..., None]:  # pragma: no cover - defensive
        """Return placeholder function for unimplemented GitClient methods.

        Parameters
        ----------
        name : str
            Method name that was accessed.

        Returns
        -------
        Callable[..., None]
            Placeholder function that raises NotImplementedError.
        """

        def _missing(*_: object, **__: object) -> None:
            """Raise NotImplementedError for unimplemented method."""
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
    file_adapter: InMemoryFileAdapter | None = None
    history_adapter: InMemoryHistoryAdapter | None = None
    cleanup_callbacks: list[Callable[[], None]] = field(default_factory=list)

    def close(self) -> None:
        """Run registered cleanup callbacks in LIFO order."""
        for callback in reversed(self.cleanup_callbacks):
            callback()

    def require_history_adapter(self) -> InMemoryHistoryAdapter:
        """Return the attached history adapter or raise if missing.

        Returns
        -------
        InMemoryHistoryAdapter
            Initialized history adapter.

        Raises
        ------
        RuntimeError
            If the harness was constructed without a history adapter.
        """
        adapter = self.history_adapter
        if adapter is None:
            message = "history adapter not initialized on harness"
            raise RuntimeError(message)
        return adapter


@dataclass(slots=True)
class AdapterSeedConfig:
    """Configuration for building harnesses with seeded adapters."""

    blame_map: dict[str, list[tuple[InMemoryCommit, list[int]]]] | None = None
    history_map: dict[str, list[InMemoryCommit]] | None = None
    history_delay: float = 0.0
    populate_repo: bool = False
    populate_repo_on_disk: bool = True


@dataclass(slots=True)
class IntegrationHarnessOptions:
    """Configuration options for building the integration harness."""

    populate_repo: bool = False
    seed_files: dict[str, str] | None = None
    file_adapter: InMemoryFileAdapter | None = None
    history_adapter: InMemoryHistoryAdapter | None = None
    catalog_factory: Callable[[DuckDBCatalogConfig, DuckDBManager], DuckDBCatalog] | None = None
    use_real_faiss: bool | None = None


@dataclass
class FakeFAISSManager:
    """Minimal FAISS manager stub satisfying readiness/search paths."""

    results: list[Any] = field(default_factory=list)
    search_side_effect: Exception | None = None
    autotune_profile_path: Path = Path(__file__).resolve().parent / "faiss-tuning.json"
    vec_dim: int = 128
    active_runtime: dict[str, Any] = field(default_factory=lambda: {"nprobe": 32})

    @staticmethod
    def load_cpu_index(*, export_idmap: Path, profile_path: Path) -> None:
        """No-op load hook to satisfy readiness checks."""
        _ = export_idmap, profile_path

    def search(self, *_: object, **__: object) -> list[Any]:
        """Return pre-configured search results or raise side effect exception.

        Returns
        -------
        list[Any]
            List of pre-configured search results.

        Raises
        ------
        Exception
            If search_side_effect is set, raises that exception instead of returning results.

        Notes
        -----
        Time O(1); memory O(1) aside from result list. No I/O, no global state.
        Thread-safe for concurrent searches. Side effect exception is raised via
        instance variable (self.search_side_effect), not directly.
        """
        if self.search_side_effect is not None:
            raise self.search_side_effect
        return list(self.results)

    @property
    def runtime(self) -> FakeRuntimeProtocol:
        """Return runtime tuning stub instance.

        Returns
        -------
        FakeRuntimeProtocol
            Runtime instance with get_runtime_tuning and set_runtime_tuning methods.
        """

        class _Runtime(FakeRuntimeProtocol):
            """Runtime tuning stub implementation for FakeFAISSManager."""

            def __init__(self, parent: FakeFAISSManager) -> None:
                """Initialize runtime stub with parent manager.

                Parameters
                ----------
                parent : FakeFAISSManager
                    Parent FAISS manager instance.
                """
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
    """Create DuckDBCatalog instance from config and manager.

    Parameters
    ----------
    catalog_cfg : DuckDBCatalogConfig
        Catalog configuration.
    manager : DuckDBManager
        DuckDB manager instance.

    Returns
    -------
    DuckDBCatalog
        Configured catalog instance.
    """
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


def _faiss_available() -> bool:
    """Return True when FAISS bindings can be imported.

    Returns
    -------
    bool
        True if FAISS module can be imported, False otherwise.
    """
    try:
        load_faiss_module("integration harness availability check")
    except ModuleNotFoundError:
        return False
    except (ImportError, OSError, AttributeError, RuntimeError):
        return False
    return True


def build_integration_harness(
    base_dir: Path,
    options: IntegrationHarnessOptions | None = None,
) -> IntegrationHarness:
    """Create an ApplicationContext with in-memory fakes suitable for integration tests.

    Parameters
    ----------
    base_dir : Path
        Base directory for creating test repository structure.
    options : IntegrationHarnessOptions | None, optional
        Optional harness configuration. When omitted, the repo starts empty (no default seed files)
        and uses lightweight FAISS stubs unless bindings are available and explicitly requested.

    Returns
    -------
    IntegrationHarness
        Integration test harness with configured ApplicationContext.
    """
    opts = options or IntegrationHarnessOptions()
    repo_root = base_dir / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    if opts.populate_repo:
        (repo_root / "README.md").write_text("sample integration content\n", encoding="utf-8")
        (repo_root / "module.py").write_text("def sample():\n    return 1\n", encoding="utf-8")
    for relpath, content in (opts.seed_files or {}).items():
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
    catalog_builder = opts.catalog_factory or _default_catalog_factory

    if paths.duckdb_path.exists():
        try:
            duckdb.connect(str(paths.duckdb_path)).close()
        except duckdb.IOException:
            paths.duckdb_path.unlink(missing_ok=True)
            duckdb.connect(str(paths.duckdb_path)).close()
    else:
        duckdb.connect(str(paths.duckdb_path)).close()

    vllm_client = cast(
        "VLLMClient",
        FakeEmbeddingClient(
            embedding_dim=app_config.vllm.embedding_dim,
            batch_size=app_config.vllm.batch_size,
        ),
    )
    use_real = _faiss_available() if opts.use_real_faiss is None else opts.use_real_faiss
    if use_real and _faiss_available():
        faiss_manager: FAISSManager | FakeFAISSManager = FAISSManager(
            index_path=paths.faiss_index,
            vec_dim=app_config.index.vec_dim,
            nlist=app_config.index.faiss_nlist,
        )
        paths.faiss_idmap_path.touch()
    else:
        faiss_manager = cast("FAISSManager", FakeFAISSManager(vec_dim=app_config.index.vec_dim))
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
        duckdb_catalog_factory=catalog_builder,
        git_client=cast("GitClient", FakeGitClient()),
        async_git_client=cast("AsyncGitClient", FakeAsyncGitClient()),
    )

    return IntegrationHarness(
        context=context,
        repo_root=repo_root,
        file_adapter=opts.file_adapter,
        history_adapter=opts.history_adapter,
        cleanup_callbacks=[duckdb_manager.close],
    )


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
    harness = build_integration_harness(
        tmp_path,
        options=IntegrationHarnessOptions(populate_repo=True),
    )
    try:
        yield harness
    finally:
        harness.close()


def seed_repo_files(
    repo_root: Path,
    *,
    files: dict[str, str],
    mtime: float | None = None,
) -> None:
    """Create files on disk to mirror logical adapter seeds.

    Parameters
    ----------
    repo_root : Path
        Repository root.
    files : dict[str, str]
        Mapping of relative path -> content.
    mtime : float | None, optional
        Override modification time for all files.
    """
    for rel_path, content in files.items():
        target = repo_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if mtime is not None:
            target.touch()
            os.utime(target, (mtime, mtime))


def build_harness_with_adapters(
    base_dir: Path,
    *,
    files: dict[str, str],
    seed_config: AdapterSeedConfig | None = None,
) -> IntegrationHarness:
    """Build harness with in-memory file/history adapters pre-seeded.

    Parameters
    ----------
    base_dir : Path
        Temporary base directory.
    files : dict[str, str]
        Mapping of relative path -> content to seed adapters (and optionally disk).
    seed_config : AdapterSeedConfig | None, optional
        Adapter seeding configuration. Defaults to empty config when omitted.

    Returns
    -------
    IntegrationHarness
        Harness with context plus in-memory adapters attached.
    """
    config = seed_config or AdapterSeedConfig()

    file_adapter = InMemoryFileAdapter()
    for rel_path, content in files.items():
        file_adapter.add_file(rel_path, content)

    history_adapter = InMemoryHistoryAdapter(delay_seconds=config.history_delay)
    if config.blame_map:
        for rel_path, entries in config.blame_map.items():
            history_adapter.set_blame(
                rel_path,
                cast("list[tuple[InMemoryCommit, Sequence[int]]]", entries),
            )
    if config.history_map:
        for rel_path, commits in config.history_map.items():
            history_adapter.set_history(rel_path, commits)

    harness = build_integration_harness(
        base_dir,
        options=IntegrationHarnessOptions(
            populate_repo=config.populate_repo,
            file_adapter=file_adapter,
            history_adapter=history_adapter,
        ),
    )
    if config.populate_repo_on_disk:
        seed_repo_files(harness.repo_root, files=files)
    return harness


def generate_concurrent_file_set(
    count: int = 100,
    prefix: str = "src/file",
    suffix: str = ".py",
) -> dict[str, str]:
    """Generate deterministic file payloads for concurrency adapter tests.

    Parameters
    ----------
    count : int, optional
        Number of files to generate, by default 100.
    prefix : str, optional
        Filename prefix, by default "src/file".
    suffix : str, optional
        Filename suffix, by default ".py".

    Returns
    -------
    dict[str, str]
        Mapping of relative path to file content for the requested count.
    """
    return {
        f"{prefix}_{idx}{suffix}": f"def func_{idx}():\n    return {idx}\n" for idx in range(count)
    }


def build_async_adapters_harness(
    base_dir: Path,
    *,
    file_count: int = 200,
    history_delay: float = 0.0,
) -> IntegrationHarness:
    """Build harness tailored for async adapter concurrency/benchmark tests.

    Parameters
    ----------
    base_dir : Path
        Base directory for the harness.
    file_count : int, optional
        Number of files to generate, by default 200.
    history_delay : float, optional
        Delay for history operations, by default 0.0.

    Returns
    -------
    IntegrationHarness
        Harness with pre-seeded files and in-memory async history adapter.
    """
    files = generate_concurrent_file_set(count=file_count)
    commits = [
        InMemoryCommit(
            hexsha=f"{idx:08x}",
            author_name="LoadTest",
            author_email="load@example.com",
            summary=f"Commit {idx}",
        )
        for idx in range(file_count)
    ]
    history_map = {path: [commits[idx]] for idx, path in enumerate(files.keys())}
    blame_map = {path: [(commits[idx], [1, 2, 3, 4, 5])] for idx, path in enumerate(files.keys())}
    harness = build_harness_with_adapters(
        base_dir,
        files=files,
        seed_config=AdapterSeedConfig(
            history_map=history_map,
            blame_map=blame_map,
            populate_repo_on_disk=True,
            populate_repo=False,
            history_delay=history_delay,
        ),
    )
    if harness.history_adapter is not None:
        harness.context = harness.context.with_overrides(async_git_client=harness.history_adapter)
    return harness
