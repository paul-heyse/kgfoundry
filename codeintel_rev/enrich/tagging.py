# SPDX-License-Identifier: MIT
"""Rule-based tagging helpers for enrichment outputs."""

from __future__ import annotations

import re
from collections.abc import Mapping
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
    fan_in: int = 0
    fan_out: int = 0
    hotspot_score: float = 0.0
    covered_lines_ratio: float = 1.0
    doc_has_summary: bool = True
    doc_param_parity: bool = True


_DEFAULT_RULES = {
    "cli": {"any_import": ["typer", "click"], "reason": "uses CLI framework"},
    "fastapi": {"any_import": ["fastapi"], "reason": "FastAPI surface"},
    "pydantic": {"any_import": ["pydantic", "pydantic_settings"], "reason": "Pydantic models"},
    "prefect": {"any_import": ["prefect"], "reason": "Prefect flows"},
    "tests": {"path_regex": r"(^|/)tests(/|$)", "reason": "test module"},
    "reexport-hub": {"is_reexport_hub": True, "reason": "has star import or large __all__"},
    "public-api": {"has_all": True, "reason": "__all__ defines public API"},
    "needs-types": {"type_errors_gt": 0, "reason": "type checker reported errors"},
    "hotspot": {"hotspot_ge": 6, "reason": "high hotspot score"},
    "low-coverage": {"coverage_lt": 0.65, "reason": "coverage below target"},
    "docs-missing": {"doc_summary_required": True, "reason": "doc summary missing or stale"},
}


def load_rules(path: str | None) -> dict[str, Any]:
    """Load tagging rules from ``path`` or fall back to the defaults.

    Parameters
    ----------
    path : str | None
        File system path to a YAML file containing tagging rules. When None
        or when the file does not exist, returns the default rules dictionary.

    Returns
    -------
    dict[str, Any]
        Rules dictionary for tag inference. Keys are tag names, values are
        rule dictionaries containing matching criteria (imports, path regex,
        traits, etc.).
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
    rules: Mapping[str, Any] | None = None,
) -> TagResult:
    """Infer tags based on module metadata.

    Parameters
    ----------
    path : str
        File system path of the module being tagged. Used for path-based
        matching rules (e.g., test detection via regex).
    traits : ModuleTraits
        Module traits (imported modules, ``__all__`` presence, re-export
        status, type error count) used for rule matching.
    rules : Mapping[str, Any] | None, optional
        Tagging rules dictionary. When None, uses the default rules.
        Each rule maps a tag name to matching criteria (imports, path regex,
        trait checks, etc.). Defaults to None.

    Returns
    -------
    TagResult
        Inferred tags and associated reasons. Contains the module path,
        set of matched tags, and a dictionary mapping tags to their
        matching reasons.
    """
    rules = rules or _DEFAULT_RULES
    tags: set[str] = set()
    reasons: dict[str, str] = {}
    for tag, rule in rules.items():
        if _rule_matches(rule, path, traits):
            tags.add(tag)
            reason = rule.get("reason")
            if isinstance(reason, str):
                reasons[tag] = reason
    return TagResult(path=path, tags=tags, reasons=reasons)


def _rule_matches(rule: Mapping[str, Any], path: str, traits: ModuleTraits) -> bool:
    impset = set(traits.imported_modules)
    conditions: list[bool] = []

    imports_rule = rule.get("any_import")
    if isinstance(imports_rule, list):
        conditions.append(any(isinstance(m, str) and m in impset for m in imports_rule))

    pattern = rule.get("path_regex")
    if isinstance(pattern, str):
        conditions.append(re.search(pattern, path) is not None)

    conditions.append(bool(rule.get("has_all")) and traits.has_all)
    conditions.append(bool(rule.get("is_reexport_hub")) and traits.is_reexport_hub)

    threshold = rule.get("type_errors_gt")
    if isinstance(threshold, int):
        conditions.append(traits.type_error_count > threshold)

    fan_in_ge = rule.get("fan_in_ge")
    if isinstance(fan_in_ge, int):
        conditions.append(traits.fan_in >= fan_in_ge)

    fan_out_ge = rule.get("fan_out_ge")
    if isinstance(fan_out_ge, int):
        conditions.append(traits.fan_out >= fan_out_ge)

    hotspot_ge = rule.get("hotspot_ge")
    if isinstance(hotspot_ge, (int, float)):
        conditions.append(traits.hotspot_score >= float(hotspot_ge))

    coverage_lt = rule.get("coverage_lt")
    if isinstance(coverage_lt, (int, float)):
        conditions.append(traits.covered_lines_ratio < float(coverage_lt))

    if bool(rule.get("doc_summary_required")):
        conditions.append(not traits.doc_has_summary)

    if bool(rule.get("doc_param_parity_required")):
        conditions.append(not traits.doc_param_parity)

    return any(conditions)
