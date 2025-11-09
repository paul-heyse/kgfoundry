"""Safe serialization helpers with schema validation and checksums.

This module provides JSON serialization with schema validation and SHA256
checksums to replace unsafe `pickle` usage. All serialized data is validated
against JSON Schema 2020-12 before persistence.

Examples
--------
>>> from pathlib import Path
>>> from kgfoundry_common.serialization import serialize_json, deserialize_json
>>> data = {"k1": 0.9, "b": 0.4, "N": 100}
>>> schema_path = Path("schema/bm25_metadata.v1.json")
>>> output_path = Path("/tmp/index.json")
>>> checksum = serialize_json(data, schema_path, output_path)
>>> loaded = deserialize_json(output_path, schema_path)
>>> assert loaded == data
"""

# [nav:section public-api]

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from kgfoundry_common.errors import (
    DeserializationError,
    SchemaValidationError,
    SerializationError,
)
from kgfoundry_common.fs import atomic_write, read_text, write_text
from kgfoundry_common.jsonschema_utils import (
    SchemaError,
    ValidationError,
)
from kgfoundry_common.jsonschema_utils import (
    validate as jsonschema_validate,
)
from kgfoundry_common.logging import get_logger
from kgfoundry_common.navmap_loader import load_nav_metadata

# JSON Schema type (from jsonschema stubs: Mapping[str, object])
JsonSchema = Mapping[str, object]

__all__ = [
    "compute_checksum",
    "deserialize_json",
    "serialize_json",
    "validate_payload",
    "verify_checksum",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


logger = get_logger(__name__)

# Schema cache: module-level dict mapping schema paths (as strings) to parsed schema objects
_schema_cache: dict[str, dict[str, object]] = {}


def _load_schema_by_path_str_impl(schema_path_str: str) -> dict[str, object]:
    """Load and parse a JSON Schema file with caching by string path.

    This internal helper caches by string path to avoid lru_cache descriptor
    typing issues with Path objects. Public API converts Path to string.

    Parameters
    ----------
    schema_path_str : str
        Path to JSON Schema 2020-12 file (as string).

    Returns
    -------
    dict[str, object]
        Parsed schema dictionary.

    Raises
    ------
    FileNotFoundError
        If schema file does not exist.
    SchemaValidationError
        If schema is invalid JSON or fails schema validation.
    """
    schema_path = Path(schema_path_str)
    if not schema_path.exists():
        msg = f"Schema file not found: {schema_path}"
        raise FileNotFoundError(msg)
    schema_text = read_text(schema_path)
    try:
        schema_raw: object = json.loads(schema_text)
        if not isinstance(schema_raw, dict):
            msg = (
                f"Schema must be a JSON object at root, got {type(schema_raw).__name__}"
            )
            raise SchemaValidationError(msg)
        schema_obj = cast("dict[str, object]", schema_raw)
    except json.JSONDecodeError as e:
        msg = f"Failed to load schema from {schema_path_str}: {e}"
        raise SchemaValidationError(msg) from e
    else:
        return schema_obj


def _load_schema_cached(schema_path: Path) -> dict[str, object]:
    """Load and parse a JSON Schema file with caching.

    Uses an in-memory cache keyed by resolved path to avoid repeated I/O
    for the same schema file. The cache persists for the lifetime of the
    module.

    Parameters
    ----------
    schema_path : Path
        Path to JSON Schema 2020-12 file. Must exist and be readable.

    Returns
    -------
    dict[str, object]
        Parsed schema dictionary ready for validation.

    Raises
    ------
    FileNotFoundError
        If schema file does not exist.
    SchemaValidationError
        If schema is invalid JSON or fails schema validation.
    """
    if not schema_path.exists():
        msg = f"Schema file not found: {schema_path}"
        raise FileNotFoundError(msg)

    schema_key = str(schema_path.resolve())
    cached = _schema_cache.get(schema_key)
    if cached is not None:
        return cached

    try:
        schema_obj = _load_schema_by_path_str_impl(schema_key)
    except SchemaValidationError as exc:
        msg = f"Failed to load schema {schema_path}: {exc}"
        raise SchemaValidationError(msg) from exc
    _schema_cache[schema_key] = schema_obj
    return schema_obj


# [nav:anchor validate_payload]
def validate_payload(payload: Mapping[str, object], schema_path: Path) -> None:
    """Validate a payload against a JSON Schema 2020-12.

    Loads the schema (with caching), validates the payload against it, and
    raises SchemaValidationError if validation fails. Used for validating
    JSON-serializable data structures before persistence.

    Parameters
    ----------
    payload : Mapping[str, object]
        Payload to validate. Must be JSON-serializable and conform to the
        schema structure (dict, list, or primitive types).
    schema_path : Path
        Path to JSON Schema 2020-12 file. Must exist and be readable.

    Raises
    ------
    FileNotFoundError
        If schema file does not exist.
    SchemaValidationError
        If payload does not match schema constraints or if the schema
        itself is invalid.

    Examples
    --------
    >>> from pathlib import Path
    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as tmpdir:
    ...     tmp = Path(tmpdir)
    ...     schema = tmp / "schema.json"
    ...     schema.write_text('{"type": "object", "properties": {"k1": {"type": "number"}}}')
    ...     validate_payload({"k1": 0.9}, schema)
    ...     validate_payload({"k1": "invalid"}, schema)  # doctest: +SKIP
    SchemaValidationError: Schema validation failed
    """
    if not schema_path.exists():
        msg = f"Schema file not found: {schema_path}"
        raise FileNotFoundError(msg)

    schema_obj = _load_schema_cached(schema_path)
    try:
        jsonschema_validate(instance=payload, schema=schema_obj)
    except ValidationError as exc:
        msg = f"Schema validation failed: {exc}"
        raise SchemaValidationError(msg) from exc
    except SchemaError as exc:
        msg = f"Invalid schema: {exc}"
        raise SchemaValidationError(msg) from exc


# [nav:anchor compute_checksum]
def compute_checksum(data: bytes) -> str:
    """Compute SHA256 checksum of binary data.

    Computes the SHA256 hash of the input bytes and returns it as a
    hexadecimal string. Used for data integrity verification.

    Parameters
    ----------
    data : bytes
        Binary data to checksum.

    Returns
    -------
    str
        Hexadecimal SHA256 checksum (64 characters, lowercase).

    Examples
    --------
    >>> checksum = compute_checksum(b"test data")
    >>> len(checksum) == 64
    True
    >>> checksum.startswith("9")
    True
    """
    return hashlib.sha256(data).hexdigest()


# [nav:anchor verify_checksum]
def verify_checksum(data: bytes, expected: str) -> None:
    """Verify SHA256 checksum matches expected value.

    Computes the SHA256 checksum of the data and compares it to the expected
    value. Raises an exception if they do not match.

    Parameters
    ----------
    data : bytes
        Binary data to verify.
    expected : str
        Expected hexadecimal SHA256 checksum (64 characters).

    Raises
    ------
    SerializationError
        If computed checksum does not match expected value. The error message
        includes truncated checksums for debugging.

    Examples
    --------
    >>> verify_checksum(b"test", compute_checksum(b"test"))
    >>> verify_checksum(b"wrong", compute_checksum(b"test"))  # doctest: +SKIP
    SerializationError: Checksum mismatch
    """
    actual = compute_checksum(data)
    if actual != expected:
        msg = f"Checksum mismatch: expected {expected[:16]}..., got {actual[:16]}..."
        raise SerializationError(msg)


# [nav:anchor serialize_json]
def serialize_json(
    obj: object,  # JSON-serializable: dict, list, str, int, float, bool, None
    schema_path: Path,
    output_path: Path,
    *,
    include_checksum: bool = True,
    indent: int | None = 2,
) -> str:
    """Serialize object to JSON with schema validation and optional checksum.

    Serializes a Python object to JSON format, validates it against the
    provided JSON Schema 2020-12, and optionally writes a SHA256 checksum
    file alongside the JSON output. Uses atomic writes to prevent corruption.

    Parameters
    ----------
    obj : object
        Python object to serialize. Must be JSON-serializable (dict, list,
        str, int, float, bool, None, or nested combinations).
    schema_path : Path
        Path to JSON Schema 2020-12 file for validation. Must exist.
    output_path : Path
        Output file path for JSON data. Parent directory must exist or be
        creatable.
    include_checksum : bool, optional
        If True, write a `.sha256` checksum file alongside the JSON file.
        Defaults to True.
    indent : int | None, optional
        JSON indentation level. Use None for compact (minified) output.
        Defaults to 2.

    Returns
    -------
    str
        SHA256 checksum of the serialized JSON (hexadecimal, 64 characters).
        Returns the checksum even if include_checksum=False.

    Raises
    ------
    SerializationError
        If JSON serialization fails or file write fails.
    SchemaValidationError
        If the object does not conform to the schema.
    FileNotFoundError
        If schema file does not exist.

    Examples
    --------
    >>> from pathlib import Path
    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as tmpdir:
    ...     tmp = Path(tmpdir)
    ...     schema = tmp / "schema.json"
    ...     schema.write_text('{"type": "object", "properties": {"k1": {"type": "number"}}}')
    ...     data = {"k1": 0.9}
    ...     output = tmp / "data.json"
    ...     checksum = serialize_json(data, schema, output)
    ...     assert len(checksum) == 64
    ...     assert output.exists()
    """
    if not schema_path.exists():
        msg = f"Schema file not found: {schema_path}"
        raise FileNotFoundError(msg)

    try:
        if isinstance(obj, Mapping):
            validate_payload(obj, schema_path)
        else:
            schema_obj = _load_schema_cached(schema_path)
            try:
                jsonschema_validate(instance=obj, schema=schema_obj)
            except ValidationError as exc:
                msg = f"Schema validation failed: {exc}"
                raise SchemaValidationError(msg) from exc
    except SchemaValidationError as exc:
        msg = f"Schema validation failed for payload written to {output_path}: {exc}"
        raise SchemaValidationError(msg) from exc

    try:
        json_text: str = json.dumps(obj, indent=indent, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        msg = f"Failed to serialize object to JSON: {exc}"
        raise SerializationError(msg) from exc

    json_bytes = json_text.encode("utf-8")
    checksum = compute_checksum(json_bytes)

    try:
        atomic_write(output_path, json_text, mode="text")
    except OSError as exc:
        msg = f"Failed to write JSON output to {output_path}: {exc}"
        raise SerializationError(msg) from exc

    if include_checksum:
        checksum_path = output_path.with_suffix(output_path.suffix + ".sha256")
        try:
            write_text(checksum_path, checksum)
        except OSError as exc:
            msg = f"Failed to write checksum file {checksum_path}: {exc}"
            raise SerializationError(msg) from exc

    logger.debug(
        "Serialized JSON",
        extra={
            "output_path": str(output_path),
            "schema_path": str(schema_path),
            "checksum": checksum,
        },
    )

    return checksum


def _verify_checksum_file(data_path: Path) -> None:
    """Verify data against checksum file if it exists.

    Parameters
    ----------
    data_path : Path
        Path to JSON file.

    Raises
    ------
    DeserializationError
        If checksum verification fails.
    """
    checksum_path = data_path.with_suffix(data_path.suffix + ".sha256")
    if not checksum_path.exists():
        logger.warning(
            "Checksum file not found, skipping verification",
            extra={"data_path": str(data_path), "checksum_path": str(checksum_path)},
        )
        return

    expected_checksum = read_text(checksum_path).strip()
    data_bytes = data_path.read_bytes()
    try:
        verify_checksum(data_bytes, expected_checksum)
    except SerializationError as exc:
        msg = f"Checksum verification failed for {data_path}"
        raise DeserializationError(msg) from exc


def _validate_json_against_schema(obj: object, schema_path: Path) -> None:
    """Validate JSON object against schema.

    Parameters
    ----------
    obj : object
        Parsed JSON object.
    schema_path : Path
        Path to JSON Schema 2020-12 file.

    Raises
    ------
    SchemaValidationError
        If validation fails.
    FileNotFoundError
        If schema file does not exist.
    """
    if not schema_path.exists():
        msg = f"Schema file not found: {schema_path}"
        raise FileNotFoundError(msg)

    if isinstance(obj, Mapping):
        validate_payload(obj, schema_path)
        return

    schema_obj = _load_schema_cached(schema_path)
    try:
        jsonschema_validate(instance=obj, schema=schema_obj)
    except ValidationError as exc:
        msg = f"Schema validation failed: {exc}"
        raise SchemaValidationError(msg) from exc
    except SchemaError as exc:
        msg = f"Invalid schema: {exc}"
        raise SchemaValidationError(msg) from exc


def _load_data_file(data_path: Path) -> str:
    """Load data file as text.

    Parameters
    ----------
    data_path : Path
        Path to JSON file.

    Returns
    -------
    str
        File contents as text.

    Raises
    ------
    FileNotFoundError
        If data file does not exist.
    """
    if not data_path.exists():
        msg = f"Data file not found: {data_path}"
        raise FileNotFoundError(msg)
    return read_text(data_path)


# [nav:anchor deserialize_json]
def deserialize_json(
    data_path: Path,
    schema_path: Path,
    *,
    verify_checksum_file: bool = True,
) -> object:  # JSON types: dict, list, str, int, float, bool, None
    """Deserialize JSON with schema validation and checksum verification.

    Loads a JSON file, optionally verifies its SHA256 checksum against a
    `.sha256` file, validates the parsed object against the provided schema,
    and returns the deserialized Python object.

    Parameters
    ----------
    data_path : Path
        Path to JSON file to deserialize. Must exist and be readable.
    schema_path : Path
        Path to JSON Schema 2020-12 file for validation. Must exist.
    verify_checksum_file : bool, optional
        If True, verify against `.sha256` checksum file (if present).
        If the checksum file is missing, logs a warning but continues.
        Defaults to True.

    Returns
    -------
    object
        Deserialized Python object (JSON-serializable types: dict, list, str,
        int, float, bool, None, or nested combinations).

    Raises
    ------
    DeserializationError
        If JSON parsing fails, checksum verification fails, or file read fails.
    SchemaValidationError
        If the parsed object does not conform to the schema.
    FileNotFoundError
        If data or schema file does not exist.

    Examples
    --------
    >>> from pathlib import Path
    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as tmpdir:
    ...     tmp = Path(tmpdir)
    ...     schema = tmp / "schema.json"
    ...     schema.write_text('{"type": "object", "properties": {"k1": {"type": "number"}}}')
    ...     data_path = tmp / "data.json"
    ...     data_path.write_text('{"k1": 0.9}')
    ...     loaded = deserialize_json(data_path, schema)
    ...     assert loaded == {"k1": 0.9}
    """
    if not data_path.exists():
        msg = f"Data file not found: {data_path}"
        raise FileNotFoundError(msg)
    if not schema_path.exists():
        msg = f"Schema file not found: {schema_path}"
        raise FileNotFoundError(msg)

    if verify_checksum_file:
        _verify_checksum_file(data_path)

    json_text = _load_data_file(data_path)
    try:
        obj: object = json.loads(json_text)
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON in {data_path}: {exc}"
        raise DeserializationError(msg) from exc

    try:
        _validate_json_against_schema(obj, schema_path)
    except SchemaValidationError as exc:
        msg = f"Schema validation failed for {data_path} against {schema_path}: {exc}"
        raise SchemaValidationError(msg) from exc

    logger.debug(
        "Deserialized JSON",
        extra={
            "data_path": str(data_path),
            "schema_path": str(schema_path),
        },
    )

    return obj
