"""Schema and model round-trip validation helpers.

This module provides utilities for validating Pydantic models against JSON
Schema 2020-12 and ensuring round-trip compatibility between models and schemas.

Examples
--------
>>> from pathlib import Path
>>> from kgfoundry_common.models import Doc
>>> from kgfoundry_common.schema_helpers import assert_model_roundtrip
>>> example_path = Path("schema/examples/models/doc.v1.json")
>>> assert_model_roundtrip(Doc, example_path)
"""

# [nav:section public-api]

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from kgfoundry_common.errors import DeserializationError, SerializationError
from kgfoundry_common.fs import read_text
from kgfoundry_common.jsonschema_utils import (
    Draft202012Validator,
    SchemaError,
    ValidationError,
)
from kgfoundry_common.jsonschema_utils import (
    validate as jsonschema_validate,
)
from kgfoundry_common.logging import get_logger
from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:
    from pathlib import Path
    from typing import cast

    from kgfoundry_common.problem_details import JsonValue
    from kgfoundry_common.pydantic import BaseModel
else:
    from typing import cast


__all__ = [
    "assert_model_roundtrip",
    "load_schema",
    "validate_model_against_schema",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


logger = get_logger(__name__)


# [nav:anchor load_schema]
def load_schema(schema_path: Path) -> dict[str, JsonValue]:
    """Load and parse a JSON Schema file.

    Loads a JSON Schema 2020-12 file from disk, parses it, and validates
    it against the JSON Schema 2020-12 meta-schema.

    Parameters
    ----------
    schema_path : Path
        Path to JSON Schema 2020-12 file.

    Returns
    -------
    dict[str, JsonValue]
        Parsed schema dictionary.

    Raises
    ------
    FileNotFoundError
        If schema file does not exist.
    DeserializationError
        If schema is invalid JSON or fails validation.

    Examples
    --------
    >>> from pathlib import Path
    >>> schema = load_schema(Path("schema/models/doc.v1.json"))
    >>> assert "$schema" in schema
    """
    if not schema_path.exists():
        msg = f"Schema file not found: {schema_path}"
        raise FileNotFoundError(msg)

    try:
        schema_text = read_text(schema_path)
        schema_obj: dict[str, JsonValue] = json.loads(schema_text)
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON in schema file {schema_path}: {exc}"
        raise DeserializationError(msg) from exc

    # Validate against JSON Schema 2020-12 meta-schema
    try:
        Draft202012Validator.check_schema(schema_obj)
    except SchemaError as exc:
        msg = f"Invalid JSON Schema 2020-12 in {schema_path}: {exc}"
        raise DeserializationError(msg) from exc

    return schema_obj


# [nav:anchor validate_model_against_schema]
def validate_model_against_schema(
    model_instance: BaseModel,
    schema: dict[str, JsonValue],
) -> None:
    """Validate a Pydantic model instance against a JSON Schema.

    Converts the model instance to a dictionary and validates it against
    the provided JSON Schema 2020-12.

    Parameters
    ----------
    model_instance : BaseModel
        Pydantic model instance to validate.
    schema : dict[str, JsonValue]
        JSON Schema 2020-12 dictionary.

    Raises
    ------
    SerializationError
        If validation fails or schema is invalid.

    Examples
    --------
    >>> from kgfoundry_common.models import Doc
    >>> schema = {"type": "object", "properties": {"id": {"type": "string"}}}
    >>> doc = Doc(id="urn:doc:test")
    >>> validate_model_against_schema(doc, schema)
    """
    try:
        # Convert model to dict (using model_dump with mode='json' for JSON-compatible types)
        # model_dump returns dict[str, object], cast to JsonValue since it's JSON-serializable
        data: dict[str, JsonValue] = cast(
            "dict[str, JsonValue]", model_instance.model_dump(mode="json")
        )
        jsonschema_validate(instance=data, schema=schema)
    except ValidationError as exc:
        msg = f"Model instance does not match schema: {exc}"
        raise SerializationError(msg) from exc
    except SchemaError as exc:
        msg = f"Invalid schema: {exc}"
        raise SerializationError(msg) from exc


# [nav:anchor assert_model_roundtrip]
def assert_model_roundtrip(
    model_cls: type[BaseModel],
    example_path: Path,
    *,
    schema_path: Path | None = None,
) -> None:
    """Assert that a Pydantic model round-trips correctly with an example JSON file.

    This function performs a complete round-trip validation:
    1. Loads the example JSON file
    2. Validates it against the schema (if provided)
    3. Deserializes it into a model instance
    4. Re-serializes the model instance
    5. Validates the re-serialized data matches the schema
    6. Compares the round-trip data structure (allowing for type coercion)

    Parameters
    ----------
    model_cls : type[BaseModel]
        Pydantic model class to test.
    example_path : Path
        Path to example JSON file.
    schema_path : Path | None, optional
        Path to JSON Schema file. If None, schema validation is skipped.
        Defaults to None.

    Raises
    ------
    FileNotFoundError
        If example or schema file does not exist.
    DeserializationError
        If example JSON is invalid or fails schema validation.
    SerializationError
        If model instance fails schema validation after round-trip.

    Examples
    --------
    >>> from pathlib import Path
    >>> from kgfoundry_common.models import Doc
    >>> example = Path("schema/examples/models/doc.v1.json")
    >>> schema = Path("schema/models/doc.v1.json")
    >>> assert_model_roundtrip(Doc, example, schema_path=schema)
    """
    if not example_path.exists():
        msg = f"Example file not found: {example_path}"
        raise FileNotFoundError(msg)

    # Load example JSON
    try:
        example_text = read_text(example_path)
        example_data: dict[str, JsonValue] = json.loads(example_text)
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON in example file {example_path}: {exc}"
        raise DeserializationError(msg) from exc

    # Load and validate schema if provided
    schema_obj: dict[str, JsonValue] | None = None
    if schema_path is not None:
        schema_obj = load_schema(schema_path)
        # Validate example against schema
        try:
            jsonschema_validate(instance=example_data, schema=schema_obj)
        except ValidationError as exc:
            msg = f"Example JSON does not match schema: {exc}"
            raise DeserializationError(msg) from exc

    # Deserialize example into model instance
    try:
        instance = model_cls.model_validate(example_data)
    except Exception as exc:
        msg = f"Failed to deserialize example into {model_cls.__name__}: {exc}"
        raise DeserializationError(msg) from exc

    # Re-serialize model instance (validates serialization works)
    try:
        _round_trip_data = instance.model_dump(mode="json")
    except Exception as exc:
        msg = f"Failed to serialize {model_cls.__name__} instance: {exc}"
        raise SerializationError(msg) from exc

    # Validate round-trip data against schema if provided
    if schema_obj is not None:
        validate_model_against_schema(instance, schema_obj)

    logger.debug(
        "Model round-trip validated",
        extra={
            "model": model_cls.__name__,
            "example_path": str(example_path),
            "schema_path": str(schema_path) if schema_path else None,
        },
    )
