# SPDX-License-Identifier: MIT
"""Rule-based tagging helpers for enrichment outputs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class TagResult:
    """Result of running :func:`infer_tags`."""

    path: str
    tags: set[str]
    reasons: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ModuleTraits:
    """Traits derived from a module used for tagging."""

    imported_modules: list[str]
    has_all: bool
    is_reexport_hub: bool
    type_error_count: int = 0


_DEFAULT_RULES = {
    "cli": {"any_import": ["typer", "click"], "reason": "uses CLI framework"},
    "fastapi": {"any_import": ["fastapi"], "reason": "FastAPI surface"},
    "pydantic": {"any_import": ["pydantic", "pydantic_settings"], "reason": "Pydantic models"},
    "prefect": {"any_import": ["prefect"], "reason": "Prefect flows"},
    "tests": {"path_regex": r"(^|/)tests(/|$)", "reason": "test module"},
    "reexport-hub": {"is_reexport_hub": True, "reason": "has star import or large __all__"},
    "public-api": {"has_all": True, "reason": "__all__ defines public API"},
    "needs-types": {"type_errors_gt": 0, "reason": "type checker reported errors"},
}


def load_rules(path: str | None) -> dict[str, Any]:
    """Load tagging rules from ``path`` or fall back to the defaults.

    Returns
    -------
    dict[str, Any]
        Rules dictionary for tag inference.
    """
    if not path:
        return _DEFAULT_RULES
    location = Path(path)
    if not location.exists():
        return _DEFAULT_RULES
    try:
        loaded = yaml.safe_load(location.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return _DEFAULT_RULES
    if isinstance(loaded, dict):
        return loaded
    return _DEFAULT_RULES


def infer_tags(
    path: str,
    traits: ModuleTraits,
    rules: dict[str, Any] | None = None,
) -> TagResult:
    """Infer tags based on module metadata.

    Returns
    -------
    TagResult
        Inferred tags and associated reasons.
    """
    rules = rules or _DEFAULT_RULES
    tags: set[str] = set()
    reasons: dict[str, str] = {}
    impset = set(traits.imported_modules)
    for tag, rule in rules.items():
        ok = False
        imports_rule = rule.get("any_import")
        if isinstance(imports_rule, list):
            ok = any(isinstance(m, str) and m in impset for m in imports_rule)
        pattern = rule.get("path_regex")
        if not ok and isinstance(pattern, str):
            ok = re.search(pattern, path) is not None
        if not ok and bool(rule.get("has_all")):
            ok = traits.has_all
        if not ok and bool(rule.get("is_reexport_hub")):
            ok = traits.is_reexport_hub
        threshold = rule.get("type_errors_gt")
        if not ok and isinstance(threshold, int):
            ok = traits.type_error_count > threshold
        if ok:
            tags.add(tag)
            reason = rule.get("reason")
            if isinstance(reason, str):
                reasons[tag] = reason
    return TagResult(path=path, tags=tags, reasons=reasons)
