"""Unit tests targeting the orchestrated PipelineRunner."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal, cast

from tools.docstring_builder.builder_types import (
    STATUS_LABELS,
    DocstringBuildRequest,
    ExitStatus,
    status_from_exit,
)
from tools.docstring_builder.metrics import MetricsRecorder
from tools.docstring_builder.orchestrator import load_builder_config
from tools.docstring_builder.pipeline import PipelineConfig, PipelineRunner
from tools.docstring_builder.pipeline_types import DocfactsResult, FileOutcome, ProcessingOptions
from tools.docstring_builder.policy import PolicyReport

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    import pytest
    from tools.docstring_builder.cache import BuilderCache
    from tools.docstring_builder.diff_manager import DiffManager
    from tools.docstring_builder.docfacts import DocFact
    from tools.docstring_builder.docfacts_coordinator import DocfactsCoordinator
    from tools.docstring_builder.file_processor import FileProcessor
    from tools.docstring_builder.models import ErrorReport, ProblemDetails
    from tools.docstring_builder.policy import PolicyEngine
    from tools.docstring_builder.semantics import SemanticResult


def _noop_record_docfacts(_facts: Iterable[DocFact], _path: Path) -> None:
    return None


def _empty_docfacts() -> list[DocFact]:
    return []


def _problem_details_stub(
    status: ExitStatus,
    request: DocstringBuildRequest,
    detail: str,
    *,
    instance: str | None = None,
    errors: Sequence[ErrorReport] | None = None,
) -> ProblemDetails:
    return {
        "type": "https://kgfoundry.dev/problems/test",
        "title": "stub",
        "status": int(status),
        "detail": detail,
        "instance": instance or "",
        "extensions": {
            "command": request.command,
            "subcommand": request.subcommand,
            "errorCount": len(errors or []),
        },
    }


class _StubPolicyEngine:
    def record(self, _semantics: Sequence[SemanticResult]) -> None:  # pragma: no cover - no-op
        return

    def finalize(self) -> PolicyReport:
        return PolicyReport(coverage=1.0, threshold=1.0, violations=[])


type DocfactsStatus = Literal["success", "violation", "config", "error"]


class _StubDocfactsCoordinator:
    def __init__(self, status: DocfactsStatus, message: str | None = None) -> None:
        self._status: DocfactsStatus = status
        self._message = message

    def reconcile(self, _docfacts: Iterable[DocFact]) -> DocfactsResult:
        return DocfactsResult(
            status=self._status,
            message=self._message,
            diff_path=None,
        )


class _StubDiffManager:
    def __init__(self) -> None:
        self.baseline_calls: list[tuple[str, str | None]] = []
        self.recorded_docfacts: list[str | None] = []

    def record_docstring_baseline(self, file_path: Path, preview: str | None) -> None:
        """Record the baseline docstring for diff inspection."""
        self.baseline_calls.append((str(file_path), preview))

    def finalize_docstring_drift(self) -> None:  # pragma: no cover - no-op
        return

    def record_docfacts_baseline_diff(self, payload_text: str | None) -> None:  # pragma: no cover
        self.recorded_docfacts.append(payload_text)

    def collect_diff_links(self) -> dict[str, str]:  # pragma: no cover - deterministic
        return {}


@dataclass(slots=True, frozen=True)
class PipelineConfigOverrides:
    """Customization knobs for building pipeline configurations in tests."""

    docfacts_status: DocfactsStatus = "success"
    docfacts_message: str | None = None
    baseline: str | None = None
    diff_manager: DiffManager | None = None


@dataclass(slots=True, frozen=True)
class _MetricsHistogram:
    labels_called: list[dict[str, object]] = field(default_factory=list)
    observed: list[float] = field(default_factory=list)

    def labels(self, **labels: object) -> _MetricsHistogram:
        self.labels_called.append(labels)
        return self

    def observe(self, value: float) -> None:
        self.observed.append(value)


@dataclass(slots=True, frozen=True)
class _MetricsCounter:
    labels_called: list[dict[str, object]] = field(default_factory=list)
    increments: list[float] = field(default_factory=list)

    def labels(self, **labels: object) -> _MetricsCounter:
        self.labels_called.append(labels)
        return self

    def inc(self, value: float = 1.0) -> None:
        self.increments.append(value)


def _build_metrics_recorder() -> MetricsRecorder:
    histogram = _MetricsHistogram()
    counter = _MetricsCounter()
    return MetricsRecorder(cli_duration_seconds=histogram, runs_total=counter)


def make_pipeline_config(
    request: DocstringBuildRequest,
    file_outcomes: Sequence[FileOutcome],
    overrides: PipelineConfigOverrides | None = None,
) -> PipelineConfig:
    """Construct a pipeline configuration tailored for orchestrator tests.

    Parameters
    ----------
    request : DocstringBuildRequest
        Build request containing command and file selection.
    file_outcomes : Sequence[FileOutcome]
        Sequence of file processing outcomes to simulate.
    overrides : PipelineConfigOverrides | None
        Optional configuration overrides for customizing test behavior.

    Returns
    -------
    PipelineConfig
        Configuration instance ready for execution by the pipeline runner.
    """
    overrides = overrides or PipelineConfigOverrides()

    def _write_cache() -> None:
        return None

    cache = cast("BuilderCache", SimpleNamespace(write=_write_cache))

    outcomes_iter = iter(file_outcomes)

    def _process_file(_path: Path) -> FileOutcome:
        try:
            return next(outcomes_iter)
        except StopIteration:  # pragma: no cover - defensive guard
            return file_outcomes[-1]

    file_processor = cast("FileProcessor", SimpleNamespace(process=_process_file))

    class CoordinatorFactory:
        """Factory for creating DocfactsCoordinator instances."""

        def __call__(self, *, check_mode: bool) -> DocfactsCoordinator:
            """Create a coordinator stub with status tailored to ``check_mode``.

            Parameters
            ----------
            check_mode : bool
                Whether to use check-mode status or success status.

            Returns
            -------
            DocfactsCoordinator
                Coordinator instance seeded with the desired status and message.
            """
            status = overrides.docfacts_status if check_mode else "success"
            return cast(
                "DocfactsCoordinator",
                _StubDocfactsCoordinator(
                    status=status,
                    message=overrides.docfacts_message,
                ),
            )

    coordinator_factory = CoordinatorFactory()

    config, _ = load_builder_config(None)

    chosen_diff_manager = overrides.diff_manager or cast("DiffManager", _StubDiffManager())

    return PipelineConfig(
        request=request,
        config=config,
        selection=None,
        options=ProcessingOptions(
            command=request.command,
            force=False,
            ignore_missing=False,
            missing_patterns=(),
            skip_docfacts=request.command not in {"update", "check"},
            baseline=overrides.baseline,
        ),
        cache=cache,
        file_processor=file_processor,
        record_docfacts=_noop_record_docfacts,
        filter_docfacts=_empty_docfacts,
        docfacts_coordinator_factory=coordinator_factory,
        plugin_manager=None,
        policy_engine=cast("PolicyEngine", _StubPolicyEngine()),
        metrics=_build_metrics_recorder(),
        diff_manager=chosen_diff_manager,
        logger=logging.getLogger(__name__),
        status_from_exit=status_from_exit,
        status_labels=STATUS_LABELS,
        build_problem_details=_problem_details_stub,
        success_status=ExitStatus.SUCCESS,
        violation_status=ExitStatus.VIOLATION,
        config_status=ExitStatus.CONFIG,
        error_status=ExitStatus.ERROR,
    )


def test_pipeline_runner_collects_diff_previews(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = DocstringBuildRequest(command="check", subcommand="check", diff=True)
    outcome = FileOutcome(
        status=ExitStatus.VIOLATION,
        docfacts=_empty_docfacts(),
        preview="diff output",
        changed=True,
        skipped=False,
    )
    config = make_pipeline_config(request, [outcome])

    dummy_path = tmp_path / "module.py"
    dummy_path.write_text("# placeholder")

    monkeypatch.setattr(
        "tools.docstring_builder.pipeline.CACHE_PATH",
        tmp_path / "cache",
    )
    monkeypatch.setattr(
        "tools.docstring_builder.pipeline.OBSERVABILITY_PATH",
        tmp_path / "observability.json",
    )

    runner = PipelineRunner(config)
    result = runner.run([dummy_path])

    assert result.diff_previews == [(dummy_path, "diff output")]


def test_pipeline_runner_records_docfacts_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = DocstringBuildRequest(command="check", subcommand="check")
    outcome = FileOutcome(
        status=ExitStatus.SUCCESS,
        docfacts=_empty_docfacts(),
        preview=None,
        changed=False,
        skipped=False,
    )
    config = make_pipeline_config(
        request,
        [outcome],
        overrides=PipelineConfigOverrides(
            docfacts_status="violation",
            docfacts_message="docfacts drift",
        ),
    )

    dummy_path = tmp_path / "module.py"
    dummy_path.write_text("# placeholder")

    monkeypatch.setattr(
        "tools.docstring_builder.pipeline.CACHE_PATH",
        tmp_path / "cache",
    )
    monkeypatch.setattr(
        "tools.docstring_builder.pipeline.OBSERVABILITY_PATH",
        tmp_path / "observability.json",
    )

    runner = PipelineRunner(config)
    result = runner.run([dummy_path])

    assert result.exit_status is ExitStatus.VIOLATION
    assert any(error["file"] == "<docfacts>" for error in result.errors)


def test_pipeline_runner_records_docfacts_baseline_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = DocstringBuildRequest(command="update", subcommand="update", json_output=True)
    outcome = FileOutcome(
        status=ExitStatus.SUCCESS,
        docfacts=_empty_docfacts(),
        preview=None,
        changed=False,
        skipped=False,
    )
    diff_manager = _StubDiffManager()
    config = make_pipeline_config(
        request,
        [outcome],
        overrides=PipelineConfigOverrides(
            diff_manager=cast("DiffManager", diff_manager),
        ),
    )

    cache_dir = tmp_path / "cache"
    observability_path = tmp_path / "observability.json"
    docfacts_path = tmp_path / "docfacts.json"
    docfacts_diff_path = tmp_path / "docfacts.diff.json"

    docfacts_payload = '{"status": "ok"}'
    docfacts_path.write_text(docfacts_payload, encoding="utf-8")
    docfacts_diff_path.write_text("{}", encoding="utf-8")

    dummy_path = tmp_path / "module.py"
    dummy_path.write_text("# placeholder")

    monkeypatch.setattr("tools.docstring_builder.pipeline.CACHE_PATH", cache_dir)
    monkeypatch.setattr(
        "tools.docstring_builder.pipeline.OBSERVABILITY_PATH",
        observability_path,
    )
    monkeypatch.setattr("tools.docstring_builder.pipeline.DOCFACTS_PATH", docfacts_path)
    monkeypatch.setattr("tools.docstring_builder.pipeline.DOCFACTS_DIFF_PATH", docfacts_diff_path)

    runner = PipelineRunner(config)
    result = runner.run([dummy_path])

    assert diff_manager.recorded_docfacts == [docfacts_payload]
    assert result.cli_payload is not None
    assert result.tooling_metadata is not None
    docfacts_report = result.cli_payload.get("docfacts")
    assert isinstance(docfacts_report, dict)
    path = docfacts_report.get("path")
    assert path is not None
    assert path.endswith("docfacts.json")
    diff = docfacts_report.get("diff")
    assert diff is not None
    assert diff.endswith("docfacts.diff.json")


def test_pipeline_runner_includes_baseline_in_file_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = DocstringBuildRequest(
        command="check",
        subcommand="check",
        json_output=True,
    )
    outcome = FileOutcome(
        status=ExitStatus.SUCCESS,
        docfacts=_empty_docfacts(),
        preview="preview",
        changed=True,
        skipped=False,
    )
    diff_manager = _StubDiffManager()
    config = make_pipeline_config(
        request,
        [outcome],
        overrides=PipelineConfigOverrides(
            baseline="main",
            diff_manager=cast("DiffManager", diff_manager),
        ),
    )

    cache_dir = tmp_path / "cache"
    observability_path = tmp_path / "observability.json"
    docfacts_path = tmp_path / "docfacts.json"

    dummy_path = tmp_path / "module.py"
    dummy_path.write_text("# placeholder")

    monkeypatch.setattr("tools.docstring_builder.pipeline.CACHE_PATH", cache_dir)
    monkeypatch.setattr(
        "tools.docstring_builder.pipeline.OBSERVABILITY_PATH",
        observability_path,
    )
    monkeypatch.setattr("tools.docstring_builder.pipeline.DOCFACTS_PATH", docfacts_path)

    runner = PipelineRunner(config)
    result = runner.run([dummy_path])

    assert diff_manager.baseline_calls
    path_recorded, preview_recorded = diff_manager.baseline_calls[0]
    assert path_recorded.endswith("module.py")
    assert preview_recorded == "preview"
    file_report = result.file_reports[0]
    baseline = file_report.get("baseline")
    assert baseline == "main"
    assert result.tooling_metadata is not None
