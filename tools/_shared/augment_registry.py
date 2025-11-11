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
from tools._shared.logging import get_logger
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

LOGGER = get_logger(__name__)

Reader = Callable[[Path], object]

_PROBLEM_TYPE = "https://kgfoundry.dev/problems/augment-registry"
_PROBLEM_TITLE = "CLI augment/registry error"


def _ensure_str_sequence(value: object) -> tuple[str, ...]:
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
        if value is None:
            return None
        return str(value)

    @field_validator("tags", "env", "problem_details", mode="before")
    @classmethod
    def _coerce_tuple(cls, value: object) -> tuple[str, ...]:
        return _ensure_str_sequence(value)

    @field_validator("examples", mode="before")
    @classmethod
    def _coerce_examples(cls, value: object) -> tuple[str, ...]:
        return _ensure_str_sequence(value)

    @field_validator("code_samples", mode="before")
    @classmethod
    def _coerce_samples(cls, value: object) -> tuple[Mapping[str, object], ...]:
        if value is None:
            return ()
        if isinstance(value, Sequence):
            return tuple(item for item in value if isinstance(item, Mapping))
        return ()

    @field_validator("extras", mode="before")
    @classmethod
    def _coerce_extras(cls, value: object) -> Mapping[str, object]:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return {str(k): v for k, v in value.items()}
        return {}

    def to_payload(self) -> dict[str, object]:
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
        return str(value)

    @field_validator("description", mode="before")
    @classmethod
    def _coerce_description(cls, value: object) -> object:
        if value is None:
            return None
        return str(value)

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: object) -> tuple[str, ...]:
        tags = _ensure_str_sequence(value)
        seen: set[str] = set()
        ordered: list[str] = []
        for tag in tags:
            if tag not in seen:
                ordered.append(tag)
                seen.add(tag)
        return tuple(ordered)

    def to_payload(self) -> dict[str, object]:
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
        if value is None:
            return None
        return str(value)

    @field_validator("operation_id", mode="before")
    @classmethod
    def _coerce_operation_id(cls, value: object) -> object:
        if value is None:
            return None
        return str(value)

    @field_validator("tags", "env", "problem_details", mode="before")
    @classmethod
    def _coerce_sequences(cls, value: object) -> tuple[str, ...]:
        return _ensure_str_sequence(value)

    def to_payload(self, default_operation_id: str) -> dict[str, object]:
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
        if value is None:
            return None
        return str(value)

    @field_validator("tags", "problem_details", mode="before")
    @classmethod
    def _coerce_tuple(cls, value: object) -> tuple[str, ...]:
        return _ensure_str_sequence(value)

    def to_payload(self) -> dict[str, object]:
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
        return self.interfaces.get(identifier)

    def to_payload(self) -> dict[str, object]:
        return {
            identifier: interface.to_payload() for identifier, interface in self.interfaces.items()
        }

    def get_interface(self, identifier: str) -> Mapping[str, object] | None:
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

    Raises
    ------
    AugmentRegistryError
        Raised when either metadata payload cannot be loaded or validated.
    """
    try:
        augment = load_augment(augment_path, reader=augment_reader)
        registry = load_registry(registry_path, reader=registry_reader)
    except AugmentRegistryError as exc:
        LOGGER.debug(
            "Propagating augment/registry error during load_tooling_metadata",
            extra={
                "status": "error",
                "augment_path": str(augment_path),
                "registry_path": str(registry_path),
            },
        )
        raise AugmentRegistryError(exc.problem) from exc
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

    Raises
    ------
    AugmentRegistryError
        Raised when the augment file is missing, unreadable, or fails validation.
    """
    resolved = path.resolve()
    try:
        if reader is None:
            return _cached_augment(str(resolved))
        return _load_augment(resolved, reader)
    except AugmentRegistryError:
        LOGGER.debug(
            "Augment metadata load failed",
            extra={"status": "error", "path": str(resolved)},
        )
        raise


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

    Raises
    ------
    AugmentRegistryError
        Raised when the registry file is missing, unreadable, or fails validation.
    """
    resolved = path.resolve()
    try:
        if reader is None:
            return _cached_registry(str(resolved))
        return _load_registry(resolved, reader)
    except AugmentRegistryError:
        LOGGER.debug(
            "Registry metadata load failed",
            extra={"status": "error", "path": str(resolved)},
        )
        raise


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
    LOGGER.error(detail, extra={"status": "error", "path": str(resolved)})
    return AugmentRegistryError(problem)


def _validation_error(
    source: str, resolved: Path, exc: ValidationError
) -> AugmentRegistryValidationError:
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
    LOGGER.error(detail, extra={"status": "error", "path": str(resolved)})
    return AugmentRegistryValidationError(problem)


def _coerce_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _coerce_mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [_coerce_mapping(item) for item in value if isinstance(item, Mapping)]


@lru_cache(maxsize=16)
def _cached_augment(path_str: str) -> AugmentMetadataModel:
    return _load_augment(Path(path_str), _default_yaml_reader)


@lru_cache(maxsize=16)
def _cached_registry(path_str: str) -> RegistryMetadataModel:
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
