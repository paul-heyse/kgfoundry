"""Helpers for loading navigation metadata aligned with CLI tooling contracts."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import sys
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import suppress
from functools import cache, lru_cache
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pydantic import BaseModel, ConfigDict, Field, model_validator
    from tools import (
        AugmentMetadataModel,
        OperationOverrideModel,
        RegistryInterfaceModel,
        RegistryOperationModel,
        ToolingMetadataModel,
    )
else:  # pragma: no cover - runtime import guarded

    @lru_cache(maxsize=1)
    def _pydantic_module() -> ModuleType:
        """Return pydantic module without introducing circular imports.

        Returns
        -------
        ModuleType
            Imported :mod:`pydantic` module reference.

        Raises
        ------
        ImportError
            If :mod:`pydantic` is not installed in the current environment.
        """
        try:
            return importlib.import_module("pydantic")
        except ImportError as exc:  # pragma: no cover - optional dependency
            msg = "pydantic is required for navigation metadata handling"
            raise ImportError(msg) from exc

    _pydantic = _pydantic_module()
    BaseModel = _pydantic.BaseModel
    ConfigDict = _pydantic.ConfigDict
    Field = _pydantic.Field
    model_validator = _pydantic.model_validator

JsonValue = str | int | float | bool | dict[str, "JsonValue"] | list["JsonValue"] | None
type NavMetadataIterator = Generator[tuple[str, JsonValue]]

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
        """Collect unknown fields into extras dictionary.

        Parameters
        ----------
        value : object
            Raw input value (dict or other object).

        Returns
        -------
        object
            Value with unknown fields moved to extras dictionary.
        """
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
        """Normalize tags and problem_details by removing duplicates.

        Returns
        -------
        NavSymbolModel
            Self if no changes needed, or new instance with deduplicated
            tags and problem_details tuples.
        """
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
        """Ensure symbols tuple has no duplicates.

        Returns
        -------
        NavSectionModel
            Self if no changes needed, or new instance with deduplicated
            symbols tuple.
        """
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
        """Collect unknown fields into extras dictionary.

        Parameters
        ----------
        value : object
            Raw input value (dict or other object).

        Returns
        -------
        object
            Value with unknown fields moved to extras dictionary.
        """
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
        """Normalize tags by removing duplicates.

        Returns
        -------
        NavModuleMeta
            Self if no changes needed, or new instance with deduplicated
            tags tuple.
        """
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
        """Collect unknown fields into extras dictionary.

        Parameters
        ----------
        value : object
            Raw input value (dict or other object).

        Returns
        -------
        object
            Value with unknown fields moved to extras dictionary.
        """
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
        """Normalize exports by removing duplicates.

        Returns
        -------
        NavMetadataModel
            Self if no changes needed, or new instance with deduplicated
            exports tuple.
        """
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

    def __iter__(self) -> Generator[tuple[str, JsonValue]]:
        """Iterate over flattened key-value pairs for dictionary compatibility.

        Extended Summary
        ----------------
        This method enables dictionary-like iteration over navigation metadata,
        yielding key-value pairs from the flattened representation that includes
        both standard fields and extras. It delegates to the underlying mapping
        via ``yield from``, making it compatible with dictionary iteration patterns.
        This implementation supports the iterator protocol, allowing the model to
        be used in for-loops, dict constructors, and other iteration contexts
        where dictionary-like behavior is expected.

        Yields
        ------
        Generator[tuple[str, JsonValue]]
            Generator yielding key and value pairs for navigation metadata entries. Keys include
            standard fields (title, exports, sections, etc.) and any additional
            fields from the extras dictionary. Each tuple represents a key-value
            pair from the flattened metadata.

        Notes
        -----
        This method implements the iterator protocol using ``yield from`` to
        delegate to the underlying mapping's items. The function is a generator
        (uses ``yield from``) and returns a generator object that can be used
        in for-loops, dict constructors, and other iteration contexts.
        Time complexity O(n) where n is the number of metadata entries; space
        complexity O(1) aside from the generator object. No I/O or side effects.

        Examples
        --------
        >>> model = NavMetadataModel(
        ...     title="test",
        ...     exports=("func1",),
        ...     sections=(),
        ...     module_meta=NavModuleMeta(tags=()),
        ...     symbols={},
        ... )
        >>> dict(model)  # Convert to dictionary
        {'title': 'test', 'exports': ('func1',), ...}
        >>> for key, value in model:  # Iterate like a dictionary
        ...     print(f"{key}: {value}")
        title: test
        exports: ('func1',)
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
    """Convert string to URL-friendly slug.

    Normalizes a string by lowercasing, replacing slashes with hyphens,
    and joining words with hyphens.

    Parameters
    ----------
    value : str
        String to convert to slug.

    Returns
    -------
    str
        URL-friendly slug (lowercase, hyphen-separated).
    """
    return "-".join(value.strip().lower().replace("/", "-").split())


def _default_nav_payload(package: str, exports: Sequence[str]) -> dict[str, Any]:
    """Build default navigation payload structure.

    Creates a default navigation metadata structure with package name as title,
    normalized exports, a default "public-api" section, and empty symbols.

    Parameters
    ----------
    package : str
        Package name to use as title.
    exports : Sequence[str]
        Public export names to include in exports and symbols.

    Returns
    -------
    dict[str, Any]
        Default navigation payload dictionary with title, exports, sections,
        module_meta, and symbols fields.
    """
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
    """Convert raw navigation data to typed NavMetadataModel.

    Merges raw navigation data with default payload structure, normalizes
    exports and symbols, and validates the result as a NavMetadataModel.

    Parameters
    ----------
    package : str
        Package name for default payload generation.
    raw : Mapping[str, Any]
        Raw navigation metadata dictionary from sidecar or runtime.
    exports : Sequence[str]
        Public export names to use if raw data doesn't specify exports.

    Returns
    -------
    NavMetadataModel
        Validated navigation metadata model with merged defaults and raw data.
    """
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
    """Generate candidate symbol names for a registry operation.

    Creates candidate symbol names from the operation key and operation_id,
    normalizing hyphens to underscores for Python identifier compatibility.

    Parameters
    ----------
    operation : RegistryOperationModel
        Registry operation model with operation_id.
    key : str
        Operation key from registry.

    Returns
    -------
    list[str]
        List of candidate symbol names (normalized, non-empty).
    """
    raw_id = operation.operation_id or key
    tokens = [
        key.replace("-", "_"),
        raw_id.split(".")[-1].replace("-", "_"),
    ]
    return [token for token in tokens if token]


def _augment_operation_candidates(operation_id: str) -> list[str]:
    """Generate candidate symbol name from augment operation ID.

    Extracts the last component from a dotted operation ID and normalizes
    hyphens to underscores for Python identifier compatibility.

    Parameters
    ----------
    operation_id : str
        Augment operation ID (may be dotted, e.g., "api.v1.search").

    Returns
    -------
    list[str]
        List containing a single candidate symbol name.
    """
    return [operation_id.rsplit(".", maxsplit=1)[-1].replace("-", "_")]


def _load_cli_tooling_metadata() -> ToolingMetadataModel | None:
    """Load CLI tooling metadata from augment and registry files.

    Dynamically imports the tools module and loads tooling metadata from
    the configured augment and registry YAML files. Returns None if the
    tools module is unavailable or if files are missing/invalid.

    Returns
    -------
    ToolingMetadataModel | None
        Loaded tooling metadata if available, None otherwise.
    """
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
    """Return cached CLI tooling metadata.

    Caches the result of _load_cli_tooling_metadata() to avoid repeated
    file I/O and parsing operations.

    Returns
    -------
    ToolingMetadataModel | None
        Cached tooling metadata if available, None otherwise.
    """
    return _load_cli_tooling_metadata()


def _candidate_modules(package: str) -> list[str]:
    """Generate candidate module names for package matching.

    Creates a list of parent module names by progressively removing
    the rightmost components. Used to match packages to registry interfaces.

    Parameters
    ----------
    package : str
        Fully qualified package name (e.g., "kgfoundry_common.errors").

    Returns
    -------
    list[str]
        List of candidate module names from most specific to least specific
        (e.g., ["kgfoundry_common.errors", "kgfoundry_common"]).
    """
    parts = package.split(".")
    return [".".join(parts[:index]) for index in range(len(parts), 0, -1)]


def _resolve_interface_for_package(
    package: str,
) -> tuple[ToolingMetadataModel, RegistryInterfaceModel] | None:
    """Resolve registry interface for a package.

    Matches a package name to a registry interface by checking candidate
    module names against interface module fields. Returns the matching
    interface and its metadata if found.

    Parameters
    ----------
    package : str
        Fully qualified package name to resolve interface for.

    Returns
    -------
    tuple[ToolingMetadataModel, RegistryInterfaceModel] | None
        Tuple of (metadata, interface) if a match is found, None otherwise.
    """
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
    """Build operation override map for an interface.

    Filters augment operation overrides to those relevant to the interface's
    operations, keyed by symbol candidate names.

    Parameters
    ----------
    augment : AugmentMetadataModel
        Augment metadata with operation overrides.
    interface_operations : Sequence[RegistryOperationModel]
        Operations from the registry interface.

    Returns
    -------
    dict[str, OperationOverrideModel]
        Dictionary mapping symbol names to operation override models.
    """
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
    """Build operation map for an interface keyed by symbol candidates.

    Creates a mapping from symbol candidate names to registry operation
    models, handling multiple candidates per operation.

    Parameters
    ----------
    interface : RegistryInterfaceModel
        Registry interface with operations.

    Returns
    -------
    dict[str, RegistryOperationModel]
        Dictionary mapping symbol names to registry operation models.
    """
    operations: dict[str, RegistryOperationModel] = {}
    for key, operation in interface.operations.items():
        for candidate in _registry_operation_candidates(operation, key):
            operations.setdefault(candidate, operation)
    return operations


def _cli_module_meta(interface: RegistryInterfaceModel) -> NavModuleMeta:
    """Extract module metadata from registry interface.

    Converts a registry interface to NavModuleMeta, extracting known fields
    and placing unknown fields in extras.

    Parameters
    ----------
    interface : RegistryInterfaceModel
        Registry interface to extract metadata from.

    Returns
    -------
    NavModuleMeta
        Module metadata model with interface fields and extras.
    """
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
    """Return the first non-empty string from candidates.

    Parameters
    ----------
    *candidates : str | None
        Candidate strings to check (may include None).

    Returns
    -------
    str | None
        First non-empty string found, or None if all are empty/None.
    """
    for candidate in candidates:
        if candidate:
            return candidate
    return None


def _first_non_empty_sequence(*candidates: Sequence[str] | None) -> tuple[str, ...]:
    """Return the first non-empty sequence from candidates, deduplicated.

    Parameters
    ----------
    *candidates : Sequence[str] | None
        Candidate sequences to check (may include None).

    Returns
    -------
    tuple[str, ...]
        First non-empty sequence as a deduplicated tuple, or empty tuple
        if all are empty/None.
    """
    for candidate in candidates:
        if candidate:
            return tuple(dict.fromkeys(candidate))
    return ()


def _build_symbol_metadata(
    registry_op: RegistryOperationModel | None,
    override: OperationOverrideModel | None,
) -> NavSymbolModel:
    """Build symbol metadata from registry operation and override.

    Merges fields from registry operation and override, with override
    taking precedence. Extracts extras and special fields (examples,
    env, code_samples) from override payload.

    Parameters
    ----------
    registry_op : RegistryOperationModel | None
        Registry operation model (may be None).
    override : OperationOverrideModel | None
        Operation override model (may be None).

    Returns
    -------
    NavSymbolModel
        Symbol metadata model with merged fields from both sources.
    """
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
    """Build symbol metadata dictionary from CLI sources.

    Creates NavSymbolModel instances for each export, merging registry
    operations and overrides.

    Parameters
    ----------
    exports : Sequence[str]
        Public export names to build symbols for.
    registry_ops : Mapping[str, RegistryOperationModel]
        Registry operations keyed by symbol name.
    overrides : Mapping[str, OperationOverrideModel]
        Operation overrides keyed by symbol name.

    Returns
    -------
    dict[str, NavSymbolModel]
        Dictionary mapping symbol names to their metadata models.
    """
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
    """Filter symbols that match tag group tags.

    Returns symbols whose tags intersect with the tag group's tags.

    Parameters
    ----------
    symbol_tags : Mapping[str, tuple[str, ...]]
        Dictionary mapping symbol names to their tag tuples.
    tag_group_tags : Sequence[str]
        Tags from the tag group to match against.

    Returns
    -------
    list[str]
        List of symbol names that have at least one matching tag.
    """
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
    """Build navigation sections from CLI augment metadata.

    Creates sections from tag groups in augment metadata, assigning symbols
    to sections based on tag matching. Remaining symbols are placed in a
    default "public-api" section.

    Parameters
    ----------
    augment : AugmentMetadataModel
        Augment metadata with tag groups.
    symbols : Mapping[str, NavSymbolModel]
        Symbol metadata dictionary keyed by symbol name.

    Returns
    -------
    tuple[NavSectionModel, ...]
        Tuple of section models with assigned symbols.
    """
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
    """Build navigation metadata from CLI tooling contracts.

    Resolves registry interface for the package and constructs navigation
    metadata using registry operations, augment overrides, and tag groups.
    Returns None if no interface is found.

    Parameters
    ----------
    package : str
        Fully qualified package name.
    exports : Sequence[str]
        Public export names.

    Returns
    -------
    NavMetadataModel | None
        Navigation metadata model if interface is found, None otherwise.
    """
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
    """Build navigation metadata from sidecar files or runtime navmap.

    Loads navigation data from package sidecar files (_nav.json) or runtime
    __navmap__ attribute, falling back to default payload if neither exists.

    Parameters
    ----------
    package : str
        Fully qualified package name.
    exports : Sequence[str]
        Public export names for default payload generation.

    Returns
    -------
    NavMetadataModel
        Navigation metadata model from sidecar/runtime or defaults.
    """
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
        Public export names exposed via ``__all__``.
        These drive the default section and symbol lists
        when metadata omits explicit values.

    Returns
    -------
    NavMetadataModel
        Typed navigation metadata. The model implements the mapping protocol
        so existing callers that expect a dictionary continue to work while
        new code can rely on typed accessors.
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
