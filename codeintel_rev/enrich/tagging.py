# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TagResult:
    path: str
    tags: set[str]
    reasons: dict[str, str] = field(default_factory=dict)


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
    if not path:
        return _DEFAULT_RULES
    p = Path(path)
    if not p.exists():
        return _DEFAULT_RULES
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or _DEFAULT_RULES
    except Exception:
        return _DEFAULT_RULES


def infer_tags(
    path: str,
    imported_modules: list[str],
    has_all: bool,
    is_reexport_hub: bool,
    type_error_count: int = 0,
    rules: dict[str, Any] | None = None,
) -> TagResult:
    rules = rules or _DEFAULT_RULES
    tags: set[str] = set()
    reasons: dict[str, str] = {}
    # Helper sets
    impset = set(imported_modules)
    for tag, rule in rules.items():
        ok = False
        if rule.get("any_import"):
            ok = any(m in impset for m in rule["any_import"])
        if not ok and rule.get("path_regex"):
            ok = re.search(rule["path_regex"], path) is not None
        if not ok and rule.get("has_all"):
            ok = bool(has_all)
        if not ok and rule.get("is_reexport_hub"):
            ok = bool(is_reexport_hub)
        if not ok and (rule.get("type_errors_gt") is not None):
            try:
                ok = type_error_count > int(rule["type_errors_gt"])
            except Exception:
                ok = False
        if ok:
            tags.add(tag)
            if rule.get("reason"):
                reasons[tag] = rule["reason"]
    return TagResult(path=path, tags=tags, reasons=reasons)
