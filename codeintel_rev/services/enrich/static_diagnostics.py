"""Static diagnostics export helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from codeintel_rev.typedness import FileTypeSignals

try:  # pragma: no cover - optional dependency
    import pyarrow as pa
except ImportError:  # pragma: no cover - optional dependency
    pa = None

STATIC_DIAGNOSTICS_SCHEMA = (
    pa.schema(
        [
            pa.field("rel_path", pa.string()),
            pa.field("pyrefly_errors", pa.int32()),
            pa.field("pyright_errors", pa.int32()),
            pa.field("total_errors", pa.int32()),
            pa.field("has_errors", pa.bool_()),
        ]
    )
    if pa is not None
    else None
)


def build_static_diagnostics_rows(
    type_signals: Mapping[str, FileTypeSignals],
) -> list[dict[str, Any]]:
    """Flatten FileTypeSignals into static_diagnostics rows.

    Parameters
    ----------
    type_signals : Mapping[str, FileTypeSignals]
        Mapping from relative paths to type checking signal objects.

    Returns
    -------
    list[dict[str, Any]]
        List of diagnostic row dictionaries with rel_path, error counts, and totals.
    """
    rows: list[dict[str, Any]] = []
    for rel_path in sorted(type_signals):
        signal = type_signals[rel_path]
        pyrefly_errors = int(getattr(signal, "pyrefly_errors", 0) or 0)
        pyright_errors = int(getattr(signal, "pyright_errors", 0) or 0)
        total_errors = pyrefly_errors + pyright_errors
        rows.append(
            {
                "rel_path": rel_path,
                "pyrefly_errors": pyrefly_errors,
                "pyright_errors": pyright_errors,
                "total_errors": total_errors,
                "has_errors": total_errors > 0,
            }
        )
    return rows


__all__ = ["STATIC_DIAGNOSTICS_SCHEMA", "build_static_diagnostics_rows"]
