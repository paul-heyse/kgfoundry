"""Integration tests for docstring builder CLI envelope emission."""

from __future__ import annotations

import json
from pathlib import Path

from tools.docstring_builder import cli


def test_schema_command_writes_cli_envelope(monkeypatch, tmp_path) -> None:
    envelope_dir = tmp_path / "cli"
    monkeypatch.setattr(cli, "CLI_ENVELOPE_DIR", envelope_dir)

    output_target = tmp_path / "schema.json"

    exit_code = cli.main(["schema", "--output", str(output_target)])

    assert exit_code == 0
    envelope_path = envelope_dir / "docstring-builder-schema.json"
    payload = json.loads(envelope_path.read_text(encoding="utf-8"))

    assert payload["status"] == "success"
    assert any(
        Path(entry["path"]).resolve() == output_target
        for entry in payload.get("files", [])
    )
