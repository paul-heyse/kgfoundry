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
import importlib.util
import json
import logging
import os
import sys
from collections.abc import Callable
from importlib import import_module, metadata
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, cast

import pytest
from fastapi import FastAPI

import tests.bootstrap  # noqa: F401
from tests.app._context_factory import build_application_context

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from _pytest.logging import LogCaptureFixture

    from kgfoundry_common.problem_details import JsonValue

P = ParamSpec("P")
R = TypeVar("R")

GPU_CORE_MODULES: tuple[str, ...] = (
    "torch",
    "torchvision",
    "torchaudio",
    "vllm",
    "faiss",
    "triton",
    "cuvs",
    "cuda",
    "cupy",
)


def _modules_available(modules: Iterable[str]) -> bool:
    return all(importlib.util.find_spec(module) is not None for module in modules)


def _has_distribution(dist_name: str) -> bool:
    """Return True when the given package distribution is installed.

    Parameters
    ----------
    dist_name : str
        Distribution package name to check.

    Returns
    -------
    bool
        True if the distribution is installed, False otherwise.
    """
    try:
        metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        return False
    return True


def _compute_has_gpu_stack() -> bool:
    if not _modules_available(GPU_CORE_MODULES):
        return False
    if os.getenv("ALLOW_GPU_TESTS_WITHOUT_CUDA") == "1":
        return True
    try:
        torch_module = import_module("torch")
    except ImportError:  # pragma: no cover - torch optional
        return False
    cuda_module: object = getattr(torch_module, "cuda", None)
    if not isinstance(cuda_module, ModuleType):
        return False
    raw_is_available = cast("object | None", getattr(cuda_module, "is_available", None))
    is_available_callable = cast(
        "Callable[[], object] | None",
        raw_is_available if callable(raw_is_available) else None,
    )
    if is_available_callable is None:
        return False
    return bool(is_available_callable())


HAS_GPU_STACK = _compute_has_gpu_stack()


def _faiss_runtime_available() -> bool:
    try:
        faiss_module = import_module("faiss")
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
# Expose GPU stack availability for tooling and test gating.

# Expose GPU stack availability for tooling and test gating.

if HAS_FAISS_SUPPORT:
    FAISS_MODULE = cast("Any", import_module("faiss"))
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
def _networking_test_app(tmp_path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Return a FastAPI app exposing readiness, capability, and SSE routes.

    The fixture mirrors the production routes but swaps heavy dependencies for
    lightweight stubs so HTTPX-based tests can exercise streaming and
    capability refresh logic without touching FAISS or GPU runtimes.

    Returns
    -------
    FastAPI
        Test application wired with readiness and capability endpoints.
    """
    from codeintel_rev.app.capabilities import Capabilities
    from codeintel_rev.app.main import capz, disable_nginx_buffering, readyz, sse_demo

    class _FakeReadinessResult:
        def __init__(self, *, healthy: bool = True, detail: str = "ok") -> None:
            self.healthy = healthy
            self._detail = detail

        def as_payload(self) -> dict[str, object]:
            return {"healthy": self.healthy, "detail": self._detail}

    class _FakeReadinessProbe:
        async def refresh(self) -> dict[str, _FakeReadinessResult]:
            await asyncio.sleep(0)
            return {"faiss": _FakeReadinessResult()}

    ctx = build_application_context(tmp_path)
    app = FastAPI()
    app.state.context = ctx
    app.state.readiness = _FakeReadinessProbe()

    initial_caps = Capabilities(
        faiss_index=True,
        duckdb=True,
        scip_index=True,
        vllm_client=True,
    )
    app.state.capabilities = initial_caps
    app.state.capability_stamp = initial_caps.stamp()

    refreshed_caps = Capabilities(
        faiss_index=False,
        duckdb=False,
        scip_index=False,
        vllm_client=False,
        faiss_importable=False,
        duckdb_importable=False,
        torch_importable=False,
        onnxruntime_importable=False,
        versions_available=2,
        active_index_version="v2",
    )

    def _fake_from_context(
        _cls: type[Capabilities],
        _context: object,
    ) -> Capabilities:
        return refreshed_caps

    monkeypatch.setattr(
        Capabilities,
        "from_context",
        classmethod(_fake_from_context),
    )

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


def _torch_smoke() -> tuple[bool, str]:
    """Perform PyTorch CUDA smoke test.

    Returns
    -------
    tuple[bool, str]
        (success, message)
    """
    import importlib.util

    torch_spec = importlib.util.find_spec("torch")
    if torch_spec is None:
        return False, "torch module not found"
    try:
        torch = importlib.import_module("torch")
    except (ImportError, ModuleNotFoundError) as exc:
        return False, f"torch import failed: {exc}"

    if not torch.cuda.is_available():
        return False, "torch.cuda.is_available() is False"

    try:
        dev = torch.device("cuda:0")
        # Init CUDA context and do a tiny GEMM
        torch.cuda.init()
        a = torch.randn(256, 256, device=dev)
        b = torch.randn(256, 256, device=dev)
        c = a @ b  # triggers cuBLAS
        c.sum().item()  # materialize
        torch.cuda.synchronize()
    except (RuntimeError, OSError) as exc:
        return False, f"torch CUDA smoke failed: {exc}"
    else:
        name = torch.cuda.get_device_name(0)
        cap = ".".join(map(str, torch.cuda.get_device_capability(0)))
        total = torch.cuda.get_device_properties(0).total_memory
        msg = f"PyTorch CUDA OK: {name}, CC {cap}, total_mem={total / 1e9:.2f} GB"
        return True, msg


def _faiss_smoke() -> tuple[bool, str]:
    """Perform FAISS GPU smoke test.

    Returns
    -------
    tuple[bool, str]
        (success, message)
    """
    import importlib.util

    faiss_spec = importlib.util.find_spec("faiss")
    if faiss_spec is None:
        return False, "faiss module not found"
    try:
        faiss = importlib.import_module("faiss")
        import numpy as np
    except (ImportError, ModuleNotFoundError) as exc:
        return False, f"faiss import failed: {exc}"

    # If this is a CPU-only wheel, gracefully skip
    if not hasattr(faiss, "StandardGpuResources"):
        return False, "faiss built without GPU bindings (StandardGpuResources missing)"

    try:
        ngpu = faiss.get_num_gpus() if hasattr(faiss, "get_num_gpus") else 0
        if ngpu <= 0:
            return False, "faiss.get_num_gpus() returned 0"

        res = faiss.StandardGpuResources()
        d = 64
        idx = faiss.GpuIndexFlatIP(res, d)
        rs = np.random.RandomState(0)
        xb = rs.randn(128, d).astype("float32")
        xq = rs.randn(4, d).astype("float32")
        # normalize for cosine-as-IP; no-op if you use L2 in your config
        xb /= np.linalg.norm(xb, axis=1, keepdims=True) + 1e-12
        xq /= np.linalg.norm(xq, axis=1, keepdims=True) + 1e-12
        idx.add(xb)
        _distances, indices = idx.search(xq, 5)
        assert indices.shape == (4, 5)
    except (RuntimeError, OSError, AttributeError) as exc:
        return False, f"FAISS GPU smoke failed: {exc}"
    else:
        msg = f"FAISS GPU OK: {ngpu} GPU(s) visible; GpuIndexFlatIP warm-up search ran"
        return True, msg


@fixture(scope="session", autouse=True)
def gpu_warmup_session() -> None:
    """Tiny GPU warm-up & early-fail. Set REQUIRE_GPU=1 to make missing GPU a hard error.

    Runs once at session start, before any tests. Performs minimal GPU operations
    to initialize CUDA contexts, cuBLAS, and FAISS GPU resources.

    If REQUIRE_GPU=1 is set, missing or unusable GPU will cause pytest to fail
    immediately with a clear message. Otherwise, warnings are issued but tests
    continue (allowing CPU-only test runs).
    """
    import warnings

    if os.getenv("SKIP_GPU_WARMUP", "0") == "1":
        print("[gpu-warmup] skipping GPU warm-up (SKIP_GPU_WARMUP=1)")
        return

    require_gpu = os.getenv("REQUIRE_GPU", "0") == "1"

    torch_ok, torch_msg = _torch_smoke()
    faiss_ok, faiss_msg = _faiss_smoke()

    # Print helpful diagnostics into pytest output
    print(f"[gpu-warmup] torch: {torch_msg}")
    print(f"[gpu-warmup] faiss: {faiss_msg}")

    if require_gpu:
        problems = []
        if not torch_ok:
            problems.append(f"PyTorch GPU not usable: {torch_msg}")
        if not faiss_ok:
            problems.append(f"FAISS GPU not usable: {faiss_msg}")
        if problems:
            pytest.fail(" | ".join(problems))
    else:
        # No hard requirement: warn so you can still run CPU-only tests locally.
        if not torch_ok:
            warnings.warn(f"[gpu-warmup] {torch_msg}", stacklevel=2)
        if not faiss_ok:
            warnings.warn(f"[gpu-warmup] {faiss_msg}", stacklevel=2)


__all__ = [
    "HAS_GPU_STACK",
    "caplog_records",
    "gpu_warmup_session",
    "load_problem_details_example",
    "problem_details_loader",
    "pytest_plugins",
    "structured_log_asserter",
    "temp_index_dir",
]
