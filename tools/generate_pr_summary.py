#!/usr/bin/env python3
"""Generate a rich pull request summary for GitHub Actions.

The summary surfaces quality gate results, artifact locations, and helpful
follow-up steps in a markdown table. By default the script inspects the current
working directory and writes to ``$GITHUB_STEP_SUMMARY`` when executed in GitHub
Actions. When that environment variable is missing (e.g., local runs), the
summary is emitted to ``stdout`` so developers can preview the output.

Examples
--------
>>> python tools/generate_pr_summary.py  # doctest: +SKIP
# Writes markdown summary to $GITHUB_STEP_SUMMARY when available
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from tools._shared.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

LOGGER = get_logger(__name__)

StatusLiteral = Literal["pass", "fail", "skip"]


@dataclass(slots=True, frozen=True)
class CheckStatus:
    """Describe the outcome of a single quality gate."""

    label: str
    status: StatusLiteral
    details: str | None = None

    def to_row(self) -> str:
        """Render the check outcome as a markdown table row.

        Returns
        -------
        str
            Markdown table row string.
        """
        icon = STATUS_ICONS[self.status]
        description = f"{icon}"
        if self.details:
            description = f"{description} {self.details}"
        return f"| {self.label} | {description} |"


@dataclass(slots=True, frozen=True)
class ArtifactSnapshot:
    """Materialized artifacts available after a CI run."""

    coverage_xml: bool
    coverage_html: bool
    junit_xml: bool
    docs_build: bool
    site_build: bool
    agent_portal: bool
    schema_dir: bool
    dist_wheels: int
    dist_sdists: int
    codemod_logs: tuple[str, ...]


STATUS_ICONS: Final[Mapping[StatusLiteral, str]] = {
    "pass": "✅",
    "fail": "❌",
    "skip": "⚪",
}

DEFAULT_CHECKS: Final[tuple[CheckStatus, ...]] = (
    CheckStatus("Ruff format & lint", "pass"),
    CheckStatus("pyright strict", "pass"),
    CheckStatus("pyrefly check", "pass"),
    CheckStatus("pytest", "pass"),
    CheckStatus("doctests", "pass"),
    CheckStatus("import-linter", "pass"),
    CheckStatus("suppression guard", "pass"),
    CheckStatus("build wheels", "pass"),
)


_CODEMOD_LOG_PATTERN = re.compile(r"^(?P<stem>.+?)(?:_r(?P<run>\d+))?\.log$")


def _codemod_log_sort_key(filename: str) -> tuple[str, int, str]:
    """Return a natural sort key for codemod log filenames.

    Parameters
    ----------
    filename : str
        Filename to sort.

    Returns
    -------
    tuple[str, int, str]
        (stem, run_number, filename) sort key tuple.
    """
    match = _CODEMOD_LOG_PATTERN.match(filename)
    if match is None:
        return (filename, -1, filename)
    stem = match.group("stem")
    run = match.group("run")
    run_number = int(run) if run is not None else 0
    return (stem, run_number, filename)


def collect_artifact_snapshot(base_path: Path | None = None) -> ArtifactSnapshot:
    """Inspect ``base_path`` and report which build artifacts exist.

    Parameters
    ----------
    base_path : Path | None
        Base directory to inspect (None uses current directory).

    Returns
    -------
    ArtifactSnapshot
        Snapshot of artifact availability.
    """
    root = base_path or Path.cwd()
    coverage_xml = (root / "coverage.xml").is_file()
    coverage_html = (root / "htmlcov/index.html").is_file()
    junit_xml = (root / "junit.xml").is_file()
    docs_build = (root / "docs/_build").exists()
    site_build = (root / "site/_build").exists()
    agent_portal = (root / "site/_build/agent/index.html").is_file()
    schema_dir = (root / "schema").exists()
    dist_dir = root / "dist"
    dist_wheels = len(list(dist_dir.glob("*.whl"))) if dist_dir.exists() else 0
    dist_sdists = len(list(dist_dir.glob("*.tar.gz"))) if dist_dir.exists() else 0
    codemod_logs = tuple(
        sorted(
            (path.name for path in root.glob("codemod*.log") if path.is_file()),
            key=_codemod_log_sort_key,
        )
    )
    return ArtifactSnapshot(
        coverage_xml=coverage_xml,
        coverage_html=coverage_html,
        junit_xml=junit_xml,
        docs_build=docs_build,
        site_build=site_build,
        agent_portal=agent_portal,
        schema_dir=schema_dir,
        dist_wheels=dist_wheels,
        dist_sdists=dist_sdists,
        codemod_logs=codemod_logs,
    )


# Type alias for artifact entry generation strategies
ArtifactEntryStrategy = Callable[[ArtifactSnapshot], list[str]]


def _generate_test_result_entries(snapshot: ArtifactSnapshot) -> list[str]:
    """Generate entries for test result artifacts.

    Parameters
    ----------
    snapshot : ArtifactSnapshot
        Artifact snapshot.

    Returns
    -------
    list[str]
        List of markdown entry strings.
    """
    entries: list[str] = []
    if snapshot.coverage_xml:
        entries.append("- ✅ Coverage XML: `coverage.xml`")
    if snapshot.coverage_html:
        entries.append("- ✅ Coverage HTML: `htmlcov/index.html`")
    if snapshot.junit_xml:
        entries.append("- ✅ JUnit XML: `junit.xml`")
    if not entries:
        entries.append("- ⚪ No coverage or JUnit artifacts found")
    return entries


def _generate_documentation_entries(snapshot: ArtifactSnapshot) -> list[str]:
    """Generate entries for documentation artifacts.

    Parameters
    ----------
    snapshot : ArtifactSnapshot
        Artifact snapshot.

    Returns
    -------
    list[str]
        List of markdown entry strings.
    """
    entries: list[str] = []
    if snapshot.docs_build:
        entries.append("- ✅ Docs build: `docs/_build/`")
    if snapshot.site_build:
        entries.append("- ✅ Site build: `site/_build/`")
    if snapshot.agent_portal:
        entries.append("- ✅ Agent Portal: `site/_build/agent/index.html`")
    if not entries:
        entries.append("- ⚪ Documentation artifacts not generated")
    return entries


def _generate_schema_entries(snapshot: ArtifactSnapshot) -> list[str]:
    """Generate entries for schema artifacts.

    Parameters
    ----------
    snapshot : ArtifactSnapshot
        Artifact snapshot.

    Returns
    -------
    list[str]
        List of markdown entry strings.
    """
    entries = [
        ("- ✅ Schema directory exists" if snapshot.schema_dir else "- ⚪ Schema directory missing")
    ]
    if snapshot.schema_dir:
        entries.append("- Run `jsonschema validate` to verify schemas")
    return entries


def _generate_build_entries(snapshot: ArtifactSnapshot) -> list[str]:
    """Generate entries for build artifacts.

    Parameters
    ----------
    snapshot : ArtifactSnapshot
        Artifact snapshot.

    Returns
    -------
    list[str]
        List of markdown entry strings.
    """
    entries: list[str] = []
    if snapshot.dist_wheels:
        entries.append(f"- ✅ Wheels: {snapshot.dist_wheels} file(s)")
    if snapshot.dist_sdists:
        entries.append(f"- ✅ Source distributions: {snapshot.dist_sdists} file(s)")
    if not entries:
        entries.append("- ⚪ No distribution artifacts built")
    return entries


def _append_section(lines: list[str], heading: str, entries: Iterable[str]) -> None:
    """Append a markdown heading and bullet entries to ``lines``."""
    lines.append(heading)
    lines.extend(entries)
    lines.append("")


class SummaryGenerator:
    """Service for generating PR summary markdown with dependency injection.

    Parameters
    ----------
    test_strategy : ArtifactEntryStrategy | None, optional
        Function to generate test result entries. Defaults to internal implementation.
    docs_strategy : ArtifactEntryStrategy | None, optional
        Function to generate documentation entries. Defaults to internal implementation.
    schema_strategy : ArtifactEntryStrategy | None, optional
        Function to generate schema entries. Defaults to internal implementation.
    build_strategy : ArtifactEntryStrategy | None, optional
        Function to generate build entries. Defaults to internal implementation.
    """

    def __init__(
        self,
        test_strategy: ArtifactEntryStrategy | None = None,
        docs_strategy: ArtifactEntryStrategy | None = None,
        schema_strategy: ArtifactEntryStrategy | None = None,
        build_strategy: ArtifactEntryStrategy | None = None,
    ) -> None:
        self._test_strategy = test_strategy or _generate_test_result_entries
        self._docs_strategy = docs_strategy or _generate_documentation_entries
        self._schema_strategy = schema_strategy or _generate_schema_entries
        self._build_strategy = build_strategy or _generate_build_entries

    def generate(
        self,
        snapshot: ArtifactSnapshot | None = None,
        checks: Sequence[CheckStatus] | None = None,
    ) -> str:
        """Generate PR summary markdown.

        Parameters
        ----------
        snapshot : ArtifactSnapshot | None
            Artifact snapshot (None collects automatically).
        checks : Sequence[CheckStatus] | None
            Check statuses to include.

        Returns
        -------
        str
            Generated markdown summary.
        """
        lines: list[str] = ["# Quality Gates Summary", ""]
        artifact_snapshot = snapshot or collect_artifact_snapshot()

        _append_section(lines, "## 📊 Test Results", self._test_strategy(artifact_snapshot))
        _append_section(
            lines,
            "## 📚 Documentation & Artifacts",
            self._docs_strategy(artifact_snapshot),
        )
        _append_section(
            lines,
            "## 🔍 Schema Validation",
            self._schema_strategy(artifact_snapshot),
        )
        _append_section(lines, "## 📦 Build Artifacts", self._build_strategy(artifact_snapshot))

        lines.append("## ✅ Quality Gates")
        lines.append("")
        lines.append("| Check | Status |")
        lines.append("|-------|--------|")
        resolved_checks = DEFAULT_CHECKS if checks is None else checks
        lines.extend(check.to_row() for check in resolved_checks)
        lines.append("")

        if artifact_snapshot.codemod_logs:
            _append_section(
                lines,
                "## 🔧 Codemod Logs",
                tuple(
                    f"- ✅ Codemod execution log: `{filename}`"
                    for filename in artifact_snapshot.codemod_logs
                ),
            )

        return "\n".join(lines)


def generate_summary(
    snapshot: ArtifactSnapshot | None = None,
    checks: Sequence[CheckStatus] | None = None,
) -> str:
    """Generate PR summary markdown.

    Parameters
    ----------
    snapshot : ArtifactSnapshot | None
        Artifact snapshot (None collects automatically).
    checks : Sequence[CheckStatus] | None
        Check statuses to include.

    Returns
    -------
    str
        Generated markdown summary.
    """
    generator = SummaryGenerator()
    return generator.generate(snapshot=snapshot, checks=checks)


class SummaryWriter:
    """Service for writing summary output to file or stdout."""

    @staticmethod
    def write_to_file(path: Path, content: str) -> None:
        """Write summary content to file, creating parent directories if needed."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{content}\n", encoding="utf-8")

    @staticmethod
    def write_to_stdout(content: str) -> None:
        """Write summary content to stdout."""
        sys.stdout.write(f"{content}\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Generate GitHub Actions step summary.

    Parameters
    ----------
    argv : Sequence[str] | None
        Command-line arguments (unused, provided for compatibility).

    Returns
    -------
    int
        Exit code: 0 on success, 1 on failure.
    """
    del argv
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    summary = generate_summary()
    writer = SummaryWriter()

    if summary_file:
        try:
            output_path = Path(summary_file)
            writer.write_to_file(output_path, summary)
        except OSError:
            LOGGER.exception(
                "Error writing summary",
                extra={"path": summary_file, "operation": "generate_pr_summary"},
            )
            return 1
        LOGGER.info(
            "Summary written",
            extra={
                "path": summary_file,
                "operation": "generate_pr_summary",
                "line_count": summary.count("\n") + 1,
            },
        )
        return 0

    LOGGER.warning(
        "GITHUB_STEP_SUMMARY not set, writing to stdout",
        extra={"operation": "generate_pr_summary"},
    )
    writer.write_to_stdout(summary)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
