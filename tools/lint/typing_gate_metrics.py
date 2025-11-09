"""Typing gate compliance metrics collection and emission.

This module provides utilities for collecting and emitting typing gate
compliance metrics to Prometheus and structured logs. It enables observability
into the typing gates enforcement system across the codebase.

Metrics:
- kgfoundry_typing_gate_checks_total: Total number of typing gate checks performed
- kgfoundry_typing_gate_violations_total: Total number of violations detected

Usage:
    from tools.lint.typing_gate_metrics import TypingGateMetrics

    metrics = TypingGateMetrics()
    metrics = metrics.record_check(filepath, num_violations)
    snapshot = metrics.to_snapshot()
    metrics.write_snapshot(path)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@dataclass(frozen=True)
class ViolationRecord:
    """A record of a typing gate violation detected."""

    filepath: str
    """File path where violation was detected."""

    violation_type: str
    """Type of violation: heavy_import, private_module, deprecated_shim."""

    module_name: str
    """Name of the module involved in the violation."""

    lineno: int
    """Line number of the violation."""


@dataclass(frozen=True)
class TypingGateMetrics:
    """Collect and emit typing gate compliance metrics."""

    checks_total: int = 0
    """Total number of typing gate checks performed."""

    violations_total: int = 0
    """Total number of violations detected."""

    violations: list[ViolationRecord] = field(default_factory=list)
    """List of violations detected."""

    timestamp: str = field(default_factory=datetime.now(UTC).isoformat)
    """Timestamp when metrics were collected."""

    def record_check(
        self, filepath: str, violations: Sequence[dict[str, object]] | None = None
    ) -> TypingGateMetrics:
        """Record a typing gate check.

        Parameters
        ----------
        filepath : str
            Path to the file checked.
        violations : Sequence[dict[str, object]] | None, optional
            List of violations found in the file (default: None).

        Returns
        -------
        TypingGateMetrics
            New metrics snapshot with the recorded check.
        """
        new_violations = list(self.violations)
        violation_increment = 0
        if violations:
            violation_increment = len(violations)
            new_violations.extend(
                ViolationRecord(
                    filepath=filepath,
                    violation_type=cast("str", v.get("violation_type", "unknown")),
                    module_name=cast("str", v.get("module_name", "unknown")),
                    lineno=cast("int", v.get("lineno", 0)),
                )
                for v in violations
            )
        return replace(
            self,
            checks_total=self.checks_total + 1,
            violations_total=self.violations_total + violation_increment,
            violations=new_violations,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Convert metrics to a snapshot dictionary.

        Returns
        -------
        dict[str, object]
            Snapshot containing checks_total, violations_total, violations, and timestamp.
        """
        violation_dicts: list[dict[str, object]] = [
            cast("dict[str, object]", asdict(v)) for v in self.violations
        ]
        summary: dict[str, object] = {
            "compliance_rate": (
                100.0
                if self.checks_total == 0
                else (100.0 * (self.checks_total - len(self.violations)) / self.checks_total)
            ),
            "files_with_violations": len({v.filepath for v in self.violations}),
            "violation_types": list({v.violation_type for v in self.violations}),
        }
        return {
            "checks_total": self.checks_total,
            "violations_total": self.violations_total,
            "violations": violation_dicts,
            "timestamp": self.timestamp,
            "summary": summary,
        }

    def write_snapshot(self, output_path: Path) -> None:
        """Write metrics snapshot to JSON file.

        Parameters
        ----------
        output_path : Path
            Path where the snapshot JSON will be written.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = self.to_snapshot()
        output_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    def emit_prometheus_counters(self) -> str:
        """Emit metrics in Prometheus text format.

        Returns
        -------
        str
            Prometheus-formatted metrics.
        """
        lines: list[str] = [
            "# HELP kgfoundry_typing_gate_checks_total Total number of typing gate checks performed",
            "# TYPE kgfoundry_typing_gate_checks_total counter",
            f"kgfoundry_typing_gate_checks_total {self.checks_total}",
            "# HELP kgfoundry_typing_gate_violations_total Total number of violations detected",
            "# TYPE kgfoundry_typing_gate_violations_total counter",
            f"kgfoundry_typing_gate_violations_total {self.violations_total}",
        ]
        return "\n".join(lines)

    def emit_structured_logs(self) -> list[str]:
        """Emit metrics as structured log lines.

        Returns
        -------
        list[str]
            List of structured log lines (JSON format).
        """
        summary_dict: dict[str, object] = {
            "event": "typing_gate_check_complete",
            "checks_total": self.checks_total,
            "violations_total": self.violations_total,
            "timestamp": self.timestamp,
        }
        logs: list[str] = [json.dumps(summary_dict)]

        # Emit per-violation logs
        violation_logs: list[str] = [
            json.dumps(
                cast(
                    "dict[str, object]",
                    {
                        "event": "typing_gate_violation",
                        "filepath": v.filepath,
                        "violation_type": v.violation_type,
                        "module_name": v.module_name,
                        "lineno": v.lineno,
                        "timestamp": self.timestamp,
                    },
                )
            )
            for v in self.violations
        ]
        logs.extend(violation_logs)
        return logs
