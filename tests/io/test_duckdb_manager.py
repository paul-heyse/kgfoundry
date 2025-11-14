from __future__ import annotations

from types import ModuleType, SimpleNamespace
from typing import cast

from codeintel_rev.io.duckdb_manager import DuckDBConfig, DuckDBManager
from codeintel_rev.observability.timeline import Timeline, bind_timeline


def test_duckdb_manager_instruments_sql(monkeypatch, tmp_path) -> None:
    executed: dict[str, object] = {}

    class _StubConn:
        def execute(self, query: object, parameters: object = None) -> _StubConn:
            executed["sql"] = query
            executed["has_params"] = parameters is not None
            return self

        def close(self) -> None:
            pass

    duckdb_stub = cast(
        "ModuleType",
        SimpleNamespace(connect=lambda _path: _StubConn()),
    )
    monkeypatch.setattr(
        "codeintel_rev.io.duckdb_manager.duckdb",
        duckdb_stub,
    )
    manager = DuckDBManager(tmp_path / "catalog.duckdb", DuckDBConfig(log_queries=True))
    timeline = Timeline(session_id="sess-test", run_id="run-test", sampled=True)
    with bind_timeline(timeline), manager.connection() as conn:
        conn.execute("SELECT 1")
    assert executed["sql"] == "SELECT 1"
    event_names = [event["name"] for event in timeline.snapshot()]
    assert "sql.exec.done" in event_names
