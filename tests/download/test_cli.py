"""Tests for the download CLI migrating to the shared tooling standard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from download import cli
from tests._helpers import assertions


def test_harvest_emits_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The harvest command should write a structured CLI envelope on success."""
    monkeypatch.setattr(cli, "CLI_ENVELOPE_DIR", tmp_path)
    expected_path = tmp_path / f"{cli.CLI_SETTINGS.bin_name}-{cli.CLI_COMMAND}-harvest.json"

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "download",
            "harvest",
            "foundation models",
            "--years",
            ">=2021",
            "--max-works",
            "100",
        ],
    )

    assertions.expect_equal(result.exit_code, 0)
    assertions.expect_in("dry-run", result.stdout)

    envelope = json.loads(expected_path.read_text(encoding="utf-8"))
    assertions.expect_equal(envelope["command"], cli.CLI_COMMAND)
    assertions.expect_equal(envelope["subcommand"], "harvest")
    assertions.expect_equal(envelope["status"], "success")
    assertions.expect_equal(envelope["files"][0]["status"], "success")
