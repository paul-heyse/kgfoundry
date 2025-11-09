from __future__ import annotations

from pathlib import Path

import pytest
from tools import CliRunConfig, Paths, cli_run


def _stub_paths(tmp_path: Path) -> Paths:
    return Paths(
        repo_root=tmp_path,
        docs_data=tmp_path / "docs/_data",
        cli_out_root=tmp_path / "docs/_data/cli",
    )


def test_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Paths, "discover", staticmethod(lambda: _stub_paths(tmp_path)))
    cfg = CliRunConfig.from_route(
        "demo", "ok", write_envelope_on="always", exit_on_error=False
    )
    with cli_run(cfg) as (context, envelope):
        assert context.operation == "demo.ok"
        envelope.set_result(summary="ok")

    # assert envelope exists
    out_dir = tmp_path / "docs/_data/cli/demo/ok"
    paths = sorted(out_dir.glob("*.json"))
    assert len(paths) == 1
    data = paths[0].read_text()
    assert '"status": "success"' in data
    assert '"operation": "demo.ok"' in data


def test_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Paths, "discover", staticmethod(lambda: _stub_paths(tmp_path)))
    cfg = CliRunConfig.from_route(
        "demo", "fail", write_envelope_on="always", exit_on_error=False
    )

    def _invoke_failure() -> None:
        with cli_run(cfg) as (context, _):
            assert context.operation == "demo.fail"
            message = "boom"
            raise RuntimeError(message)

    with pytest.raises(RuntimeError):
        _invoke_failure()
    out_dir = tmp_path / "docs/_data/cli/demo/fail"
    assert any('"status": "error"' in p.read_text() for p in out_dir.glob("*.json"))
