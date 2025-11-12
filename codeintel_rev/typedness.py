# SPDX-License-Identifier: MIT
"""Typedness utilities that build on Pyrefly/Pyright summaries."""

from __future__ import annotations

from dataclasses import dataclass

from codeintel_rev.enrich.libcst_bridge import ModuleIndex
from codeintel_rev.enrich.type_integration import TypeSummary, collect_pyrefly, collect_pyright


@dataclass(slots=True, frozen=True)
class FileTypeSignals:
    """Joined Pyrefly/Pyright error counts for a single file."""

    pyrefly_errors: int = 0
    pyright_errors: int = 0

    @property
    def total(self) -> int:
        """Return the max error count across all sources."""
        return max(self.pyrefly_errors, self.pyright_errors)


def collect_type_signals(
    pyrefly_report: str | None = None,
    pyright_json: str | None = None,
) -> dict[str, FileTypeSignals]:
    """Collect Pyrefly/Pyright diagnostics keyed by file path.

    Parameters
    ----------
    pyrefly_report : str | None, optional
        Path to a Pyrefly JSON/JSONL report. When None, Pyrefly is not queried.
    pyright_json : str | None, optional
        Directory or file path passed through to ``collect_pyright``. When None,
        Pyright is not queried.

    Returns
    -------
    dict[str, FileTypeSignals]
        Mapping of normalized file paths to joined error counts.
    """
    signals: dict[str, FileTypeSignals] = {}
    summaries: list[tuple[TypeSummary | None, str]] = [
        (collect_pyrefly(pyrefly_report), "pyrefly"),
        (collect_pyright(pyright_json), "pyright"),
    ]
    for summary, name in summaries:
        if summary is None:
            continue
        for path, record in summary.by_file.items():
            existing = signals.setdefault(path, FileTypeSignals())
            if name == "pyrefly":
                signals[path] = FileTypeSignals(
                    pyrefly_errors=record.error_count,
                    pyright_errors=existing.pyright_errors,
                )
            else:
                signals[path] = FileTypeSignals(
                    pyrefly_errors=existing.pyrefly_errors,
                    pyright_errors=record.error_count,
                )
    return signals


def annotation_ratio(module_index: ModuleIndex) -> dict[str, float]:
    """Return per-module annotation ratios derived from :class:`ModuleIndex`.

    Parameters
    ----------
    module_index : ModuleIndex
        Parsed module metadata produced by ``index_module``.

    Returns
    -------
    dict[str, float]
        Mapping with ``"params"`` and ``"returns"`` ratios clamped to ``[0.0, 1.0]``.
    """
    ratio = module_index.annotation_ratio or {"params": 1.0, "returns": 1.0}
    return {
        "params": max(0.0, min(1.0, float(ratio.get("params", 1.0)))),
        "returns": max(0.0, min(1.0, float(ratio.get("returns", 1.0)))),
    }
