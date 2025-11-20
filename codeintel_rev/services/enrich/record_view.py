# SPDX-License-Identifier: MIT
"""Typed helpers for reading module record data safely."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from codeintel_rev.enrich.models import ModuleRecord


@dataclass(frozen=True, slots=True)
class ModuleRecordView:
    """Typed projection of a module record."""

    path: str
    module: str
    tags: list[str]
    loc: int
    meta: dict[str, object]


def as_record_view(record: ModuleRecord | Mapping[str, object]) -> ModuleRecordView:
    """Return a typed view over a module record or mapping.

    Returns
    -------
    ModuleRecordView
        Normalized path/module/tags/loc/meta fields.
    """
    if isinstance(record, ModuleRecord):
        module_name = record.module_name or record.repo_path or record.path
        tags = list(record.tags)
        loc = record.loc
        meta_map = record.meta
        return ModuleRecordView(
            path=record.path,
            module=module_name,
            tags=tags,
            loc=loc,
            meta=meta_map,
        )
    mapping = cast("Mapping[str, object]", record)
    path = str(mapping.get("path", ""))
    module_name = str(mapping.get("module_name") or mapping.get("module") or path)
    tags_raw = mapping.get("tags")
    tags_iterable = tags_raw if isinstance(tags_raw, (list, tuple, set)) else []
    tags = [str(tag) for tag in tags_iterable if isinstance(tag, (str, int, float))]

    complexity_obj = mapping.get("complexity")
    complexity_map = complexity_obj if isinstance(complexity_obj, Mapping) else {}
    loc_raw = mapping.get("loc", complexity_map.get("loc", 0))
    loc = int(loc_raw) if isinstance(loc_raw, (int, float)) else 0

    meta_raw = mapping.get("meta")
    meta = dict(meta_raw) if isinstance(meta_raw, Mapping) else {}
    return ModuleRecordView(path=path, module=module_name, tags=tags, loc=loc, meta=meta)


__all__ = ["ModuleRecordView", "as_record_view"]
