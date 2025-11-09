"""Shared schema helpers for tooling payload validation and emission.

This module centralises JSON Schema lookups for tooling artefacts. It exposes
helpers for resolving schema paths under ``schema/tools`` and validating payloads
using the canonical utilities in :mod:`kgfoundry_common.serialization`.

Phase 4 introduces generation utilities so msgspec-based models can emit
schema documents directly. Each schema write persists metadata alongside the
JSON Schema (checksum, version, timestamp) enabling drift detection without
parsing the schema itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import msgspec
from msgspec import json as msgspec_json

from kgfoundry_common.errors import SchemaValidationError
from kgfoundry_common.serialization import validate_payload

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schema" / "tools"

__all__ = [
    "SchemaContext",
    "SchemaMetadata",
    "get_schema_path",
    "render_schema",
    "validate_struct_payload",
    "validate_tools_payload",
    "write_schema",
]

_SCHEMA_CACHE: dict[str, Path] = {}


@dataclass(frozen=True, slots=True)
class SchemaMetadata:
    """Metadata persisted next to generated schemas."""

    schema: str
    version: str | None
    checksum: str
    generated_at: datetime

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation of the metadata.

        Returns
        -------
        dict[str, object]
            Dictionary representation of metadata.
        """
        return {
            "schema": self.schema,
            "version": self.version,
            "checksum": self.checksum,
            "generated_at": self.generated_at.isoformat(timespec="seconds"),
        }


@dataclass(frozen=True, slots=True)
class SchemaContext:
    """Optional context fields used when emitting schemas."""

    name: str | None = None
    schema_id: str | None = None
    version: str | None = None


def get_schema_path(name: str) -> Path:
    """Return the absolute path for a tooling schema.

    Parameters
    ----------
    name : str
        Basename of the schema file under ``schema/tools``.

    Returns
    -------
    Path
        Absolute path to the schema file.

    Raises
    ------
    FileNotFoundError
        If the schema file is missing.
    """
    candidate = SCHEMA_ROOT / name
    if not candidate.exists():
        msg = f"Tooling schema not found: {candidate}"
        raise FileNotFoundError(msg)
    cached = _SCHEMA_CACHE.get(name)
    if cached is not None:
        return cached
    _SCHEMA_CACHE[name] = candidate
    return candidate


def validate_tools_payload(payload: Mapping[str, object], schema_name: str) -> None:
    """Validate ``payload`` against a tooling schema.

    Parameters
    ----------
    payload : Mapping[str, object]
        Payload to validate.
    schema_name : str
        Schema file basename under ``schema/tools``.

    Notes
    -----
    This function calls ``validate_payload`` from ``kgfoundry_common.serialization``
    which may raise validation errors.
    """
    schema_path = get_schema_path(schema_name)
    validate_payload(payload, schema_path)


def validate_struct_payload(payload: Mapping[str, object], model: type[msgspec.Struct]) -> None:
    """Validate ``payload`` against a msgspec struct ``model``.

    Parameters
    ----------
    payload : Mapping[str, object]
        Payload to validate.
    model : type[msgspec.Struct]
        msgspec Struct class to validate against.

    Raises
    ------
    SchemaValidationError
        If validation fails.
    """
    try:
        msgspec.convert(payload, model)
    except (msgspec.ValidationError, msgspec.DecodeError, TypeError, ValueError) as exc:
        msg = f"Payload does not conform to {model.__name__}"
        raise SchemaValidationError(msg) from exc


def render_schema(
    model: type[msgspec.Struct],
    *,
    name: str | None = None,
    schema_id: str | None = None,
) -> dict[str, object]:
    """Return a JSON Schema (draft 2020-12) for ``model``.

    Parameters
    ----------
    model : type[msgspec.Struct]
        msgspec Struct class to generate schema for.
    name : str | None, optional
        Optional schema title.
    schema_id : str | None, optional
        Optional schema $id field.

    Returns
    -------
    dict[str, object]
        JSON Schema document.

    Raises
    ------
    RuntimeError
        If msgspec JSON schema extras are not available.
    """
    schema_fn = cast(
        "Callable[[type[msgspec.Struct]], dict[str, object]] | None",
        getattr(msgspec_json, "schema", None),
    )
    if schema_fn is None:  # pragma: no cover - defensive guard for optional dependency
        msg = "msgspec>=0.19 with the optional JSON schema extras is required"
        raise RuntimeError(msg)
    schema = schema_fn(model)
    if "$schema" not in schema:
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    if schema_id is not None:
        schema["$id"] = schema_id
    if name is not None:
        schema.setdefault("title", name)
    return schema


def _ensure_metadata_path(destination: Path, metadata_path: Path | None) -> Path:
    if metadata_path is not None:
        return metadata_path
    return destination.with_suffix(destination.suffix + ".metadata.json")


def _write_json(destination: Path, payload: Mapping[str, object]) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    destination.write_text(text + "\n", encoding="utf-8")
    return text


def write_schema(
    model: type[msgspec.Struct],
    destination: Path,
    *,
    context: SchemaContext | None = None,
    metadata_path: Path | None = None,
) -> SchemaMetadata:
    """Render ``model`` as JSON Schema and persist alongside metadata.

    Parameters
    ----------
    model : type[msgspec.Struct]
        msgspec Struct class to generate schema for.
    destination : Path
        Output path for the schema file.
    context : SchemaContext | None, optional
        Optional context fields. Default is None.
    metadata_path : Path | None, optional
        Optional metadata file path. Default is None.

    Returns
    -------
    SchemaMetadata
        Generated metadata.
    """
    ctx = context or SchemaContext()
    schema = render_schema(model, name=ctx.name, schema_id=ctx.schema_id)
    text = _write_json(destination, schema)
    checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
    metadata = SchemaMetadata(
        schema=destination.name,
        version=ctx.version,
        checksum=checksum,
        generated_at=datetime.now(tz=UTC),
    )
    metadata_file = _ensure_metadata_path(destination, metadata_path)
    _write_json(metadata_file, metadata.to_dict())
    return metadata
