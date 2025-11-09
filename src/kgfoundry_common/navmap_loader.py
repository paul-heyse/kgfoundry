"""Helpers for loading navigation metadata aligned with CLI tooling contracts."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import suppress
from functools import cache
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from tools import (
        AugmentMetadataModel,
        OperationOverrideModel,
        RegistryInterfaceModel,
        RegistryOperationModel,
        ToolingMetadataModel,
    )

from pydantic import BaseModel, ConfigDict, Field, model_validator

JsonValue = str | int | float | bool | dict[str, "JsonValue"] | list["JsonValue"] | None
type NavMetadataIterator = Iterator[tuple[str, JsonValue]]

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_AUGMENT_PATH = REPO_ROOT / "openapi" / "_augment_cli.yaml"
CLI_REGISTRY_PATH = REPO_ROOT / "tools" / "mkdocs_suite" / "api_registry.yaml"


def _candidate_sidecars(package: str) -> list[Path]:
    """Return ordered sidecar file candidates for ``package``.

    Parameters
    ----------
    package : str
        Fully qualified package name to find sidecars for.

    Returns
    -------
    list[Path]
        Candidate paths in priority order where `_nav.json` sidecars may live.
    """
    spec = importlib.util.find_spec(package)
    if spec is None:
        return []

    candidates: list[Path] = []
    origin = Path(spec.origin) if isinstance(spec.origin, str) else None

    if origin is not None:
        if origin.name != "__init__.py":
            candidates.append(origin.with_name(f"{origin.stem}._nav.json"))
        candidates.append(origin.parent / "_nav.json")

    if spec.submodule_search_locations:
        for location in spec.submodule_search_locations:
            location_path = Path(location)
            candidate = location_path / "_nav.json"
            if candidate not in candidates:
                candidates.append(candidate)

    # Remove duplicates while preserving order.
    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)

    return deduped


def _load_sidecar_data(package: str) -> dict[str, Any]:
    """Return metadata loaded from package sidecar files.

    Parameters
    ----------
    package : str
        Fully qualified package name to load sidecar data for.

    Returns
    -------
    dict[str, Any]
        Parsed JSON payload when a sidecar exists, otherwise an empty dict.
    """
    for candidate in _candidate_sidecars(package):
        if candidate.is_file():
            with candidate.open("r", encoding="utf-8") as handle:
                return json.load(handle)
    return {}


def _load_runtime_nav(package: str) -> dict[str, Any]:
    """Return runtime ``__navmap__`` data if available.

    Parameters
    ----------
    package : str
        Fully qualified package name to load runtime navmap for.

    Returns
    -------
    dict[str, Any]
        Deep-copied runtime navmap if exposed by the module, else empty dict.
    """
    module = sys.modules.get(package)
    if module is None:
        try:
            module = importlib.import_module(package)
        except ImportError:
            module = None
    if module is None:
        return {}
    runtime_nav = getattr(module, "__navmap__", None)
    if isinstance(runtime_nav, dict):
        return copy.deepcopy(runtime_nav)
    return {}


class NavSymbolModel(BaseModel):
    """Symbol-level metadata exposed in navigation payloads."""

    model_config = ConfigDict(frozen=True)

    summary: str | None = None
    description: str | None = None
    handler: str | None = None
    tags: tuple[str, ...] = ()
    problem_details: tuple[str, ...] = ()
    extras: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_extras(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        known = {
            "summary",
            "description",
            "handler",
            "tags",
            "problem_details",
            "extras",
        }
        extras = {key: data.pop(key) for key in list(data.keys()) if key not in known}
        data.setdefault("extras", {}).update(extras)
        return data

    @model_validator(mode="after")
    def _normalise(self) -> NavSymbolModel:
        tags = tuple(dict.fromkeys(self.tags))
        problem_details = tuple(dict.fromkeys(self.problem_details))
        if tags == self.tags and problem_details == self.problem_details:
            return self
        return self.model_copy(update={"tags": tags, "problem_details": problem_details})


class NavSectionModel(BaseModel):
    """Section grouping symbols for navigation."""

    model_config = ConfigDict(frozen=True)

    id: str
    symbols: tuple[str, ...]
    title: str | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _ensure_tuple(self) -> NavSectionModel:
        symbols = tuple(dict.fromkeys(self.symbols))
        if symbols == self.symbols:
            return self
        return self.model_copy(update={"symbols": symbols})


class NavModuleMeta(BaseModel):
    """Module-level metadata derived from registry interfaces or sidecars."""

    model_config = ConfigDict(frozen=True)

    owner: str | None = None
    stability: str | None = None
    since: str | None = None
    spec: str | None = None
    augment: str | None = None
    binary: str | None = None
    protocol: str | None = None
    tags: tuple[str, ...] = ()
    extras: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_extras(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        known = {
            "owner",
            "stability",
            "since",
            "spec",
            "augment",
            "binary",
            "protocol",
            "tags",
            "extras",
        }
        extras = {key: data.pop(key) for key in list(data.keys()) if key not in known}
        data.setdefault("extras", {}).update(extras)
        return data

    @model_validator(mode="after")
    def _normalise(self) -> NavModuleMeta:
        tags = tuple(dict.fromkeys(self.tags))
        if tags == self.tags:
            return self
        return self.model_copy(update={"tags": tags})


class NavMetadataModel(BaseModel):
    """Typed navigation metadata aligned with historical navmap structure."""

    model_config = ConfigDict(frozen=True)

    title: str
    exports: tuple[str, ...]
    sections: tuple[NavSectionModel, ...]
    module_meta: NavModuleMeta
    symbols: dict[str, NavSymbolModel]
    synopsis: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_extras(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        known = {
            "title",
            "synopsis",
            "exports",
            "sections",
            "module_meta",
            "symbols",
            "extras",
        }
        extras = {key: data.pop(key) for key in list(data.keys()) if key not in known}
        data.setdefault("extras", {}).update(extras)
        return data

    @model_validator(mode="after")
    def _normalise(self) -> NavMetadataModel:
        exports = tuple(dict.fromkeys(self.exports))
        if exports == self.exports:
            return self
        return self.model_copy(update={"exports": exports})

    def __getitem__(self, key: str) -> JsonValue:
        """Return flattened navigation metadata value for ``key``.

        Parameters
        ----------
        key : str
            Key to look up in the flattened metadata.

        Returns
        -------
        JsonValue
            Value associated with ``key`` after merging `extras`.
        """
        return self.as_mapping()[key]

    def __iter__(self) -> Iterator[tuple[str, JsonValue]]:
        """Iterate over flattened key-value pairs for dictionary compatibility.

        This method enables dictionary-like iteration over navigation metadata,
        yielding key-value pairs from the flattened representation that includes
        both standard fields and extras. It delegates to the underlying mapping
        via ``yield from``, making it compatible with dictionary iteration patterns.

        Yields
        ------
        tuple[str, JsonValue]
            Key and value pairs for navigation metadata entries. Keys include
            standard fields (title, exports, sections, etc.) and any additional
            fields from the extras dictionary. Each tuple represents a key-value
            pair from the flattened metadata.

        Notes
        -----
        This method implements the iterator protocol using ``yield from`` to
        delegate to the underlying mapping's items. The function is a generator
        (uses ``yield from``) and returns a generator object that can be used
        in for-loops, dict constructors, and other iteration contexts.

        Examples
        --------
        >>> model = NavMetadataModel(...)
        >>> dict(model)  # Convert to dictionary
        >>> for key, value in model:  # Iterate like a dictionary
        ...     print(f"{key}: {value}")
        """
        yield from self.as_mapping().items()

    def as_mapping(self) -> dict[str, JsonValue]:
        """Return flattened navigation metadata as a standard dictionary.

        Returns
        -------
        dict[str, JsonValue]
            Navigation metadata with extras merged into top-level keys.
        """
        data = super().model_dump()
        extras = data.pop("extras", {})
        if isinstance(extras, Mapping):
            data.update(extras)
        return cast("dict[str, JsonValue]", data)


def _slugify(value: str) -> str:
    return "-".join(value.strip().lower().replace("/", "-").split())


def _default_nav_payload(package: str, exports: Sequence[str]) -> dict[str, Any]:
    normalized_exports = list(dict.fromkeys(str(item) for item in exports))
    return {
        "title": package,
        "exports": normalized_exports,
        "sections": [
            {
                "id": "public-api",
                "title": "Public API",
                "symbols": normalized_exports,
            }
        ],
        "module_meta": {},
        "symbols": {symbol: {} for symbol in normalized_exports},
    }


def _to_nav_metadata(
    package: str, raw: Mapping[str, Any], exports: Sequence[str]
) -> NavMetadataModel:
    sidecar_exports = raw.get("exports") if isinstance(raw.get("exports"), Sequence) else None
    export_candidates = (
        list(dict.fromkeys(str(item) for item in sidecar_exports))
        if sidecar_exports and not isinstance(sidecar_exports, (str, bytes))
        else list(dict.fromkeys(exports))
    )

    base = _default_nav_payload(package, export_candidates)
    merged = {**base, **raw}
    merged["exports"] = export_candidates
    symbols_value = merged.get("symbols")
    if isinstance(symbols_value, Mapping):
        typed_symbols: dict[str, Any] = dict(symbols_value)
    else:
        typed_symbols = {}
    for symbol in export_candidates:
        typed_symbols.setdefault(symbol, {})
    merged["symbols"] = typed_symbols
    sections = merged.get("sections")
    if not sections:
        merged["sections"] = base["sections"]
    return NavMetadataModel.model_validate(merged)


def _registry_operation_candidates(operation: RegistryOperationModel, key: str) -> list[str]:
    raw_id = operation.operation_id or key
    tokens = [
        key.replace("-", "_"),
        raw_id.split(".")[-1].replace("-", "_"),
    ]
    return [token for token in tokens if token]


def _augment_operation_candidates(operation_id: str) -> list[str]:
    return [operation_id.rsplit(".", maxsplit=1)[-1].replace("-", "_")]


def _load_cli_tooling_metadata() -> ToolingMetadataModel | None:
    try:
        tools_module = import_module("tools")
    except ImportError:  # pragma: no cover - optional dependency
        return None
    load_tooling = getattr(tools_module, "load_tooling_metadata", None)
    if load_tooling is None:
        return None
    load_tooling_callable = cast("Callable[..., ToolingMetadataModel]", load_tooling)
    augment_error = cast(
        "type[BaseException]",
        getattr(tools_module, "AugmentRegistryError", RuntimeError),
    )
    if not CLI_AUGMENT_PATH.is_file() or not CLI_REGISTRY_PATH.is_file():
        return None
    try:
        return load_tooling_callable(
            augment_path=CLI_AUGMENT_PATH,
            registry_path=CLI_REGISTRY_PATH,
        )
    except (
        augment_error,
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ):
        return None


@cache
def _cached_cli_tooling_metadata() -> ToolingMetadataModel | None:
    return _load_cli_tooling_metadata()


def _candidate_modules(package: str) -> list[str]:
    parts = package.split(".")
    return [".".join(parts[:index]) for index in range(len(parts), 0, -1)]


def _resolve_interface_for_package(
    package: str,
) -> tuple[ToolingMetadataModel, RegistryInterfaceModel] | None:
    metadata = _cached_cli_tooling_metadata()
    if metadata is None:
        with suppress(AttributeError):  # pragma: no cover - python <3.9 safeguard
            _cached_cli_tooling_metadata.cache_clear()
        metadata = _cached_cli_tooling_metadata()
    if metadata is None:
        return None
    typed_metadata = metadata
    candidates = set(_candidate_modules(package))
    for interface in typed_metadata.registry.interfaces.values():
        module = interface.module
        if module and module in candidates:
            return typed_metadata, interface
    return None


def _operation_overrides_for_interface(
    augment: AugmentMetadataModel,
    interface_operations: Sequence[RegistryOperationModel],
) -> dict[str, OperationOverrideModel]:
    overrides: dict[str, OperationOverrideModel] = {}
    relevant_ids = {
        (operation.operation_id or "")
        for operation in interface_operations
        if operation.operation_id
    }
    for op_id, override in augment.operations.items():
        symbol = _augment_operation_candidates(op_id)[0]
        if not relevant_ids or op_id in relevant_ids:
            overrides.setdefault(symbol, override)
    return overrides


def _registry_operations_for_interface(
    interface: RegistryInterfaceModel,
) -> dict[str, RegistryOperationModel]:
    operations: dict[str, RegistryOperationModel] = {}
    for key, operation in interface.operations.items():
        for candidate in _registry_operation_candidates(operation, key):
            operations.setdefault(candidate, operation)
    return operations


def _cli_module_meta(interface: RegistryInterfaceModel) -> NavModuleMeta:
    payload = interface.to_payload()
    known = {
        "id",
        "module",
        "owner",
        "stability",
        "augment",
        "binary",
        "protocol",
        "spec",
        "description",
        "tags",
        "problem_details",
    }
    extras = {key: value for key, value in payload.items() if key not in known}
    return NavModuleMeta(
        owner=interface.owner,
        stability=interface.stability,
        augment=interface.augment,
        binary=interface.binary,
        protocol=interface.protocol,
        spec=interface.spec,
        tags=tuple(interface.tags),
        extras=extras,
    )


def _first_non_empty(*candidates: str | None) -> str | None:
    for candidate in candidates:
        if candidate:
            return candidate
    return None


def _first_non_empty_sequence(*candidates: Sequence[str] | None) -> tuple[str, ...]:
    for candidate in candidates:
        if candidate:
            return tuple(dict.fromkeys(candidate))
    return ()


def _build_symbol_metadata(
    registry_op: RegistryOperationModel | None,
    override: OperationOverrideModel | None,
) -> NavSymbolModel:
    summary = _first_non_empty(
        override.summary if override else None,
        registry_op.summary if registry_op else None,
    )
    description = _first_non_empty(
        override.description if override else None,
        registry_op.description if registry_op else None,
    )
    handler = _first_non_empty(
        override.handler if override else None,
        registry_op.handler if registry_op else None,
    )

    tags = _first_non_empty_sequence(
        override.tags if override else None,
        registry_op.tags if registry_op else None,
    )
    problem_details = _first_non_empty_sequence(
        override.problem_details if override else None,
        registry_op.problem_details if registry_op else None,
    )

    extras: dict[str, Any] = {}
    if override:
        extras.update(override.extras)
        override_payload = override.to_payload()
        for key in ("examples", "env", "code_samples"):
            if key in override_payload:
                extras.setdefault(key, override_payload[key])
    if registry_op:
        extras.update(registry_op.extras)
    return NavSymbolModel(
        summary=summary,
        description=description,
        handler=handler,
        tags=tags,
        problem_details=problem_details,
        extras=extras,
    )


def _symbols_from_cli(
    exports: Sequence[str],
    registry_ops: Mapping[str, RegistryOperationModel],
    overrides: Mapping[str, OperationOverrideModel],
) -> dict[str, NavSymbolModel]:
    symbols: dict[str, NavSymbolModel] = {}
    for symbol in dict.fromkeys(exports):
        registry_op = registry_ops.get(symbol)
        override = overrides.get(symbol)
        symbols[symbol] = _build_symbol_metadata(registry_op, override)
    return symbols


def _section_symbols(
    symbol_tags: Mapping[str, tuple[str, ...]],
    tag_group_tags: Sequence[str],
) -> list[str]:
    collected: list[str] = []
    tag_set = set(tag_group_tags)
    for symbol, tags in symbol_tags.items():
        if any(tag in tag_set for tag in tags):
            collected.append(symbol)
    return collected


def _sections_from_cli(
    augment: AugmentMetadataModel,
    symbols: Mapping[str, NavSymbolModel],
) -> tuple[NavSectionModel, ...]:
    section_models: list[NavSectionModel] = []
    remaining_symbols = list(symbols)
    for tag_group in augment.tag_groups:
        section_symbols = _section_symbols(
            {symbol: model.tags for symbol, model in symbols.items()},
            tag_group.tags,
        )
        if not section_symbols:
            continue
        for symbol in section_symbols:
            if symbol in remaining_symbols:
                remaining_symbols.remove(symbol)
        section_models.append(
            NavSectionModel(
                id=_slugify(tag_group.name),
                title=tag_group.name,
                description=tag_group.description,
                symbols=tuple(section_symbols),
            )
        )
    if remaining_symbols:
        section_models.append(
            NavSectionModel(
                id="public-api",
                title="Public API",
                symbols=tuple(remaining_symbols),
            )
        )
    return tuple(section_models)


def _cli_nav_metadata(package: str, exports: Sequence[str]) -> NavMetadataModel | None:
    resolved = _resolve_interface_for_package(package)
    if resolved is None:
        return None
    metadata, interface = resolved
    augment = metadata.augment
    registry_ops_map = _registry_operations_for_interface(interface)
    interface_operations = list(interface.operations.values())
    overrides_map = _operation_overrides_for_interface(augment, interface_operations)

    normalized_exports = list(dict.fromkeys(exports))
    symbols = _symbols_from_cli(normalized_exports, registry_ops_map, overrides_map)

    sections = _sections_from_cli(augment, symbols)
    title = interface.description or interface.module or package
    module_meta = _cli_module_meta(interface)
    synopsis = interface.description
    extras: dict[str, Any] = {
        "interface_id": interface.identifier,
    }
    return NavMetadataModel(
        title=title,
        synopsis=synopsis,
        exports=tuple(dict.fromkeys(normalized_exports)),
        sections=sections,
        module_meta=module_meta,
        symbols=symbols,
        extras=extras,
    )


def _sidecar_nav_metadata(package: str, exports: Sequence[str]) -> NavMetadataModel:
    data = _load_sidecar_data(package)
    if not data:
        data = _load_runtime_nav(package)
    if not data:
        data = {}
    return _to_nav_metadata(package, data, exports)


@cache
def load_nav_metadata(package: str, exports: tuple[str, ...]) -> NavMetadataModel:
    """Return navigation metadata for ``package`` using shared CLI contracts when available.

    Parameters
    ----------
    package : str
        Fully qualified package name whose metadata should be loaded.
    exports : tuple[str, ...]
        Public export names exposed via ``__all__``. These drive the default section and symbol lists
        when metadata omits explicit values.

    Returns
    -------
    NavMetadataModel
        Typed navigation metadata. The model implements the mapping protocol so existing callers that
        expect a dictionary continue to work while new code can rely on typed accessors.
    """
    cli_metadata = _cli_nav_metadata(package, exports)
    if cli_metadata is not None:
        return cli_metadata
    return _sidecar_nav_metadata(package, exports)


def clear_navmap_caches() -> None:
    """Clear internal navigation metadata caches.

    Intended for tests and tooling that need to force regeneration after modifying augment or
    registry metadata sources at runtime.
    """
    load_nav_metadata.cache_clear()
    with suppress(AttributeError):  # pragma: no cover - python <3.9 safeguard
        _cached_cli_tooling_metadata.cache_clear()
