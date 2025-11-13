# SPDX-License-Identifier: MIT
"""Helpers for optional polars exports."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import cast

from codeintel_rev.typing import PolarsDataFrame, PolarsModule

type PolarsFrameFactory = Callable[[Sequence[Mapping[str, object]]], PolarsDataFrame]
"""Callable signature for constructing polars DataFrames."""


def resolve_polars_frame_factory(polars: PolarsModule) -> PolarsFrameFactory | None:
    """Return a DataFrame factory that works across polars versions.

    This function attempts to resolve a DataFrame factory function that works
    across different polars versions. It first checks for the legacy ``data_frame``
    helper (available in older polars releases), then falls back to the canonical
    ``DataFrame`` constructor (available in newer versions). Returns None if neither
    is available, allowing callers to select alternative serialization strategies.

    Parameters
    ----------
    polars : PolarsModule
        Polars module object (typically from lazy import or gate_import). Used to
        access polars API methods (data_frame, DataFrame). The module must expose
        at least one of these methods for the function to return a factory.

    Returns
    -------
    PolarsFrameFactory | None
        Callable DataFrame constructor when available (either legacy data_frame
        helper or canonical DataFrame constructor), otherwise None. When None, callers
        should use alternative serialization strategies (e.g., manual DataFrame
        construction or different serialization formats).
    """
    legacy_helper = getattr(polars, "data_frame", None)
    if callable(legacy_helper):
        return cast("PolarsFrameFactory", legacy_helper)

    constructor = getattr(polars, "DataFrame", None)
    if callable(constructor):
        return cast("PolarsFrameFactory", constructor)

    return None
