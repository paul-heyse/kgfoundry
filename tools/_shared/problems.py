"""Lightweight Problem Details helpers shared by the CLI façade."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ProblemDetails:
    """Subset of RFC 9457 Problem Details used by CLI envelope builders."""

    type: str
    title: str
    detail: str | None = None
    status: int | None = None
    instance: str | None = None
    code: str | None = None
    ext: Mapping[str, object] | None = None


def problem_from_exc(
    exc: BaseException,
    *,
    code_map: Mapping[type[BaseException], str] | None = None,
    operation: str | None = None,
    run_id: str | None = None,
) -> ProblemDetails:
    """Return a :class:`ProblemDetails` instance describing ``exc``.

    Parameters
    ----------
    exc : BaseException
        The exception raised while executing the CLI command.
    code_map : Mapping[type[BaseException], str] | None, optional
        Optional mapping from exception type to canonical error codes. Defaults
        to ``None``.
    operation : str | None, optional
        Fully qualified operation identifier for the active CLI command.
    run_id : str | None, optional
        Identifier assigned to the CLI run.

    Returns
    -------
    ProblemDetails
        Structured problem metadata ready to be embedded in envelopes.
    """
    name = exc.__class__.__name__
    code = (code_map or {}).get(type(exc))
    type_uri = f"urn:kgf:problem:{name.lower()}"
    title = name.replace("_", " ")
    detail = str(exc) or None
    instance = f"urn:kgf:op:{operation}:run:{run_id}" if operation and run_id else None
    return ProblemDetails(
        type=type_uri,
        title=title,
        detail=detail,
        status=500,
        instance=instance,
        code=code,
    )


__all__ = ["ProblemDetails", "problem_from_exc"]
