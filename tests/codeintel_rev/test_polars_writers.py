# SPDX-License-Identifier: MIT
"""Tests covering optional polars export helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest
from codeintel_rev import graph_builder, uses_builder
from codeintel_rev.polars_support import resolve_polars_frame_factory
from codeintel_rev.typing import PolarsDataFrame, PolarsModule


class _DummyFrame(PolarsDataFrame):
    """Lightweight stand-in for a polars DataFrame."""

    def __init__(self, records: Sequence[Mapping[str, object]]) -> None:
        self.records = [dict(record) for record in records]

    def write_parquet(self, file: str | Path) -> None:
        Path(file).write_text(json.dumps(self.records), encoding="utf-8")


class _PolarsLegacy:
    """Simulate polars releases that expose ``data_frame``."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, object]]] = []

    def data_frame(self, data: Sequence[Mapping[str, object]]) -> PolarsDataFrame:
        payload = [dict(item) for item in data]
        self.calls.append(payload)
        return _DummyFrame(payload)


class _PolarsModern:
    """Simulate polars releases that rely solely on ``DataFrame``."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, object]]] = []

    def DataFrame(self, data: Sequence[Mapping[str, object]]) -> PolarsDataFrame:  # noqa: N802
        payload = [dict(item) for item in data]
        self.calls.append(payload)
        return _DummyFrame(payload)


def test_resolve_polars_frame_factory_prefers_legacy_helper() -> None:
    """Legacy helper should be returned when available."""
    polars = _PolarsLegacy()

    factory = resolve_polars_frame_factory(cast("PolarsModule", polars))
    payload = [{"src_path": "a.py", "dst_path": "b.py"}]

    assert factory is not None
    frame = factory(payload)
    assert isinstance(frame, _DummyFrame)
    assert polars.calls == [payload]


def test_resolve_polars_frame_factory_supports_dataframe_constructor() -> None:
    """Modern constructor should be used when ``data_frame`` is absent."""
    polars = _PolarsModern()

    factory = resolve_polars_frame_factory(cast("PolarsModule", polars))
    payload = [{"src_path": "a.py", "dst_path": "b.py"}]

    assert factory is not None
    frame = factory(payload)
    assert isinstance(frame, _DummyFrame)
    assert polars.calls == [payload]


def test_resolve_polars_frame_factory_returns_none_without_entry_points() -> None:
    """Helper should return ``None`` when neither API surface exists."""
    assert resolve_polars_frame_factory(cast("PolarsModule", object())) is None


def test_write_import_graph_supports_dataframe_only_polars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Import graph export should work without ``data_frame`` helper."""
    polars = _PolarsModern()
    monkeypatch.setattr(
        graph_builder, "gate_import", lambda *_args, **_kwargs: cast("PolarsModule", polars)
    )
    graph = graph_builder.ImportGraph(
        edges={"a.py": {"b.py"}},
        fan_in={"a.py": 0, "b.py": 1},
        fan_out={"a.py": 1, "b.py": 0},
        cycle_group={"a.py": 0, "b.py": 0},
    )
    target = tmp_path / "imports.parquet"

    graph_builder.write_import_graph(graph, target)

    assert target.exists()
    assert polars.calls[0] == [{"src_path": "a.py", "dst_path": "b.py"}]


def test_write_use_graph_supports_dataframe_only_polars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use graph export should work without ``data_frame`` helper."""
    polars = _PolarsModern()
    monkeypatch.setattr(
        uses_builder, "gate_import", lambda *_args, **_kwargs: cast("PolarsModule", polars)
    )
    use_graph = uses_builder.UseGraph(
        uses_by_file={"a.py": {"b.py"}},
        symbol_usage={"a.py": 1},
        edges=[("a.py", "b.py", "sym")],
    )
    target = tmp_path / "uses.parquet"

    uses_builder.write_use_graph(use_graph, target)

    assert target.exists()
    assert polars.calls[0] == [{"def_path": "a.py", "use_path": "b.py", "symbol": "sym"}]
