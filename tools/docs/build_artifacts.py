"""Coordinator for regenerating documentation artefacts in sequence."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from kgfoundry_common.logging import setup_logging
from tools._shared.error_codes import format_error_message
from tools._shared.logging import get_logger, with_fields
from tools._shared.proc import ToolExecutionError, run_tool

REPO_ROOT = Path(__file__).resolve().parents[2]


def _pythonpath_env() -> dict[str, str]:
    existing = os.environ.get("PYTHONPATH")
    parts = [str(REPO_ROOT)]
    if existing:
        parts.append(existing)
    env: dict[str, str] = {
        "PYTHONPATH": os.pathsep.join(parts),
        "DISABLE_PROM_METRICS": "1",
        "PROMETHEUS_DISABLE_CREATED_SERIES": "True",
    }
    return env


LOGGER = get_logger(__name__)
setup_logging()

STEPS: list[tuple[str, list[str], str]] = [
    (
        "docstrings",
        [
            sys.executable,
            "-m",
            "tools.docstring_builder.cli",
            "--ignore-missing",
            "generate",
        ],
        "[docstrings] synchronized managed docstrings and DocFacts",
    ),
    (
        "navmap",
        [
            sys.executable,
            "-m",
            "tools.navmap.build_navmap",
            "--write",
            str(REPO_ROOT / "site" / "_build" / "navmap" / "navmap.json"),
        ],
        "[navmap] regenerated site/_build/navmap/navmap.json",
    ),
    (
        "test-map",
        [sys.executable, "tools/docs/build_test_map.py"],
        "[testmap] refreshed docs/_build/test_map artefacts",
    ),
    (
        "symbol-index",
        [sys.executable, "docs/_scripts/build_symbol_index.py"],
        "[symbols] generated docs/_build/symbol index artefacts",
    ),
    (
        "symbol-delta",
        [sys.executable, "docs/_scripts/symbol_delta.py"],
        "[symbols] computed docs/_build/symbols.delta.json",
    ),
    (
        "observability",
        [sys.executable, "tools/docs/scan_observability.py"],
        "[observability] updated docs/_build/configuration snapshots",
    ),
    (
        "schemas",
        [sys.executable, "tools/docs/export_schemas.py"],
        "[schemas] exported API schemas",
    ),
    (
        "docs-validation",
        [sys.executable, "docs/_scripts/validate_artifacts.py"],
        "[docs] validated docs/_build JSON artefacts",
    ),
]

STEP_TIMEOUTS: dict[str, float] = {
    "docstrings": 120.0,
    "navmap": 60.0,
    "test-map": 60.0,
    "symbol-index": 300.0,
    "symbol-delta": 120.0,
    "observability": 120.0,
    "schemas": 180.0,
    "docs-validation": 120.0,
}

STEP_ERROR_CODES: dict[str, str] = {
    "docstrings": "KGF-DOC-BLD-001",
    "navmap": "KGF-DOC-BLD-010",
    "test-map": "KGF-DOC-BLD-030",
    "symbol-index": "KGF-DOC-BLD-020",
    "symbol-delta": "KGF-DOC-BLD-021",
    "observability": "KGF-DOC-BLD-040",
    "schemas": "KGF-DOC-BLD-050",
    "docs-validation": "KGF-DOC-BLD-105",
}


def _run_step(name: str, command: list[str], message: str) -> int:
    """Execute a single artefact regeneration step.

    Parameters
    ----------
    name : str
        Step name identifier.
    command : list[str]
        Command to execute.
    message : str
        Success message to log.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    log_adapter = with_fields(LOGGER, operation=name, command=command)
    try:
        timeout = STEP_TIMEOUTS.get(name, 60.0)
        result = run_tool(
            command,
            timeout=timeout,
            cwd=REPO_ROOT,
            env=_pythonpath_env(),
            check=False,
        )
        if result.returncode != 0:
            if result.stdout:
                log_adapter.error(
                    "[artifacts] %s stdout captured",
                    name,
                    extra={"stdout": result.stdout},
                )
            if result.stderr:
                log_adapter.error(
                    "[artifacts] %s stderr captured",
                    name,
                    extra={"stderr": result.stderr},
                )
            code = STEP_ERROR_CODES.get(name, "KGF-DOC-BLD-105")
            log_adapter.error(
                format_error_message(
                    code,
                    f"Artifact step '{name}' failed",
                    details=(result.stderr or result.stdout or "").strip(),
                ),
                extra={"error_code": code, "returncode": result.returncode},
            )
            return result.returncode
    except ToolExecutionError as exc:
        code = STEP_ERROR_CODES.get(name, "KGF-DOC-BLD-105")
        details = getattr(exc, "stderr", "")
        log_adapter.exception(
            format_error_message(
                code,
                f"Artifact step '{name}' raised ToolExecutionError",
                details=details,
            ),
            extra={"error_code": code},
        )
        return exc.returncode if exc.returncode is not None else 1
    else:
        log_adapter.info(message)
        return 0


def main() -> int:
    """Run all artefact regeneration steps and stop on the first failure.

    Returns
    -------
    int
        Exit code (0 if all steps succeed, non-zero on first failure).
    """
    for name, command, message in STEPS:
        status = _run_step(name, command, message)
        if status != 0:
            return status
    LOGGER.info("[artifacts] all steps completed successfully")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
