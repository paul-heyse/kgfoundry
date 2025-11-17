from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from tools import (
    AugmentMetadataModel,
    CLIToolingContext,
    CLIToolSettings,
    OperationOverrideModel,
    RegistryInterfaceModel,
    RegistryMetadataModel,
    ToolingMetadataModel,
)

class CLIContextDefinition:
    def __init__(
        self,
        *,
        command: str,
        title: str,
        interface_id: str,
        operation_ids: Mapping[str, str],
        bin_name: str | None = ...,
        version_resolver: Callable[[], str] | None = ...,
        augment_path: Path | None = ...,
        registry_path: Path | None = ...,
        context_factory: Callable[[CLIToolSettings], CLIToolingContext] | None = ...,
    ) -> None: ...

    command: str
    title: str
    interface_id: str
    operation_ids: Mapping[str, str]
    bin_name: str | None
    version_resolver: Callable[[], str] | None
    augment_path: Path | None
    registry_path: Path | None
    context_factory: Callable[[CLIToolSettings], CLIToolingContext] | None

    @property
    def bin_label(self) -> str: ...
    @property
    def operation_map(self) -> Mapping[str, str]: ...

class CLIContextRegistry:
    def register(self, key: str, definition: CLIContextDefinition) -> None: ...
    def definition_for(self, key: str) -> CLIContextDefinition: ...
    def settings_for(self, key: str) -> CLIToolSettings: ...
    def context_for(self, key: str) -> CLIToolingContext: ...
    def augment_for(self, key: str) -> AugmentMetadataModel: ...
    def registry_for(self, key: str) -> RegistryMetadataModel: ...
    def interface_for(self, key: str) -> RegistryInterfaceModel: ...
    def tooling_metadata_for(self, key: str) -> ToolingMetadataModel: ...
    def operation_override_for(
        self,
        key: str,
        *,
        subcommand: str,
        tokens: Sequence[str] | None = ...,
    ) -> OperationOverrideModel | None: ...

REGISTRY: CLIContextRegistry

def default_version_resolver(*packages: str) -> Callable[[], str]: ...
def register_cli(key: str, definition: CLIContextDefinition) -> None: ...
def definition_for(key: str) -> CLIContextDefinition: ...
def settings_for(key: str) -> CLIToolSettings: ...
def context_for(key: str) -> CLIToolingContext: ...
def augment_for(key: str) -> AugmentMetadataModel: ...
def registry_for(key: str) -> RegistryMetadataModel: ...
def interface_for(key: str) -> RegistryInterfaceModel: ...
def tooling_metadata_for(key: str) -> ToolingMetadataModel: ...
def operation_override_for(
    key: str,
    *,
    subcommand: str,
    tokens: Sequence[str] | None = ...,
) -> OperationOverrideModel | None: ...
