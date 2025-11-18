"""Guarded optional dependency imports with Problem Details and observability.

This module provides typed helpers for safely importing optional dependencies
(Griffe, AutoAPI, Sphinx) with structured error handling, logging, and metrics.

All import failures raise ArtifactDependencyError carrying RFC 9457 Problem Details
with correlation IDs and remediation guidance.

Examples
--------
>>> from kgfoundry_common.optional_deps import safe_import_griffe
>>> try:
...     griffe = safe_import_griffe()
...     loader = griffe.GriffeLoader()
... except ArtifactDependencyError as e:
...     print(f"Griffe unavailable: {e.problem_details()}")
"""

# [nav:section public-api]

from __future__ import annotations

import importlib
import uuid
from typing import TYPE_CHECKING, TypeVar, cast

from kgfoundry_common.errors import ArtifactDependencyError
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.problem_details import build_problem_details

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kgfoundry_common.types import JsonValue

__all__ = [
    "OptionalDependencyError",
    "safe_import_autoapi",
    "safe_import_griffe",
    "safe_import_sphinx",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


T = TypeVar("T")


# [nav:anchor OptionalDependencyError]
class OptionalDependencyError(ArtifactDependencyError):
    """Raised when an optional dependency cannot be imported.

    This error includes RFC 9457 Problem Details, remediation guidance,
    and correlation IDs for observability.

    Initializes optional dependency error with message, module name, and optional context.

    Parameters
    ----------
    message : str
        Human-readable error message describing the missing dependency.
    module_name : str, optional
        Name of the missing module (e.g., "griffe", "autoapi"). Defaults to "".
    extra : Mapping[str, object] | None, optional
        Additional context fields for Problem Details. Defaults to None.
    cause : Exception | None, optional
        Underlying exception that caused the import failure. Defaults to None.

    Examples
    --------
    >>> from kgfoundry_common.optional_deps import OptionalDependencyError
    >>> try:
    ...     raise OptionalDependencyError(
    ...         "Module griffe not found",
    ...         module_name="griffe",
    ...         extra={"install_command": "pip install kgfoundry[docs]"},
    ...     )
    ... except OptionalDependencyError as e:
    ...     print(f"Error: {e}")
    ...     assert e.context is not None
    ...     assert e.context.get("module_name") == "griffe"
    Error: OptionalDependencyError[artifact-dependency-error]: Module griffe not found
    """

    def __init__(
        self,
        message: str,
        module_name: str = "",
        extra: Mapping[str, object] | None = None,
        cause: Exception | None = None,
    ) -> None:
        """Initialize optional dependency error.

        Parameters
        ----------
        message : str
            Human-readable error message describing the missing dependency.
        module_name : str, optional
            Name of the missing module (e.g., "griffe", "autoapi"). Defaults to "".
        extra : Mapping[str, object] | None, optional
            Additional context fields for Problem Details. Defaults to None.
        cause : Exception | None, optional
            Underlying exception that caused the import failure.
        """
        context = dict(extra or {})
        context["module_name"] = module_name
        context["correlation_id"] = str(uuid.uuid4())
        super().__init__(message, cause=cause, context=context)


def _make_remediation_guidance(module_name: str) -> dict[str, str]:
    """Build remediation guidance for missing optional dependency.

    Parameters
    ----------
    module_name : str
        The name of the missing module.

    Returns
    -------
    dict[str, str]
        Guidance with install commands and documentation links.
    """
    guidance_map = {
        "griffe": {
            "install": "pip install kgfoundry[docs]",
            "docs": "https://docs.kgfoundry.dev/getting-started",
        },
        "autoapi": {
            "install": "pip install kgfoundry[docs]",
            "docs": "https://docs.kgfoundry.dev/docs-toolchain",
        },
        "sphinx": {
            "install": "pip install kgfoundry[docs]",
            "docs": "https://docs.kgfoundry.dev/docs-toolchain",
        },
    }
    return guidance_map.get(module_name, {"install": f"pip install {module_name}"})


# [nav:anchor safe_import_griffe]
def safe_import_griffe() -> object:
    """Safely import Griffe with Problem Details on failure.

    Returns
    -------
    object
        The griffe module.

    Raises
    ------
    OptionalDependencyError
        If Griffe is not installed or cannot be imported.

    Examples
    --------
    >>> from kgfoundry_common.optional_deps import safe_import_griffe
    >>> try:
    ...     griffe = safe_import_griffe()
    ...     # Use griffe
    ... except OptionalDependencyError as e:
    ...     print(f"Griffe not available: {e}")
    """
    correlation_id = str(uuid.uuid4())
    try:
        griffe = importlib.import_module("griffe")
    except ImportError as exc:
        remediation = _make_remediation_guidance("griffe")
        message = f"Griffe is not installed. Install it with: {remediation['install']}"
        # Build Problem Details
        problem = build_problem_details(
            problem_type="https://docs.kgfoundry.dev/problems/optional-dependency-missing",
            title="Optional dependency not installed",
            status=400,
            detail=message,
            instance=f"urn:kgfoundry:docs:griffe:{correlation_id}",
            extensions=cast(
                "Mapping[str, JsonValue]",
                {
                    "module": "griffe",
                    "correlation_id": correlation_id,
                    "remediation": remediation,
                },
            ),
        )

        raise OptionalDependencyError(
            message,
            module_name="griffe",
            extra={
                "correlation_id": correlation_id,
                "remediation": remediation,
                "problem_details": problem,
            },
            cause=exc,
        ) from exc
    else:
        return griffe


# [nav:anchor safe_import_autoapi]
def safe_import_autoapi() -> object:
    """Safely import AutoAPI with Problem Details on failure.

    Returns
    -------
    object
        The autoapi module.

    Raises
    ------
    OptionalDependencyError
        If AutoAPI is not installed or cannot be imported.

    Examples
    --------
    >>> from kgfoundry_common.optional_deps import safe_import_autoapi
    >>> try:
    ...     autoapi = safe_import_autoapi()
    ...     # Use autoapi
    ... except OptionalDependencyError as e:
    ...     print(f"AutoAPI not available: {e}")
    """
    correlation_id = str(uuid.uuid4())
    try:
        autoapi = importlib.import_module("autoapi")
    except ImportError as exc:
        remediation = _make_remediation_guidance("autoapi")
        message = f"AutoAPI is not installed. Install it with: {remediation['install']}"

        problem = build_problem_details(
            problem_type="https://docs.kgfoundry.dev/problems/optional-dependency-missing",
            title="Optional dependency not installed",
            status=400,
            detail=message,
            instance=f"urn:kgfoundry:docs:autoapi:{correlation_id}",
            extensions=cast(
                "Mapping[str, JsonValue]",
                {
                    "module": "autoapi",
                    "correlation_id": correlation_id,
                    "remediation": remediation,
                },
            ),
        )

        raise OptionalDependencyError(
            message,
            module_name="autoapi",
            extra={
                "correlation_id": correlation_id,
                "remediation": remediation,
                "problem_details": problem,
            },
            cause=exc,
        ) from exc
    else:
        return autoapi


# [nav:anchor safe_import_sphinx]
def safe_import_sphinx() -> object:
    """Safely import Sphinx with Problem Details on failure.

    Returns
    -------
    object
        The sphinx module.

    Raises
    ------
    OptionalDependencyError
        If Sphinx is not installed or cannot be imported.

    Examples
    --------
    >>> from kgfoundry_common.optional_deps import safe_import_sphinx
    >>> try:
    ...     sphinx = safe_import_sphinx()
    ...     # Use sphinx
    ... except OptionalDependencyError as e:
    ...     print(f"Sphinx not available: {e}")
    """
    correlation_id = str(uuid.uuid4())
    try:
        sphinx = importlib.import_module("sphinx")
    except ImportError as exc:
        remediation = _make_remediation_guidance("sphinx")
        message = f"Sphinx is not installed. Install it with: {remediation['install']}"

        problem = build_problem_details(
            problem_type="https://docs.kgfoundry.dev/problems/optional-dependency-missing",
            title="Optional dependency not installed",
            status=400,
            detail=message,
            instance=f"urn:kgfoundry:docs:sphinx:{correlation_id}",
            extensions=cast(
                "Mapping[str, JsonValue]",
                {
                    "module": "sphinx",
                    "correlation_id": correlation_id,
                    "remediation": remediation,
                },
            ),
        )

        raise OptionalDependencyError(
            message,
            module_name="sphinx",
            extra={
                "correlation_id": correlation_id,
                "remediation": remediation,
                "problem_details": problem,
            },
            cause=exc,
        ) from exc
    else:
        return sphinx
