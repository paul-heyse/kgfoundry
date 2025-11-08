"""Shared pytest fixtures for table-driven testing and observability validation.

This module provides reusable fixtures for:
- Search options and configuration factories
- Problem Details payload loading and validation
- CLI command execution with captured output
- Logging and metrics capture (logs, Prometheus, OpenTelemetry)
- Idempotency and retry simulation
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import TYPE_CHECKING, ParamSpec, Protocol, TypeVar, cast

import pytest
from prometheus_client.registry import CollectorRegistry

from tests.bootstrap import ensure_src_path

# Ensure src path is available before importing kgfoundry_common modules
# Note: ensure_src_path() is idempotent and already called by importing tests.bootstrap,
# but we call it explicitly here for clarity and to ensure it runs before lazy imports
ensure_src_path()

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from _pytest.logging import LogCaptureFixture

    from kgfoundry_common.opentelemetry_types import (
        SpanExporterProtocol,
        SpanProtocol,
        TracerProviderProtocol,
    )
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
# Expose GPU stack availability for tooling and test gating.

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


class MetricSample(Protocol):
    """Protocol for Prometheus metric sample objects.

    Attributes
    ----------
    value : float
        Metric sample value.
    """

    value: float


class MetricFamily(Protocol):
    """Protocol for Prometheus metric family objects.

    Attributes
    ----------
    name : str
        Metric family name.
    samples : Sequence[MetricSample] | Iterable[MetricSample]
        Metric samples collection.
    """

    name: str
    samples: Sequence[MetricSample] | Iterable[MetricSample]


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


@fixture
def prometheus_registry() -> CollectorRegistry:
    """Provide an isolated Prometheus registry for metrics capture.

    Returns
    -------
    CollectorRegistry
        Fresh registry for this test; cleaned up after test completes.
    """
    return CollectorRegistry()


# Optional OpenTelemetry fixtures


@fixture
def otel_span_exporter() -> SpanExporterProtocol:
    """Provide an in-memory OpenTelemetry span exporter for testing.

    Returns
    -------
    SpanExporterProtocol
        In-memory span exporter instance.

    Raises
    ------
    SkipReturnedUnexpectedlyError
        If pytest.skip is called but control flow continues unexpectedly.
    """
    # Lazy import after path setup to avoid E402
    otel_types = import_module("kgfoundry_common.opentelemetry_types")
    load_exporter = cast(
        "Callable[[], Callable[[], SpanExporterProtocol] | None]",
        otel_types.load_in_memory_span_exporter_cls,
    )
    exporter_factory = load_exporter()
    if exporter_factory is None:
        skip_reason = "OpenTelemetry span exporter required for observability tests"
        pytest.skip(skip_reason)
        raise SkipReturnedUnexpectedlyError
    return exporter_factory()


@fixture
def otel_tracer_provider(
    otel_span_exporter: SpanExporterProtocol,
) -> Iterator[TracerProviderProtocol]:
    """Provide an OpenTelemetry tracer provider configured with in-memory exporter.

    Parameters
    ----------
    otel_span_exporter : SpanExporterProtocol
        Span exporter to use.

    Yields
    ------
    TracerProviderProtocol
        Configured tracer provider.

    Raises
    ------
    SkipReturnedUnexpectedlyError
        If pytest.skip is called but control flow continues unexpectedly.
    """
    # Lazy import after path setup to avoid E402
    otel_types = import_module("kgfoundry_common.opentelemetry_types")
    load_tracer_provider = cast(
        "Callable[[], Callable[[], TracerProviderProtocol] | None]",
        otel_types.load_tracer_provider_cls,
    )

    tracer_provider_factory = load_tracer_provider()
    if tracer_provider_factory is None:
        skip_reason = "OpenTelemetry SDK required for observability tests"
        pytest.skip(skip_reason)
        raise SkipReturnedUnexpectedlyError

    otel_trace_mod = cast(
        "ModuleType",
        pytest.importorskip(
            "opentelemetry.trace",
            reason="OpenTelemetry API required for observability tests",
        ),
    )

    provider = tracer_provider_factory()
    span_processor = _SimpleSpanProcessor(otel_span_exporter)
    provider.add_span_processor(span_processor)
    set_tracer_provider = cast(
        "Callable[[TracerProviderProtocol], None]", otel_trace_mod.set_tracer_provider
    )
    get_tracer_provider = cast(
        "Callable[[], TracerProviderProtocol]", otel_trace_mod.get_tracer_provider
    )
    set_tracer_provider(provider)
    try:
        yield provider
    finally:
        set_tracer_provider(get_tracer_provider())


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


@fixture
def metrics_asserter(
    prometheus_registry: CollectorRegistry,
) -> Callable[[str, int | float | None], None]:
    """Provide helpers for asserting Prometheus metrics.

    Parameters
    ----------
    prometheus_registry : CollectorRegistry
        Prometheus registry to check metrics in.

    Returns
    -------
    Callable[[str, int | float | None], None]
        Function to assert metric exists and has expected value.
    """

    def assert_metric(name: str, value: float | None = None) -> None:
        """Assert Prometheus metric exists and optionally has expected value.

        This helper function verifies that a Prometheus metric exists in the
        registry and optionally checks that it has the expected value. It
        searches through all registered collectors to find the metric by name.

        Parameters
        ----------
        name : str
            Metric name to check.
        value : float | None, optional
            Expected value (if None, only checks existence).

        Raises
        ------
        AssertionError
            If metric not found or value mismatch.
        """
        # Collect all families and samples
        families = [cast("MetricFamily", family) for family in prometheus_registry.collect()]
        for family in families:
            if family.name == name:
                samples_raw = list(family.samples)
                if samples_raw and value is not None:
                    sample = samples_raw[0]
                    actual = float(sample.value)
                    if actual != value:
                        msg = f"Metric {name}: expected {value}, got {actual}"
                        raise AssertionError(msg)
                return

        msg = f"Metric not found: {name}"
        raise AssertionError(msg)

    return assert_metric


class _SimpleSpanProcessor:
    """Simple span processor for in-memory collection during tests.

    This processor collects OpenTelemetry spans and immediately exports them
    through the provided exporter. It's designed for testing scenarios where
    spans need to be captured and inspected without the complexity of a full
    production span processor.

    Parameters
    ----------
    exporter : SpanExporterProtocol
        OTEL span exporter used to export collected spans.
    """

    def __init__(self, exporter: SpanExporterProtocol) -> None:
        self.exporter = exporter

    def on_start(self, span: SpanProtocol, parent_context: object | None = None) -> None:
        """No-op start hook to satisfy span processor protocol."""

    def force_flush(self, timeout_millis: int | None = None) -> bool:
        """Flush spans immediately (noop).

        Parameters
        ----------
        timeout_millis : int | None, optional
            Timeout in milliseconds (ignored).

        Returns
        -------
        bool
            Always returns True.
        """
        del timeout_millis
        return True

    def on_end(self, span: SpanProtocol) -> None:
        """Process ended span.

        This method is called by the OpenTelemetry SDK when a span ends.
        It immediately exports the span through the configured exporter.

        Parameters
        ----------
        span : SpanProtocol
            The ended span to export.
        """
        self.exporter.export([span])

    def shutdown(self) -> None:
        """Allow graceful shutdown calls (noop)."""


def _torch_smoke() -> tuple[bool, str]:
    """Perform PyTorch CUDA smoke test.

    Returns
    -------
    tuple[bool, str]
        (success, message)
    """
    try:
        import torch
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
    try:
        import faiss
        import numpy as np
    except (ImportError, ModuleNotFoundError) as exc:
        return False, f"faiss import failed: {exc}"

    # If this is a CPU-only wheel, gracefully skip
    if not hasattr(faiss, "StandardGpuResources"):
        return False, "faiss built without GPU bindings (StandardGpuResources missing)"

    try:
        ngpu = faiss.get_num_gpus() if hasattr(faiss, "get_num_gpus") else 0  # type: ignore[attr-defined]
        if ngpu <= 0:
            return False, "faiss.get_num_gpus() returned 0"

        res = faiss.StandardGpuResources()
        d = 64
        idx = faiss.GpuIndexFlatIP(res, d)  # type: ignore[attr-defined]
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
    "metrics_asserter",
    "otel_span_exporter",
    "otel_tracer_provider",
    "problem_details_loader",
    "prometheus_registry",
    "pytest_plugins",
    "structured_log_asserter",
    "temp_index_dir",
]
