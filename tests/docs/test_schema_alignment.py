"""Unit tests for schema alignment helpers.

Tests verify alignment utilities for canonical field validation, legacy payload migration, and RFC
9457 Problem Details error handling.
"""

from __future__ import annotations

import pytest
from docs.types.artifacts import (
    SYMBOL_DELTA_PAYLOAD_FIELDS,
    SYMBOL_INDEX_ROW_FIELDS,
    align_schema_fields,
)

from kgfoundry_common.errors import ArtifactValidationError


class TestAlignmentFieldSets:
    """Tests for alignment field set constants."""

    def test_symbol_index_row_fields_complete(self) -> None:
        """Verify SYMBOL_INDEX_ROW_FIELDS includes all canonical fields."""
        # Core fields (required or important)
        assert "path" in SYMBOL_INDEX_ROW_FIELDS
        assert "kind" in SYMBOL_INDEX_ROW_FIELDS
        assert "doc" in SYMBOL_INDEX_ROW_FIELDS

        # Metadata fields
        assert "deprecated_in" in SYMBOL_INDEX_ROW_FIELDS
        assert "stability" in SYMBOL_INDEX_ROW_FIELDS
        assert "since" in SYMBOL_INDEX_ROW_FIELDS

        # Span/location fields
        assert "lineno" in SYMBOL_INDEX_ROW_FIELDS
        assert "endlineno" in SYMBOL_INDEX_ROW_FIELDS
        assert "span" in SYMBOL_INDEX_ROW_FIELDS

    def test_symbol_delta_payload_fields_complete(self) -> None:
        """Verify SYMBOL_DELTA_PAYLOAD_FIELDS includes tracking fields."""
        assert "base_sha" in SYMBOL_DELTA_PAYLOAD_FIELDS
        assert "head_sha" in SYMBOL_DELTA_PAYLOAD_FIELDS
        assert "added" in SYMBOL_DELTA_PAYLOAD_FIELDS
        assert "removed" in SYMBOL_DELTA_PAYLOAD_FIELDS
        assert "changed" in SYMBOL_DELTA_PAYLOAD_FIELDS


class TestAlignSchemaFieldsCanonical:
    """Tests for canonical (valid) payload alignment."""

    @pytest.mark.parametrize(
        "payload",
        [
            {
                "path": "pkg.func",
                "kind": "function",
                "doc": "A function",
                "deprecated_in": "0.2.0",
                "tested_by": [],
                "source_link": {},
            },
            {
                "path": "pkg.Class",
                "kind": "class",
                "doc": "A class",
                "tested_by": [],
                "source_link": {},
            },
            {
                "base_sha": "abc123",
                "head_sha": "def456",
                "added": [],
                "removed": [],
                "changed": [],
            },
        ],
    )
    def test_canonical_payloads_align_successfully(self, payload: dict[str, object]) -> None:
        """Verify canonical payloads pass alignment without errors."""
        if "path" in payload and "kind" in payload:
            aligned = align_schema_fields(
                payload,
                expected_fields=SYMBOL_INDEX_ROW_FIELDS,
                artifact_id="test-symbol-row",
            )
        else:
            aligned = align_schema_fields(
                payload,
                expected_fields=SYMBOL_DELTA_PAYLOAD_FIELDS,
                artifact_id="test-delta-payload",
            )

        assert isinstance(aligned, dict)
        assert all(
            k in (SYMBOL_INDEX_ROW_FIELDS if "path" in payload else SYMBOL_DELTA_PAYLOAD_FIELDS)
            for k in aligned
        )

    def test_canonical_alignment_preserves_values(self) -> None:
        """Verify alignment preserves all field values."""
        payload = {
            "path": "pkg.mod.func",
            "kind": "function",
            "doc": "Documentation",
            "deprecated_in": "0.2.0",
            "stability": "experimental",
            "tested_by": ["test_func.py::test_func"],
            "source_link": {"github": "https://github.com/..."},
        }
        aligned = align_schema_fields(
            payload,
            expected_fields=SYMBOL_INDEX_ROW_FIELDS,
            artifact_id="preservation-test",
        )

        assert aligned["path"] == "pkg.mod.func"
        assert aligned["deprecated_in"] == "0.2.0"
        assert aligned["stability"] == "experimental"
        assert aligned["tested_by"] == ["test_func.py::test_func"]


class TestAlignSchemaFieldsInvalid:
    """Tests for invalid payload rejection and Problem Details."""

    def test_unknown_fields_rejected_with_details(self) -> None:
        """Verify unknown fields trigger ArtifactValidationError with context."""
        payload = {
            "path": "pkg.func",
            "kind": "function",
            "doc": "A function",
            "unknown_field": "invalid",
            "tested_by": [],
            "source_link": {},
        }

        with pytest.raises(ArtifactValidationError) as exc_info:
            align_schema_fields(
                payload,
                expected_fields=SYMBOL_INDEX_ROW_FIELDS,
                artifact_id="symbol-index-row",
            )

        error = exc_info.value
        assert "unknown_field" in str(error)
        assert error.context is not None
        assert "unknown_fields" in error.context
        assert error.context["unknown_fields"] == ["unknown_field"]

    @pytest.mark.parametrize(
        "bad_payload",
        [
            [],  # list instead of dict
            "not a dict",  # string
            42,  # int
            None,  # None
        ],
    )
    def test_non_dict_payloads_rejected(self, bad_payload: object) -> None:
        """Verify non-dict payloads are rejected early."""
        with pytest.raises(ArtifactValidationError) as exc_info:
            align_schema_fields(
                bad_payload,
                expected_fields=SYMBOL_INDEX_ROW_FIELDS,
                artifact_id="type-check",
            )

        error = exc_info.value
        assert "dict" in str(error).lower()

    def test_multiple_unknown_fields_listed(self) -> None:
        """Verify multiple unknown fields are all reported."""
        payload = {
            "path": "pkg.func",
            "kind": "function",
            "doc": "A function",
            "bad_field_1": "invalid",
            "bad_field_2": "invalid",
            "bad_field_3": "invalid",
            "tested_by": [],
            "source_link": {},
        }

        with pytest.raises(ArtifactValidationError) as exc_info:
            align_schema_fields(
                payload,
                expected_fields=SYMBOL_INDEX_ROW_FIELDS,
                artifact_id="multi-bad",
            )

        error = exc_info.value
        assert error.context is not None
        unknown_fields_value: object = error.context.get("unknown_fields", [])
        unknown_fields = unknown_fields_value if isinstance(unknown_fields_value, list) else []
        assert sorted(unknown_fields) == ["bad_field_1", "bad_field_2", "bad_field_3"]

    def test_error_provides_remediation_guidance(self) -> None:
        """Verify error context includes remediation guidance."""
        payload = {
            "path": "pkg.func",
            "kind": "function",
            "doc": "A function",
            "bad_field": "invalid",
            "tested_by": [],
            "source_link": {},
        }

        with pytest.raises(ArtifactValidationError) as exc_info:
            align_schema_fields(
                payload,
                expected_fields=SYMBOL_INDEX_ROW_FIELDS,
                artifact_id="remediation-test",
            )

        error = exc_info.value
        assert error.context is not None
        remediation_value: object = error.context.get("remediation", "")
        if isinstance(remediation_value, str):
            assert len(remediation_value) > 0
            assert "schema" in remediation_value.lower()
        else:
            # Remediation should be a string; if it's not, fail
            assert isinstance(remediation_value, str), "remediation must be a string"


class TestAlignSchemaFieldsEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_payload_with_optional_fields(self) -> None:
        """Verify empty payload (all fields optional) aligns."""
        payload: dict[str, object] = {}
        aligned = align_schema_fields(
            payload,
            expected_fields=SYMBOL_INDEX_ROW_FIELDS,
            artifact_id="empty-test",
        )

        assert aligned == {}

    def test_subset_of_fields_is_valid(self) -> None:
        """Verify payloads with subset of fields align successfully."""
        payload = {
            "path": "pkg.func",
            "kind": "function",
            "doc": "A function",
        }
        aligned = align_schema_fields(
            payload,
            expected_fields=SYMBOL_INDEX_ROW_FIELDS,
            artifact_id="subset-test",
        )

        assert len(aligned) == 3
        assert aligned["path"] == "pkg.func"

    def test_null_values_preserved(self) -> None:
        """Verify None/null values in canonical fields are preserved."""
        payload: dict[str, object] = {
            "path": "pkg.func",
            "kind": "function",
            "doc": "A function",
            "deprecated_in": None,
            "stability": None,
            "tested_by": [],
            "source_link": {},
        }
        aligned = align_schema_fields(
            payload,
            expected_fields=SYMBOL_INDEX_ROW_FIELDS,
            artifact_id="null-test",
        )

        assert aligned["deprecated_in"] is None
        assert aligned["stability"] is None

    def test_custom_artifact_id_in_error(self) -> None:
        """Verify custom artifact_id appears in error messages."""
        payload = {
            "path": "pkg.func",
            "kind": "function",
            "doc": "A function",
            "bad_field": "invalid",
            "tested_by": [],
            "source_link": {},
        }

        with pytest.raises(ArtifactValidationError) as exc_info:
            align_schema_fields(
                payload,
                expected_fields=SYMBOL_INDEX_ROW_FIELDS,
                artifact_id="my-custom-artifact",
            )

        error = exc_info.value
        assert "my-custom-artifact" in str(error)

    def test_alignment_is_idempotent(self) -> None:
        """Verify aligning an already-aligned payload is idempotent."""
        payload = {
            "path": "pkg.func",
            "kind": "function",
            "doc": "A function",
            "deprecated_in": "0.2.0",
            "tested_by": [],
            "source_link": {},
        }

        aligned1 = align_schema_fields(
            payload,
            expected_fields=SYMBOL_INDEX_ROW_FIELDS,
            artifact_id="idempotent-test",
        )
        aligned2 = align_schema_fields(
            aligned1,
            expected_fields=SYMBOL_INDEX_ROW_FIELDS,
            artifact_id="idempotent-test",
        )

        assert aligned1 == aligned2
