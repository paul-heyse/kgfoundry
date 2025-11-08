"""Helpers for generating HTML drift previews."""

from __future__ import annotations

import difflib
import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_DIFF = difflib.HtmlDiff(wrapcolumn=80)


def write_html_diff(before: str, after: str, output: Path, title: str) -> None:
    """Render an HTML diff between ``before`` and ``after`` to ``output``."""
    output.parent.mkdir(parents=True, exist_ok=True)
    html_output = _DIFF.make_file(
        before.splitlines(),
        after.splitlines(),
        fromdesc=f"{title} (previous)",
        todesc=f"{title} (current)",
        context=True,
        numlines=20,
    )
    output.write_text(html_output, encoding="utf-8")


@dataclass(slots=True, frozen=True)
class DocstringDriftEntry:
    """Represents drift between two versions of a source file."""

    path: str
    before: str
    after: str


def write_docstring_drift(entries: list[DocstringDriftEntry], output: Path) -> None:
    """Render an aggregated docstring drift preview."""
    if not entries:
        output.unlink(missing_ok=True)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    sections: list[str] = []
    for entry in entries:
        table = _DIFF.make_table(
            entry.before.splitlines(),
            entry.after.splitlines(),
            fromdesc=f"{entry.path} (baseline)",
            todesc=f"{entry.path} (current)",
            context=True,
            numlines=20,
        )
        heading = f"<h2>{html.escape(entry.path)}</h2>"
        sections.append(f"{heading}\n{table}")
    body = "\n".join(sections)
    html_output = (
        "<html><head><meta charset='utf-8'><title>Docstring drift</title></head><body>"
        f"<h1>Docstring drift preview</h1>\n{body}\n"
        "</body></html>"
    )
    output.write_text(html_output, encoding="utf-8")


__all__ = ["DocstringDriftEntry", "write_docstring_drift", "write_html_diff"]
