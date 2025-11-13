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

    The helper prefers the legacy ``data_frame`` helper that older releases
    expose and falls back to the canonical ``DataFrame`` constructor added in
    newer polars versions.

    Returns
    -------
    PolarsFrameFactory | None
        Callable constructor when available, otherwise ``None`` so callers can
        select a different serialization strategy.
    """
    legacy_helper = getattr(polars, "data_frame", None)
    if callable(legacy_helper):
        return cast("PolarsFrameFactory", legacy_helper)

    constructor = getattr(polars, "DataFrame", None)
    if callable(constructor):
        return cast("PolarsFrameFactory", constructor)

    return None
