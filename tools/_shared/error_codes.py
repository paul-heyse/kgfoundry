"""Canonical error code registry for tooling and pipelines.

This module defines a stable set of error codes that can be surfaced by
shell scripts, Python tooling, HTTP APIs, and CLI utilities. Error codes are
structured so they can be displayed to end users and indexed by observability
systems. Each code maps to metadata describing the failure domain, category,
severity, and recommended remediation steps.

Examples
--------
>>> from tools._shared.error_codes import format_error_message, get_error_code
>>> message = format_error_message("KGF-DOC-BLD-001", "Docstring builder failed")
>>> "KGF-DOC-BLD-001" in message
True
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "CANONICAL_ERROR_CODES",
    "CanonicalErrorCode",
    "format_error_message",
    "get_error_code",
]


@dataclass(frozen=True, slots=True)
class CanonicalErrorCode:
    """Metadata describing a canonical error code."""

    code: str
    title: str
    summary: str
    domain: str
    category: str
    severity: str
    remediation: str

    def format(self, message: str, *, details: str | None = None) -> str:
        """Return a formatted terminal message for ``message``.

        Parameters
        ----------
        message : str
            Human-readable failure description.
        details : str | None, optional
            Optional additional context appended on separate lines.

        Returns
        -------
        str
            Formatted error message string.
        """
        header = f"[ERROR {self.code}] {message}"
        suffix = f"Hint: {self.remediation}" if self.remediation else ""
        if details:
            return "\n".join(word for word in (header, details, suffix) if word)
        if suffix:
            return f"{header}\n{suffix}"
        return header


def _code(code: str, **kwargs: str) -> CanonicalErrorCode:
    return CanonicalErrorCode(code=code, **kwargs)


CANONICAL_ERROR_CODES: Final[dict[str, CanonicalErrorCode]] = {
    # Documentation pipeline (docs/ site build)
    "KGF-DOC-ENV-001": _code(
        "KGF-DOC-ENV-001",
        title="Tooling prerequisites missing",
        summary="One or more required documentation tools are not available",
        domain="documentation",
        category="environment",
        severity="error",
        remediation=(
            "Run 'scripts/bootstrap.sh' or 'uv sync --frozen' to install the toolchain."
        ),
    ),
    "KGF-DOC-ENV-002": _code(
        "KGF-DOC-ENV-002",
        title="DocFacts schema not found",
        summary="docs/_build/schema_docfacts.json is missing",
        domain="documentation",
        category="environment",
        severity="error",
        remediation="Restore docs/_build/schema_docfacts.json from version control or rerun the schema export utility.",
    ),
    "KGF-DOC-BLD-001": _code(
        "KGF-DOC-BLD-001",
        title="Docstring builder failed",
        summary="Managed docstring generation did not complete successfully",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Inspect the stdout/stderr output above and fix cited modules or plugins.",
    ),
    "KGF-DOC-BLD-002": _code(
        "KGF-DOC-BLD-002",
        title="Docformatter failed",
        summary="Docformatter exited with a non-zero status",
        domain="documentation",
        category="format",
        severity="error",
        remediation="Fix formatting issues or rerun with --check to locate offending files.",
    ),
    "KGF-DOC-BLD-003": _code(
        "KGF-DOC-BLD-003",
        title="Pydocstyle validation failed",
        summary="pydocstyle reported missing or invalid docstrings",
        domain="documentation",
        category="lint",
        severity="error",
        remediation="Add the missing docstrings or correct the reported style violations.",
    ),
    "KGF-DOC-BLD-004": _code(
        "KGF-DOC-BLD-004",
        title="Docstring coverage threshold not met",
        summary="docstr-coverage did not reach the configured threshold",
        domain="documentation",
        category="quality",
        severity="error",
        remediation="Increase docstring coverage or adjust the threshold if intentional.",
    ),
    "KGF-DOC-BLD-005": _code(
        "KGF-DOC-BLD-005",
        title="DocFacts schema synchronization failed",
        summary="The pipeline could not copy schema/docs/schema_docfacts.json into docs/_build",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Verify the canonical schema exists under schema/docs/ and rerun the synchronization stage.",
    ),
    "KGF-DOC-BLD-006": _code(
        "KGF-DOC-BLD-006",
        title="DocFacts schema validation failed",
        summary="Docstring builder output violated the DocFacts schema",
        domain="documentation",
        category="validation",
        severity="error",
        remediation="Ensure docs/_build/schema_docfacts.json matches the canonical schema and re-run the docstring builder.",
    ),
    "KGF-DOC-BLD-009": _code(
        "KGF-DOC-BLD-009",
        title="Python compilation failed",
        summary="Static compilation of sources with compileall detected syntax errors",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Run 'uv run python -m compileall -q src' locally to locate and fix the syntax error.",
    ),
    "KGF-DOC-BLD-016": _code(
        "KGF-DOC-BLD-016",
        title="CLI OpenAPI generation failed",
        summary="The Typer to OpenAPI conversion utility exited with a non-zero status",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Run 'uv run python tools/typer_to_openapi_cli.py --app orchestration.cli:app' locally to inspect the failure.",
    ),
    "KGF-DOC-BLD-012": _code(
        "KGF-DOC-BLD-012",
        title="Gallery validation failed",
        summary="tools/validate_gallery.py detected inconsistencies",
        domain="documentation",
        category="validation",
        severity="error",
        remediation="Run 'uv run python tools/validate_gallery.py --verbose' to inspect failing examples.",
    ),
    "KGF-DOC-BLD-013": _code(
        "KGF-DOC-BLD-013",
        title="Example doctest suite failed",
        summary="Gallery doctests did not pass",
        domain="documentation",
        category="tests",
        severity="error",
        remediation="Review failing doctests and update the examples to match current behaviour.",
    ),
    "KGF-DOC-BLD-015": _code(
        "KGF-DOC-BLD-015",
        title="README generation failed",
        summary="Automated README generation or doctoc execution failed",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Run 'uv run python tools/gen_readmes.py' manually and address reported errors.",
    ),
    "KGF-DOC-BLD-010": _code(
        "KGF-DOC-BLD-010",
        title="Navmap generation failed",
        summary="Automatic navigation map could not be regenerated",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Review navmap logs; run 'uv run python tools/navmap/build_navmap.py' manually.",
    ),
    "KGF-DOC-BLD-011": _code(
        "KGF-DOC-BLD-011",
        title="Navmap integrity check failed",
        summary="tools/navmap/check_navmap.py detected drift",
        domain="documentation",
        category="validation",
        severity="error",
        remediation="Inspect the reported differences and update navmap artifacts as needed.",
    ),
    "KGF-DOC-BLD-020": _code(
        "KGF-DOC-BLD-020",
        title="Symbol index build failed",
        summary="AutoAPI symbol index generation exited with errors",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Check failing modules for import errors or broken annotations.",
    ),
    "KGF-DOC-BLD-021": _code(
        "KGF-DOC-BLD-021",
        title="Symbol delta build failed",
        summary="Symbol delta computation did not complete",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Inspect docs/_scripts/symbol_delta.py output and ensure prior symbol artifacts exist.",
    ),
    "KGF-DOC-BLD-030": _code(
        "KGF-DOC-BLD-030",
        title="Test map build failed",
        summary="Test map artifacts could not be regenerated",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Run 'uv run python tools/docs/build_test_map.py' with --verbose for details.",
    ),
    "KGF-DOC-BLD-040": _code(
        "KGF-DOC-BLD-040",
        title="Observability scan failed",
        summary="Observability catalog scan exited with errors",
        domain="documentation",
        category="validation",
        severity="error",
        remediation="Inspect tooling logs and ensure observability configs are current.",
    ),
    "KGF-DOC-BLD-050": _code(
        "KGF-DOC-BLD-050",
        title="Schema export failed",
        summary="tools/docs/export_schemas.py encountered an error",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Verify schema definitions and recent model changes for compatibility issues.",
    ),
    "KGF-DOC-BLD-060": _code(
        "KGF-DOC-BLD-060",
        title="Graph build failed",
        summary="Dependency graph generation did not complete",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Review graph build logs and ensure pydeps/pyreverse are installed.",
    ),
    "KGF-DOC-BLD-070": _code(
        "KGF-DOC-BLD-070",
        title="Sphinx HTML build failed",
        summary="Sphinx HTML output failed to compile",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Fix the Sphinx warnings/errors printed above and re-run the build.",
    ),
    "KGF-DOC-BLD-080": _code(
        "KGF-DOC-BLD-080",
        title="Sphinx JSON build failed",
        summary="Sphinx JSON output failed to compile",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Fix the reported Sphinx issues and retry the JSON build.",
    ),
    "KGF-DOC-BLD-090": _code(
        "KGF-DOC-BLD-090",
        title="MkDocs build failed",
        summary="MkDocs static site generation exited with errors",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Inspect MkDocs output; ensure mkdocs and plugins are installed.",
    ),
    "KGF-DOC-BLD-091": _code(
        "KGF-DOC-BLD-091",
        title="MkDocs suite build failed",
        summary="MkDocs suite configuration failed to build",
        domain="documentation",
        category="build",
        severity="error",
        remediation="Run 'uv run mkdocs build --config-file tools/mkdocs_suite/mkdocs.yml --strict' to reproduce and fix configuration issues.",
    ),
    "KGF-DOC-BLD-105": _code(
        "KGF-DOC-BLD-105",
        title="Documentation artifact validation failed",
        summary="docs/_scripts/validate_artifacts.py detected issues",
        domain="documentation",
        category="validation",
        severity="error",
        remediation="Resolve validation errors reported by docs/_scripts/validate_artifacts.py before retrying.",
    ),
}


def get_error_code(code: str) -> CanonicalErrorCode:
    """Return metadata for ``code``.

    Parameters
    ----------
    code : str
        Error code identifier.

    Returns
    -------
    CanonicalErrorCode
        Error code metadata.

    Raises
    ------
    KeyError
        If the code is not registered.
    """
    try:
        return CANONICAL_ERROR_CODES[code]
    except KeyError as exc:  # pragma: no cover - defensive guard
        message = f"Unknown error code: {code}"
        raise KeyError(message) from exc


def format_error_message(code: str, message: str, *, details: str | None = None) -> str:
    """Return a formatted error message for ``code`` and ``message``.

    Parameters
    ----------
    code : str
        Error code identifier.
    message : str
        Human-readable error message.
    details : str | None, optional
        Optional additional context.

    Returns
    -------
    str
        Formatted error message string.
    """
    return get_error_code(code).format(message, details=details)
