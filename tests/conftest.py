"""Shared pytest fixtures for table-driven testing.

This module provides reusable fixtures for:
- Search options and configuration factories
- Problem Details payload loading and validation
- CLI command execution with captured output
- Logging capture
- Idempotency and retry simulation
"""

from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing as mp
import sys
from collections.abc import Callable, Mapping
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, cast

import pytest
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.main import capz, disable_nginx_buffering, readyz, sse_demo
from codeintel_rev.app.server_settings import get_server_settings
from codeintel_rev.cli.bm25 import BM25CliContext
from codeintel_rev.cli.splade import SpladeCliContext
from codeintel_rev.config.paths import ResolvedPaths
from codeintel_rev.io.bm25_manager import BM25IndexManager
from codeintel_rev.io.faiss_compat import load_faiss_module
from codeintel_rev.io.splade_manager import (
    SpladeArtifactsManager,
    SpladeEncoderService,
    SpladeIndexManager,
)
from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.ops.runtime.xtr_open import XtrOpenContext
from codeintel_rev.runtime.multiprocessing import ensure_spawn_start_method
from codeintel_rev.typedness import FileTypeSignals
from fastapi import FastAPI
from tools import repo_scan

from download.cli import ArtifactFS, DownloadCliContext, HarvestHandler
from orchestration.cli import BM25BuildConfig, OrchestrationCliContext
from orchestration.config import IndexCliConfig
from tests._helpers.http import build_test_app
from tests._helpers.repo import SampleRepo, bootstrap_sample_repo
from tests.app._context_factory import build_application_context

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from _pytest.logging import LogCaptureFixture
    from codeintel_rev.config.api import AppConfig
    from codeintel_rev.enrich.scip_reader import Document, SCIPIndex
    from codeintel_rev.enrich.stubs_overlay import OverlayPolicy

    from kgfoundry_common.problem_details import JsonValue
else:
    AppConfig = Any

P = ParamSpec("P")
R = TypeVar("R")

ensure_spawn_start_method(force=True)


def pytest_sessionstart(session: pytest.Session) -> None:
    """Run before any tests so multiprocessing always uses spawn."""
    del session
    method = mp.get_start_method(allow_none=True)
    if method != "spawn":
        mp.set_start_method("spawn", force=True)
    ensure_spawn_start_method(force=True)


def _faiss_runtime_available() -> bool:
    try:
        faiss_module = load_faiss_module("pytest FAISS support check")
    except ModuleNotFoundError:
        return False
    except (
        ImportError,
        OSError,
        AttributeError,
        RuntimeError,
    ) as exc:  # pragma: no cover - defensive against broken wheels
        logging.getLogger(__name__).debug(
            "faiss import failed, disabling FAISS-dependent tests", exc_info=exc
        )
        return False
    required_attrs = ("normalize_L2", "IndexFlatIP", "write_index")
    return all(hasattr(faiss_module, attr) for attr in required_attrs)


HAS_FAISS_SUPPORT = _faiss_runtime_available()

if HAS_FAISS_SUPPORT:
    FAISS_MODULE = cast("Any", load_faiss_module("pytest FAISS module cache"))
else:
    FAISS_MODULE: Any | None = None

pytest_plugins: tuple[str, ...] = ()
# Pytest plugin modules auto-loaded for the test suite.


if TYPE_CHECKING:  # pragma: no cover - typing support only

    def fixture(*args: object, **kwargs: object) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Create a pytest fixture.

        Parameters
        ----------
        *args : object
            Positional arguments for pytest.fixture.
        **kwargs : object
            Keyword arguments for pytest.fixture.

        Returns
        -------
        Callable[[Callable[P, R]], Callable[P, R]]
            Decorator function for creating fixtures.
        """
        ...

else:
    fixture = pytest.fixture


# Type aliases - use lazy import for JsonValue to avoid E402
def _get_json_value() -> object:
    """Lazy import JsonValue after path setup.

    Returns
    -------
    object
        JsonValue type alias.
    """
    module = import_module("kgfoundry_common.problem_details")
    return module.JsonValue


if TYPE_CHECKING:
    ProblemDetailsDict = dict[str, JsonValue]
else:
    _JsonValue = _get_json_value()
    ProblemDetailsDict = dict[str, _JsonValue]


@fixture(name="networking_test_app")
def _networking_test_app(tmp_path: Path) -> FastAPI:
    """Return a FastAPI app exposing readiness, capability, and SSE routes.

    The fixture mirrors the production routes but swaps heavy dependencies for
    lightweight stubs so HTTPX-based tests can exercise streaming and
    capability refresh logic without touching heavy FAISS runtimes.

    Returns
    -------
    FastAPI
        Test application wired with readiness and capability endpoints.
    """

    class _FakeReadinessResult:
        def __init__(self, *, healthy: bool = True, detail: str = "ok") -> None:
            self.healthy = healthy
            self._detail = detail

        def as_payload(self) -> dict[str, object]:
            """Convert readiness result to payload dictionary.

            Returns
            -------
            dict[str, object]
                Dictionary with healthy and detail fields.
            """
            return {"healthy": self.healthy, "detail": self._detail}

    class _FakeReadinessProbe:
        def __init__(self) -> None:
            self.refresh_calls = 0

        async def refresh(self) -> dict[str, _FakeReadinessResult]:
            """Refresh readiness checks and track call count.

            Returns
            -------
            dict[str, _FakeReadinessResult]
                Dictionary mapping "faiss" to fake readiness result.
            """
            await asyncio.sleep(0)
            self.refresh_calls += 1
            return {"faiss": _FakeReadinessResult()}

    ctx = build_application_context(tmp_path)
    app = build_test_app(ctx)
    app.state.server_settings = get_server_settings().model_copy(deep=True)
    app.state.readiness = _FakeReadinessProbe()

    capabilities = Capabilities.from_context(ctx)
    app.state.capabilities = capabilities
    app.state.capability_stamp = capabilities.stamp()

    app.add_api_route("/readyz", readyz)
    app.add_api_route("/capz", capz)
    app.add_api_route("/sse", sse_demo)
    app.middleware("http")(disable_nginx_buffering)
    return app


class SkipReturnedUnexpectedlyError(RuntimeError):
    """Raised when control reaches code after `pytest.skip`."""


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest by setting up Python path for src packages.

    This hook is called by pytest during initialization to configure the test
    environment. It ensures that the project's source directory is added to
    sys.path so that test modules can import packages from the src directory.

    Parameters
    ----------
    config : pytest.Config
        Pytest configuration object (required by pytest hook).
    """
    _ = config  # Unused but required by pytest hook signature
    repo_root = Path(__file__).parent.parent
    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


@fixture
def temp_index_dir() -> Iterator[Path]:
    """Provide a temporary directory for index operations.

    Yields
    ------
    Path
        Temporary directory that is cleaned up after the test.
    """
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@fixture
def caplog_records(caplog: LogCaptureFixture) -> dict[str, list[logging.LogRecord]]:
    """Capture logs by operation name for structured assertions.

    This fixture captures log records during test execution and groups them
    by operation name (extracted from the 'operation' field in structured logs).
    This enables test assertions that verify log messages for specific operations.

    Parameters
    ----------
    caplog : LogCaptureFixture
        Pytest fixture for capturing log records.

    Returns
    -------
    dict[str, list[logging.LogRecord]]
        Mapping of operation → list of log records for that operation.
    """

    def _collect_records() -> dict[str, list[logging.LogRecord]]:
        """Collect records grouped by operation.

        Returns
        -------
        dict[str, list[logging.LogRecord]]
            Mapping of operation name to log records.
        """
        records_by_op: dict[str, list[logging.LogRecord]] = {}
        records = [record for record in caplog.records if isinstance(record, logging.LogRecord)]
        for record in records:
            record_dict = cast("dict[str, object]", record.__dict__)
            op_obj = record_dict.get("operation", "unknown")
            op = op_obj if isinstance(op_obj, str) else "unknown"
            records_by_op.setdefault(op, []).append(record)
        return records_by_op

    return _collect_records()


def load_problem_details_example(example_name: str) -> ProblemDetailsDict:
    """Load a Problem Details example from schema/examples.

    Parameters
    ----------
    example_name : str
        Name of the example file (e.g., "search-missing-index").

    Returns
    -------
    ProblemDetailsDict
        Parsed Problem Details JSON.

    Raises
    ------
    FileNotFoundError
        If example file does not exist.
    """
    example_path = (
        Path(__file__).parent.parent / "schema/examples/problem_details" / f"{example_name}.json"
    )
    if not example_path.exists():
        msg = f"Problem Details example not found: {example_path}"
        raise FileNotFoundError(msg)

    # Lazy import JsonValue after path setup to avoid E402

    return cast("dict[str, JsonValue]", json.loads(example_path.read_text(encoding="utf-8")))


@fixture
def problem_details_loader() -> Callable[[str], ProblemDetailsDict]:
    """Fixture providing access to Problem Details examples.

    Returns
    -------
    Callable[[str], ProblemDetailsDict]
        Function load_problem_details_example() bound to this fixture.
    """
    return load_problem_details_example


@fixture
def structured_log_asserter() -> Callable[[logging.LogRecord, set[str]], None]:
    """Provide helpers for asserting structured log fields.

    Returns
    -------
    Callable[[logging.LogRecord, set[str]], None]
        Function to assert log record has required fields.
    """

    def assert_log_has_fields(
        record: logging.LogRecord,
        required_fields: set[str],
    ) -> None:
        """Assert log record includes all required fields.

        This helper function checks that a log record contains all expected
        structured fields. It extracts fields from the log record's 'extra'
        dictionary and verifies that all required field names are present.

        Parameters
        ----------
        record : logging.LogRecord
            The log record to check.
        required_fields : set[str]
            Field names that must be present.

        Raises
        ------
        AssertionError
            If any required field is missing.
        """
        record_dict = cast("dict[str, object]", record.__dict__)
        missing = required_fields - set(record_dict.keys())
        if missing:
            msg = f"Missing fields in log record: {missing}"
            raise AssertionError(msg)

    return assert_log_has_fields


@pytest.fixture(name="scan_inputs_builder")
def fixture_scan_inputs_builder(tmp_path: Path) -> Callable[..., Any]:
    """Return a factory for constructing ``ScanInputs`` instances.

    Returns
    -------
    Callable[..., ScanInputs]
        Builder function that accepts override keyword arguments and yields
        populated ``ScanInputs`` objects.
    """

    def build(  # noqa: PLR0913
        *,
        repo_root: Path | None = None,
        scip_index: SCIPIndex | None = None,
        scip_by_file: Mapping[str, Document] | None = None,
        type_signals: Mapping[str, FileTypeSignals] | None = None,
        coverage_map: Mapping[str, Mapping[str, float]] | None = None,
        tagging_rules: Mapping[str, object] | None = None,
        max_file_bytes: int = 10_000,
        package_prefix: str | None = None,
    ) -> Any:
        """Build ScanInputs instance with optional overrides.

        Parameters
        ----------
        repo_root : Path | None, optional
            Repository root directory.
        scip_index : SCIPIndex | None, optional
            SCIP index instance.
        scip_by_file : Mapping[str, Document] | None, optional
            SCIP documents by file path.
        type_signals : Mapping[str, FileTypeSignals] | None, optional
            Type signals by file path.
        coverage_map : Mapping[str, Mapping[str, float]] | None, optional
            Coverage map by file path.
        tagging_rules : Mapping[str, object] | None, optional
            Tagging rules.
        max_file_bytes : int, optional
            Maximum file size in bytes, by default 10_000.
        package_prefix : str | None, optional
            Package prefix string.

        Returns
        -------
        ScanInputs
            Configured ScanInputs instance.
        """
        root = repo_root or (tmp_path / "repo")
        root.mkdir(parents=True, exist_ok=True)
        from codeintel_rev.cli.enrich_pipeline import ScanInputs, ScipContext
        from codeintel_rev.enrich.scip_reader import SCIPIndex

        scip = scip_index or SCIPIndex()
        context = ScipContext(index=scip, by_file=scip_by_file or {})
        return ScanInputs(
            scip_ctx=context,
            type_signals=type_signals or {},
            coverage_map=coverage_map or {},
            tagging_rules=tagging_rules or {},
            repo_root=root,
            max_file_bytes=max_file_bytes,
            package_prefix=package_prefix or root.name,
        )

    return build


@pytest.fixture(name="overlay_context_builder")
def fixture_overlay_context_builder(tmp_path: Path) -> Callable[..., Any]:
    """Provide a factory for building ``OverlayContext`` instances.

    Returns
    -------
    Callable[..., OverlayContext]
        Builder for ``OverlayContext`` objects rooted in temporary directories.
    """

    def build(  # noqa: PLR0913
        *,
        repo_root: Path | None = None,
        overlays_root: Path | None = None,
        stubs_root: Path | None = None,
        type_counts: Mapping[str, int] | None = None,
        policy: OverlayPolicy | None = None,
        scip_index: SCIPIndex | None = None,
        overlay_paths: frozenset[str] | None = None,
    ) -> Any:
        """Build OverlayContext instance with optional overrides.

        Parameters
        ----------
        repo_root : Path | None, optional
            Repository root directory.
        overlays_root : Path | None, optional
            Overlays directory root.
        stubs_root : Path | None, optional
            Stubs directory root.
        type_counts : Mapping[str, int] | None, optional
            Type error counts by file path.
        policy : OverlayPolicy | None, optional
            Overlay policy configuration.
        scip_index : SCIPIndex | None, optional
            SCIP index instance.
        overlay_paths : frozenset[str] | None, optional
            Set of overlay-tagged file paths.

        Returns
        -------
        OverlayContext
            Configured OverlayContext instance.
        """
        root = repo_root or (tmp_path / "overlay_repo")
        overlays = overlays_root or (tmp_path / "overlays")
        stubs = stubs_root or (tmp_path / "stubs")
        for path in (root, overlays, stubs):
            path.mkdir(parents=True, exist_ok=True)
        from codeintel_rev.cli.enrich_pipeline import OverlayContext
        from codeintel_rev.enrich.scip_reader import SCIPIndex
        from codeintel_rev.enrich.stubs_overlay import OverlayInputs, OverlayPolicy

        scip = scip_index or SCIPIndex()
        resolved_policy = policy or OverlayPolicy(
            overlays_root=overlays,
            include_public_defs=True,
            inject_module_getattr_any=False,
            when_type_errors=False,
            min_type_errors=0,
            max_overlays=32,
            export_hub_threshold=10,
            overlay_tag="overlay-needed",
        )
        return OverlayContext(
            root=root,
            package_name=root.name,
            overlays_root=overlays,
            stubs_root=stubs,
            scip_index=scip,
            type_counts=dict(type_counts or {}),
            policy=resolved_policy,
            inputs=OverlayInputs(
                scip=scip,
                type_error_counts=dict(type_counts or {}),
                overlay_tagged_paths=overlay_paths or frozenset(),
            ),
        )

    return build


@pytest.fixture(name="orchestration_cli_context_builder")
def fixture_orchestration_cli_context_builder() -> Callable[..., OrchestrationCliContext]:
    """Return a builder for orchestration CLI contexts used across tests.

    Returns
    -------
    Callable[..., OrchestrationCliContext]
        Factory that accepts dependency overrides for CLI invocations.
    """
    base = OrchestrationCliContext.production()

    def build(
        *,
        uuid_factory: Callable[[], str] | None = None,
        bm25_builder: Callable[[BM25BuildConfig, logging.Logger], tuple[str, int]] | None = None,
        faiss_runner: Callable[[IndexCliConfig], dict[str, object]] | None = None,
        artifact_fs: ArtifactFS | None = None,
    ) -> OrchestrationCliContext:
        """Build OrchestrationCliContext with optional dependency overrides.

        Parameters
        ----------
        uuid_factory : Callable[[], str] | None, optional
            UUID generation factory.
        bm25_builder : Callable[[BM25BuildConfig, logging.Logger], tuple[str, int]] | None, optional
            BM25 index builder function.
        faiss_runner : Callable[[IndexCliConfig], dict[str, object]] | None, optional
            FAISS indexing runner function.
        artifact_fs : ArtifactFS | None, optional
            Artifact filesystem interface.

        Returns
        -------
        OrchestrationCliContext
            Configured orchestration CLI context.
        """
        return OrchestrationCliContext(
            uuid_factory=uuid_factory or base.uuid_factory,
            bm25_builder=bm25_builder or base.bm25_builder,
            faiss_runner=faiss_runner or base.faiss_runner,
            artifact_fs=artifact_fs or base.artifact_fs,
        )

    return build


@pytest.fixture(name="xtr_cli_context_builder")
def fixture_xtr_cli_context_builder() -> Callable[..., XtrOpenContext]:
    """Return a builder for XTR CLI contexts used in runtime ops tests.

    Returns
    -------
    Callable[..., XtrOpenContext]
        Builder function that creates XtrOpenContext instances with optional
        overrides for app_config_loader, paths_resolver, and index_factory.
    """
    base = XtrOpenContext.production()

    def build(
        *,
        app_config_loader: Callable[[], AppConfig] | None = None,
        paths_resolver: Callable[[AppConfig], ResolvedPaths] | None = None,
        index_factory: Callable[[Path, AppConfig], XTRIndex] | None = None,
    ) -> XtrOpenContext:
        """Build XtrOpenContext with optional dependency overrides.

        Parameters
        ----------
        app_config_loader : Callable[[], AppConfig] | None, optional
            Application configuration loader.
        paths_resolver : Callable[[AppConfig], ResolvedPaths] | None, optional
            Paths resolver function.
        index_factory : Callable[[Path, AppConfig], XTRIndex] | None, optional
            XTR index factory function.

        Returns
        -------
        XtrOpenContext
            Configured XTR CLI context.
        """
        return XtrOpenContext(
            app_config_loader=app_config_loader or base.app_config_loader,
            paths_resolver=paths_resolver or base.paths_resolver,
            index_factory=index_factory or base.index_factory,
        )

    return build


@pytest.fixture(name="bm25_cli_context_builder")
def fixture_bm25_cli_context_builder() -> Callable[..., BM25CliContext]:
    """Return a builder for BM25 CLI contexts used in search/index tests.

    Returns
    -------
    Callable[..., BM25CliContext]
        Factory accepting a custom manager factory override.
    """
    base = BM25CliContext.production()

    def build(
        *,
        manager_factory: Callable[[], BM25IndexManager] | None = None,
    ) -> BM25CliContext:
        """Build BM25CliContext with optional manager factory override.

        Parameters
        ----------
        manager_factory : Callable[[], BM25IndexManager] | None, optional
            BM25 index manager factory.

        Returns
        -------
        BM25CliContext
            Configured BM25 CLI context.
        """
        return BM25CliContext(manager_factory=manager_factory or base.manager_factory)

    return build


@pytest.fixture(name="splade_cli_context_builder")
def fixture_splade_cli_context_builder() -> Callable[..., SpladeCliContext]:
    """Return a builder for SPLADE CLI contexts.

    Returns
    -------
    Callable[..., SpladeCliContext]
        Factory accepting overrides for artifacts/encoder/index factories.
    """
    base = SpladeCliContext.production()

    def build(
        *,
        artifacts_factory: Callable[[], SpladeArtifactsManager] | None = None,
        encoder_factory: Callable[[], SpladeEncoderService] | None = None,
        index_factory: Callable[[], SpladeIndexManager] | None = None,
    ) -> SpladeCliContext:
        """Build SpladeCliContext with optional factory overrides.

        Parameters
        ----------
        artifacts_factory : Callable[[], SpladeArtifactsManager] | None, optional
            Artifacts manager factory.
        encoder_factory : Callable[[], SpladeEncoderService] | None, optional
            Encoder service factory.
        index_factory : Callable[[], SpladeIndexManager] | None, optional
            Index manager factory.

        Returns
        -------
        SpladeCliContext
            Configured SPLADE CLI context.
        """
        return SpladeCliContext(
            artifacts_factory=artifacts_factory or base.artifacts_factory,
            encoder_factory=encoder_factory or base.encoder_factory,
            index_factory=index_factory or base.index_factory,
        )

    return build


@pytest.fixture(name="download_cli_context_builder")
def fixture_download_cli_context_builder() -> Callable[..., DownloadCliContext]:
    """Return a builder for download CLI contexts.

    Returns
    -------
    Callable[..., DownloadCliContext]
        Factory accepting a harvest handler override.
    """
    base = DownloadCliContext.production()

    def build(
        *,
        harvest_handler: HarvestHandler | None = None,
        artifact_dir: Path | None = None,
        artifact_fs: ArtifactFS | None = None,
    ) -> DownloadCliContext:
        """Build DownloadCliContext with optional dependency overrides.

        Parameters
        ----------
        harvest_handler : HarvestHandler | None, optional
            Harvest handler instance.
        artifact_dir : Path | None, optional
            Artifact directory path.
        artifact_fs : ArtifactFS | None, optional
            Artifact filesystem interface.

        Returns
        -------
        DownloadCliContext
            Configured download CLI context.
        """
        return DownloadCliContext(
            harvest_handler=harvest_handler or base.harvest_handler,
            artifact_dir=artifact_dir or base.artifact_dir,
            artifact_fs=artifact_fs or base.artifact_fs,
        )

    return build


@pytest.fixture(name="sample_repo_builder")
def fixture_sample_repo_builder(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[str | None], SampleRepo]:
    """Return a builder that bootstraps sample repositories for CLI tests.

    Returns
    -------
    Callable[[str | None], SampleRepo]
        Factory that materializes deterministic repositories under tmp dirs.
    """

    def build(subdir: str | None = None) -> SampleRepo:
        """Build sample repository in temporary directory.

        Parameters
        ----------
        subdir : str | None, optional
            Subdirectory name for temporary directory.

        Returns
        -------
        SampleRepo
            Bootstrapped sample repository instance.
        """
        base_dir = tmp_path_factory.mktemp(subdir or "sample_repo")
        return bootstrap_sample_repo(base_dir)

    return build


@pytest.fixture(name="sample_repo")
def fixture_sample_repo(
    sample_repo_builder: Callable[[str | None], SampleRepo],
) -> SampleRepo:
    """Provide a ready-to-use sample repository rooted in a temporary directory.

    Returns
    -------
    SampleRepo
        Bootstrapped repository with SCIP index and git metadata.
    """
    return sample_repo_builder(None)


@pytest.fixture(name="repo_scan_invoker")
def fixture_repo_scan_invoker(tmp_path: Path) -> Callable[..., tuple[dict[str, Any], Path, Path]]:
    """Return a helper that runs repo_scan with explicit arguments.

    Returns
    -------
    Callable[..., tuple[dict[str, Any], Path, Path]]
        Function that executes repo_scan and yields payload + artifact paths.
    """

    def run(
        *,
        scan_root: Path,
        out_dir: Path | None = None,
        argv: list[str] | None = None,
    ) -> tuple[dict[str, Any], Path, Path]:
        """Run repo_scan with specified arguments.

        Parameters
        ----------
        scan_root : Path
            Root directory to scan.
        out_dir : Path | None, optional
            Output directory for artifacts.
        argv : list[str] | None, optional
            Additional command-line arguments.

        Returns
        -------
        tuple[dict[str, Any], Path, Path]
            Tuple of payload dictionary, dot file path, and enriched dot file path.
        """
        out_root = out_dir or (tmp_path / "repo_scan_out")
        out_root.mkdir(parents=True, exist_ok=True)
        json_path = out_root / "metrics.json"
        dot_path = out_root / "graph.dot"
        enriched_path = out_root / "graph_enriched.dot"
        args = [
            str(scan_root),
            "--repo-root",
            str(scan_root),
            "--out-json",
            str(json_path),
            "--out-dot",
            str(dot_path),
            "--enriched-dot",
            str(enriched_path),
        ]
        if argv:
            args.extend(argv)
        payload, edges = repo_scan.run_with_args(args)
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        repo_scan.write_dot(edges, dot_path)
        repo_scan.write_enriched_dot(edges, enriched_path, payload.get("graph_summary", {}))
        return payload, dot_path, enriched_path

    return run


__all__ = [
    "caplog_records",
    "load_problem_details_example",
    "problem_details_loader",
    "pytest_plugins",
    "structured_log_asserter",
    "temp_index_dir",
]
