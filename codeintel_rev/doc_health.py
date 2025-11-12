# SPDX-License-Identifier: MIT
"""Docstring summarization helpers."""

from __future__ import annotations

from typing import Any

from codeintel_rev.enrich.libcst_bridge import ModuleIndex


def summarize_doc_health(index: ModuleIndex) -> dict[str, Any]:
    """Return a normalized doc health summary for a module.

    Parameters
    ----------
    index : ModuleIndex
        Module index containing docstring health metrics.

    Returns
    -------
    dict[str, Any]
        Dictionary containing ``doc_summary``, ``doc_metrics``, and ``doc_items``.
    """
    return {
        "doc_summary": index.doc_summary,
        "doc_metrics": index.doc_metrics,
        "doc_items": index.doc_items,
    }
