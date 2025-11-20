"""Shared registry for CLI context metadata consumed by the façade helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

from tools._shared.augment_registry import (
    AugmentMetadataModel,
    OperationOverrideModel,
    RegistryInterfaceModel,
    RegistryMetadataModel,
    ToolingMetadataModel,
)
from tools._shared.cli_tooling import (
    CLIToolingContext,
    CLIToolSettings,
    load_cli_tooling_context,
)
from tools._shared.paths import Paths


@dataclass(frozen=True, slots=True)
class CLIContextDefinition:
    """Describe the metadata required to materialise CLI context helpers."""

    command: str
    title: str
    interface_id: str
    operation_ids: Mapping[str, str]
    bin_name: str | None = None
    version_resolver: Callable[[], str] | None = None
    augment_path: Path | None = None
    registry_path: Path | None = None
    context_factory: Callable[[CLIToolSettings], CLIToolingContext] | None = None
    _operation_map: Mapping[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate and normalize CLI context definition fields.

        Validates that command and interface_id are non-empty strings, then
        normalizes the operation_ids mapping by filtering out empty keys or
        values and storing the result in _operation_map.

        Raises
        ------
        ValueError
            If command or interface_id is empty or whitespace-only.
        """
        if not self.command.strip():
            msg = "CLI command label must be a non-empty string."
            raise ValueError(msg)
        if not self.interface_id.strip():
            msg = "Interface identifier must be a non-empty string."
            raise ValueError(msg)
        normalised = {k: v for k, v in (self.operation_ids or {}).items() if k and v}
        object.__setattr__(self, "_operation_map", normalised)

    @property
    def bin_label(self) -> str:
        """Return the executable/bin label associated with the CLI."""
        return self.bin_name or self.command

    @property
    def operation_map(self) -> Mapping[str, str]:
        """Return the cleaned subcommand → operation identifier mapping."""
        return self._operation_map


def default_version_resolver(*packages: str) -> Callable[[], str]:
    """Return a callable that resolves the CLI version from the given packages.

    Parameters
    ----------
    *packages : str
        Package names to check for version resolution. The first package found
        will be used. If no packages are provided, defaults to checking
        "kgfoundry-tools" and "kgfoundry" in that order.

    Returns
    -------
    Callable[[], str]
        Callable that returns the first matching package version or ``"0.0.0"``.
    """
    package_candidates = tuple(packages) or ("kgfoundry-tools", "kgfoundry")

    def _resolve() -> str:
        """Resolve version from package metadata.

        Iterates through package candidates and returns the first matching
        package version found via importlib.metadata. Returns "0.0.0" if
        no packages are found.

        Returns
        -------
        str
            Package version string or "0.0.0" if not found.
        """
        for name in package_candidates:
            try:
                return metadata.version(name)
            except metadata.PackageNotFoundError:
                continue
        return "0.0.0"

    return _resolve


class CLIContextRegistry:
    """Registry storing CLI metadata definitions and cached materialisations."""

    def __init__(self) -> None:
        """Initialize empty registry with empty caches.

        Creates a new registry instance with empty dictionaries for definitions,
        settings cache, and context cache. Caches are populated on-demand via
        register(), settings_for(), and context_for() methods.
        """
        self._definitions: dict[str, CLIContextDefinition] = {}
        self._settings_cache: dict[str, CLIToolSettings] = {}
        self._context_cache: dict[str, CLIToolingContext] = {}

    def register(self, key: str, definition: CLIContextDefinition) -> None:
        """Register a CLI context definition.

        Parameters
        ----------
        key : str
            Registry key identifying the CLI context.
        definition : CLIContextDefinition
            CLI context metadata definition to register.

        Raises
        ------
        ValueError
            If the key is invalid or a conflicting definition already exists.
        """
        key = self._clean_key(key)
        existing = self._definitions.get(key)
        if existing is not None:
            if (
                existing.command == definition.command
                and existing.title == definition.title
                and existing.interface_id == definition.interface_id
                and existing.operation_map == definition.operation_map
                and existing.bin_name == definition.bin_name
            ):
                return
            msg = f"CLI definition already registered for key '{key}'."
            raise ValueError(msg)
        self._definitions[key] = definition
        self._settings_cache.pop(key, None)
        self._context_cache.pop(key, None)

    def definition_for(self, key: str) -> CLIContextDefinition:
        """Retrieve a CLI context definition by key.

        Parameters
        ----------
        key : str
            Registry key identifying the CLI context.

        Returns
        -------
        CLIContextDefinition
            The registered CLI context definition.

        """
        return self._definitions[self._normalise_key(key)]

    def settings_for(self, key: str) -> CLIToolSettings:
        """Retrieve or create CLI tool settings for a registered context.

        Parameters
        ----------
        key : str
            Registry key identifying the CLI context.

        Returns
        -------
        CLIToolSettings
            Cached or newly created CLI tool settings.

        """
        key = self._normalise_key(key)
        try:
            return self._settings_cache[key]
        except KeyError:
            definition = self.definition_for(key)
            augment_path, registry_path = self._resolve_paths(definition)
            version_resolver = definition.version_resolver or default_version_resolver()
            settings = CLIToolSettings(
                bin_name=definition.bin_label,
                title=definition.title,
                version=version_resolver(),
                augment_path=augment_path,
                registry_path=registry_path,
                interface_id=definition.interface_id,
            )
            self._settings_cache[key] = settings
            return settings

    def context_for(self, key: str) -> CLIToolingContext:
        """Retrieve or create a CLI tooling context for a registered CLI.

        Parameters
        ----------
        key : str
            Registry key identifying the CLI context.

        Returns
        -------
        CLIToolingContext
            Cached or newly created CLI tooling context.

        """
        key = self._normalise_key(key)
        try:
            return self._context_cache[key]
        except KeyError:
            definition = self.definition_for(key)
            loader = definition.context_factory or load_cli_tooling_context
            context = loader(self.settings_for(key))
            self._context_cache[key] = context
            return context

    def augment_for(self, key: str) -> AugmentMetadataModel:
        """Retrieve augment metadata for a registered CLI.

        Parameters
        ----------
        key : str
            Registry key identifying the CLI context.

        Returns
        -------
        AugmentMetadataModel
            Augment metadata from the CLI tooling context.

        """
        return self.context_for(key).augment

    def registry_for(self, key: str) -> RegistryMetadataModel:
        """Retrieve registry metadata for a registered CLI.

        Parameters
        ----------
        key : str
            Registry key identifying the CLI context.

        Returns
        -------
        RegistryMetadataModel
            Registry metadata from the CLI tooling context.

        """
        return self.context_for(key).registry

    def interface_for(self, key: str) -> RegistryInterfaceModel:
        """Retrieve interface metadata for a registered CLI.

        Parameters
        ----------
        key : str
            Registry key identifying the CLI context.

        Returns
        -------
        RegistryInterfaceModel
            Interface metadata matching the CLI's interface ID.

        Raises
        ------
        KeyError
            If the key is not found or the interface ID is missing from registry.
        """
        definition = self.definition_for(key)
        interface = self.registry_for(key).interface(definition.interface_id)
        if interface is None:
            msg = f"Registry metadata missing interface '{definition.interface_id}'."
            raise KeyError(msg)
        return interface

    def tooling_metadata_for(self, key: str) -> ToolingMetadataModel:
        """Retrieve combined tooling metadata for a registered CLI.

        Parameters
        ----------
        key : str
            Registry key identifying the CLI context.

        Returns
        -------
        ToolingMetadataModel
            Combined augment and registry metadata.

        """
        context = self.context_for(key)
        return ToolingMetadataModel(augment=context.augment, registry=context.registry)

    def operation_override_for(
        self,
        key: str,
        *,
        subcommand: str,
        tokens: Sequence[str] | None = None,
    ) -> OperationOverrideModel | None:
        """Retrieve operation override metadata for a subcommand.

        Parameters
        ----------
        key : str
            Registry key identifying the CLI context.
        subcommand : str
            Subcommand name to look up.
        tokens : Sequence[str] | None, optional
            Optional token sequence for override matching.

        Returns
        -------
        OperationOverrideModel | None
            Operation override if found, otherwise None.

        """
        definition = self.definition_for(key)
        operation_id = definition.operation_map.get(subcommand)
        if operation_id is None:
            return None
        return self.augment_for(key).operation_override(operation_id, tokens=tokens)

    @staticmethod
    def _clean_key(key: str) -> str:
        """Strip whitespace and validate registry key.

        Parameters
        ----------
        key : str
            Registry key to clean and validate.

        Returns
        -------
        str
            Stripped key string.

        Raises
        ------
        ValueError
            If key is empty or whitespace-only after stripping.
        """
        key = key.strip()
        if not key:
            msg = "CLI registry key must be a non-empty string."
            raise ValueError(msg)
        return key

    def _normalise_key(self, key: str) -> str:
        """Normalize and validate registry key against registered definitions.

        Cleans the key and verifies it exists in the registry. Raises KeyError
        with available keys if the key is not registered.

        Parameters
        ----------
        key : str
            Registry key to normalize and validate.

        Returns
        -------
        str
            Normalized key string.

        Raises
        ------
        KeyError
            If key is not registered in the registry (after cleaning).
            Also propagates ValueError from _clean_key if key is empty or whitespace-only.
        """
        key = self._clean_key(key)
        if key not in self._definitions:
            available = ", ".join(sorted(self._definitions))
            msg = f"Unknown CLI registry key '{key}'. Available keys: {available or '<none>'}."
            raise KeyError(msg)
        return key

    @staticmethod
    def _resolve_paths(definition: CLIContextDefinition) -> tuple[Path, Path]:
        """Resolve augment and registry file paths from definition.

        Returns paths from the definition if provided, otherwise discovers
        repository paths and uses default locations relative to repo root.

        Parameters
        ----------
        definition : CLIContextDefinition
            CLI context definition containing optional augment_path and
            registry_path fields.

        Returns
        -------
        tuple[Path, Path]
            Tuple of (augment_path, registry_path) resolved from definition
            or default repository locations.
        """
        if definition.augment_path is not None and definition.registry_path is not None:
            return definition.augment_path, definition.registry_path
        repo_paths = Paths.discover()
        augment_path = definition.augment_path or (
            repo_paths.repo_root / "openapi" / "_augment_cli.yaml"
        )
        registry_path = definition.registry_path or (
            repo_paths.repo_root / "tools" / "mkdocs_suite" / "api_registry.yaml"
        )
        return augment_path, registry_path


REGISTRY = CLIContextRegistry()


def register_cli(key: str, definition: CLIContextDefinition) -> None:
    """Register a CLI context definition in the global registry.

    Parameters
    ----------
    key : str
        Registry key identifying the CLI context.
    definition : CLIContextDefinition
        CLI context metadata definition to register.

    """
    REGISTRY.register(key, definition)


def definition_for(key: str) -> CLIContextDefinition:
    """Retrieve a CLI context definition by key from the global registry.

    Parameters
    ----------
    key : str
        Registry key identifying the CLI context.

    Returns
    -------
    CLIContextDefinition
        The registered CLI context definition.

    """
    return REGISTRY.definition_for(key)


def settings_for(key: str) -> CLIToolSettings:
    """Retrieve CLI tool settings for a registered context from the global registry.

    Parameters
    ----------
    key : str
        Registry key identifying the CLI context.

    Returns
    -------
    CLIToolSettings
        Cached or newly created CLI tool settings.

    """
    return REGISTRY.settings_for(key)


def context_for(key: str) -> CLIToolingContext:
    """Retrieve a CLI tooling context for a registered CLI from the global registry.

    Parameters
    ----------
    key : str
        Registry key identifying the CLI context.

    Returns
    -------
    CLIToolingContext
        Cached or newly created CLI tooling context.

    """
    return REGISTRY.context_for(key)


def augment_for(key: str) -> AugmentMetadataModel:
    """Retrieve augment metadata for a registered CLI from the global registry.

    Parameters
    ----------
    key : str
        Registry key identifying the CLI context.

    Returns
    -------
    AugmentMetadataModel
        Augment metadata from the CLI tooling context.

    """
    return REGISTRY.augment_for(key)


def registry_for(key: str) -> RegistryMetadataModel:
    """Retrieve registry metadata for a registered CLI from the global registry.

    Parameters
    ----------
    key : str
        Registry key identifying the CLI context.

    Returns
    -------
    RegistryMetadataModel
        Registry metadata from the CLI tooling context.

    """
    return REGISTRY.registry_for(key)


def interface_for(key: str) -> RegistryInterfaceModel:
    """Retrieve interface metadata for a registered CLI from the global registry.

    Parameters
    ----------
    key : str
        Registry key identifying the CLI context.

    Returns
    -------
    RegistryInterfaceModel
        Interface metadata matching the CLI's interface ID.

    """
    return REGISTRY.interface_for(key)


def tooling_metadata_for(key: str) -> ToolingMetadataModel:
    """Retrieve combined tooling metadata for a registered CLI from the global registry.

    Parameters
    ----------
    key : str
        Registry key identifying the CLI context.

    Returns
    -------
    ToolingMetadataModel
        Combined augment and registry metadata.

    """
    return REGISTRY.tooling_metadata_for(key)


def operation_override_for(
    key: str,
    *,
    subcommand: str,
    tokens: Sequence[str] | None = None,
) -> OperationOverrideModel | None:
    """Retrieve operation override metadata for a subcommand from the global registry.

    Parameters
    ----------
    key : str
        Registry key identifying the CLI context.
    subcommand : str
        Subcommand name to look up.
    tokens : Sequence[str] | None, optional
        Optional token sequence for override matching.

    Returns
    -------
    OperationOverrideModel | None
        Operation override if found, otherwise None.

    """
    return REGISTRY.operation_override_for(key, subcommand=subcommand, tokens=tokens)
