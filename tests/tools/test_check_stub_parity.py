"""Tests for the stub parity checker CLI."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

import pytest

from kgfoundry_common.errors import ConfigurationError
from tests._helpers import assertions

if TYPE_CHECKING:
    from pathlib import Path

    from tools.check_stub_parity import (
        StubParityContext,
        StubParityIssueRecord,
        StubParityReport,
    )

_stub_parity_module = cast("Any", importlib.import_module("tools.check_stub_parity"))

StubParityIssueRecord = _stub_parity_module.StubParityIssueRecord
StubParityReport = _stub_parity_module.StubParityReport
build_stub_parity_context = _stub_parity_module.build_stub_parity_context
evaluate_stub = _stub_parity_module.evaluate_stub
run_stub_parity_checks = _stub_parity_module.run_stub_parity_checks


def _register_runtime_module(name: str, exports: tuple[str, ...]) -> None:
    module = ModuleType(name)
    module_dict = cast("dict[str, object]", module.__dict__)
    module_dict["__all__"] = list(exports)

    def _placeholder(*_args: object, **_kwargs: object) -> None:
        return None

    for export in exports:
        setattr(module, export, _placeholder)

    sys.modules[name] = module


def test_evaluate_stub_reports_any_usage(tmp_path: Path) -> None:
    """`evaluate_stub` should capture Any usages for downstream reporting."""
    module_name = "stub_parity_any_usage"
    _register_runtime_module(module_name, ("api",))

    stub_path = tmp_path / f"{module_name}.pyi"
    stub_path.write_text(
        "from typing import Any\n\ndef api(value: Any) -> None: ...\n",
        encoding="utf-8",
    )

    outcome = evaluate_stub(module_name, stub_path)

    assertions.expect_true(bool(outcome.any_usages), reason="should have any_usages")
    assertions.expect_equal(outcome.any_usages[0][0], 3)  # First element is line_number
    assertions.expect_true(outcome.has_errors, reason="should have errors")


def test_run_stub_parity_checks_success(tmp_path: Path) -> None:
    """A fully matching stub should complete without raising."""
    module_name = "stub_parity_success"
    _register_runtime_module(module_name, ("foo",))

    stub_path = tmp_path / f"{module_name}.pyi"
    stub_path.write_text("def foo() -> None: ...\n", encoding="utf-8")

    report = run_stub_parity_checks([(module_name, stub_path)])

    assertions.expect_equal(report.issue_count, 0)
    assertions.expect_false(report.has_issues, reason="should not have issues")


def test_report_from_context_validates_counts(tmp_path: Path) -> None:
    """from_context should reject mismatched issue/error counts."""
    module_name = "stub_parity_mismatch"
    _register_runtime_module(module_name, ("foo",))
    stub_path = tmp_path / f"{module_name}.pyi"
    stub_path.write_text("def bar() -> None: ...\n", encoding="utf-8")

    with pytest.raises(ConfigurationError) as excinfo:
        run_stub_parity_checks([(module_name, stub_path)])

    context = cast("StubParityContext | None", excinfo.value.context)
    assertions.expect_true(context is not None, reason="context should not be None")
    if context is None:  # pragma: no cover - defensive
        pytest.fail("context should not be None")
    report = StubParityReport.from_context(context)
    mutated_context: StubParityContext = build_stub_parity_context(report)
    mutated_context["issue_count"] = 0

    message_pattern = r"expected counts \(0, \d+\), got"

    with pytest.raises(ValueError, match=message_pattern):
        StubParityReport.from_context(mutated_context)


def test_run_stub_parity_checks_raises_with_context(tmp_path: Path) -> None:
    """Missing runtime exports should surface through `ConfigurationError` context."""
    module_name = "stub_parity_missing"
    _register_runtime_module(module_name, ("foo",))

    stub_path = tmp_path / f"{module_name}.pyi"
    stub_path.write_text("def bar() -> None: ...\n", encoding="utf-8")

    with pytest.raises(ConfigurationError) as excinfo:
        run_stub_parity_checks([(module_name, stub_path)])

    context = excinfo.value.context
    expected_report = StubParityReport(
        issues=(
            StubParityIssueRecord(
                module=module_name,
                stub_path=stub_path.resolve(),
                missing_symbols=("foo",),
                extra_symbols=("bar",),
                any_usages=(),
            ),
        ),
    )

    assertions.expect_equal(context, build_stub_parity_context(expected_report))
