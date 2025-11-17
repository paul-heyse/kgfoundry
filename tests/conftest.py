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
import sys
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, cast

import pytest
from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.main import capz, disable_nginx_buffering, readyz, sse_demo
from codeintel_rev.app.server_settings import get_server_settings
from fastapi import FastAPI

from tests.app._context_factory import build_application_context

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from _pytest.logging import LogCaptureFixture

    from kgfoundry_common.problem_details import JsonValue

P = ParamSpec("P")
R = TypeVar("R")


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
def _networking_test_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
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
            return {"healthy": self.healthy, "detail": self._detail}

    class _FakeReadinessProbe:
        def __init__(self) -> None:
            self.refresh_calls = 0

        async def refresh(self) -> dict[str, _FakeReadinessResult]:
            await asyncio.sleep(0)
            self.refresh_calls += 1
            return {"faiss": _FakeReadinessResult()}

    ctx = build_application_context(tmp_path)
    app = FastAPI()
    app.state.server_settings = get_server_settings().model_copy(deep=True)
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


__all__ = [
    "caplog_records",
    "load_problem_details_example",
    "problem_details_loader",
    "pytest_plugins",
    "structured_log_asserter",
    "temp_index_dir",
]
