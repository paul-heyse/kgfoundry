"""Shared facade exposing typed metadata contracts for CLI tooling.

The facade deserialises augment and registry payloads, validates them via
Pydantic models, and returns immutable objects that downstream tooling can rely
on. Validation failures raise :class:`AugmentRegistryValidationError` carrying
RFC 9457 Problem Details payloads so callers can surface consistent error
messages.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic_core import PydanticCustomError

from kgfoundry_common.typing import gate_import
from tools._shared.problem_details import (
    ProblemDetailsParams,
    build_problem_details,
)

if TYPE_CHECKING:
    from pydantic import (
        AliasChoices,
        BaseModel,
        ConfigDict,
        Field,
        ValidationError,
        ValidationInfo,
        field_validator,
        model_validator,
    )

    from kgfoundry_common.types import JsonValue
    from tools._shared.problem_details import ProblemDetailsDict
else:  # pragma: no cover - runtime fallback for typing aliases
    JsonValue = object
    _pydantic = gate_import("pydantic", "augment registry modeling")
    AliasChoices = _pydantic.AliasChoices
    BaseModel = _pydantic.BaseModel
    ConfigDict = _pydantic.ConfigDict
    Field = _pydantic.Field
    ValidationError = _pydantic.ValidationError
    ValidationInfo = _pydantic.ValidationInfo
    field_validator = _pydantic.field_validator
    model_validator = _pydantic.model_validator

Reader = Callable[[Path], object]

_PROBLEM_TYPE = "https://kgfoundry.dev/problems/augment-registry"
_PROBLEM_TITLE = "CLI augment/registry error"


def _ensure_str_sequence(value: object) -> tuple[str, ...]:
    """Coerce value to tuple of unique strings.

    Parameters
    ----------
    value : object
        Value to coerce (None, sequence, or other).

    Returns
    -------
    tuple[str, ...]
        Tuple of unique strings, empty if value is None.

    Raises
    ------
    PydanticCustomError
        If value is a string/bytes or not a sequence.
    """
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        code = "sequence_type"
        msg = "Value must be a sequence of strings."
        raise PydanticCustomError(code, msg)
    seen: set[str] = set()
    items: list[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item)
        if text not in seen:
            seen.add(text)
            items.append(text)
    return tuple(items)


class AugmentRegistryError(RuntimeError):
    """Base exception for augment/registry loading failures."""

    def __init__(self, problem: ProblemDetailsDict) -> None:
        """Initialize exception with RFC 9457 Problem Details payload.

        Parameters
        ----------
        problem : ProblemDetailsDict
            RFC 9457 Problem Details dictionary containing type, title, status,
            detail, instance, and optional extensions fields.
        """
        detail = str(problem.get("detail", _PROBLEM_TITLE))
        super().__init__(detail)
        self.problem = problem


class AugmentRegistryValidationError(AugmentRegistryError):
    """Raised when payload validation fails against metadata contracts."""


class CodeSampleModel(BaseModel):
    """Typed representation of an ``x-codeSamples`` entry."""

    model_config = ConfigDict(frozen=True, extra="allow")

    lang: str
    source: str
    label: str | None = None

    @field_validator("lang", "source", "label", mode="before")
    @classmethod
    def _coerce_str(cls, value: object) -> object:
        """Coerce value to string or None.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        object
            String representation or None if value is None.
        """
        if value is None:
            return None
        return str(value)


class OperationOverrideModel(BaseModel):
    """Pydantic model describing augment operation overrides."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    summary: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    handler: str | None = Field(
        default=None,
        alias="x-handler",
        validation_alias=AliasChoices("x-handler", "handler"),
    )
    env: tuple[str, ...] = Field(
        default_factory=tuple,
        alias="x-env",
        validation_alias=AliasChoices("x-env", "env"),
    )
    code_samples: tuple[CodeSampleModel, ...] = Field(
        default_factory=tuple,
        alias="x-codeSamples",
        validation_alias=AliasChoices("x-codeSamples"),
    )
    problem_details: tuple[str, ...] = Field(
        default_factory=tuple,
        alias="x-problemDetails",
        validation_alias=AliasChoices("x-problemDetails", "problem_details"),
    )
    extras: Mapping[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _prepare(cls, value: object) -> Mapping[str, object]:
        """Prepare operation override payload by extracting extras.

        Parameters
        ----------
        value : object
            Raw operation override payload.

        Returns
        -------
        Mapping[str, object]
            Prepared payload with extras separated.

        Raises
        ------
        TypeError
            If value is not a mapping.
        """
        if not isinstance(value, Mapping):
            msg = "Operation override must be a mapping."
            raise TypeError(msg)
        data = {str(key): item for key, item in value.items()}
        extras: dict[str, object] = {}
        for key in list(data.keys()):
            if key.startswith("x-") and key not in {
                "x-handler",
                "x-env",
                "x-codeSamples",
                "x-problemDetails",
            }:
                extras[key] = data.pop(key)
        data.setdefault("extras", extras)
        return data

    @field_validator("summary", "description", "handler", mode="before")
    @classmethod
    def _coerce_optional_str(cls, value: object) -> object:
        """Coerce value to optional string.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        object
            String representation or None if value is None.
        """
        if value is None:
            return None
        return str(value)

    @field_validator("tags", "env", "problem_details", mode="before")
    @classmethod
    def _coerce_tuple(cls, value: object) -> tuple[str, ...]:
        """Coerce value to tuple of strings.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        tuple[str, ...]
            Tuple of unique strings.
        """
        return _ensure_str_sequence(value)

    @field_validator("examples", mode="before")
    @classmethod
    def _coerce_examples(cls, value: object) -> tuple[str, ...]:
        """Coerce examples value to tuple of strings.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        tuple[str, ...]
            Tuple of unique example strings.
        """
        return _ensure_str_sequence(value)

    @field_validator("code_samples", mode="before")
    @classmethod
    def _coerce_samples(cls, value: object) -> tuple[Mapping[str, object], ...]:
        """Coerce code samples value to tuple of mappings.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        tuple[Mapping[str, object], ...]
            Tuple of mapping dictionaries, empty if value is None or not a sequence.
        """
        if value is None:
            return ()
        if isinstance(value, Sequence):
            return tuple(item for item in value if isinstance(item, Mapping))
        return ()

    @field_validator("extras", mode="before")
    @classmethod
    def _coerce_extras(cls, value: object) -> Mapping[str, object]:
        """Coerce extras value to string-keyed mapping.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        Mapping[str, object]
            String-keyed mapping, empty if value is None or not a mapping.
        """
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return {str(k): v for k, v in value.items()}
        return {}

    def to_payload(self) -> dict[str, object]:
        """Convert operation override model to dictionary payload.

        Returns
        -------
        dict[str, object]
            Dictionary representation suitable for serialization to YAML/JSON.
        """
        payload: dict[str, object] = {}
        if self.summary:
            payload["summary"] = self.summary
        if self.description:
            payload["description"] = self.description
        if self.tags:
            payload["tags"] = list(self.tags)
        if self.examples:
            payload["examples"] = list(self.examples)
        if self.handler:
            payload["x-handler"] = self.handler
        if self.env:
            payload["x-env"] = list(self.env)
        if self.code_samples:
            payload["x-codeSamples"] = [sample.model_dump() for sample in self.code_samples]
        if self.problem_details:
            payload["x-problemDetails"] = list(self.problem_details)
        payload.update(self.extras)
        return payload


class TagGroupModel(BaseModel):
    """Typed representation of an ``x-tagGroups`` entry."""

    model_config = ConfigDict(frozen=True)

    name: str
    tags: tuple[str, ...]
    description: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _coerce_name(cls, value: object) -> str:
        """Coerce value to string for tag group name.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        str
            String representation of value.
        """
        return str(value)

    @field_validator("description", mode="before")
    @classmethod
    def _coerce_description(cls, value: object) -> object:
        """Coerce value to optional string for tag group description.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        object
            String representation or None if value is None.
        """
        if value is None:
            return None
        return str(value)

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: object) -> tuple[str, ...]:
        """Coerce tags value to tuple of unique strings preserving order.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        tuple[str, ...]
            Tuple of unique tag strings in original order.
        """
        tags = _ensure_str_sequence(value)
        seen: set[str] = set()
        ordered: list[str] = []
        for tag in tags:
            if tag not in seen:
                ordered.append(tag)
                seen.add(tag)
        return tuple(ordered)

    def to_payload(self) -> dict[str, object]:
        """Convert tag group model to dictionary payload.

        Returns
        -------
        dict[str, object]
            Dictionary representation with name and tags fields.
        """
        payload: dict[str, object] = {"name": self.name, "tags": list(self.tags)}
        if self.description:
            payload["description"] = self.description
        return payload


class AugmentMetadataModel(BaseModel):
    """Top-level augment metadata model."""

    model_config = ConfigDict(frozen=True)

    path: Path
    payload: Mapping[str, object]
    operations: Mapping[str, OperationOverrideModel]
    tag_groups: tuple[TagGroupModel, ...]
    extras: Mapping[str, object]

    @model_validator(mode="before")
    @classmethod
    def _prepare(cls, value: dict[str, object]) -> dict[str, object]:
        """Prepare augment metadata by parsing operations and tag groups.

        Parameters
        ----------
        value : dict[str, object]
            Raw augment metadata dictionary.

        Returns
        -------
        dict[str, object]
            Prepared dictionary with parsed operations and tag groups.

        Raises
        ------
        TypeError
            If payload is not a mapping.
        """
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            msg = "Augment payload must be a mapping."
            raise TypeError(msg)
        payload_dict = {str(key): item for key, item in payload.items()}
        operations_raw = payload_dict.get("operations")
        operations_map = _coerce_mapping(operations_raw)
        tag_groups_raw = payload_dict.get("x-tagGroups")
        extras = {
            key: item
            for key, item in payload_dict.items()
            if key not in {"operations", "x-tagGroups"}
        }
        operations = {
            key: OperationOverrideModel.model_validate(item) for key, item in operations_map.items()
        }
        tag_groups = tuple(
            TagGroupModel.model_validate(item) for item in _coerce_mapping_list(tag_groups_raw)
        )
        canonical: dict[str, object] = dict(extras)
        if operations:
            canonical["operations"] = {
                key: override.to_payload() for key, override in operations.items()
            }
        if tag_groups:
            canonical["x-tagGroups"] = [group.to_payload() for group in tag_groups]
        value.update(
            {
                "payload": canonical,
                "operations": operations,
                "tag_groups": tag_groups,
                "extras": extras,
            }
        )
        return value

    def operation_override(
        self,
        operation_id: str,
        *,
        tokens: Sequence[str] | None = None,
    ) -> OperationOverrideModel | None:
        """Retrieve operation override by operation ID or token sequence.

        Parameters
        ----------
        operation_id : str
            Operation identifier to look up.
        tokens : Sequence[str] | None, optional
            Optional token sequence for alternative lookup key.

        Returns
        -------
        OperationOverrideModel | None
            Operation override model if found, otherwise None.
        """
        override = self.operations.get(operation_id)
        if override is not None:
            return override
        if tokens:
            token_key = " ".join(token.strip() for token in tokens)
            if token_key:
                return self.operations.get(token_key)
        return None

    def get_operation(
        self,
        operation_id: str,
        *,
        tokens: Sequence[str] | None = None,
    ) -> Mapping[str, object] | None:
        """Retrieve operation override payload by operation ID or token sequence.

        Parameters
        ----------
        operation_id : str
            Operation identifier to look up.
        tokens : Sequence[str] | None, optional
            Optional token sequence for alternative lookup key.

        Returns
        -------
        Mapping[str, object] | None
            Operation override payload dictionary if found, otherwise None.
        """
        override = self.operation_override(operation_id, tokens=tokens)
        if override is None:
            return None
        return override.to_payload()


class RegistryOperationModel(BaseModel):
    """Typed representation of registry operation metadata."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    operation_id: str | None = Field(
        default=None, validation_alias=AliasChoices("operation_id", "operationId")
    )
    summary: str | None = None
    description: str | None = None
    handler: str | None = None
    tags: tuple[str, ...] = ()
    env: tuple[str, ...] = ()
    problem_details: tuple[str, ...] = Field(
        default_factory=tuple,
        validation_alias=AliasChoices("problem_details", "x-problemDetails"),
    )
    extras: Mapping[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _prepare(cls, value: object) -> Mapping[str, object]:
        """Prepare registry operation metadata by extracting extras.

        Parameters
        ----------
        value : object
            Raw operation metadata payload.

        Returns
        -------
        Mapping[str, object]
            Prepared payload with extras separated.

        Raises
        ------
        TypeError
            If value is not a mapping.
        """
        if not isinstance(value, Mapping):
            msg = "Operation metadata must be a mapping."
            raise TypeError(msg)
        data = {str(key): item for key, item in value.items()}
        extras: dict[str, object] = {}
        for key in list(data.keys()):
            if key not in {
                "operation_id",
                "operationId",
                "summary",
                "description",
                "handler",
                "tags",
                "env",
                "problem_details",
                "x-problemDetails",
            }:
                extras[key] = data.pop(key)
        data["extras"] = extras
        return data

    @field_validator("summary", "description", "handler", mode="before")
    @classmethod
    def _coerce_optional(cls, value: object) -> object:
        """Coerce value to optional string.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        object
            String representation or None if value is None.
        """
        if value is None:
            return None
        return str(value)

    @field_validator("operation_id", mode="before")
    @classmethod
    def _coerce_operation_id(cls, value: object) -> object:
        """Coerce operation ID value to optional string.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        object
            String representation or None if value is None.
        """
        if value is None:
            return None
        return str(value)

    @field_validator("tags", "env", "problem_details", mode="before")
    @classmethod
    def _coerce_sequences(cls, value: object) -> tuple[str, ...]:
        """Coerce value to tuple of strings.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        tuple[str, ...]
            Tuple of unique strings.
        """
        return _ensure_str_sequence(value)

    def to_payload(self, default_operation_id: str) -> dict[str, object]:
        """Convert registry operation model to dictionary payload.

        Parameters
        ----------
        default_operation_id : str
            Default operation ID to use if model's operation_id is None.

        Returns
        -------
        dict[str, object]
            Dictionary representation suitable for serialization.
        """
        payload: dict[str, object] = {}
        operation_id = self.operation_id or default_operation_id
        payload["operation_id"] = operation_id
        if self.summary:
            payload["summary"] = self.summary
        if self.description:
            payload["description"] = self.description
        if self.handler:
            payload["handler"] = self.handler
        if self.tags:
            payload["tags"] = list(self.tags)
        if self.env:
            payload["env"] = list(self.env)
        if self.problem_details:
            payload["problem_details"] = list(self.problem_details)
        payload.update(self.extras)
        return payload


class RegistryInterfaceModel(BaseModel):
    """Typed representation of registry interface metadata."""

    model_config = ConfigDict(frozen=True)

    type: str | None = None
    identifier: str
    module: str | None = None
    owner: str | None = None
    stability: str | None = None
    entrypoint: str | None = None
    binary: str | None = None
    protocol: str | None = None
    spec: str | None = None
    augment: str | None = None
    tags: tuple[str, ...] = ()
    description: str | None = None
    problem_details: tuple[str, ...] = ()
    operations: Mapping[str, RegistryOperationModel] = Field(default_factory=dict)
    extras: Mapping[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _prepare(cls, value: object, info: ValidationInfo) -> Mapping[str, object]:
        """Prepare registry interface metadata by parsing operations and extracting extras.

        Parameters
        ----------
        value : object
            Raw interface metadata payload.
        info : ValidationInfo
            Pydantic validation context.

        Returns
        -------
        Mapping[str, object]
            Prepared payload with parsed operations and extras separated.

        Raises
        ------
        TypeError
            If value is not a mapping.
        ValueError
            If identifier is missing.
        """
        if not isinstance(value, Mapping):
            msg = "Registry interface entry must be a mapping."
            raise TypeError(msg)
        data = {str(key): item for key, item in value.items()}
        existing_identifier: object | None = None
        if isinstance(info.data, Mapping):
            existing_identifier = info.data.get("identifier")
        identifier = existing_identifier or data.get("identifier") or data.get("id")
        if not identifier:
            msg = "Registry interface requires an identifier."
            raise ValueError(msg)
        data.setdefault("identifier", str(identifier))
        operations_raw = data.get("operations")
        operations_map = _coerce_mapping(operations_raw)
        data["operations"] = {
            key: RegistryOperationModel.model_validate(item) for key, item in operations_map.items()
        }
        extras: dict[str, object] = {}
        for key in list(data.keys()):
            if key in {
                "type",
                "identifier",
                "module",
                "owner",
                "stability",
                "entrypoint",
                "binary",
                "protocol",
                "spec",
                "augment",
                "tags",
                "description",
                "problem_details",
                "operations",
            }:
                continue
            extras[key] = data.pop(key)
        data["extras"] = extras
        return data

    @field_validator(
        "module",
        "owner",
        "stability",
        "entrypoint",
        "binary",
        "protocol",
        "spec",
        "augment",
        "description",
        mode="before",
    )
    @classmethod
    def _coerce_optional(cls, value: object) -> object:
        """Coerce value to optional string.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        object
            String representation or None if value is None.
        """
        if value is None:
            return None
        return str(value)

    @field_validator("tags", "problem_details", mode="before")
    @classmethod
    def _coerce_tuple(cls, value: object) -> tuple[str, ...]:
        """Coerce value to tuple of strings.

        Parameters
        ----------
        value : object
            Value to coerce.

        Returns
        -------
        tuple[str, ...]
            Tuple of unique strings.
        """
        return _ensure_str_sequence(value)

    def to_payload(self) -> dict[str, object]:
        """Convert registry interface model to dictionary payload.

        Returns
        -------
        dict[str, object]
            Dictionary representation with identifier and optional metadata fields.
        """
        payload: dict[str, object] = {
            "id": self.identifier,
        }
        for key in (
            "module",
            "owner",
            "stability",
            "entrypoint",
            "binary",
            "protocol",
            "spec",
            "augment",
            "description",
        ):
            value = getattr(self, key)
            if value:
                payload[key] = value
        if self.tags:
            payload["tags"] = list(self.tags)
        if self.problem_details:
            payload["problem_details"] = list(self.problem_details)
        if self.operations:
            payload["operations"] = {key: op.to_payload(key) for key, op in self.operations.items()}
        payload.update(self.extras)
        return payload


class RegistryMetadataModel(BaseModel):
    """Registry metadata containing typed interface entries."""

    model_config = ConfigDict(frozen=True)

    path: Path
    interfaces: Mapping[str, RegistryInterfaceModel]

    @model_validator(mode="before")
    @classmethod
    def _prepare(cls, value: dict[str, object]) -> dict[str, object]:
        """Prepare registry metadata by parsing interfaces.

        Parameters
        ----------
        value : dict[str, object]
            Raw registry metadata dictionary.

        Returns
        -------
        dict[str, object]
            Prepared dictionary with parsed interface models.
        """
        interfaces_raw = value.get("interfaces")
        interfaces_map = _coerce_mapping(interfaces_raw)
        interfaces: dict[str, RegistryInterfaceModel] = {}
        for identifier, meta in interfaces_map.items():
            interfaces[identifier] = RegistryInterfaceModel.model_validate(
                {"identifier": identifier, **_coerce_mapping(meta)}
            )
        value["interfaces"] = interfaces
        return value

    def interface(self, identifier: str) -> RegistryInterfaceModel | None:
        """Retrieve interface model by identifier.

        Parameters
        ----------
        identifier : str
            Interface identifier to look up.

        Returns
        -------
        RegistryInterfaceModel | None
            Interface model if found, otherwise None.
        """
        return self.interfaces.get(identifier)

    def to_payload(self) -> dict[str, object]:
        """Convert registry metadata model to dictionary payload.

        Returns
        -------
        dict[str, object]
            Dictionary mapping interface identifiers to their payload dictionaries.
        """
        return {
            identifier: interface.to_payload() for identifier, interface in self.interfaces.items()
        }

    def get_interface(self, identifier: str) -> Mapping[str, object] | None:
        """Retrieve interface payload by identifier.

        Parameters
        ----------
        identifier : str
            Interface identifier to look up.

        Returns
        -------
        Mapping[str, object] | None
            Interface payload dictionary if found, otherwise None.
        """
        interface_model = self.interface(identifier)
        if interface_model is None:
            return None
        return interface_model.to_payload()


class ToolingMetadataModel(BaseModel):
    """Composite metadata returned by :func:`load_tooling_metadata`."""

    model_config = ConfigDict(frozen=True)

    augment: AugmentMetadataModel
    registry: RegistryMetadataModel

    def operation_override(
        self,
        operation_id: str,
        *,
        tokens: Sequence[str] | None = None,
    ) -> OperationOverrideModel | None:
        """Retrieve operation override from augment metadata.

        Parameters
        ----------
        operation_id : str
            Operation identifier to look up.
        tokens : Sequence[str] | None, optional
            Optional token sequence for alternative lookup key.

        Returns
        -------
        OperationOverrideModel | None
            Operation override model if found, otherwise None.
        """
        return self.augment.operation_override(operation_id, tokens=tokens)

    def get_operation(self, operation_id: str) -> Mapping[str, object] | None:
        """Return the override for ``operation_id`` when present.

        Parameters
        ----------
        operation_id : str
            Operation identifier to resolve.

        Returns
        -------
        Mapping[str, object] | None
            Operation override mapping when available; otherwise ``None``.
        """
        return self.augment.get_operation(operation_id)

    def get_interface(self, interface_id: str) -> Mapping[str, object] | None:
        """Return metadata for ``interface_id`` when available.

        Parameters
        ----------
        interface_id : str
            Interface identifier to resolve.

        Returns
        -------
        Mapping[str, object] | None
            Registry metadata mapping when available; otherwise ``None``.
        """
        return self.registry.get_interface(interface_id)


def load_tooling_metadata(
    *,
    augment_path: Path,
    registry_path: Path,
    augment_reader: Reader | None = None,
    registry_reader: Reader | None = None,
) -> ToolingMetadataModel:
    """Return combined augment and registry metadata as typed models.

    Parameters
    ----------
    augment_path : Path
        Filesystem path to the augment metadata YAML document.
    registry_path : Path
        Filesystem path to the registry metadata YAML document.
    augment_reader : Reader | None, optional
        Custom reader used for tests; defaults to the canonical YAML reader.
    registry_reader : Reader | None, optional
        Custom reader used for tests; defaults to the canonical YAML reader.

    Returns
    -------
    ToolingMetadataModel
        Immutable composite of augment and registry metadata.

    Notes
    -----
    Propagates :class:`AugmentRegistryError` when augment or registry payloads
    fail to load or validate.
    """
    augment = load_augment(augment_path, reader=augment_reader)
    registry = load_registry(registry_path, reader=registry_reader)
    return ToolingMetadataModel(augment=augment, registry=registry)


def load_augment(path: Path, *, reader: Reader | None = None) -> AugmentMetadataModel:
    """Return augment metadata for ``path`` as an :class:`AugmentMetadataModel`.

    Parameters
    ----------
    path : Path
        Filesystem location of the augment YAML document.
    reader : Reader | None, optional
        Custom payload reader, primarily for testing.

    Returns
    -------
    AugmentMetadataModel
        Immutable augment metadata bundle.

    Notes
    -----
    Propagates :class:`AugmentRegistryError` when the augment file is missing,
    unreadable, or fails validation.
    """
    resolved = path.resolve()
    if reader is None:
        return _cached_augment(str(resolved))
    return _load_augment(resolved, reader)


def load_registry(path: Path, *, reader: Reader | None = None) -> RegistryMetadataModel:
    """Return registry metadata for ``path`` as a :class:`RegistryMetadataModel`.

    Parameters
    ----------
    path : Path
        Filesystem location of the registry YAML document.
    reader : Reader | None, optional
        Custom payload reader, primarily for testing.

    Returns
    -------
    RegistryMetadataModel
        Immutable registry metadata bundle.

    Notes
    -----
    Propagates :class:`AugmentRegistryError` when the registry file is missing,
    unreadable, or fails validation.
    """
    resolved = path.resolve()
    if reader is None:
        return _cached_registry(str(resolved))
    return _load_registry(resolved, reader)


def clear_cache() -> None:
    """Clear cached augment and registry payloads (useful for tests)."""
    _cached_augment.cache_clear()
    _cached_registry.cache_clear()


def render_problem_details(error: AugmentRegistryError) -> str:
    """Return a canonical JSON string for ``error.problem``.

    Parameters
    ----------
    error : AugmentRegistryError
        Augment or registry exception containing a Problem Details payload.

    Returns
    -------
    str
        JSON-formatted representation of the Problem Details payload.
    """
    return json.dumps(error.problem, indent=2, sort_keys=True)


def _load_augment(resolved: Path, reader: Reader) -> AugmentMetadataModel:
    """Load and validate augment metadata from a YAML file.

    Extended Summary
    ----------------
    This function orchestrates the loading and validation of augment metadata
    files used by CLI tooling to customize OpenAPI operation descriptions. It
    delegates YAML parsing to the provided reader function, validates the
    resulting payload structure, and constructs an immutable Pydantic model
    that downstream tooling can rely on for type safety. The function is part
    of the internal loading pipeline called by :func:`load_augment` and
    :func:`load_tooling_metadata`. All errors are wrapped in RFC 9457 Problem
    Details format via :class:`AugmentRegistryError` and
    :class:`AugmentRegistryValidationError` to ensure consistent error reporting
    across CLI boundaries.

    Parameters
    ----------
    resolved : Path
        Absolute filesystem path to the augment YAML file. Must be a resolved
        path (no symlinks or relative components).
    reader : Reader
        Callable that accepts a Path and returns parsed YAML content. Used for
        dependency injection in tests; production code uses the canonical YAML
        reader.

    Returns
    -------
    AugmentMetadataModel
        Immutable validated model containing augment metadata. The model
        includes path, payload, and all validated operation overrides.

    Raises
    ------
    AugmentRegistryError
        If the file cannot be read (missing, permission denied, I/O error), if
        the YAML is malformed, or if the payload is not a mapping structure.
        The exception includes RFC 9457 Problem Details with status codes
        (404 for missing files, 422 for invalid structure, 500 for I/O errors).
    AugmentRegistryValidationError
        If the payload fails Pydantic validation against the
        :class:`AugmentMetadataModel` schema. The exception includes detailed
        validation error information in the Problem Details extensions.

    Notes
    -----
    • Time complexity: O(n) where n is file size; dominated by YAML parsing
      and Pydantic validation.
    • Side effects: Reads from filesystem via the reader function; no global
      state mutations.
    • Thread-safety: Safe if reader is thread-safe; no shared mutable state.
    • Error handling: All exceptions preserve original cause chains via
      ``raise ... from exc`` to maintain stack trace context.
    • Design: Uses helper functions :func:`_registry_error` and
      :func:`_validation_error` to construct exceptions with consistent Problem
      Details structure.

    See Also
    --------
    load_augment : Public API that resolves paths and caches results
    _read_yaml : Lower-level YAML reading with error handling
    AugmentMetadataModel : The validated model type returned

    Examples
    --------
    >>> from pathlib import Path
    >>> def mock_reader(path: Path) -> dict:
    ...     return {"operations": {"test": {"summary": "Test op"}}}
    >>> result = _load_augment(Path("/tmp/augment.yaml"), mock_reader)
    >>> isinstance(result, AugmentMetadataModel)
    True
    >>> result.path == Path("/tmp/augment.yaml")
    True
    """
    payload = _read_yaml(resolved, reader, source="augment")
    if not isinstance(payload, Mapping):
        raise _registry_error(
            source="augment",
            resolved=resolved,
            detail="Augment file must decode to a mapping.",
            status=422,
        )
    try:
        return AugmentMetadataModel.model_validate({"path": resolved, "payload": payload})
    except ValidationError as exc:  # pragma: no cover - exercised in tests
        validation_error = _validation_error("augment", resolved, exc)
        raise validation_error from exc


def _load_registry(resolved: Path, reader: Reader) -> RegistryMetadataModel:
    """Load and validate registry metadata from a YAML file.

    Extended Summary
    ----------------
    This function orchestrates the loading and validation of registry metadata
    files that define CLI tooling interfaces and their operations. It delegates
    YAML parsing to the provided reader function, validates the payload
    structure (ensuring it contains an "interfaces" mapping), and constructs an
    immutable Pydantic model that downstream tooling uses to discover and
    configure CLI operations. The function is part of the internal loading
    pipeline called by :func:`load_registry` and :func:`load_tooling_metadata`.
    All errors are wrapped in RFC 9457 Problem Details format via
    :class:`AugmentRegistryError` and :class:`AugmentRegistryValidationError` to
    ensure consistent error reporting across CLI boundaries.

    Parameters
    ----------
    resolved : Path
        Absolute filesystem path to the registry YAML file. Must be a resolved
        path (no symlinks or relative components).
    reader : Reader
        Callable that accepts a Path and returns parsed YAML content. Used for
        dependency injection in tests; production code uses the canonical YAML
        reader.

    Returns
    -------
    RegistryMetadataModel
        Immutable validated model containing registry metadata. The model
        includes path, interfaces mapping, and all validated interface
        definitions with their operations.

    Raises
    ------
    AugmentRegistryError
        If the file cannot be read (missing, permission denied, I/O error), if
        the YAML is malformed, if the payload is not a mapping structure, or if
        the required "interfaces" key is missing or not a mapping. The exception
        includes RFC 9457 Problem Details with status codes (404 for missing
        files, 422 for invalid structure, 500 for I/O errors).
    AugmentRegistryValidationError
        If the payload fails Pydantic validation against the
        :class:`RegistryMetadataModel` schema. The exception includes detailed
        validation error information in the Problem Details extensions.

    Notes
    -----
    • Time complexity: O(n + m) where n is file size and m is the number of
      interfaces; dominated by YAML parsing and recursive Pydantic validation
      of interface and operation models.
    • Side effects: Reads from filesystem via the reader function; no global
      state mutations.
    • Thread-safety: Safe if reader is thread-safe; no shared mutable state.
    • Error handling: All exceptions preserve original cause chains via
      ``raise ... from exc`` to maintain stack trace context.
    • Design: Uses helper functions :func:`_registry_error` and
      :func:`_validation_error` to construct exceptions with consistent Problem
      Details structure. Validates both top-level structure and nested
      "interfaces" mapping before model construction.

    See Also
    --------
    load_registry : Public API that resolves paths and caches results
    _read_yaml : Lower-level YAML reading with error handling
    RegistryMetadataModel : The validated model type returned

    Examples
    --------
    >>> from pathlib import Path
    >>> def mock_reader(path: Path) -> dict:
    ...     return {"interfaces": {"test": {"identifier": "test_iface"}}}
    >>> result = _load_registry(Path("/tmp/registry.yaml"), mock_reader)
    >>> isinstance(result, RegistryMetadataModel)
    True
    >>> result.path == Path("/tmp/registry.yaml")
    True
    """
    payload = _read_yaml(resolved, reader, source="registry")
    if not isinstance(payload, Mapping):
        raise _registry_error(
            source="registry",
            resolved=resolved,
            detail="Registry file must decode to a mapping.",
            status=422,
        )
    interfaces = payload.get("interfaces")
    if not isinstance(interfaces, Mapping):
        raise _registry_error(
            source="registry",
            resolved=resolved,
            detail="Registry file must expose an 'interfaces' mapping.",
            status=422,
        )
    try:
        return RegistryMetadataModel.model_validate({"path": resolved, "interfaces": interfaces})
    except ValidationError as exc:  # pragma: no cover - exercised in tests
        validation_error = _validation_error("registry", resolved, exc)
        raise validation_error from exc


def _read_yaml(resolved: Path, reader: Reader, *, source: str) -> object:
    """Read and parse a YAML file using the provided reader function.

    Extended Summary
    ----------------
    This function provides a unified error-handling wrapper around YAML file
    reading operations. It invokes the provided reader function and catches
    filesystem and YAML parsing errors, converting them into structured
    :class:`AugmentRegistryError` exceptions with RFC 9457 Problem Details
    payloads. The function is used internally by :func:`_load_augment` and
    :func:`_load_registry` to handle the low-level I/O and parsing concerns,
    allowing those functions to focus on structure validation and model
    construction. Error messages include the source identifier ("augment" or
    "registry") to help callers identify which metadata file failed.

    Parameters
    ----------
    resolved : Path
        Absolute filesystem path to the YAML file. Must be a resolved path (no
        symlinks or relative components).
    reader : Reader
        Callable that accepts a Path and returns parsed YAML content. Typically
        wraps :func:`yaml.safe_load` with file opening logic. Used for
        dependency injection in tests.
    source : str
        Source identifier for error messages and Problem Details instance URIs.
        Must be "augment" or "registry" to match expected metadata file types.

    Returns
    -------
    object
        Parsed YAML content, typically a dictionary but may be any YAML-serializable
        type (list, str, int, etc.). The caller is responsible for validating
        the structure.

    Raises
    ------
    AugmentRegistryError
        If the file is missing (:exc:`FileNotFoundError`), contains invalid YAML
        (:exc:`yaml.YAMLError`), or encounters an I/O error (:exc:`OSError`).
        The exception includes RFC 9457 Problem Details with appropriate status
        codes (404 for missing files, 422 for YAML syntax errors, 500 for I/O
        failures) and preserves the original exception as the cause.

    Notes
    -----
    • Time complexity: O(n) where n is file size; dominated by filesystem I/O
      and YAML parsing.
    • Side effects: Reads from filesystem via the reader function; no global
      state mutations.
    • Thread-safety: Safe if reader is thread-safe; no shared mutable state.
    • Error handling: All exceptions preserve original cause chains via
      ``raise ... from exc`` to maintain stack trace context. FileNotFoundError,
      yaml.YAMLError, and OSError are caught and re-raised as AugmentRegistryError
      with structured Problem Details.
    • Design: This function isolates I/O and parsing error handling from
      structure validation, allowing callers to focus on business logic. The
      source parameter enables contextual error messages that help diagnose
      which metadata file failed.

    See Also
    --------
    _load_augment : Higher-level function that validates augment structure
    _load_registry : Higher-level function that validates registry structure
    _registry_error : Helper that constructs AugmentRegistryError instances

    Examples
    --------
    >>> from pathlib import Path
    >>> def mock_reader(path: Path) -> dict:
    ...     return {"key": "value"}
    >>> result = _read_yaml(Path("/tmp/test.yaml"), mock_reader, source="augment")
    >>> result == {"key": "value"}
    True
    """
    try:
        return reader(resolved)
    except FileNotFoundError as exc:  # pragma: no cover - filesystem behaviour
        raise _registry_error(
            source=source,
            resolved=resolved,
            detail=f"File '{resolved}' does not exist.",
            status=404,
        ) from exc
    except yaml.YAMLError as exc:
        raise _registry_error(
            source=source,
            resolved=resolved,
            detail=f"Failed to parse YAML: {exc}",
            status=422,
        ) from exc
    except OSError as exc:  # pragma: no cover - I/O failure
        raise _registry_error(
            source=source,
            resolved=resolved,
            detail=f"I/O error: {exc.__class__.__name__}",
            status=500,
        ) from exc


def _registry_error(
    *, source: str, resolved: Path, detail: str, status: int
) -> AugmentRegistryError:
    """Build AugmentRegistryError with Problem Details payload.

    Parameters
    ----------
    source : str
        Source identifier ("augment" or "registry").
    resolved : Path
        Resolved file path.
    detail : str
        Error detail message.
    status : int
        HTTP status code for Problem Details.

    Returns
    -------
    AugmentRegistryError
        Exception with Problem Details payload.
    """
    problem = build_problem_details(
        ProblemDetailsParams(
            type=_PROBLEM_TYPE,
            title=_PROBLEM_TITLE,
            status=status,
            detail=detail,
            instance=f"urn:cli:{source}:{resolved.name}",
            extensions={"path": str(resolved)},
        )
    )
    return AugmentRegistryError(problem)


def _validation_error(
    source: str, resolved: Path, exc: ValidationError
) -> AugmentRegistryValidationError:
    """Build AugmentRegistryValidationError from Pydantic ValidationError.

    Parameters
    ----------
    source : str
        Source identifier ("augment" or "registry").
    resolved : Path
        Resolved file path.
    exc : ValidationError
        Pydantic validation error.

    Returns
    -------
    AugmentRegistryValidationError
        Exception with Problem Details payload including validation errors.
    """
    errors_raw = [
        {
            "loc": ".".join(str(token) for token in error["loc"]),
            "msg": str(error["msg"]),
            "type": str(error["type"]),
        }
        for error in exc.errors()
    ]
    errors_json: list[JsonValue] = []
    for entry in errors_raw:
        json_entry: dict[str, JsonValue] = {
            "loc": entry["loc"],
            "msg": entry["msg"],
            "type": entry["type"],
        }
        errors_json.append(json_entry)
    first_msg = str(errors_raw[0]["msg"]) if errors_raw else "Validation error"
    detail = f"{source.capitalize()} metadata validation failed: {first_msg}"
    problem = build_problem_details(
        ProblemDetailsParams(
            type=_PROBLEM_TYPE,
            title=_PROBLEM_TITLE,
            status=422,
            detail=detail,
            instance=f"urn:cli:{source}:{resolved.name}",
            extensions={
                "path": str(resolved),
                "errors": errors_json,
            },
        )
    )
    return AugmentRegistryValidationError(problem)


def _coerce_mapping(value: object) -> dict[str, object]:
    """Coerce value to string-keyed mapping.

    Parameters
    ----------
    value : object
        Value to coerce.

    Returns
    -------
    dict[str, object]
        String-keyed dictionary, empty if value is not a mapping.
    """
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _coerce_mapping_list(value: object) -> list[dict[str, object]]:
    """Coerce value to list of string-keyed mappings.

    Parameters
    ----------
    value : object
        Value to coerce.

    Returns
    -------
    list[dict[str, object]]
        List of string-keyed dictionaries, empty if value is not a sequence of mappings.
    """
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [_coerce_mapping(item) for item in value if isinstance(item, Mapping)]


@lru_cache(maxsize=16)
def _cached_augment(path_str: str) -> AugmentMetadataModel:
    """Load augment metadata with caching.

    Parameters
    ----------
    path_str : str
        String path to augment YAML file.

    Returns
    -------
    AugmentMetadataModel
        Cached augment metadata model.
    """
    return _load_augment(Path(path_str), _default_yaml_reader)


@lru_cache(maxsize=16)
def _cached_registry(path_str: str) -> RegistryMetadataModel:
    """Load registry metadata with caching.

    Parameters
    ----------
    path_str : str
        String path to registry YAML file.

    Returns
    -------
    RegistryMetadataModel
        Cached registry metadata model.
    """
    return _load_registry(Path(path_str), _default_yaml_reader)


def _default_yaml_reader(path: Path) -> object:
    """Return a parsed YAML payload for ``path`` using ``yaml.safe_load``.

    Parameters
    ----------
    path : Path
        File to deserialize.

    Returns
    -------
    object
        Parsed YAML content (dictionary, list, or scalar). Returns an empty dict when the file is empty.
    """
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


__all__ = [
    "AugmentMetadataModel",
    "AugmentRegistryError",
    "AugmentRegistryValidationError",
    "RegistryInterfaceModel",
    "RegistryMetadataModel",
    "RegistryOperationModel",
    "TagGroupModel",
    "ToolingMetadataModel",
    "clear_cache",
    "load_augment",
    "load_registry",
    "load_tooling_metadata",
    "render_problem_details",
]
