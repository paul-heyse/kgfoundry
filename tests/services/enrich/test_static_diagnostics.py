# SPDX-License-Identifier: MIT
"""Tests for static diagnostics exports."""

from __future__ import annotations

from codeintel_rev.services.enrich.static_diagnostics import build_static_diagnostics_rows
from codeintel_rev.typedness import FileTypeSignals

from tests._helpers import assertions


def test_build_static_diagnostics_rows() -> None:
    """Ensure static diagnostic rows reflect aggregated error counts."""
    signals = {
        "a.py": FileTypeSignals(pyrefly_errors=1, pyright_errors=2),
        "b.py": FileTypeSignals(pyrefly_errors=0, pyright_errors=0),
    }

    rows = build_static_diagnostics_rows(signals)
    assertions.expect_equal(len(rows), 2)

    first = next(row for row in rows if row["rel_path"] == "a.py")
    second = next(row for row in rows if row["rel_path"] == "b.py")

    assertions.expect_equal(first["total_errors"], 3)
    assertions.expect_true(first["has_errors"])
    assertions.expect_equal(second["total_errors"], 0)
    assertions.expect_false(second["has_errors"])
