"""Unit tests for optional dependency guards and Problem Details handling.

This module tests:
- Safe import helpers with guarded exception handling
- RFC 9457 Problem Details generation
- Structured logging and correlation IDs
- Graceful degradation when dependencies are missing
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest

from kgfoundry_common.errors import ArtifactDependencyError
from kgfoundry_common.optional_deps import (
    OptionalDependencyError,
    safe_import_autoapi,
    safe_import_griffe,
    safe_import_sphinx,
)
from tests._helpers import assertions


def _expect_mapping(value: object, label: str) -> Mapping[str, Any]:
    """Assert value is a mapping or raise TypeError.

    Parameters
    ----------
    value : object
        Value to check.
    label : str
        Label for error message.

    Returns
    -------
    Mapping[str, Any]
        Value cast to mapping.

    Raises
    ------
    TypeError
        If value is not a mapping.
    """
    if not isinstance(value, Mapping):
        message = f"Expected {label} to be a mapping, got {type(value)!r}"
        raise TypeError(message)
    return value


def _successful_importer(result: object, calls: list[str]) -> Callable[[str], object]:
    """Create an importer that succeeds and records calls.

    Parameters
    ----------
    result : object
        Object to return for all import requests.
    calls : list[str]
        List to append module names to when imported.

    Returns
    -------
    Callable[[str], object]
        Import function that returns result and records calls.
    """

    def importer(name: str) -> object:
        """Record import call and return result.

        Parameters
        ----------
        name : str
            Module name being imported.

        Returns
        -------
        object
            Pre-configured result object.
        """
        calls.append(name)
        return result

    return importer


def _failing_importer(calls: list[str]) -> Callable[[str], object]:
    """Create an importer that fails and records calls.

    Parameters
    ----------
    calls : list[str]
        List to append module names to when import attempted.

    Returns
    -------
    Callable[[str], object]
        Import function that raises ImportError and records calls.
    """

    def importer(name: str) -> object:
        """Record import call and raise ImportError.

        Parameters
        ----------
        name : str
            Module name being imported.

        Raises
        ------
        ImportError
            Always raised with message "No module named '{name}'".
        """
        calls.append(name)
        message = f"No module named '{name}'"
        raise ImportError(message)

    return importer


def test_is_artifact_dependency_error() -> None:
    """OptionalDependencyError extends ArtifactDependencyError."""
    err = OptionalDependencyError("test message", module_name="griffe")
    assertions.expect_true(
        isinstance(err, ArtifactDependencyError), reason="should be ArtifactDependencyError"
    )


def test_includes_correlation_id() -> None:
    """OptionalDependencyError includes unique correlation ID."""
    err = OptionalDependencyError("test message", module_name="griffe")
    context: Mapping[str, Any] = _expect_mapping(err.context, "context")
    correlation_id: str | Any = context.get("correlation_id")
    assertions.expect_true(isinstance(correlation_id, str), reason="correlation_id should be str")
    assertions.expect_true(len(correlation_id) > 0, reason="correlation_id should not be empty")


def test_includes_module_name() -> None:
    """OptionalDependencyError includes the missing module name."""
    err = OptionalDependencyError("test message", module_name="griffe")
    context: Mapping[str, Any] = _expect_mapping(err.context, "context")
    assertions.expect_equal(context.get("module_name"), "griffe")


def test_extra_context_preserved() -> None:
    """Extra context is preserved in error."""
    extra = {"install": "pip install griffe"}
    err = OptionalDependencyError("test message", module_name="griffe", extra=extra)
    context = _expect_mapping(err.context, "context")
    assertions.expect_equal(context.get("install"), "pip install griffe")


@pytest.mark.parametrize(
    ("module_name", "message"),
    [
        ("griffe", "Griffe failed to import"),
        ("autoapi", "AutoAPI failed to import"),
        ("sphinx", "Sphinx failed to import"),
    ],
)
def test_error_with_various_modules(module_name: str, message: str) -> None:
    """OptionalDependencyError works with various module names."""
    err = OptionalDependencyError(message, module_name=module_name)
    context = _expect_mapping(err.context, "context")
    assertions.expect_equal(context.get("module_name"), module_name)


def test_safe_import_griffe_success() -> None:
    """safe_import_griffe returns griffe module when available."""
    calls: list[str] = []
    sentinel = object()
    result = safe_import_griffe(importer=_successful_importer(sentinel, calls))
    assertions.expect_true(result is sentinel, reason="should return sentinel module")
    assertions.expect_sequence_equal(calls, ["griffe"])


def test_safe_import_griffe_missing() -> None:
    """safe_import_griffe raises OptionalDependencyError when missing."""
    calls: list[str] = []
    with pytest.raises(OptionalDependencyError) as exc_info:
        safe_import_griffe(importer=_failing_importer(calls))

    err = exc_info.value
    assertions.expect_true("griffe" in str(err).lower(), reason="error should mention griffe")
    context = _expect_mapping(err.context, "context")
    assertions.expect_equal(context.get("module_name"), "griffe")
    assertions.expect_sequence_equal(calls, ["griffe"])


def test_problem_details_in_context() -> None:
    """safe_import_griffe includes Problem Details in error context."""
    with pytest.raises(OptionalDependencyError) as exc_info:
        safe_import_griffe(importer=_failing_importer([]))

    err = exc_info.value
    context = _expect_mapping(err.context, "context")
    details = _expect_mapping(context.get("problem_details"), "problem_details")
    assertions.expect_equal(
        details.get("type"),
        "https://docs.kgfoundry.dev/problems/optional-dependency-missing",
    )
    assertions.expect_equal(details.get("status"), 400)


def test_correlation_id_in_problem_details() -> None:
    """safe_import_griffe includes correlation ID in Problem Details."""
    with pytest.raises(OptionalDependencyError) as exc_info:
        safe_import_griffe(importer=_failing_importer([]))

    err = exc_info.value
    context = _expect_mapping(err.context, "context")
    assertions.expect_true("correlation_id" in context, reason="context should have correlation_id")


def test_safe_import_autoapi_success() -> None:
    """safe_import_autoapi returns autoapi module when available."""
    calls: list[str] = []
    sentinel = object()
    result = safe_import_autoapi(importer=_successful_importer(sentinel, calls))
    assertions.expect_true(result is sentinel, reason="should return sentinel module")
    assertions.expect_sequence_equal(calls, ["autoapi"])


def test_safe_import_autoapi_missing() -> None:
    """safe_import_autoapi raises OptionalDependencyError when missing."""
    calls: list[str] = []
    with pytest.raises(OptionalDependencyError) as exc_info:
        safe_import_autoapi(importer=_failing_importer(calls))

    err = exc_info.value
    assertions.expect_true("autoapi" in str(err).lower(), reason="error should mention autoapi")
    context = _expect_mapping(err.context, "context")
    assertions.expect_equal(context.get("module_name"), "autoapi")
    assertions.expect_sequence_equal(calls, ["autoapi"])


def test_safe_import_sphinx_success() -> None:
    """safe_import_sphinx returns sphinx module when available."""
    calls: list[str] = []
    sentinel = object()
    result = safe_import_sphinx(importer=_successful_importer(sentinel, calls))
    assertions.expect_true(result is sentinel, reason="should return sentinel module")
    assertions.expect_sequence_equal(calls, ["sphinx"])


def test_safe_import_sphinx_missing() -> None:
    """safe_import_sphinx raises OptionalDependencyError when missing."""
    calls: list[str] = []
    with pytest.raises(OptionalDependencyError) as exc_info:
        safe_import_sphinx(importer=_failing_importer(calls))

    err = exc_info.value
    assertions.expect_true("sphinx" in str(err).lower(), reason="error should mention sphinx")
    context = _expect_mapping(err.context, "context")
    assertions.expect_equal(context.get("module_name"), "sphinx")
    assertions.expect_sequence_equal(calls, ["sphinx"])


@pytest.mark.parametrize(
    ("import_func", "module_name"),
    [
        (safe_import_griffe, "griffe"),
        (safe_import_autoapi, "autoapi"),
        (safe_import_sphinx, "sphinx"),
    ],
)
def test_includes_remediation_guidance(import_func: Callable[..., Any], module_name: str) -> None:
    """Safe import functions include remediation guidance."""
    failing_importer = _failing_importer([])
    with pytest.raises(OptionalDependencyError) as exc_info:
        import_func(importer=failing_importer)

    err = exc_info.value
    context = _expect_mapping(err.context, "context")
    assertions.expect_equal(context.get("module_name"), module_name)
    remediation = _expect_mapping(context.get("remediation"), "remediation")
    install = remediation.get("install")
    assertions.expect_true(isinstance(install, str), reason="install should be str")
    if not isinstance(install, str):  # pragma: no cover - defensive
        pytest.fail("install should be a string")
    assertions.expect_true(
        "pip install kgfoundry[docs]" in install, reason="install should mention docs extra"
    )
