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
from collections.abc import Callable
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
ImporterCallable = Callable[[str], object]
_DEFAULT_IMPORTER: ImporterCallable = importlib.import_module
_MODULE_DISPLAY_NAMES: dict[str, str] = {
    "griffe": "Griffe",
    "autoapi": "AutoAPI",
    "sphinx": "Sphinx",
}


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


def _safe_import_dependency(
    module_name: str,
    *,
    importer: ImporterCallable,
) -> object:
    """Import ``module_name`` using ``importer`` or raise OptionalDependencyError."""
    correlation_id = str(uuid.uuid4())
    try:
        return importer(module_name)
    except ImportError as exc:
        remediation = _make_remediation_guidance(module_name)
        display = _MODULE_DISPLAY_NAMES.get(module_name, module_name)
        message = f"{display} is not installed. Install it with: {remediation['install']}"
        problem = build_problem_details(
            problem_type="https://docs.kgfoundry.dev/problems/optional-dependency-missing",
            title="Optional dependency not installed",
            status=400,
            detail=message,
            instance=f"urn:kgfoundry:docs:{module_name}:{correlation_id}",
            extensions=cast(
                "Mapping[str, JsonValue]",
                {
                    "module": module_name,
                    "correlation_id": correlation_id,
                    "remediation": remediation,
                },
            ),
        )
        raise OptionalDependencyError(
            message,
            module_name=module_name,
            extra={
                "correlation_id": correlation_id,
                "remediation": remediation,
                "problem_details": problem,
            },
            cause=exc,
        ) from exc


# [nav:anchor safe_import_griffe]
def safe_import_griffe(
    *,
    importer: ImporterCallable | None = None,
) -> object:
    """Safely import Griffe with Problem Details on failure.

    Returns
    -------
    object
        The griffe module.

    Raises
    ------
    OptionalDependencyError
        If Griffe is not installed or cannot be imported.

    Parameters
    ----------
    importer : Callable[[str], object] | None, optional
        Alternative import resolver used for dependency injection in tests.

    Examples
    --------
    >>> from kgfoundry_common.optional_deps import safe_import_griffe
    >>> try:
    ...     griffe = safe_import_griffe()
    ...     # Use griffe
    ... except OptionalDependencyError as e:
    ...     print(f"Griffe not available: {e}")
    """
    return _safe_import_dependency("griffe", importer=importer or _DEFAULT_IMPORTER)


# [nav:anchor safe_import_autoapi]
def safe_import_autoapi(
    *,
    importer: ImporterCallable | None = None,
) -> object:
    """Safely import AutoAPI with Problem Details on failure.

    Returns
    -------
    object
        The autoapi module.

    Raises
    ------
    OptionalDependencyError
        If AutoAPI is not installed or cannot be imported.

    Parameters
    ----------
    importer : Callable[[str], object] | None, optional
        Alternative import resolver used for dependency injection in tests.

    Examples
    --------
    >>> from kgfoundry_common.optional_deps import safe_import_autoapi
    >>> try:
    ...     autoapi = safe_import_autoapi()
    ...     # Use autoapi
    ... except OptionalDependencyError as e:
    ...     print(f"AutoAPI not available: {e}")
    """
    return _safe_import_dependency("autoapi", importer=importer or _DEFAULT_IMPORTER)


# [nav:anchor safe_import_sphinx]
def safe_import_sphinx(
    *,
    importer: ImporterCallable | None = None,
) -> object:
    """Safely import Sphinx with Problem Details on failure.

    Returns
    -------
    object
        The sphinx module.

    Raises
    ------
    OptionalDependencyError
        If Sphinx is not installed or cannot be imported.

    Parameters
    ----------
    importer : Callable[[str], object] | None, optional
        Alternative import resolver used for dependency injection in tests.

    Examples
    --------
    >>> from kgfoundry_common.optional_deps import safe_import_sphinx
    >>> try:
    ...     sphinx = safe_import_sphinx()
    ...     # Use sphinx
    ... except OptionalDependencyError as e:
    ...     print(f"Sphinx not available: {e}")
    """
    return _safe_import_dependency("sphinx", importer=importer or _DEFAULT_IMPORTER)
