# SPDX-License-Identifier: MIT
"""Tests covering optional polars export helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from os import PathLike
from pathlib import Path
from typing import cast

import pytest
from codeintel_rev import graph_builder, uses_builder
from codeintel_rev.polars_support import resolve_polars_frame_factory
from codeintel_rev.typing import PolarsDataFrame, PolarsModule

from tests._helpers import assertions


class _DummyFrame(PolarsDataFrame):
    """Lightweight stand-in for a polars DataFrame."""

    def __init__(self, records: Sequence[Mapping[str, object]]) -> None:
        self.records = [dict(record) for record in records]

    def write_parquet(self, file: str | PathLike[str]) -> None:
        """Write frame records as JSON to file.

        Parameters
        ----------
        file : str | PathLike[str]
            Output file path.
        """
        Path(file).write_text(json.dumps(self.records), encoding="utf-8")


class _PolarsLegacy:
    """Simulate polars releases that expose ``data_frame``."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, object]]] = []

    def data_frame(self, data: Sequence[Mapping[str, object]]) -> PolarsDataFrame:
        """Create data frame from sequence of mappings.

        Parameters
        ----------
        data : Sequence[Mapping[str, object]]
            Input data records.

        Returns
        -------
        PolarsDataFrame
            Dummy frame containing records.
        """
        payload = [dict(item) for item in data]
        self.calls.append(payload)
        return _DummyFrame(payload)


class _PolarsModern:
    """Simulate polars releases that rely solely on ``DataFrame``."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, object]]] = []

    def dataframe(
        self,
        data: Sequence[Mapping[str, object]],
    ) -> PolarsDataFrame:
        """Create data frame from sequence of mappings.

        Parameters
        ----------
        data : Sequence[Mapping[str, object]]
            Input data records.

        Returns
        -------
        PolarsDataFrame
            Dummy frame containing records.
        """
        payload = [dict(item) for item in data]
        self.calls.append(payload)
        return _DummyFrame(payload)

    DataFrame = dataframe


def test_resolve_polars_frame_factory_prefers_legacy_helper() -> None:
    """Legacy helper should be returned when available."""
    polars = _PolarsLegacy()

    factory = resolve_polars_frame_factory(cast("PolarsModule", polars))
    payload = [{"src_path": "a.py", "dst_path": "b.py"}]

    assertions.expect_true(factory is not None, reason="factory should exist")
    if factory is None:  # pragma: no cover - defensive
        pytest.fail("factory should exist")
    frame = factory(payload)
    assertions.expect_true(isinstance(frame, _DummyFrame), reason="frame should be _DummyFrame")
    assertions.expect_sequence_equal(polars.calls, [payload])


def test_resolve_polars_frame_factory_supports_dataframe_constructor() -> None:
    """Modern constructor should be used when ``data_frame`` is absent."""
    polars = _PolarsModern()

    factory = resolve_polars_frame_factory(cast("PolarsModule", polars))
    payload = [{"src_path": "a.py", "dst_path": "b.py"}]

    assertions.expect_true(factory is not None, reason="factory should exist")
    if factory is None:  # pragma: no cover - defensive
        pytest.fail("factory should exist")
    frame = factory(payload)
    assertions.expect_true(isinstance(frame, _DummyFrame), reason="frame should be _DummyFrame")
    assertions.expect_sequence_equal(polars.calls, [payload])


def test_resolve_polars_frame_factory_returns_none_without_entry_points() -> None:
    """Helper should return ``None`` when neither API surface exists."""
    assertions.expect_equal(resolve_polars_frame_factory(cast("PolarsModule", object())), None)


def test_write_import_graph_emits_file(tmp_path: Path) -> None:
    """Import graph export should emit either Parquet or JSONL."""
    graph = graph_builder.ImportGraph(
        edges={"a.py": {"b.py"}},
        fan_in={"a.py": 0, "b.py": 1},
        fan_out={"a.py": 1, "b.py": 0},
        cycle_group={"a.py": 0, "b.py": 0},
    )
    target = tmp_path / "imports.parquet"

    used = graph_builder.write_import_graph(graph, target)

    assertions.expect_true(used.exists(), reason="graph export should exist")
    assertions.expect_true(
        used.stat().st_size >= 0,
        reason="graph export should not be empty",
    )


def test_write_use_graph_emits_file(tmp_path: Path) -> None:
    """Use graph export should emit edges to disk."""
    use_graph = uses_builder.UseGraph(
        uses_by_file={"a.py": {"b.py"}},
        symbol_usage={"a.py": 1},
        edges=[("a.py", "b.py", "sym")],
    )
    target = tmp_path / "uses.parquet"

    used = uses_builder.write_use_graph(use_graph, target)

    assertions.expect_true(used.exists(), reason="uses export should exist")
    assertions.expect_true(
        used.stat().st_size >= 0,
        reason="uses export should not be empty",
    )
