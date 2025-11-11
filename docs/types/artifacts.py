"""Typed re-exports for :mod:`docs._types.artifacts`."""

from __future__ import annotations

from importlib import import_module

_alignment = import_module("docs._types.alignment")
_artifacts = import_module("docs._types.artifacts")

SYMBOL_DELTA_CHANGE_FIELDS = _alignment.SYMBOL_DELTA_CHANGE_FIELDS
SYMBOL_DELTA_PAYLOAD_FIELDS = _alignment.SYMBOL_DELTA_PAYLOAD_FIELDS
SYMBOL_INDEX_ARTIFACTS_FIELDS = _alignment.SYMBOL_INDEX_ARTIFACTS_FIELDS
SYMBOL_INDEX_ROW_FIELDS = _alignment.SYMBOL_INDEX_ROW_FIELDS
align_schema_fields = _alignment.align_schema_fields

ArtifactValidationError = _artifacts.ArtifactValidationError
JsonPayload = _artifacts.JsonPayload
JsonPrimitive = _artifacts.JsonPrimitive
JsonValue = _artifacts.JsonValue
LineSpan = _artifacts.LineSpan
SymbolDeltaChange = _artifacts.SymbolDeltaChange
SymbolDeltaPayload = _artifacts.SymbolDeltaPayload
SymbolIndexArtifacts = _artifacts.SymbolIndexArtifacts
SymbolIndexRow = _artifacts.SymbolIndexRow
dump_symbol_delta = _artifacts.dump_symbol_delta
dump_symbol_index = _artifacts.dump_symbol_index
load_symbol_delta = _artifacts.load_symbol_delta
load_symbol_index = _artifacts.load_symbol_index
symbol_delta_from_json = _artifacts.symbol_delta_from_json
symbol_delta_to_payload = _artifacts.symbol_delta_to_payload
symbol_index_from_json = _artifacts.symbol_index_from_json
symbol_index_to_payload = _artifacts.symbol_index_to_payload

del _alignment, _artifacts

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
