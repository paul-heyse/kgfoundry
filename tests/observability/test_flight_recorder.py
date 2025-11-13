from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from codeintel_rev.observability.flight_recorder import build_report_uri


def test_build_report_uri_uses_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    started_at = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    uri = build_report_uri("sess", "run-7", trace_id="trace", started_at=started_at)
    assert uri is not None
    path = Path(uri)
    assert path.parts[-4] == "runs"
    assert path.parts[-2] == "sess"
    assert path.parts[-1] == "run-7.json"
