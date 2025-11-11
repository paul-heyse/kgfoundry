"""Authoritative typed models for documentation artifacts.

This module provides Pydantic V2-backed data structures and conversion helpers for all
documentation pipeline artifacts (symbol index, delta, reverse lookups). Models
serialize to payloads that validate against the canonical JSON Schemas under
`schema/docs/`.

The module owns the JSON contract and encapsulates all transformations, ensuring:

- Deterministic serialization (stable field order, sorted keys in JSON)
- Schema compliance (all payloads validate via jsonschema)
- Type safety (no Any-typed access in public functions)
- Defensive validation (field coercion, missing-key handling)
- Self-documenting schemas (generated from model definitions)

Examples
--------
**Canonical constructor usage (recommended):**

>>> import json
>>> from pathlib import Path
>>> from docs._types.artifacts import (
...     SymbolIndexRow,
...     SymbolIndexArtifacts,
...     symbol_index_to_payload,
...     symbol_index_from_json,
...     SYMBOL_INDEX_ROW_FIELDS,
...     align_schema_fields,
... )

Construct models with keyword arguments matching canonical schema field names:

>>> row = SymbolIndexRow(
...     path="pkg.mod.func",
...     canonical_path=None,
...     kind="function",
...     doc="A function module.",
...     module="pkg.mod",
...     package="pkg",
...     file="pkg/mod.py",
...     span=None,
...     signature="(x: int) -> str",
...     owner=None,
...     stability=None,
...     since=None,
...     deprecated_in=None,  # canonical snake_case field name
...     section=None,
...     tested_by=(),
...     source_link={},
...     is_async=False,
...     is_property=False,
... )
>>> artifacts = SymbolIndexArtifacts(
...     rows=(row,),
...     by_file={"pkg/mod.py": ("pkg.mod.func",)},
...     by_module={"pkg.mod": ("pkg.mod.func",)},
... )
>>> payload = symbol_index_to_payload(artifacts)
>>> assert isinstance(payload, list)
>>> restored = symbol_index_from_json(payload)
>>> assert restored.rows[0].path == "pkg.mod.func"

**Legacy payload migration with alignment helpers:**

When processing payloads from external sources, use `align_schema_fields` to
validate and normalize before constructing models:

>>> legacy_payload = {
...     "path": "pkg.func",
...     "kind": "function",
...     "doc": "A function",
...     "deprecated_in": "0.2.0",
...     "tested_by": [],
...     "source_link": {},
... }
>>> try:
...     normalized = align_schema_fields(
...         legacy_payload,
...         expected_fields=SYMBOL_INDEX_ROW_FIELDS,
...         artifact_id="symbol-index-row",
...     )
...     row = SymbolIndexRow(**normalized)  # type: ignore[arg-type]
... except Exception as e:
...     print(f"Validation error: {e}")

**Invalid payload rejection with Problem Details:**

Payloads with unknown fields trigger `ArtifactValidationError` with RFC 9457
Problem Details context:

>>> invalid_payload = {
...     "path": "pkg.func",
...     "kind": "function",
...     "doc": "A function",
...     "unknown_field": "invalid",
...     "tested_by": [],
...     "source_link": {},
... }
>>> try:
...     align_schema_fields(
...         invalid_payload,
...         expected_fields=SYMBOL_INDEX_ROW_FIELDS,
...         artifact_id="symbol-index-row",
...     )
... except Exception as e:
...     # Error includes remediation guidance and schema link
...     assert "unknown_field" in str(e)
"""

from __future__ import annotations

import json
from collections.abc import Mapping as MappingABC
from importlib import import_module
from typing import TYPE_CHECKING, NoReturn, cast

from kgfoundry_common.errors import (
    ArtifactDeserializationError,
    ArtifactSerializationError,
    ArtifactValidationError,
)

_alignment_module = import_module("docs._types.alignment")
SYMBOL_DELTA_CHANGE_FIELDS = _alignment_module.SYMBOL_DELTA_CHANGE_FIELDS
SYMBOL_DELTA_PAYLOAD_FIELDS = _alignment_module.SYMBOL_DELTA_PAYLOAD_FIELDS
SYMBOL_INDEX_ARTIFACTS_FIELDS = _alignment_module.SYMBOL_INDEX_ARTIFACTS_FIELDS
SYMBOL_INDEX_ROW_FIELDS = _alignment_module.SYMBOL_INDEX_ROW_FIELDS
align_schema_fields = _alignment_module.align_schema_fields
del _alignment_module

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
else:  # pragma: no cover - runtime import guarded
    _pydantic = import_module("pydantic")
    BaseModel = _pydantic.BaseModel
    ConfigDict = _pydantic.ConfigDict
    Field = _pydantic.Field
    ValidationError = _pydantic.ValidationError
    field_validator = _pydantic.field_validator

# Type aliases matching RFC 7159 JSON structure
type JsonPrimitive = str | int | float | bool | None

type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]

type JsonPayload = dict[str, JsonValue] | list[JsonValue]

__all__ = [
    "SYMBOL_DELTA_CHANGE_FIELDS",
    "SYMBOL_DELTA_PAYLOAD_FIELDS",
    "SYMBOL_INDEX_ARTIFACTS_FIELDS",
    "SYMBOL_INDEX_ROW_FIELDS",
    "ArtifactValidationError",
    "JsonPayload",
    "JsonPrimitive",
    "JsonValue",
    "LineSpan",
    "SymbolDeltaChange",
    "SymbolDeltaPayload",
    "SymbolIndexArtifacts",
    "SymbolIndexRow",
    "align_schema_fields",
    "dump_symbol_delta",
    "dump_symbol_index",
    "load_symbol_delta",
    "load_symbol_index",
    "symbol_delta_from_json",
    "symbol_delta_to_payload",
    "symbol_index_from_json",
    "symbol_index_to_payload",
]


class FrozenBaseModel(BaseModel):
    """Base class for immutable documentation artifacts."""

    model_config = ConfigDict(frozen=True)


class LineSpan(FrozenBaseModel):
    """Start/end line numbers for a symbol.

    Attributes
    ----------
    start : int | None
        Starting line number (1-indexed), or None if unknown.
    end : int | None
        Ending line number (1-indexed, inclusive), or None if unknown.

    Parameters
    ----------
    start : int | None
        Starting line number (1-indexed), or None if unknown.
    end : int | None
        Ending line number (1-indexed, inclusive), or None if unknown.
    """

    start: int | None = Field(None, ge=0, description="Start line (1-indexed)")
    end: int | None = Field(None, ge=0, description="End line (1-indexed, inclusive)")


class SymbolIndexRow(FrozenBaseModel):
    """A single symbol entry in the index.

    Each row represents one documented symbol (function, class, module, etc.) with
    metadata needed for search, deep linking, and reverse lookups.

    Attributes
    ----------
    path : str
        Fully qualified symbol path (e.g., "pkg.mod.ClassName.method_name").
    kind : str
        Symbol kind: "module", "class", "function", "method", etc.
    doc : str
        Documentation string/docstring for this symbol.
    tested_by : tuple[str, ...]
        Test paths (relative to tests/) that cover this symbol.
    source_link : dict[str, str]
        Links to source code (e.g., GitHub, local paths).
    canonical_path : str | None
        If this symbol is an alias, canonical_path points to the real definition.
    module : str | None
        Module containing this symbol (e.g., "pkg.mod").
    package : str | None
        Top-level package name (e.g., "pkg").
    file : str | None
        Relative path to source file (e.g., "pkg/mod.py").
    span : LineSpan | None
        Start/end line numbers in the source file.
    signature : str | None
        Function/method signature string (e.g., "(x: int) -> str").
    owner : str | None
        For methods: qualified path to the owner class.
    stability : str | None
        Stability tag (e.g., "stable", "experimental").
    since : str | None
        Version when first introduced (e.g., "0.1.0").
    deprecated_in : str | None
        Version when deprecated (e.g., "0.2.0").
    section : str | None
        Documentation section or category.
    is_async : bool
        True if this is an async function/method.
    is_property : bool
        True if this is a @property.

    Parameters
    ----------
    path : str
        Fully qualified symbol path (e.g., "pkg.mod.ClassName.method_name").
    kind : str
        Symbol kind: "module", "class", "function", "method", etc.
    doc : str
        Documentation string/docstring for this symbol.
    tested_by : tuple[str, ...]
        Test paths (relative to tests/) that cover this symbol.
    source_link : dict[str, str]
        Links to source code (e.g., GitHub, local paths).
    canonical_path : str | None, optional
        If this symbol is an alias, canonical_path points to the real definition.
        Defaults to None.
    module : str | None, optional
        Module containing this symbol (e.g., "pkg.mod").
        Defaults to None.
    package : str | None, optional
        Top-level package name (e.g., "pkg").
        Defaults to None.
    file : str | None, optional
        Relative path to source file (e.g., "pkg/mod.py").
        Defaults to None.
    span : LineSpan | None, optional
        Start/end line numbers in the source file.
        Defaults to None.
    signature : str | None, optional
        Function/method signature string (e.g., "(x: int) -> str").
        Defaults to None.
    owner : str | None, optional
        For methods: qualified path to the owner class.
        Defaults to None.
    stability : str | None, optional
        Stability tag (e.g., "stable", "experimental").
        Defaults to None.
    since : str | None, optional
        Version when first introduced (e.g., "0.1.0").
        Defaults to None.
    deprecated_in : str | None, optional
        Version when deprecated (e.g., "0.2.0").
        Defaults to None.
    section : str | None, optional
        Documentation section or category.
        Defaults to None.
    is_async : bool, optional
        True if this is an async function/method.
        Defaults to False.
    is_property : bool, optional
        True if this is a @property.
        Defaults to False.
    """

    path: str = Field(..., description="Fully qualified symbol path")
    kind: str = Field(..., description="Symbol kind (module, class, function, etc.)")
    doc: str = Field(..., description="Documentation/docstring for this symbol")
    tested_by: tuple[str, ...] = Field(
        default_factory=tuple, description="Test paths covering this symbol"
    )
    source_link: dict[str, str] = Field(
        default_factory=dict, description="Links to source code (GitHub, etc.)"
    )
    canonical_path: str | None = Field(None, description="Canonical path if this is an alias")
    module: str | None = Field(None, description="Module containing this symbol")
    package: str | None = Field(None, description="Top-level package name")
    file: str | None = Field(None, description="Relative path to source file")
    span: LineSpan | None = Field(None, description="Start/end line numbers")
    signature: str | None = Field(None, description="Function/method signature")
    owner: str | None = Field(None, description="Owner class (for methods)")
    stability: str | None = Field(None, description="Stability tag")
    since: str | None = Field(None, description="Version when introduced")
    deprecated_in: str | None = Field(None, description="Version when deprecated")
    section: str | None = Field(None, description="Documentation section")
    is_async: bool = Field(default=False, description="True if async function/method")
    is_property: bool = Field(default=False, description="True if @property")

    @field_validator("path", mode="before")
    @classmethod
    def path_not_empty(cls, v: object) -> str:
        """Ensure path is a non-empty string.

        Parameters
        ----------
        v : object
            Value to validate.

        Returns
        -------
        str
            Validated non-empty string.

        Raises
        ------
        ValueError
            If value is not a non-empty string.
        """
        if not isinstance(v, str) or not v.strip():
            error_msg = "path must be a non-empty string"
            raise ValueError(error_msg)
        return v

    @field_validator("kind", mode="before")
    @classmethod
    def kind_not_empty(cls, v: object) -> str:
        """Ensure kind is a non-empty string.

        Parameters
        ----------
        v : object
            Value to validate.

        Returns
        -------
        str
            Validated non-empty string.

        Raises
        ------
        ValueError
            If value is not a non-empty string.
        """
        if not isinstance(v, str) or not v.strip():
            error_msg = "kind must be a non-empty string"
            raise ValueError(error_msg)
        return v

    @field_validator("doc", mode="before")
    @classmethod
    def doc_not_empty(cls, v: object) -> str:
        """Ensure doc is a non-empty string.

        Parameters
        ----------
        v : object
            Value to validate.

        Returns
        -------
        str
            Validated non-empty string.

        Raises
        ------
        ValueError
            If value is not a non-empty string.
        """
        if not isinstance(v, str) or not v.strip():
            error_msg = "doc must be a non-empty string"
            raise ValueError(error_msg)
        return v

    @field_validator("tested_by", mode="before")
    @classmethod
    def coerce_tested_by(cls, v: object) -> tuple[str, ...]:
        """Coerce tested_by to tuple, defaulting to empty.

        Parameters
        ----------
        v : object
            Value to coerce.

        Returns
        -------
        tuple[str, ...]
            Coerced tuple of strings.
        """
        if v is None:
            return ()
        if isinstance(v, (list, tuple)):
            return tuple(str(item) for item in v)
        return ()

    @field_validator("source_link", mode="before")
    @classmethod
    def coerce_source_link(cls, v: object) -> dict[str, str]:
        """Coerce source_link to dict, defaulting to empty.

        Parameters
        ----------
        v : object
            Value to coerce.

        Returns
        -------
        dict[str, str]
            Coerced dictionary of string keys and values.
        """
        if v is None:
            return {}
        if isinstance(v, dict):
            return {str(k): str(val) for k, val in v.items()}
        return {}


class SymbolIndexArtifacts(FrozenBaseModel):
    """Complete symbol index payload with forward and reverse lookups.

    Attributes
    ----------
    rows : tuple[SymbolIndexRow, ...]
        All symbol entries, sorted by path.
    by_file : dict[str, tuple[str, ...]]
        Reverse lookup: file path -> sorted tuple of symbol paths.
    by_module : dict[str, tuple[str, ...]]
        Reverse lookup: module name -> sorted tuple of symbol paths.

    Parameters
    ----------
    rows : tuple[SymbolIndexRow, ...]
        All symbol entries, sorted by path.
    by_file : dict[str, tuple[str, ...]]
        Reverse lookup: file path -> sorted tuple of symbol paths.
    by_module : dict[str, tuple[str, ...]]
        Reverse lookup: module name -> sorted tuple of symbol paths.
    """

    rows: tuple[SymbolIndexRow, ...] = Field(
        default_factory=tuple, description="All symbol entries (sorted by path)"
    )
    by_file: dict[str, tuple[str, ...]] = Field(
        default_factory=dict, description="Reverse lookup: file -> symbol paths"
    )
    by_module: dict[str, tuple[str, ...]] = Field(
        default_factory=dict, description="Reverse lookup: module -> symbol paths"
    )

    @field_validator("rows", mode="before")
    @classmethod
    def coerce_rows(cls, v: object) -> tuple[SymbolIndexRow, ...]:
        """Coerce rows to tuple.

        Parameters
        ----------
        v : object
            Value to coerce.

        Returns
        -------
        tuple[SymbolIndexRow, ...]
            Coerced tuple of symbol index rows.
        """
        if v is None:
            return ()
        if isinstance(v, (list, tuple)):
            return tuple(v)
        return ()


class SymbolDeltaChange(FrozenBaseModel):
    """A single changed symbol between two versions.

    Attributes
    ----------
    path : str
        The symbol path that changed.
    before : dict[str, JsonValue]
        Previous version of the row (serialized).
    after : dict[str, JsonValue]
        New version of the row (serialized).
    reasons : tuple[str, ...]
        List of reasons why the symbol changed (e.g., ["signature_changed"]).

    Parameters
    ----------
    path : str
        The symbol path that changed.
    before : dict[str, JsonValue]
        Previous version of the row (serialized).
    after : dict[str, JsonValue]
        New version of the row (serialized).
    reasons : tuple[str, ...]
        List of reasons why the symbol changed (e.g., ["signature_changed"]).
    """

    path: str = Field(..., description="Symbol path that changed")
    before: dict[str, JsonValue] = Field(
        default_factory=dict, description="Previous row (serialized)"
    )
    after: dict[str, JsonValue] = Field(default_factory=dict, description="New row (serialized)")
    reasons: tuple[str, ...] = Field(default_factory=tuple, description="Reasons for the change")

    @field_validator("path", mode="before")
    @classmethod
    def path_not_empty(cls, v: object) -> str:
        """Ensure path is a non-empty string.

        Parameters
        ----------
        v : object
            Value to validate.

        Returns
        -------
        str
            Validated non-empty string.

        Raises
        ------
        ValueError
            If value is not a non-empty string.
        """
        if not isinstance(v, str) or not v.strip():
            error_msg = "path must be a non-empty string"
            raise ValueError(error_msg)
        return v

    @field_validator("reasons", mode="before")
    @classmethod
    def coerce_reasons(cls, v: object) -> tuple[str, ...]:
        """Coerce reasons to tuple.

        Parameters
        ----------
        v : object
            Value to coerce.

        Returns
        -------
        tuple[str, ...]
            Coerced tuple of strings.
        """
        if v is None:
            return ()
        if isinstance(v, (list, tuple)):
            return tuple(str(item) for item in v)
        return ()


class SymbolDeltaPayload(FrozenBaseModel):
    """Delta (diff) of symbols between two git commits or documentation builds.

    Attributes
    ----------
    base_sha : str | None
        Git SHA or build identifier for the baseline.
    head_sha : str | None
        Git SHA or build identifier for the current state.
    added : tuple[str, ...]
        Sorted tuple of newly added symbol paths.
    removed : tuple[str, ...]
        Sorted tuple of removed symbol paths.
    changed : tuple[SymbolDeltaChange, ...]
        List of symbols that changed (sorted by path).

    Parameters
    ----------
    base_sha : str | None
        Git SHA or build identifier for the baseline.
    head_sha : str | None
        Git SHA or build identifier for the current state.
    added : tuple[str, ...]
        Sorted tuple of newly added symbol paths.
    removed : tuple[str, ...]
        Sorted tuple of removed symbol paths.
    changed : tuple[SymbolDeltaChange, ...]
        List of symbols that changed (sorted by path).
    """

    base_sha: str | None = Field(None, description="Baseline git SHA or build ID")
    head_sha: str | None = Field(None, description="Current git SHA or build ID")
    added: tuple[str, ...] = Field(default_factory=tuple, description="Newly added symbol paths")
    removed: tuple[str, ...] = Field(default_factory=tuple, description="Removed symbol paths")
    changed: tuple[SymbolDeltaChange, ...] = Field(
        default_factory=tuple, description="Changed symbols"
    )

    @field_validator("added", mode="before")
    @classmethod
    def coerce_added(cls, v: object) -> tuple[str, ...]:
        """Coerce added to tuple.

        Parameters
        ----------
        v : object
            Value to coerce.

        Returns
        -------
        tuple[str, ...]
            Coerced tuple of strings.
        """
        if v is None:
            return ()
        if isinstance(v, (list, tuple)):
            return tuple(str(item) for item in v)
        return ()

    @field_validator("removed", mode="before")
    @classmethod
    def coerce_removed(cls, v: object) -> tuple[str, ...]:
        """Coerce removed to tuple.

        Parameters
        ----------
        v : object
            Value to coerce.

        Returns
        -------
        tuple[str, ...]
            Coerced tuple of strings.
        """
        if v is None:
            return ()
        if isinstance(v, (list, tuple)):
            return tuple(str(item) for item in v)
        return ()

    @field_validator("changed", mode="before")
    @classmethod
    def coerce_changed(cls, v: object) -> tuple[SymbolDeltaChange, ...]:
        """Coerce changed to tuple.

        Parameters
        ----------
        v : object
            Value to coerce.

        Returns
        -------
        tuple[SymbolDeltaChange, ...]
            Coerced tuple of symbol delta changes.
        """
        if v is None:
            return ()
        if isinstance(v, (list, tuple)):
            changes: list[SymbolDeltaChange] = []
            raw_entries = cast("list[object] | tuple[object, ...]", v)
            entries = tuple(raw_entries)
            for index, entry in enumerate(entries):
                coerced = _coerce_delta_change(entry, artifact="symbol-delta", index=index)
                changes.append(coerced)
            return tuple(changes)
        changed_field = "changed"
        _validation_error(
            changed_field,
            "a sequence of change mappings",
            artifact="symbol-delta",
        )
        return ()


def _validation_error(
    field: str,
    expected: str,
    *,
    artifact: str,
    row: int | None = None,
) -> NoReturn:
    """Raise ArtifactValidationError with formatted message.

    Parameters
    ----------
    field : str
        Field name for error messages.
    expected : str
        Expected value description.
    artifact : str
        Artifact name for error messages.
    row : int | None, optional
        Row number for error context.

    Raises
    ------
    ArtifactValidationError
        Always raised with formatted validation error message.
    """
    prefix = f"Row {row}: " if row is not None else ""
    message = f"{prefix}field '{field}' must be {expected}"
    raise ArtifactValidationError(
        message,
        context={"artifact": artifact, "field": field},
    )


def _coerce_optional_str(
    value: object,
    *,
    field: str,
    artifact: str,
    row: int | None = None,
) -> str | None:
    """Coerce value to optional string.

    Parameters
    ----------
    value : object
        Value to coerce.
    field : str
        Field name for error messages.
    artifact : str
        Artifact name for error messages.
    row : int | None, optional
        Row number for error context.

    Returns
    -------
    str | None
        Coerced string value or None.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    error_msg = f"{field} must be a string or null"
    if row is not None:
        error_msg = f"Row {row}: {error_msg}"
    _validation_error(field, "a string or null", artifact=artifact, row=row)


def _coerce_str_tuple(
    value: object,
    *,
    field: str,
    artifact: str,
    row: int | None = None,
) -> tuple[str, ...]:
    """Coerce value to tuple of strings.

    Parameters
    ----------
    value : object
        Value to coerce.
    field : str
        Field name for error messages.
    artifact : str
        Artifact name for error messages.
    row : int | None, optional
        Row number for error context.

    Returns
    -------
    tuple[str, ...]
        Coerced tuple of strings, sorted if input was a set.
    """
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        iterable = cast("list[object] | tuple[object, ...] | set[object]", value)
        for index, entry in enumerate(iterable):
            if isinstance(entry, str):
                items.append(entry)
                continue
            indexed_field = f"{field}[{index}]"
            _validation_error(indexed_field, "a string", artifact=artifact, row=row)
        if isinstance(value, set):
            return tuple(sorted(items))
        return tuple(items)
    _validation_error(field, "a sequence of strings", artifact=artifact, row=row)


def _coerce_str_mapping(
    value: object,
    *,
    field: str,
    artifact: str,
    row: int | None = None,
) -> dict[str, str]:
    """Coerce value to dictionary of string keys and values.

    Parameters
    ----------
    value : object
        Value to coerce.
    field : str
        Field name for error messages.
    artifact : str
        Artifact name for error messages.
    row : int | None, optional
        Row number for error context.

    Returns
    -------
    dict[str, str]
        Coerced dictionary, empty if value is None.
    """
    if value is None:
        return {}
    if isinstance(value, MappingABC):
        result: dict[str, str] = {}
        for key, val in value.items():
            if not isinstance(key, str):
                key_field = f"{field} key"
                _validation_error(key_field, "a string", artifact=artifact, row=row)
            if not isinstance(val, str):
                val_field = f"{field}['{key}']"
                _validation_error(val_field, "a string", artifact=artifact, row=row)
            result[key] = val
        return result
    _validation_error(
        field,
        "a mapping of string keys to string values",
        artifact=artifact,
        row=row,
    )


def _coerce_optional_int(
    value: object,
    *,
    field: str,
    artifact: str,
    row: int | None = None,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        _validation_error(field, "an integer", artifact=artifact, row=row)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    _validation_error(field, "an integer", artifact=artifact, row=row)


def _coerce_delta_change(
    entry: object,
    *,
    artifact: str,
    index: int,
) -> SymbolDeltaChange:
    """Coerce a single change entry into a SymbolDeltaChange instance.

    Parameters
    ----------
    entry : object
        Entry to coerce.
    artifact : str
        Artifact name for error messages.
    index : int
        Index of the entry in the sequence.

    Returns
    -------
    SymbolDeltaChange
        Coerced symbol delta change instance.
    """
    symbol_delta_cls: type[SymbolDeltaChange] = SymbolDeltaChange
    if isinstance(entry, symbol_delta_cls):
        return entry

    if isinstance(entry, MappingABC):
        mapping: dict[str, object] = {}
        for key, value in entry.items():
            if not isinstance(key, str):
                key_field = f"changed[{index}] key"
                _validation_error(key_field, "a string", artifact=artifact)
            mapping[key] = value

        validator = cast(
            "Callable[[dict[str, object]], SymbolDeltaChange]",
            symbol_delta_cls.model_validate,
        )

        try:
            return validator(mapping)
        except ValidationError:  # pragma: no cover - propagated with context
            indexed_field = f"changed[{index}]"
            _validation_error(
                indexed_field,
                "a valid symbol delta change",
                artifact=artifact,
            )

    indexed_field = f"changed[{index}]"
    _validation_error(
        indexed_field,
        "a mapping describing the change",
        artifact=artifact,
    )


def _coerce_delta_changes(value: object, *, artifact: str) -> tuple[SymbolDeltaChange, ...]:
    """Coerce value to tuple of SymbolDeltaChange.

    Parameters
    ----------
    value : object
        Value to coerce.
    artifact : str
        Artifact name for error messages.

    Returns
    -------
    tuple[SymbolDeltaChange, ...]
        Coerced tuple of symbol delta changes.
    """
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        changes: list[SymbolDeltaChange] = []
        raw_entries = cast("list[object] | tuple[object, ...]", value)
        entries = tuple(raw_entries)
        for index, entry in enumerate(entries):
            coerced = _coerce_delta_change(entry, artifact=artifact, index=index)
            changes.append(coerced)
        return tuple(changes)
    changed_field = "changed"
    _validation_error(
        changed_field,
        "a sequence of change mappings",
        artifact=artifact,
    )


def symbol_index_from_json(raw: JsonPayload) -> SymbolIndexArtifacts:
    """Construct a SymbolIndexArtifacts from a JSON payload with validation.

    Parameters
    ----------
    raw : JsonPayload
        Raw JSON payload (typically loaded via json.load or dict/list).

    Returns
    -------
    SymbolIndexArtifacts
        Validated typed artifact.

    Raises
    ------
    ArtifactDeserializationError
        If the payload structure is invalid or rows cannot be constructed.

    Examples
    --------
    >>> from docs._types.artifacts import symbol_index_from_json
    >>> payload = [
    ...     {
    ...         "path": "mod.func",
    ...         "canonical_path": None,
    ...         "kind": "function",
    ...         "doc": "A function.",
    ...         "module": "mod",
    ...         "package": "pkg",
    ...         "file": "mod.py",
    ...         "lineno": 10,
    ...         "endlineno": 20,
    ...         "signature": "(x: int) -> str",
    ...         "owner": None,
    ...         "stability": None,
    ...         "since": None,
    ...         "deprecated_in": None,
    ...         "section": None,
    ...         "tested_by": [],
    ...         "is_async": False,
    ...         "is_property": False,
    ...     }
    ... ]
    >>> artifacts = symbol_index_from_json(payload)
    >>> assert len(artifacts.rows) == 1
    """
    if not isinstance(raw, list):
        msg = f"Expected list of rows, got {type(raw).__name__}"
        raise ArtifactDeserializationError(
            msg,
            context={"artifact": "symbol-index", "expected": "list"},
        )

    rows: list[SymbolIndexRow] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            msg = f"Row {i}: expected dict, got {type(item).__name__}"
            raise ArtifactDeserializationError(
                msg,
                context={"artifact": "symbol-index", "row": i},
            )

        try:
            path_raw = item.get("path")
            path_field = "path"
            if not isinstance(path_raw, str):
                _validation_error(path_field, "a string", artifact="symbol-index", row=i)
            kind_raw = item.get("kind")
            kind_field = "kind"
            if not isinstance(kind_raw, str):
                _validation_error(kind_field, "a string", artifact="symbol-index", row=i)
            doc_raw = item.get("doc")
            doc_field = "doc"
            if not isinstance(doc_raw, str):
                _validation_error(doc_field, "a string", artifact="symbol-index", row=i)

            lineno = _coerce_optional_int(
                item.get("lineno"), field="lineno", artifact="symbol-index", row=i
            )
            endlineno = _coerce_optional_int(
                item.get("endlineno"), field="endlineno", artifact="symbol-index", row=i
            )
            span: LineSpan | None = None
            if lineno is not None or endlineno is not None:
                span = LineSpan(start=lineno, end=endlineno)

            row = SymbolIndexRow(
                path=path_raw,
                kind=kind_raw,
                doc=doc_raw,
                tested_by=_coerce_str_tuple(
                    item.get("tested_by"),
                    field="tested_by",
                    artifact="symbol-index",
                    row=i,
                ),
                source_link=_coerce_str_mapping(
                    item.get("source_link"),
                    field="source_link",
                    artifact="symbol-index",
                    row=i,
                ),
                canonical_path=_coerce_optional_str(
                    item.get("canonical_path"),
                    field="canonical_path",
                    artifact="symbol-index",
                    row=i,
                ),
                module=_coerce_optional_str(
                    item.get("module"), field="module", artifact="symbol-index", row=i
                ),
                package=_coerce_optional_str(
                    item.get("package"), field="package", artifact="symbol-index", row=i
                ),
                file=_coerce_optional_str(
                    item.get("file"), field="file", artifact="symbol-index", row=i
                ),
                span=span,
                signature=_coerce_optional_str(
                    item.get("signature"),
                    field="signature",
                    artifact="symbol-index",
                    row=i,
                ),
                owner=_coerce_optional_str(
                    item.get("owner"), field="owner", artifact="symbol-index", row=i
                ),
                stability=_coerce_optional_str(
                    item.get("stability"),
                    field="stability",
                    artifact="symbol-index",
                    row=i,
                ),
                since=_coerce_optional_str(
                    item.get("since"), field="since", artifact="symbol-index", row=i
                ),
                deprecated_in=_coerce_optional_str(
                    item.get("deprecated_in"),
                    field="deprecated_in",
                    artifact="symbol-index",
                    row=i,
                ),
                section=_coerce_optional_str(
                    item.get("section"), field="section", artifact="symbol-index", row=i
                ),
                is_async=bool(item.get("is_async", False)),
                is_property=bool(item.get("is_property", False)),
            )
            rows.append(row)
        except (KeyError, ValueError, TypeError) as e:
            msg = f"Row {i}: failed to construct SymbolIndexRow: {e}"
            raise ArtifactDeserializationError(
                msg,
                cause=e,
                context={"artifact": "symbol-index", "row": i},
            ) from e

    # Return artifacts with empty lookups (to be populated separately if needed)
    return SymbolIndexArtifacts(
        rows=cast("tuple[SymbolIndexRow, ...]", tuple(rows)),
        by_file=cast("dict[str, tuple[str, ...]]", {}),
        by_module=cast("dict[str, tuple[str, ...]]", {}),
    )


def symbol_index_to_payload(model: SymbolIndexArtifacts) -> list[dict[str, JsonValue]]:
    """Serialize SymbolIndexArtifacts to a JSON payload.

    Parameters
    ----------
    model : SymbolIndexArtifacts
        Typed artifact to serialize.

    Returns
    -------
    list[dict[str, JsonValue]]
        JSON payload ready for writing to disk or validation.

    Examples
    --------
    >>> from docs._types.artifacts import (
    ...     SymbolIndexRow,
    ...     SymbolIndexArtifacts,
    ...     symbol_index_to_payload,
    ... )
    >>> row = SymbolIndexRow(path="mod.func", kind="function", doc="A function.")
    >>> artifacts = SymbolIndexArtifacts(
    ...     rows=(row,),
    ...     by_file={},
    ...     by_module={},
    ... )
    >>> payload = symbol_index_to_payload(artifacts)
    >>> assert payload[0]["path"] == "mod.func"
    """
    result: list[dict[str, JsonValue]] = []
    for row in model.rows:
        entry: dict[str, JsonValue] = {
            "path": row.path,
            "canonical_path": row.canonical_path,
            "kind": row.kind,
            "doc": row.doc,
            "source_link": cast("JsonValue", row.source_link),
            "module": row.module,
            "package": row.package,
            "file": row.file,
            "signature": row.signature,
            "owner": row.owner,
            "stability": row.stability,
            "since": row.since,
            "deprecated_in": row.deprecated_in,
            "section": row.section,
            "tested_by": cast("JsonValue", list(row.tested_by)),
            "is_async": row.is_async,
            "is_property": row.is_property,
        }
        if row.span is not None:
            entry["lineno"] = row.span.start
            entry["endlineno"] = row.span.end
        result.append(entry)
    return result


def symbol_delta_from_json(raw: JsonPayload) -> SymbolDeltaPayload:
    """Construct a SymbolDeltaPayload from a JSON payload with validation.

    Parameters
    ----------
    raw : JsonPayload
        Raw JSON payload (typically loaded via json.load).

    Returns
    -------
    SymbolDeltaPayload
        Validated typed artifact.

    Raises
    ------
    ArtifactDeserializationError
        If the payload structure is invalid or construction fails.

    Examples
    --------
    >>> from docs._types.artifacts import symbol_delta_from_json
    >>> payload = {
    ...     "base_sha": "abc123",
    ...     "head_sha": "def456",
    ...     "added": ["new.symbol"],
    ...     "removed": [],
    ...     "changed": [],
    ... }
    >>> delta = symbol_delta_from_json(payload)
    >>> assert delta.base_sha == "abc123"
    """
    if not isinstance(raw, dict):
        msg = f"Expected dict, got {type(raw).__name__}"
        raise ArtifactDeserializationError(
            msg,
            context={"artifact": "symbol-delta", "expected": "dict"},
        )

    try:
        base_sha = _coerce_optional_str(
            raw.get("base_sha"), field="base_sha", artifact="symbol-delta"
        )
        head_sha = _coerce_optional_str(
            raw.get("head_sha"), field="head_sha", artifact="symbol-delta"
        )
        added = _coerce_str_tuple(raw.get("added"), field="added", artifact="symbol-delta")
        removed = _coerce_str_tuple(raw.get("removed"), field="removed", artifact="symbol-delta")
        changed = _coerce_delta_changes(raw.get("changed"), artifact="symbol-delta")
        return SymbolDeltaPayload(
            base_sha=base_sha,
            head_sha=head_sha,
            added=added,
            removed=removed,
            changed=changed,
        )
    except ArtifactDeserializationError:
        raise
    except (ValueError, TypeError) as e:
        msg = f"Failed to construct SymbolDeltaPayload: {e}"
        raise ArtifactDeserializationError(
            msg,
            cause=e,
            context={"artifact": "symbol-delta"},
        ) from e


def symbol_delta_to_payload(model: SymbolDeltaPayload) -> dict[str, JsonValue]:
    """Serialize SymbolDeltaPayload to a JSON payload.

    Parameters
    ----------
    model : SymbolDeltaPayload
        Typed artifact to serialize.

    Returns
    -------
    dict[str, JsonValue]
        JSON payload ready for writing to disk or validation.

    Examples
    --------
    >>> from docs._types.artifacts import (
    ...     SymbolDeltaChange,
    ...     SymbolDeltaPayload,
    ...     symbol_delta_to_payload,
    ... )
    >>> delta = SymbolDeltaPayload(
    ...     base_sha="abc123",
    ...     head_sha="def456",
    ... )
    >>> payload = symbol_delta_to_payload(delta)
    >>> assert payload["base_sha"] == "abc123"
    """
    changed_list = [
        {
            "path": change.path,
            "before": cast("JsonValue", change.before),
            "after": cast("JsonValue", change.after),
            "reasons": cast("JsonValue", list(change.reasons)),
        }
        for change in model.changed
    ]

    return {
        "base_sha": model.base_sha,
        "head_sha": model.head_sha,
        "added": cast("JsonValue", list(model.added)),
        "removed": cast("JsonValue", list(model.removed)),
        "changed": cast("JsonValue", changed_list),
    }


def load_symbol_index(path: Path) -> SymbolIndexArtifacts:
    """Load and validate a symbol index artifact from disk.

    Parameters
    ----------
    path : Path
        Path to the symbol index JSON file.

    Returns
    -------
    SymbolIndexArtifacts
        Validated typed artifact.

    Raises
    ------
    ArtifactDeserializationError
        If the file cannot be read or parsed.

    Examples
    --------
    >>> from pathlib import Path
    >>> from docs._types.artifacts import load_symbol_index
    >>> # artifacts = load_symbol_index(Path("docs/_build/symbols.json"))
    """
    try:
        payload = cast("JsonPayload", json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as e:
        msg = f"Failed to load {path}: {e}"
        raise ArtifactDeserializationError(
            msg,
            cause=e,
            context={"artifact": "symbol-index", "path": str(path)},
        ) from e

    return symbol_index_from_json(payload)


def dump_symbol_index(path: Path, model: SymbolIndexArtifacts) -> None:
    """Write a symbol index artifact to disk with deterministic formatting.

    Parameters
    ----------
    path : Path
        Destination file path.
    model : SymbolIndexArtifacts
        Artifact to write.

    Raises
    ------
    ArtifactSerializationError
        If the file cannot be written or serialization fails.

    Examples
    --------
    >>> from pathlib import Path
    >>> from docs._types.artifacts import (
    ...     SymbolIndexRow,
    ...     SymbolIndexArtifacts,
    ...     dump_symbol_index,
    ... )
    >>> row = SymbolIndexRow(path="mod.func", kind="function", doc="A function.")
    >>> artifacts = SymbolIndexArtifacts(rows=(row,))
    >>> # dump_symbol_index(Path("output.json"), artifacts)
    """
    try:
        payload = symbol_index_to_payload(model)
        json_str = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
        path.write_text(json_str + "\n", encoding="utf-8")
    except (OSError, TypeError) as e:
        msg = f"Failed to dump symbol index to {path}: {e}"
        raise ArtifactSerializationError(
            msg,
            cause=e,
            context={"artifact": "symbol-index", "path": str(path)},
        ) from e


def load_symbol_delta(path: Path) -> SymbolDeltaPayload:
    """Load and validate a symbol delta artifact from disk.

    Parameters
    ----------
    path : Path
        Path to the symbol delta JSON file.

    Returns
    -------
    SymbolDeltaPayload
        Validated typed artifact.

    Raises
    ------
    ArtifactDeserializationError
        If the file cannot be read or parsed.

    Examples
    --------
    >>> from pathlib import Path
    >>> from docs._types.artifacts import load_symbol_delta
    >>> # delta = load_symbol_delta(Path("docs/_build/symbols.delta.json"))
    """
    try:
        payload = cast("JsonPayload", json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as e:
        msg = f"Failed to load {path}: {e}"
        raise ArtifactDeserializationError(
            msg,
            cause=e,
            context={"artifact": "symbol-delta", "path": str(path)},
        ) from e

    return symbol_delta_from_json(payload)


def dump_symbol_delta(path: Path, model: SymbolDeltaPayload) -> None:
    """Write a symbol delta artifact to disk with deterministic formatting.

    Parameters
    ----------
    path : Path
        Destination file path.
    model : SymbolDeltaPayload
        Artifact to write.

    Raises
    ------
    ArtifactSerializationError
        If the file cannot be written or serialization fails.

    Examples
    --------
    >>> from pathlib import Path
    >>> from docs._types.artifacts import (
    ...     SymbolDeltaPayload,
    ...     dump_symbol_delta,
    ... )
    >>> delta = SymbolDeltaPayload(base_sha="abc123", head_sha="def456")
    >>> # dump_symbol_delta(Path("output.delta.json"), delta)
    """
    try:
        payload = symbol_delta_to_payload(model)
        json_str = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
        path.write_text(json_str + "\n", encoding="utf-8")
    except (OSError, TypeError) as e:
        msg = f"Failed to dump symbol delta to {path}: {e}"
        raise ArtifactSerializationError(
            msg,
            cause=e,
            context={"artifact": "symbol-delta", "path": str(path)},
        ) from e
