"""Tests for typing gate compliance metrics collection and emission.

Tests verify:
- Metrics recording and accumulation
- Snapshot generation with compliance summary
- Structured log emission
- JSON snapshot file writing

Task: Phase 2, Task 2.5 - Surface compliance metrics
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

from tools.lint.typing_gate_metrics import TypingGateMetrics, ViolationRecord

from tests._helpers import assertions
from tests.helpers import assert_frozen_attribute


class TestViolationRecord:
    """Test ViolationRecord data class."""

    def test_violation_record_creation(self) -> None:
        """Verify ViolationRecord can be created with all fields."""
        record = ViolationRecord(
            filepath="src/module.py",
            violation_type="heavy_import",
            module_name="numpy",
            lineno=42,
        )
        assertions.expect_equal(record.filepath, "src/module.py")
        assertions.expect_equal(record.violation_type, "heavy_import")
        assertions.expect_equal(record.module_name, "numpy")
        assertions.expect_equal(record.lineno, 42)

    def test_violation_record_is_frozen(self) -> None:
        """Verify ViolationRecord is immutable."""
        record = ViolationRecord(
            filepath="src/module.py",
            violation_type="heavy_import",
            module_name="numpy",
            lineno=42,
        )
        assert_frozen_attribute(record, "lineno", value=100)


class TestTypingGateMetrics:
    """Test TypingGateMetrics collection and emission."""

    def test_metrics_initialization(self) -> None:
        """Verify metrics initialize with zeros."""
        metrics = TypingGateMetrics()
        assertions.expect_equal(metrics.checks_total, 0)
        assertions.expect_equal(metrics.violations_total, 0)
        assertions.expect_equal(len(metrics.violations), 0)

    def test_record_check_without_violations(self) -> None:
        """Verify recording a clean check increments checks_total only."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check("clean_file.py", None)
        assertions.expect_equal(metrics.checks_total, 1)
        assertions.expect_equal(metrics.violations_total, 0)

    def test_record_check_with_violations(self) -> None:
        """Verify recording violations increments both counters."""
        metrics = TypingGateMetrics()
        violations: list[dict[str, object]] = [
            {"violation_type": "heavy_import", "module_name": "numpy", "lineno": 10},
            {
                "violation_type": "private_module",
                "module_name": "docs._types",
                "lineno": 20,
            },
        ]
        metrics = metrics.record_check("bad_file.py", violations)
        assertions.expect_equal(metrics.checks_total, 1)
        assertions.expect_equal(metrics.violations_total, 2)
        assertions.expect_equal(len(metrics.violations), 2)

    def test_multiple_checks_accumulation(self) -> None:
        """Verify metrics accumulate across multiple checks."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check("file1.py", None)
        metrics = metrics.record_check(
            "file2.py",
            [{"violation_type": "heavy_import", "module_name": "numpy", "lineno": 5}],
        )
        metrics = metrics.record_check("file3.py", None)
        assertions.expect_equal(metrics.checks_total, 3)
        assertions.expect_equal(metrics.violations_total, 1)

    def test_snapshot_generation(self) -> None:
        """Verify snapshot contains all required fields."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check(
            "file.py",
            [{"violation_type": "heavy_import", "module_name": "numpy", "lineno": 10}],
        )

        snapshot = metrics.to_snapshot()
        assertions.expect_in("checks_total", snapshot)
        assertions.expect_in("violations_total", snapshot)
        assertions.expect_in("violations", snapshot)
        assertions.expect_in("timestamp", snapshot)
        assertions.expect_in("summary", snapshot)

    def test_snapshot_summary_compliance_rate(self) -> None:
        """Verify snapshot includes compliance rate."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check("file1.py", None)  # Clean
        metrics = metrics.record_check(
            "file2.py",
            [{"violation_type": "heavy_import", "module_name": "numpy", "lineno": 5}],
        )

        snapshot = metrics.to_snapshot()
        summary = cast("dict[str, object]", snapshot["summary"])
        # 1 clean out of 2 checks = 50% compliance
        assertions.expect_equal(cast("float", summary["compliance_rate"]), 50.0)

    def test_snapshot_summary_files_with_violations(self) -> None:
        """Verify snapshot counts unique files with violations."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check(
            "file1.py",
            [
                {"violation_type": "heavy_import", "module_name": "numpy", "lineno": 5},
                {
                    "violation_type": "private_module",
                    "module_name": "docs._types",
                    "lineno": 10,
                },
            ],
        )
        metrics = metrics.record_check(
            "file2.py",
            [
                {
                    "violation_type": "heavy_import",
                    "module_name": "fastapi",
                    "lineno": 15,
                }
            ],
        )

        snapshot = metrics.to_snapshot()
        summary = cast("dict[str, object]", snapshot["summary"])
        assertions.expect_equal(cast("int", summary["files_with_violations"]), 2)

    def test_snapshot_summary_violation_types(self) -> None:
        """Verify snapshot lists all violation types found."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check(
            "file.py",
            [
                {"violation_type": "heavy_import", "module_name": "numpy", "lineno": 5},
                {
                    "violation_type": "private_module",
                    "module_name": "docs._types",
                    "lineno": 10,
                },
                {
                    "violation_type": "deprecated_shim",
                    "module_name": "resolve_numpy",
                    "lineno": 15,
                },
            ],
        )

        snapshot = metrics.to_snapshot()
        summary = cast("dict[str, object]", snapshot["summary"])
        violation_types = set(cast("list[str]", summary["violation_types"]))
        assertions.expect_in("heavy_import", violation_types)
        assertions.expect_in("private_module", violation_types)
        assertions.expect_in("deprecated_shim", violation_types)

    def test_structured_logs_format(self) -> None:
        """Verify structured logs are valid JSON."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check(
            "file.py",
            [{"violation_type": "heavy_import", "module_name": "numpy", "lineno": 5}],
        )

        logs = metrics.emit_structured_logs()
        assertions.expect_equal(len(logs), 2)  # 1 summary + 1 violation

        # Parse each log to verify JSON
        for log in logs:
            data = cast("dict[str, object]", json.loads(log))
            assertions.expect_in("event", data)
            assertions.expect_in("timestamp", data)

    def test_structured_logs_summary_event(self) -> None:
        """Verify first log contains summary event."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check("file.py", None)

        logs = metrics.emit_structured_logs()
        summary_log = cast("dict[str, object]", json.loads(logs[0]))
        assertions.expect_equal(cast("str", summary_log["event"]), "typing_gate_check_complete")
        assertions.expect_equal(cast("int", summary_log["checks_total"]), 1)
        assertions.expect_equal(cast("int", summary_log["violations_total"]), 0)

    def test_structured_logs_violation_events(self) -> None:
        """Verify violation logs contain correct data."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check(
            "file.py",
            [{"violation_type": "heavy_import", "module_name": "numpy", "lineno": 5}],
        )

        logs = metrics.emit_structured_logs()
        violation_log = cast("dict[str, object]", json.loads(logs[1]))
        assertions.expect_equal(cast("str", violation_log["event"]), "typing_gate_violation")
        assertions.expect_equal(cast("str", violation_log["filepath"]), "file.py")
        assertions.expect_equal(cast("str", violation_log["violation_type"]), "heavy_import")
        assertions.expect_equal(cast("str", violation_log["module_name"]), "numpy")
        assertions.expect_equal(cast("int", violation_log["lineno"]), 5)

    def test_write_snapshot_creates_file(self, tmp_path: Path) -> None:
        """Verify write_snapshot creates the JSON file."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check("file.py", None)

        output_path = tmp_path / "metrics.json"
        metrics.write_snapshot(output_path)

        assertions.expect_true(output_path.exists(), reason="output path should exist")
        content = cast("dict[str, object]", json.loads(output_path.read_text(encoding="utf-8")))
        assertions.expect_equal(cast("int", content["checks_total"]), 1)
        assertions.expect_equal(cast("int", content["violations_total"]), 0)

    def test_write_snapshot_creates_parent_directories(self, tmp_path: Path) -> None:
        """Verify write_snapshot creates parent directories if needed."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check("file.py", None)

        output_path = tmp_path / "deep" / "nested" / "path" / "metrics.json"
        metrics.write_snapshot(output_path)

        assertions.expect_true(output_path.exists(), reason="output path should exist")
        assertions.expect_true(output_path.parent.exists(), reason="parent directory should exist")

    def test_compliance_rate_100_percent(self) -> None:
        """Verify compliance rate is 100% when no violations."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check("file1.py", None)
        metrics = metrics.record_check("file2.py", None)
        snapshot = metrics.to_snapshot()
        summary = cast("dict[str, object]", snapshot["summary"])
        assertions.expect_equal(cast("float", summary["compliance_rate"]), 100.0)

    def test_compliance_rate_zero_percent(self) -> None:
        """Verify compliance rate is 0% when all checks have violations."""
        metrics = TypingGateMetrics()
        metrics = metrics.record_check(
            "file1.py",
            [{"violation_type": "heavy_import", "module_name": "numpy", "lineno": 5}],
        )
        metrics = metrics.record_check(
            "file2.py",
            [
                {
                    "violation_type": "private_module",
                    "module_name": "docs._types",
                    "lineno": 10,
                }
            ],
        )
        snapshot = metrics.to_snapshot()
        summary = cast("dict[str, object]", snapshot["summary"])
        assertions.expect_equal(cast("float", summary["compliance_rate"]), 0.0)
