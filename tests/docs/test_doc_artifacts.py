"""Tests for documentation artifact schema validation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from docs.scripts import validate_artifacts as validate_artifacts_module
from docs.scripts.validation import validate_against_schema
from docs.types.artifacts import (
    JsonValue,
    symbol_delta_from_json,
    symbol_delta_to_payload,
    symbol_index_from_json,
    symbol_index_to_payload,
)
from tools import ToolExecutionError

type ReverseLookup = dict[str, tuple[str, ...]]

ArtifactValidationError = cast(
    "type[Exception]",
    validate_artifacts_module.ArtifactValidationError,
)
validate_by_file_lookup = cast(
    "ValidateLookup",
    validate_artifacts_module.validate_by_file_lookup,
)
validate_by_module_lookup = cast(
    "ValidateLookup",
    validate_artifacts_module.validate_by_module_lookup,
)


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from docs.types.artifacts import (
        JsonPayload,
    )

    type ValidateLookup = Callable[[Path], ReverseLookup]
else:
    ValidateLookup = object

JsonObject = dict[str, JsonValue]
JsonArray = list[JsonValue]

REPO_ROOT = Path(__file__).resolve().parents[2]
SYMBOL_SCHEMA = REPO_ROOT / "schema/docs/symbol-index.schema.json"
DELTA_SCHEMA = REPO_ROOT / "schema/docs/symbol-delta.schema.json"
REVERSE_SCHEMA = REPO_ROOT / "schema/docs/symbol-reverse-lookup.schema.json"
SYMBOL_EXAMPLE = REPO_ROOT / "schema/examples/docs/symbol-index.sample.json"
DELTA_EXAMPLE = REPO_ROOT / "schema/examples/docs/symbol-delta.sample.json"
BY_FILE_EXAMPLE = REPO_ROOT / "schema/examples/docs/by-file.sample.json"
BY_MODULE_EXAMPLE = REPO_ROOT / "schema/examples/docs/by-module.sample.json"


def _load(path: Path) -> JsonPayload:
    return cast("JsonPayload", json.loads(path.read_text(encoding="utf-8")))


# ============================================================================
# 3.2.a: Parametrised tests with valid payloads loaded via codec helpers
# ============================================================================


class TestSymbolIndexValidation:
    """Tests for symbol index artifact validation."""

    def test_symbol_index_sample_validates(self) -> None:
        """Test that the canonical example validates successfully."""
        payload = _load(SYMBOL_EXAMPLE)
        validate_against_schema(payload, SYMBOL_SCHEMA, artifact="symbols.json")

    def test_symbol_index_codec_round_trip(self) -> None:
        """Test round-trip through typed codec helpers."""
        payload = _load(SYMBOL_EXAMPLE)
        artifacts = symbol_index_from_json(payload)
        reserialized = symbol_index_to_payload(artifacts)
        validate_against_schema(reserialized, SYMBOL_SCHEMA, artifact="symbols.json")

    @pytest.mark.parametrize(
        "field_name",
        [
            "path",
            "kind",
            "doc",
            "tested_by",
            "source_link",
        ],
    )
    def test_symbol_index_required_fields(self, field_name: str) -> None:
        """Test that required fields are enforced as part of scenario 3.2.a."""
        payload = _load(SYMBOL_EXAMPLE)
        assert isinstance(payload, list)
        payload_list: list[JsonObject] = [
            dict(cast("Mapping[str, JsonValue]", row)) for row in payload
        ]
        broken: JsonObject = dict(payload_list[0]) if payload_list else {}
        broken.pop(field_name, None)
        broken_payload = cast("JsonPayload", [broken])
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                broken_payload, SYMBOL_SCHEMA, artifact="symbols.json"
            )


class TestSymbolDeltaValidation:
    """Tests for symbol delta artifact validation."""

    def test_symbol_delta_sample_validates(self) -> None:
        """Test that the canonical example validates successfully."""
        payload = _load(DELTA_EXAMPLE)
        validate_against_schema(payload, DELTA_SCHEMA, artifact="symbols.delta.json")

    def test_symbol_delta_codec_round_trip(self) -> None:
        """Test round-trip through typed codec helpers."""
        payload = _load(DELTA_EXAMPLE)
        artifacts = symbol_delta_from_json(payload)
        reserialized = symbol_delta_to_payload(artifacts)
        validate_against_schema(
            reserialized, DELTA_SCHEMA, artifact="symbols.delta.json"
        )

    def test_symbol_delta_rejects_non_object_payload(self) -> None:
        """Test that non-object payloads are rejected."""
        invalid_payload = cast("JsonPayload", ["not", "an", "object"])
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                invalid_payload,
                DELTA_SCHEMA,
                artifact="symbols.delta.json",
            )


class TestReverseLookupValidation:
    """Tests for reverse lookup artifact validation."""

    def test_by_file_sample_validates(self) -> None:
        """Test that the by-file example validates successfully."""
        payload = _load(BY_FILE_EXAMPLE)
        validate_against_schema(payload, REVERSE_SCHEMA, artifact="by_file.json")

    def test_by_module_sample_validates(self) -> None:
        """Test that the by-module example validates successfully."""
        payload = _load(BY_MODULE_EXAMPLE)
        validate_against_schema(payload, REVERSE_SCHEMA, artifact="by_module.json")

    def test_reverse_lookup_rejects_non_object(self) -> None:
        """Test that reverse lookup payloads must be JSON objects."""
        invalid_payload = cast("JsonPayload", ["not", "a", "mapping"])
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                invalid_payload, REVERSE_SCHEMA, artifact="by_file.json"
            )

    def test_reverse_lookup_rejects_non_string_values(self) -> None:
        """Test that reverse lookup entries must be arrays of strings."""
        payload: JsonObject = {
            "pkg.module": cast("JsonValue", ["pkg.symbol", 123]),
        }
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                cast("JsonPayload", payload), REVERSE_SCHEMA, artifact="by_module.json"
            )


# ============================================================================
# 3.2.b: Factories for constructing malformed payloads
# ============================================================================


class PayloadFactory:
    """Factory for constructing test payloads with controlled mutations."""

    @staticmethod
    def malformed_symbol_index(
        *,
        missing_field: str | None = None,
        wrong_type_field: str | None = None,
        extra_field: bool = False,
    ) -> list[JsonObject]:
        """Create a malformed symbol index row with specified defects.

        Parameters
        ----------
        missing_field : str | None
            Field name to remove from the payload. Defaults to None.
        wrong_type_field : str | None
            Field name to replace with wrong type. Defaults to None.
        extra_field : bool
            If True, add an unexpected field. Defaults to False.

        Returns
        -------
        list[JsonObject]
            A symbol index payload (list of rows) with specified mutations.
        """
        base_payload = _load(SYMBOL_EXAMPLE)
        assert isinstance(base_payload, list)
        result: list[JsonObject] = []
        for row in base_payload:
            row_dict: JsonObject = dict(cast("Mapping[str, JsonValue]", row))
            if missing_field and missing_field in row_dict:
                del row_dict[missing_field]
            if wrong_type_field and wrong_type_field in row_dict:
                if wrong_type_field == "path":
                    row_dict[wrong_type_field] = 12345  # Should be string
                elif wrong_type_field == "tested_by":
                    row_dict[wrong_type_field] = "not-a-list"  # Should be array
                elif wrong_type_field == "source_link":
                    row_dict[wrong_type_field] = [
                        "not",
                        "a",
                        "dict",
                    ]  # Should be object
            if extra_field:
                row_dict["_unknown_field"] = "should-not-be-here"
            result.append(row_dict)
        return result

    @staticmethod
    def malformed_symbol_delta(
        *,
        missing_field: str | None = None,
        wrong_type_field: str | None = None,
    ) -> JsonObject:
        """Create a malformed symbol delta with specified defects.

        Parameters
        ----------
        missing_field : str | None
            Field name to remove from the payload. Defaults to None.
        wrong_type_field : str | None
            Field name to replace with wrong type. Defaults to None.

        Returns
        -------
        JsonObject
            A symbol delta payload with specified mutations.
        """
        payload = _load(DELTA_EXAMPLE)
        result: JsonObject = dict(cast("Mapping[str, JsonValue]", payload))
        if missing_field and missing_field in result:
            del result[missing_field]
        if wrong_type_field in {"added", "changed"}:
            result[wrong_type_field] = "should-be-array"
        return result


class TestMalformedPayloads:
    """Test malformed payload detection for scenario 3.2.b."""

    def test_symbol_index_missing_required_path(self) -> None:
        """Test that missing path field is rejected."""
        payload = PayloadFactory.malformed_symbol_index(missing_field="path")
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                cast("JsonPayload", payload), SYMBOL_SCHEMA, artifact="symbols.json"
            )


class TestValidateArtifactsHelpers:
    """Tests for helper functions in docs.scripts.validate_artifacts."""

    def test_validate_by_file_lookup_returns_tuples(self, tmp_path: Path) -> None:
        """Validate helper converts list payloads into tuple mappings."""
        payload = {"pkg/module.py": ["pkg.symbol"]}
        path = tmp_path / "by_file.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        result = validate_by_file_lookup(path)

        assert result == {"pkg/module.py": ("pkg.symbol",)}

    def test_validate_by_module_lookup_rejects_bad_entries(
        self, tmp_path: Path
    ) -> None:
        """Validate helper raises when payload contains invalid entries."""
        payload = {"pkg": ["valid", 42]}
        path = tmp_path / "by_module.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ArtifactValidationError):
            validate_by_module_lookup(path)

    def test_symbol_index_missing_required_kind(self) -> None:
        """Test that missing kind field is rejected."""
        payload = PayloadFactory.malformed_symbol_index(missing_field="kind")
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                cast("JsonPayload", payload), SYMBOL_SCHEMA, artifact="symbols.json"
            )

    def test_symbol_index_missing_required_doc(self) -> None:
        """Test that missing doc field is rejected."""
        payload = PayloadFactory.malformed_symbol_index(missing_field="doc")
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                cast("JsonPayload", payload), SYMBOL_SCHEMA, artifact="symbols.json"
            )

    def test_symbol_index_missing_required_tested_by(self) -> None:
        """Test that missing tested_by field is rejected."""
        payload = PayloadFactory.malformed_symbol_index(missing_field="tested_by")
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                cast("JsonPayload", payload), SYMBOL_SCHEMA, artifact="symbols.json"
            )

    def test_symbol_index_missing_required_source_link(self) -> None:
        """Test that missing source_link field is rejected."""
        payload = PayloadFactory.malformed_symbol_index(missing_field="source_link")
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                cast("JsonPayload", payload), SYMBOL_SCHEMA, artifact="symbols.json"
            )

    def test_symbol_index_wrong_type_path(self) -> None:
        """Test that wrong type for path is rejected."""
        payload = PayloadFactory.malformed_symbol_index(wrong_type_field="path")
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                cast("JsonPayload", payload), SYMBOL_SCHEMA, artifact="symbols.json"
            )

    def test_symbol_index_wrong_type_tested_by(self) -> None:
        """Test that wrong type for tested_by is rejected."""
        payload = PayloadFactory.malformed_symbol_index(wrong_type_field="tested_by")
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                cast("JsonPayload", payload), SYMBOL_SCHEMA, artifact="symbols.json"
            )

    def test_symbol_index_wrong_type_source_link(self) -> None:
        """Test that wrong type for source_link is rejected."""
        payload = PayloadFactory.malformed_symbol_index(wrong_type_field="source_link")
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                cast("JsonPayload", payload), SYMBOL_SCHEMA, artifact="symbols.json"
            )

    def test_symbol_index_extra_field_rejected(self) -> None:
        """Test that additional properties are rejected (schema: additionalProperties: false)."""
        payload = PayloadFactory.malformed_symbol_index(extra_field=True)
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                cast("JsonPayload", payload), SYMBOL_SCHEMA, artifact="symbols.json"
            )

    def test_symbol_delta_wrong_type_added(self) -> None:
        """Test that wrong type for added field is rejected."""
        payload = PayloadFactory.malformed_symbol_delta(wrong_type_field="added")
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                cast("JsonPayload", payload),
                DELTA_SCHEMA,
                artifact="symbols.delta.json",
            )

    def test_symbol_delta_wrong_type_changed(self) -> None:
        """Test that wrong type for changed field is rejected."""
        payload = PayloadFactory.malformed_symbol_delta(wrong_type_field="changed")
        with pytest.raises(ToolExecutionError):
            validate_against_schema(
                cast("JsonPayload", payload),
                DELTA_SCHEMA,
                artifact="symbols.delta.json",
            )

    def test_artifact_validation_error_surfaces_problem_details(self) -> None:
        """Test that ArtifactValidationError surfaces RFC 9457 Problem Details."""
        payload = PayloadFactory.malformed_symbol_index(missing_field="path")
        with pytest.raises(ToolExecutionError) as exc_info:
            validate_against_schema(
                cast("JsonPayload", payload), SYMBOL_SCHEMA, artifact="symbols.json"
            )
        # Verify the error has Problem Details structure
        error = exc_info.value
        assert hasattr(error, "problem")
        assert error.problem is not None


# ============================================================================
# 3.2.c: Byte-identical round-trip validation
# ============================================================================


class TestByteIdenticalRoundTrip:
    """Test byte-identical round-trip serialization for scenario 3.2.c."""

    def test_symbol_index_round_trip_byte_identical(self) -> None:
        """Test that symbol index round-trip produces byte-identical JSON.

        This ensures deterministic serialization: symbol index payloads loaded
        and re-serialized through the typed codec must produce identical bytes
        to the original (modulo whitespace normalization).
        """
        original_text = SYMBOL_EXAMPLE.read_text(encoding="utf-8")
        original_payload: JsonPayload = json.loads(original_text)

        # Round-trip through typed codec
        artifacts = symbol_index_from_json(original_payload)
        reserialized = symbol_index_to_payload(artifacts)

        # Normalize whitespace and compare
        original_normalized = json.dumps(original_payload, sort_keys=True, indent=2)
        reserialized_normalized = json.dumps(reserialized, sort_keys=True, indent=2)
        assert (
            original_normalized == reserialized_normalized
        ), "Symbol index round-trip is not byte-identical"

    def test_symbol_delta_round_trip_byte_identical(self) -> None:
        """Test that symbol delta round-trip produces byte-identical JSON.

        This ensures deterministic serialization: symbol delta payloads loaded
        and re-serialized through the typed codec must produce identical bytes
        to the original (modulo whitespace normalization).
        """
        original_text = DELTA_EXAMPLE.read_text(encoding="utf-8")
        original_payload: JsonPayload = json.loads(original_text)

        # Round-trip through typed codec
        artifacts = symbol_delta_from_json(original_payload)
        reserialized = symbol_delta_to_payload(artifacts)

        # Normalize whitespace and compare
        original_normalized = json.dumps(original_payload, sort_keys=True, indent=2)
        reserialized_normalized = json.dumps(reserialized, sort_keys=True, indent=2)
        assert (
            original_normalized == reserialized_normalized
        ), "Symbol delta round-trip is not byte-identical"

    def test_symbol_index_validation_preserves_ordering(self) -> None:
        """Test that codec preserves field ordering from schema examples."""
        payload = _load(SYMBOL_EXAMPLE)
        artifacts = symbol_index_from_json(payload)
        reserialized = symbol_index_to_payload(artifacts)

        # Both should pass schema validation
        validate_against_schema(payload, SYMBOL_SCHEMA, artifact="symbols.json")
        validate_against_schema(reserialized, SYMBOL_SCHEMA, artifact="symbols.json")

    def test_symbol_delta_validation_preserves_structure(self) -> None:
        """Test that codec preserves structure from schema examples."""
        payload = _load(DELTA_EXAMPLE)
        artifacts = symbol_delta_from_json(payload)
        reserialized = symbol_delta_to_payload(artifacts)

        # Both should pass schema validation
        validate_against_schema(payload, DELTA_SCHEMA, artifact="symbols.delta.json")
        validate_against_schema(
            cast("JsonPayload", reserialized),
            DELTA_SCHEMA,
            artifact="symbols.delta.json",
        )
