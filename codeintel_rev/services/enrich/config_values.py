"""Helpers for building normalized config value datasets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.services.enrich.analytics import ConfigReferenceState

FORMAT_BY_SUFFIX: dict[str, str] = {
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".ini": "ini",
    ".cfg": "ini",
    ".env": "env",
}
EXPECTED_SUFFIX_PARTS = 2


def _guess_format(path: str) -> str:
    suffix = path.lower().rsplit(".", maxsplit=1)
    if len(suffix) == EXPECTED_SUFFIX_PARTS:
        candidate = f".{suffix[1]}"
        return FORMAT_BY_SUFFIX.get(candidate, "other")
    return "other"


def _module_by_path(
    module_rows: Sequence[ModuleRecord | Mapping[str, Any]],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in module_rows:
        path = row.path if isinstance(row, ModuleRecord) else row.get("path")
        module_name = (
            row.module_name
            if isinstance(row, ModuleRecord)
            else row.get("module_name") or row.get("module")
        )
        if isinstance(path, str):
            mapping[path] = module_name if isinstance(module_name, str) else path
    return mapping


def build_config_value_rows(
    state: ConfigReferenceState,
    module_rows: Sequence[ModuleRecord | Mapping[str, Any]],
) -> list[dict[str, object]]:
    """Flatten config records into per-key rows with reference metadata.

    Parameters
    ----------
    state : ConfigReferenceState
        Prepared config reference state containing records and reference index.
    module_rows : Sequence[ModuleRecord | Mapping[str, Any]]
        Module rows used to derive module names for reference paths.

    Returns
    -------
    list[dict[str, object]]
        Normalized rows ready for Parquet/JSONL export.
    """
    module_lookup = _module_by_path(module_rows)
    rows: list[dict[str, object]] = []

    for record in state.records:
        config_path = record.get("path") if isinstance(record, Mapping) else None
        if not isinstance(config_path, str):
            continue
        record_keys = record.get("keys") or []
        format_hint = record.get("format")
        resolved_format = (
            format_hint
            if isinstance(format_hint, str) and format_hint
            else _guess_format(config_path)
        )

        for key in record_keys:
            if not isinstance(key, str):
                continue
            ref_paths = state.references.get(config_path, set())
            recorded_refs = {
                str(path) for path in record.get("references") or [] if isinstance(path, str)
            }
            sorted_paths = sorted(set(ref_paths).union(recorded_refs))
            reference_modules = sorted(
                {module_lookup[path] for path in sorted_paths if path in module_lookup}
            )
            rows.append(
                {
                    "config_path": config_path,
                    "format": resolved_format,
                    "key": key,
                    "reference_paths": sorted_paths,
                    "reference_modules": reference_modules,
                    "reference_count": len(sorted_paths),
                }
            )

    return rows


__all__ = ["build_config_value_rows"]
