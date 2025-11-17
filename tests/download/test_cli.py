"""Tests for the download CLI migrating to the shared tooling standard."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from download import cli
from download.cli import DownloadCliContext, HarvestRequest
from tests._helpers import assertions


def test_harvest_emits_envelope(tmp_path: Path) -> None:
    """The harvest command should write a structured CLI envelope on success."""
    expected_path = tmp_path / f"{cli.CLI_SETTINGS.bin_name}-{cli.CLI_COMMAND}-harvest.json"
    received: list[HarvestRequest] = []

    def _handler(request: HarvestRequest) -> str:
        received.append(request)
        return f"[dry-run] mock harvest {request.topic} years={request.years} max={request.max_works}"

    context = DownloadCliContext(harvest_handler=_handler)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "--envelope-dir",
            str(tmp_path),
            "download",
            "harvest",
            "foundation models",
            "--years",
            ">=2021",
            "--max-works",
            "100",
        ],
        obj={"cli_context": context},
    )

    assertions.expect_equal(result.exit_code, 0)
    assertions.expect_in("dry-run", result.stdout)
    assertions.expect_equal(len(received), 1)
    request = received[0]
    assertions.expect_equal(request.topic, "foundation models")
    assertions.expect_equal(request.years, ">=2021")
    assertions.expect_equal(request.max_works, 100)

    envelope = json.loads(expected_path.read_text(encoding="utf-8"))
    assertions.expect_equal(envelope["command"], cli.CLI_COMMAND)
    assertions.expect_equal(envelope["subcommand"], "harvest")
    assertions.expect_equal(envelope["status"], "success")
    assertions.expect_equal(envelope["files"][0]["status"], "success")
