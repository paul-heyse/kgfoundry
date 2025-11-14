# SPDX-License-Identifier: MIT
"""Dataclasses and helpers shared across enrichment stages."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, MutableMapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from codeintel_rev.enrich.errors import StageError

__all__ = ["ModuleRecord"]


def _clone_dict(values: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow dict copy safe for JSON serialization.

    Parameters
    ----------
    values : dict[str, Any]
        Dictionary to clone. The returned copy is a shallow copy, meaning nested
        dictionaries and lists are not recursively copied.

    Returns
    -------
    dict[str, Any]
        Shallow copy of ``values`` preserving the original structure.
    """
    return dict(values)


def _dedupe_strings(values: Iterable[object]) -> list[str]:
    """Return a list of unique stringified values preserving order.

    Parameters
    ----------
    values : Iterable[object]
        Iterable of values to deduplicate. Each value is converted to a string
        using ``str()`` before comparison. The first occurrence of each unique
        string is preserved.

    Returns
    -------
    list[str]
        Deduplicated sequence maintaining the first occurrence order.
    """
    seen: list[str] = []
    for token in values:
        token_str = str(token)
        if token_str not in seen:
            seen.append(token_str)
    return seen


@dataclass(slots=True, frozen=True)
class ModuleRecord(MutableMapping[str, Any]):
    """Canonical per-module row emitted to ``modules.jsonl``."""

    path: str
    repo_path: str = ""
    module_name: str | None = None
    stable_id: str = ""
    docstring: str | None = None
    doc_has_summary: bool = False
    doc_param_parity: bool = True
    doc_examples_present: bool = False
    imports: list[dict[str, Any]] = field(default_factory=list)
    defs: list[dict[str, Any]] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    exports_declared: list[str] = field(default_factory=list)
    outline_nodes: list[dict[str, Any]] = field(default_factory=list)
    scip_symbols: list[str] = field(default_factory=list)
    parse_ok: bool = True
    errors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    type_errors: int = 0
    type_error_count: int = 0
    doc_summary: str | None = None
    doc_metrics: dict[str, Any] = field(default_factory=dict)
    doc_items: list[dict[str, Any]] = field(default_factory=list)
    annotation_ratio: dict[str, Any] = field(default_factory=dict)
    untyped_defs: int = 0
    side_effects: dict[str, Any] = field(default_factory=dict)
    raises: list[str] = field(default_factory=list)
    complexity: dict[str, Any] = field(default_factory=dict)
    covered_lines_ratio: float = 0.0
    covered_defs_ratio: float = 0.0
    config_refs: list[str] = field(default_factory=list)
    overlay_needed: bool = False
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    _FIELD_ORDER: ClassVar[tuple[str, ...]] = (
        "path",
        "repo_path",
        "module_name",
        "stable_id",
        "docstring",
        "doc_has_summary",
        "doc_param_parity",
        "doc_examples_present",
        "imports",
        "defs",
        "exports",
        "exports_declared",
        "outline_nodes",
        "scip_symbols",
        "parse_ok",
        "errors",
        "tags",
        "type_errors",
        "type_error_count",
        "doc_summary",
        "doc_metrics",
        "doc_items",
        "annotation_ratio",
        "untyped_defs",
        "side_effects",
        "raises",
        "complexity",
        "covered_lines_ratio",
        "covered_defs_ratio",
        "config_refs",
        "overlay_needed",
    )

    def __getitem__(self, key: str) -> object:
        """Return the stored value for ``key``.

        Parameters
        ----------
        key : str
            Field name to retrieve. If the key is in the canonical field order,
            returns the dataclass field value. Otherwise, returns the value from
            the extra fields dictionary.

        Returns
        -------
        object
            Value associated with ``key``.
        """
        if key in self._FIELD_ORDER:
            return getattr(self, key)
        return self._extra[key]

    def __setitem__(self, key: str, value: object) -> None:
        """Update ``key`` with ``value`` in either the dataclass field or extras."""
        if key in self._FIELD_ORDER:
            setattr(self, key, value)
            return
        self._extra[key] = value

    def __delitem__(self, key: str) -> None:
        """Remove an extra field entry.

        Parameters
        ----------
        key : str
            Field name to delete. If the key is in the canonical field order,
            deletion is not allowed and a KeyError is raised. Otherwise, the
            key is removed from the extra fields dictionary.

        Raises
        ------
        KeyError
            Raised when attempting to delete a required dataclass field.
        """
        if key in self._FIELD_ORDER:
            message = f"Cannot delete required field '{key}' from ModuleRecord."
            raise KeyError(message)
        del self._extra[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate over base field names followed by dynamic extras.

        Yields
        ------
        str
            Field names exposed by the record.
        """
        yield from self._FIELD_ORDER
        yield from self._extra

    def __len__(self) -> int:
        """Return the number of exposed keys.

        Returns
        -------
        int
            Count of base fields plus extra keys.
        """
        return len(self._FIELD_ORDER) + len(self._extra)

    def add_error(self, error: StageError | str) -> None:
        """Append a structured error token and flag ``parse_ok`` as False."""
        token = error.token() if isinstance(error, StageError) else str(error)
        if not token:
            return
        errors = list(self.errors)
        errors.append(token)
        self.set_fields(errors=errors, parse_ok=False)

    def set_fields(self, **changes: object) -> None:
        """Update record fields via ``object.__setattr__`` for frozen safety."""
        for key, value in changes.items():
            if key in self._FIELD_ORDER:
                object.__setattr__(self, key, value)  # noqa: PLC2801
            else:
                self._extra[key] = value

    def as_json_row(self) -> dict[str, Any]:
        """Return a JSON-friendly dictionary for downstream writers.

        Returns
        -------
        dict[str, Any]
            Serializable representation of the module record.
        """
        row = {field_name: self._serialize_field(field_name) for field_name in self._FIELD_ORDER}
        row.update(self._extra)
        return row

    def _serialize_field(self, field_name: str) -> object:
        """Serialize a single dataclass field into JSON-friendly primitives.

        Parameters
        ----------
        field_name : str
            Name of the dataclass field to serialize. Must be one of the fields
            defined in the ModuleRecord dataclass.

        Returns
        -------
        object
            Serialized representation of ``field_name``. Complex types (lists,
            dicts) are cloned to ensure JSON serializability. String sequences
            are sorted and deduplicated.
        """
        value = getattr(self, field_name)
        serialized: object = value
        if field_name in {"imports", "defs", "outline_nodes", "doc_items"}:
            cloned: list[object] = []
            for entry in value:
                if isinstance(entry, dict):
                    cloned.append(_clone_dict(entry))
                else:
                    cloned.append(entry)
            serialized = cloned
        elif field_name in {"doc_metrics", "annotation_ratio", "side_effects", "complexity"}:
            serialized = _clone_dict(dict(value))
        elif field_name in {"exports", "exports_declared", "raises"}:
            serialized = sorted(str(item) for item in value)
        elif field_name == "scip_symbols":
            serialized = sorted(set(value))
        elif field_name in {"errors", "tags", "config_refs"}:
            deduped = _dedupe_strings(value)
            serialized = sorted(deduped) if field_name == "tags" else deduped
        elif field_name == "type_error_count" and not value:
            serialized = int(self.type_errors)
        return serialized
