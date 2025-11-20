"""Helpers for building normalized config value datasets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from codeintel_rev.enrich.models import ModuleRecord

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
    records: Sequence[Mapping[str, Any]],
    module_rows: Sequence[ModuleRecord | Mapping[str, Any]],
    *,
    reference_index: Mapping[str, Iterable[str]] | None = None,
) -> list[dict[str, object]]:
    """Flatten config records into per-key rows with reference metadata.

    Parameters
    ----------
    records : Sequence[Mapping[str, Any]]
        Config records produced by the config indexer and augmentation steps.
        Each record should include ``path`` and ``keys`` fields, and may
        optionally include ``references`` (list of code paths).
    module_rows : Sequence[ModuleRecord | Mapping[str, Any]]
        Module rows used to derive module names for reference paths.
    reference_index : Mapping[str, Iterable[str]] | None, optional
        Optional override mapping from config key to referencing paths. When
        provided, it is used in preference to ``record['references']``.

    Returns
    -------
    list[dict[str, object]]
        Normalized rows ready for Parquet/JSONL export.
    """
    module_lookup = _module_by_path(module_rows)
    rows: list[dict[str, object]] = []

    for record in records:
        config_path = record.get("path")
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
            reference_paths: set[str] = set()
            if reference_index is not None:
                reference_paths.update(str(path) for path in reference_index.get(key, ()))
            recorded_refs = record.get("references") or []
            reference_paths.update(str(path) for path in recorded_refs if isinstance(path, str))
            sorted_paths = sorted(reference_paths)
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
