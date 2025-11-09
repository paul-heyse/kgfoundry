"""Shared helpers for CLI tooling metadata and configuration.

The helpers delegate augment/registry loading to
:mod:`tools._shared.augment_registry` so all tooling consumes the same immutable
metadata facade. They assemble ``CLIConfig`` instances compatible with
``tools.typer_to_openapi_cli`` and raise :class:`CLIConfigError` with RFC 9457
Problem Details payloads when configuration cannot be resolved.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from tools._shared import augment_registry
from tools._shared.logging import get_logger
from tools._shared.problem_details import ProblemDetailsParams, build_problem_details

LOGGER = get_logger(__name__)

AugmentRegistryError = augment_registry.AugmentRegistryError
load_augment = augment_registry.load_augment
load_registry = augment_registry.load_registry
load_tooling_metadata = augment_registry.load_tooling_metadata

if TYPE_CHECKING:
    from tools import ProblemDetailsDict
    from tools._shared.augment_registry import (
        AugmentMetadataModel,
        RegistryInterfaceModel,
        RegistryMetadataModel,
        ToolingMetadataModel,
    )
else:  # pragma: no cover - used only to keep runtime references lightweight
    ProblemDetailsDict = dict[str, object]
    AugmentMetadataModel = augment_registry.AugmentMetadataModel
    RegistryInterfaceModel = augment_registry.RegistryInterfaceModel
    RegistryMetadataModel = augment_registry.RegistryMetadataModel
    ToolingMetadataModel = augment_registry.ToolingMetadataModel

AugmentPayload = dict[str, object]

JSONMapping = Mapping[str, object]

_CLI_CONFIG_PROBLEM_TYPE = "https://kgfoundry.dev/problems/cli-config"
_CLI_CONFIG_PROBLEM_TITLE = "CLI configuration error"
_CANONICAL_FIELDS = {"type", "title", "status", "detail", "instance"}

Reader = Callable[[Path], object]


class CLIConfigError(RuntimeError):
    """Raised when CLI configuration metadata cannot be loaded or validated.

    Parameters
    ----------
    problem : ProblemDetailsDict
        RFC 9457 Problem Details payload describing the failure.
    """

    def __init__(self, problem: ProblemDetailsDict) -> None:
        detail = str(problem.get("detail", _CLI_CONFIG_PROBLEM_TITLE))
        super().__init__(detail)
        self.problem = problem


AugmentConfig = AugmentMetadataModel
RegistryContext = RegistryMetadataModel


@dataclass(frozen=True, slots=True)
class CLIToolSettings:
    """Settings describing CLI tooling inputs and metadata defaults."""

    bin_name: str
    title: str
    version: str
    augment_path: Path
    registry_path: Path
    interface_id: str | None = None


@dataclass(frozen=True, slots=True)
class CLIToolingContext:
    """Composite context bundling augment, registry, and CLI configuration."""

    augment: AugmentConfig
    registry: RegistryContext
    cli_config: object


def load_cli_tooling_context(
    settings: CLIToolSettings,
    *,
    augment_reader: Reader | None = None,
    registry_reader: Reader | None = None,
    config_factory: Callable[..., object] | None = None,
) -> CLIToolingContext:
    """Return a :class:`CLIToolingContext` for the supplied ``settings``.

    Parameters
    ----------
    settings : CLIToolSettings
        CLI tooling inputs including augment/registry paths and metadata.
    augment_reader : Reader | None, optional
        Optional custom reader for augment files. Defaults to safe YAML reader.
    registry_reader : Reader | None, optional
        Optional custom reader for registry files. Defaults to safe YAML reader.
    config_factory : Callable[..., object] | None, optional
        Factory callable producing ``CLIConfig`` instances. Defaults to the
        canonical :class:`tools.typer_to_openapi_cli.CLIConfig` implementation.

    Returns
    -------
    CLIToolingContext
        Composite context containing augment data, registry metadata, and the
        constructed CLI configuration.

    Raises
    ------
    CLIConfigError
        Raised when augment or registry metadata cannot be loaded or validated.
    """
    try:
        metadata = _load_tooling_metadata(
            settings,
            augment_reader=augment_reader,
            registry_reader=registry_reader,
        )
    except CLIConfigError:
        LOGGER.exception(
            "Failed to load CLI tooling metadata",
            extra={
                "status": "error",
                "operation": settings.bin_name,
                "augment_path": str(settings.augment_path),
                "registry_path": str(settings.registry_path),
            },
        )
        raise
    cli_config = build_cli_config(
        augment=metadata.augment,
        registry=metadata.registry,
        settings=settings,
        config_factory=config_factory,
    )
    return CLIToolingContext(
        augment=metadata.augment,
        registry=metadata.registry,
        cli_config=cli_config,
    )


def load_augment_config(path: Path, *, reader: Reader | None = None) -> AugmentConfig:
    """Load augment metadata from ``path``.

    Parameters
    ----------
    path : Path
        Filesystem path to the augment YAML document.
    reader : Reader | None, optional
        Optional custom reader used for testing. Defaults to YAML safe load.

    Returns
    -------
    AugmentConfig
        Immutable augment metadata bundle.

    Raises
    ------
    CLIConfigError
        Raised when the augment file cannot be read or parsed as a mapping.
    """
    try:
        return load_augment(path, reader=reader)
    except AugmentRegistryError as exc:
        instance = f"urn:cli:augment:{path.name}"
        raise CLIConfigError(_remap_problem(exc.problem, instance=instance)) from exc


def load_registry_context(path: Path, *, reader: Reader | None = None) -> RegistryContext:
    """Load CLI registry metadata from ``path``.

    Parameters
    ----------
    path : Path
        Filesystem path to the registry YAML document.
    reader : Reader | None, optional
        Optional custom reader used for testing. Defaults to YAML safe load.

    Returns
    -------
    RegistryContext
        Immutable registry metadata bundle.

    Raises
    ------
    CLIConfigError
        Raised when the registry file cannot be read or lacks an 'interfaces' mapping.
    """
    try:
        return load_registry(path, reader=reader)
    except AugmentRegistryError as exc:
        instance = f"urn:cli:registry:{path.name}"
        raise CLIConfigError(_remap_problem(exc.problem, instance=instance)) from exc


def build_cli_config(
    *,
    augment: AugmentConfig,
    registry: RegistryContext,
    settings: CLIToolSettings,
    config_factory: Callable[..., object] | None = None,
) -> object:
    """Return a ``CLIConfig`` constructed from the supplied metadata.

    Parameters
    ----------
    augment : AugmentConfig
        Augment metadata configuration.
    registry : RegistryContext
        Registry metadata containing interface definitions.
    settings : CLIToolSettings
        CLI tool settings including interface ID and paths.
    config_factory : Callable[..., object] | None, optional
        Factory function to create the CLI config instance. If None, uses
        the default factory resolver.

    Returns
    -------
    object
        Instantiated ``CLIConfig`` produced by ``config_factory``.

    Raises
    ------
    CLIConfigError
        Raised when ``settings.interface_id`` references a non-existent interface.
    """
    factory = config_factory or _resolve_cli_config_factory()
    interface_model: RegistryInterfaceModel | None = None
    if settings.interface_id:
        interface_model = registry.interface(settings.interface_id)
        if interface_model is None:
            raise CLIConfigError(
                _build_cli_problem(
                    detail=(
                        f"Interface '{settings.interface_id}' is not defined in registry "
                        f"'{registry.path}'."
                    ),
                    status=422,
                    instance=f"urn:cli:registry:{registry.path.name}",
                    extras={
                        "path": str(registry.path),
                        "interface_id": settings.interface_id,
                    },
                )
            )

    return factory(
        bin_name=settings.bin_name,
        title=settings.title,
        version=settings.version,
        augment=augment,
        interface_id=settings.interface_id,
        interface_meta=interface_model,
    )


def _resolve_cli_config_factory() -> Callable[..., object]:
    module = importlib.import_module("tools.typer_to_openapi_cli")
    return module.CLIConfig


def _load_tooling_metadata(
    settings: CLIToolSettings,
    *,
    augment_reader: Reader | None,
    registry_reader: Reader | None,
) -> ToolingMetadataModel:
    try:
        return load_tooling_metadata(
            augment_path=settings.augment_path,
            registry_path=settings.registry_path,
            augment_reader=augment_reader,
            registry_reader=registry_reader,
        )
    except AugmentRegistryError as exc:
        instance = f"urn:cli:metadata:{settings.augment_path.name}"
        raise CLIConfigError(_remap_problem(exc.problem, instance=instance)) from exc


def _remap_problem(problem: ProblemDetailsDict, *, instance: str) -> ProblemDetailsDict:
    detail = str(problem.get("detail") or _CLI_CONFIG_PROBLEM_TITLE)
    status_raw = problem.get("status")
    status = int(status_raw) if isinstance(status_raw, int) else 500
    extras_raw = problem.get("extensions")
    extras: dict[str, str] | None = None
    if isinstance(extras_raw, Mapping):
        extras = {str(key): str(value) for key, value in extras_raw.items()}
    return _build_cli_problem(
        detail=detail,
        status=status,
        instance=instance,
        extras=extras,
    )


def _build_cli_problem(
    detail: str,
    *,
    instance: str,
    status: int,
    extras: Mapping[str, str] | None = None,
) -> ProblemDetailsDict:
    """Return a Problem Details payload describing a CLI configuration error.

    Parameters
    ----------
    detail : str
        Human-readable error message describing the failure.
    instance : str
        URI identifying the specific occurrence of the problem.
    status : int
        HTTP status code for the error.
    extras : Mapping[str, str] | None, optional
        Additional extension fields for the Problem Details payload.

    Returns
    -------
    ProblemDetailsDict
        RFC 9457 Problem Details mapping representing the failure.
    """
    problem = build_problem_details(
        ProblemDetailsParams(
            type=_CLI_CONFIG_PROBLEM_TYPE,
            title=_CLI_CONFIG_PROBLEM_TITLE,
            status=status,
            detail=detail,
            instance=instance,
            extensions=extras,
        )
    )
    LOGGER.error(detail, extra={**({} if extras is None else dict(extras)), "status": "error"})
    return problem


__all__ = [
    "AugmentConfig",
    "AugmentPayload",
    "CLIConfigError",
    "CLIToolSettings",
    "CLIToolingContext",
    "JSONMapping",
    "build_cli_config",
    "load_augment_config",
    "load_cli_tooling_context",
    "load_registry_context",
]
