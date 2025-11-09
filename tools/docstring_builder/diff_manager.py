"""Diff management helpers for the docstring builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tools.docstring_builder.io import read_baseline_version
from tools.docstring_builder.paths import (
    DOCFACTS_DIFF_PATH,
    DOCFACTS_PATH,
    DOCSTRINGS_DIFF_PATH,
    NAVMAP_DIFF_PATH,
    REPO_ROOT,
    SCHEMA_DIFF_PATH,
)
from tools.drift_preview import (
    DocstringDriftEntry,
    write_docstring_drift,
    write_html_diff,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tools.docstring_builder.pipeline_types import ProcessingOptions


@dataclass(slots=True, frozen=True)
class DiffManager:
    """Track and emit diff artifacts produced by the pipeline."""

    options: ProcessingOptions
    docstring_diffs: list[DocstringDriftEntry] = field(default_factory=list)

    def record_docstring_baseline(
        self,
        file_path: Path,
        preview: str | None,
    ) -> None:
        """Record docstring drift when baseline differs from current content."""
        if not self.options.baseline:
            return
        baseline_text = read_baseline_version(self.options.baseline, file_path)
        if baseline_text is None:
            return
        if preview is not None:
            current_text = preview
        else:
            try:
                current_text = file_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                current_text = ""
        if baseline_text == current_text:
            return
        self.docstring_diffs.append(
            DocstringDriftEntry(
                path=str(file_path.relative_to(REPO_ROOT)),
                before=baseline_text,
                after=current_text,
            )
        )

    def finalize_docstring_drift(self) -> None:
        """Write the docstring drift summary to disk."""
        write_docstring_drift(self.docstring_diffs, DOCSTRINGS_DIFF_PATH)

    def record_docfacts_baseline_diff(
        self,
        docfacts_text: str | None,
    ) -> None:
        """Write a baseline diff for DocFacts when necessary."""
        if (
            not self.options.baseline
            or not docfacts_text
            or DOCFACTS_DIFF_PATH.exists()
        ):
            return
        baseline_docfacts = read_baseline_version(self.options.baseline, DOCFACTS_PATH)
        if baseline_docfacts is None or baseline_docfacts == docfacts_text:
            return
        write_html_diff(
            baseline_docfacts,
            docfacts_text,
            DOCFACTS_DIFF_PATH,
            "DocFacts baseline drift",
        )

    @staticmethod
    def finalize_schema_diff(previous_schema: str, current_schema: str) -> None:
        """Write a schema drift preview if the contents changed."""
        if previous_schema and previous_schema != current_schema:
            write_html_diff(
                previous_schema,
                current_schema,
                SCHEMA_DIFF_PATH,
                "Schema drift",
            )
        else:
            SCHEMA_DIFF_PATH.unlink(missing_ok=True)

    @staticmethod
    def collect_diff_links() -> dict[str, str]:
        """Return a mapping of available diff artifact labels to relative paths.

        Returns
        -------
        dict[str, str]
            Dictionary mapping diff artifact labels (e.g., "docfacts", "docstrings")
            to relative file paths. Only includes entries for artifacts that exist.
        """
        links: dict[str, str] = {}
        for label, path in (
            ("docfacts", DOCFACTS_DIFF_PATH),
            ("docstrings", DOCSTRINGS_DIFF_PATH),
            ("navmap", NAVMAP_DIFF_PATH),
            ("schema", SCHEMA_DIFF_PATH),
        ):
            if path.exists():
                links[label] = str(path.relative_to(REPO_ROOT))
        return links
