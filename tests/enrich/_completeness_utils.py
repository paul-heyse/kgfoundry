"""Helpers for normalizing completeness reports in tests."""

from __future__ import annotations

from typing import Any


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministically ordered completeness payload.

    Parameters
    ----------
    payload : dict[str, Any]
        Raw completeness payload dictionary to normalize.

    Returns
    -------
    dict[str, Any]
        Normalized payload with sorted collections.
    """
    missing_modules = sorted(payload.get("missing_modules", []))
    extra_modules = sorted(payload.get("extra_modules", []))
    unresolved = sorted([tuple(item) for item in payload.get("unresolved_local_imports", [])])
    invalid = sorted([tuple(item) for item in payload.get("invalid_relative_imports", [])])
    missing_inits = sorted(payload.get("missing_package_inits", []))
    impacts_raw = payload.get("impacts", {})
    impacts = {key: sorted(value) for key, value in sorted(impacts_raw.items())}
    return {
        "missing_modules": missing_modules,
        "extra_modules": extra_modules,
        "unresolved_local_imports": unresolved,
        "invalid_relative_imports": invalid,
        "missing_package_inits": missing_inits,
        "impacts": impacts,
    }
