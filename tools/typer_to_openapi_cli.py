"""Generate an OpenAPI 3.1 document describing a Typer/Click CLI.

The resulting YAML includes rich ``x-cli`` metadata (examples, handlers, env vars)
and groups operations using tag metadata supplied via ``_augment_cli.yaml``.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import click
import yaml

from tools._shared.augment_registry import RegistryMetadataModel
from tools._shared.cli_tooling import (
    CLIConfigError,
    CLIToolSettings,
    load_cli_tooling_context,
)
from tools._shared.problem_details import render_problem

if TYPE_CHECKING:
    from tools._shared.augment_registry import (
        AugmentMetadataModel,
        OperationOverrideModel,
        RegistryInterfaceModel,
        RegistryOperationModel,
    )


type TyperCommandFactory = Callable[[object], click.core.Command]

try:  # Typer is optional at runtime; degrade gracefully when absent.
    from typer.main import get_command as _raw_get_command
except (
    ImportError,
    AttributeError,
):  # pragma: no cover - Typer may be unavailable in slim envs
    TYPER_GET_COMMAND: TyperCommandFactory | None = None
else:
    TYPER_GET_COMMAND = cast("TyperCommandFactory", _raw_get_command)


LOGGER = logging.getLogger(__name__)

JSONMapping = Mapping[str, object]


def _looks_like_typer(obj: object) -> bool:
    """Return ``True`` when ``obj`` appears to be a Typer application.

    Parameters
    ----------
    obj : object
        Object to test for Typer application characteristics.

    Returns
    -------
    bool
        ``True`` if the object resembles a Typer application.
    """
    if obj is None:
        return False
    module_name = getattr(obj, "__module__", "")
    class_name = obj.__class__.__name__
    return module_name.startswith("typer") or class_name == "Typer"


SCRIPT_ROOT = Path(__file__).resolve().parent
DEFAULT_REGISTRY_PATH = SCRIPT_ROOT / "mkdocs_suite" / "api_registry.yaml"
HTTP_METHODS: set[str] = {
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "trace",
}


def import_object(path: str) -> object:
    """Import a module or attribute by dotted path.

    Parameters
    ----------
    path : str
        Module path or ``module:attribute`` string to import.

    Returns
    -------
    object
        Imported module or attribute referenced by ``path``.
    """
    if ":" in path:
        module_name, attribute = path.split(":", 1)
        module = importlib.import_module(module_name)
        return getattr(module, attribute)
    return importlib.import_module(path)


def to_click_command(obj: object) -> click.core.Command:
    """Adapt Typer applications or raw click commands to ``click.Command``.

    Parameters
    ----------
    obj : object
        Typer application instance or click ``Command`` / ``Group``.

    Returns
    -------
    click.core.Command
        Click command instance suitable for traversal.

    Raises
    ------
    RuntimeError
        If Typer is not installed and obj is not already a click.Command.
    """
    if isinstance(obj, click.core.Command):
        return obj
    if TYPER_GET_COMMAND is None:
        message = "Typer is not installed; install typer or pass a click.Command."
        raise RuntimeError(message)
    if not _looks_like_typer(obj):
        message = "Expected Typer application when adapting to click command."
        raise RuntimeError(message)
    return TYPER_GET_COMMAND(obj)


def snake_to_kebab(value: str) -> str:
    """Convert a snake_case string to kebab-case.

    Parameters
    ----------
    value : str
        Snake-case string to convert.

    Returns
    -------
    str
        Kebab-case variant of ``value``.
    """
    return value.replace("_", "-")


def param_schema(param: click.Parameter) -> tuple[dict[str, object], bool, str]:
    """Return JSON schema metadata for a click parameter.

    Parameters
    ----------
    param : click.Parameter
        Click parameter to analyse.

    Returns
    -------
    tuple[dict[str, object], bool, str]
        Tuple containing the schema dictionary, a required flag, and the parameter name.
    """
    schema: dict[str, object] = {"type": "string"}
    required = bool(getattr(param, "required", False))
    example_name = param.name or "param"

    param_type = getattr(param, "type", None)
    type_name = getattr(param_type, "name", "").lower()
    if (
        param_type is not None
        and hasattr(param_type, "choices")
        and getattr(param_type, "choices", None)
    ):
        schema["enum"] = list(param_type.choices)
    elif type_name in {"int", "integer"}:
        schema["type"] = "integer"
    elif type_name in {"float"}:
        schema["type"] = "number"
    elif type_name in {"bool", "boolean"}:
        schema["type"] = "boolean"
    elif type_name in {"path", "file", "filename"}:
        schema["format"] = "path"

    if getattr(param, "multiple", False) or getattr(param, "nargs", 1) not in {1, None}:
        schema = {"type": "array", "items": schema}

    help_text = getattr(param, "help", None)
    if help_text:
        schema["description"] = help_text

    return schema, required, example_name


def build_example(bin_name: str, tokens: Sequence[str], params: Sequence[click.Parameter]) -> str:
    """Construct a CLI usage example string for documentation.

    Parameters
    ----------
    bin_name : str
        Binary/executable name for the CLI command.
    tokens : Sequence[str]
        Command tokens representing the command path (e.g., ["sub", "command"]).
    params : Sequence[click.Parameter]
        Click parameters to include in the example.

    Returns
    -------
    str
        CLI example illustrating invocation of the command.
    """
    parts = [bin_name, *tokens]
    for param in params:
        if param.param_type_name == "argument":
            param_name = param.name or "arg"
            parts.append(f"<{param_name}>")
            continue
        param_name = param.name or "option"
        option = f"--{snake_to_kebab(param_name)}"
        if getattr(param, "is_flag", False):
            parts.append(option)
        else:
            parts.extend([option, f"<{param_name}>"])
    return " ".join(parts)


def walk_commands(
    cmd: click.core.Command, tokens: list[str]
) -> list[tuple[list[str], click.core.Command]]:
    """Traverse nested click group returning runnable commands.

    Parameters
    ----------
    cmd : click.core.Command
        Click command to traverse.
    tokens : list[str]
        Current command path tokens.

    Returns
    -------
    list[tuple[list[str], click.core.Command]]
        List of (token path, command) tuples for all runnable commands.
    """
    results: list[tuple[list[str], click.core.Command]] = []
    if isinstance(cmd, click.core.Group):
        command_map = getattr(cmd, "commands", None)
        if isinstance(command_map, Mapping):
            if getattr(cmd, "callback", None):
                results.append((tokens, cmd))
            for name, subcommand in command_map.items():
                results.extend(walk_commands(subcommand, [*tokens, name]))
            return results
    results.append((tokens, cmd))
    return results


def _augment_lookup(
    augment: AugmentMetadataModel, op_id: str, tokens: Sequence[str]
) -> OperationOverrideModel | None:
    return augment.operation_override(op_id, tokens=tokens)


def _ensure_str_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value]
    return []


def _coerce_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): val for key, val in value.items()}


def _coerce_mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [
        {str(key): val for key, val in item.items()} for item in value if isinstance(item, Mapping)
    ]


def _operation_metadata(
    interface_meta: RegistryInterfaceModel | None,
    tokens: Sequence[str],
    operation_id: str,
) -> dict[str, object]:
    if interface_meta is None:
        return {}
    token_list = list(tokens)
    slug = "-".join(snake_to_kebab(token) for token in token_list)
    candidates = (operation_id, slug, " ".join(token_list))
    for key in candidates:
        operation = interface_meta.operations.get(key)
        if operation is not None:
            return operation.to_payload(key)
    return {}


def _interface_metadata(
    interface_meta: RegistryInterfaceModel | None,
) -> dict[str, object] | None:
    if interface_meta is None:
        return None
    return {
        "id": interface_meta.identifier,
        "module": interface_meta.module,
        "owner": interface_meta.owner,
        "stability": interface_meta.stability,
        "binary": interface_meta.binary,
        "protocol": interface_meta.protocol,
    }


def _initial_document(
    title: str,
    version: str,
    augment: AugmentMetadataModel,
    interface_meta: RegistryInterfaceModel | None,
) -> dict[str, object]:
    tag_entries = [
        entry for entry in _coerce_mapping_list(augment.payload.get("tags")) if "name" in entry
    ]
    document: dict[str, object] = {
        "openapi": "3.1.0",
        "info": {"title": title, "version": version},
        "tags": tag_entries,
        "paths": {},
    }
    if interface_meta:
        extension = _interface_metadata(interface_meta)
        if extension:
            info_section = document.setdefault("info", {})
            if isinstance(info_section, dict):
                info_section.setdefault("x-kgf-interface", extension)
    tag_groups = augment.payload.get("x-tagGroups")
    if isinstance(tag_groups, Sequence) and not isinstance(tag_groups, (str, bytes)):
        document["x-tagGroups"] = list(tag_groups)
    return document


def _request_schema_for_command(
    params: Sequence[click.Parameter],
) -> tuple[dict[str, object], bool]:
    properties: dict[str, object] = {}
    required: list[str] = []
    for param in params:
        schema, is_required, example_name = param_schema(param)
        properties[example_name] = schema
        is_flag = bool(getattr(param, "is_flag", False))
        has_default = getattr(param, "default", None) is not None
        if is_required and not is_flag and not has_default:
            required.append(example_name)
    schema: dict[str, object] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = sorted(required)
    return schema, bool(properties)


def _apply_override_to_x_cli(
    block: dict[str, object], override: OperationOverrideModel | None
) -> None:
    if override is None:
        return
    if override.handler:
        block["x-handler"] = override.handler
    if override.env:
        block["x-env"] = list(override.env)
    if override.code_samples:
        sample_block = cast("list[object]", block.setdefault("x-codeSamples", []))
        sample_block.extend(sample.model_dump() for sample in override.code_samples)
    if override.examples:
        example_block = cast("list[str]", block.setdefault("examples", []))
        example_block.extend(override.examples)
    if override.problem_details:
        problem_block = cast("list[str]", block.setdefault("x-problemDetails", []))
        problem_block.extend(override.problem_details)
    if override.extras:
        block.update(override.extras)


def _collect_problem_details(
    op_meta: JSONMapping,
    interface_meta: RegistryInterfaceModel | None,
    override: OperationOverrideModel | None,
) -> list[str]:
    details: list[str] = []
    details.extend(_ensure_str_list(op_meta.get("problem_details")))
    if interface_meta:
        details.extend(interface_meta.problem_details)
    if override:
        details.extend(override.problem_details)
    return details


def _select_operation_tags(
    override: OperationOverrideModel | None,
    op_meta: JSONMapping,
    interface_meta: RegistryInterfaceModel | None,
    default_tag: str,
) -> list[str]:
    for candidate in (
        list(override.tags) if override else [],
        _ensure_str_list(op_meta.get("tags")),
        list(interface_meta.tags) if interface_meta else [],
    ):
        if candidate:
            return candidate
    return [default_tag]


@dataclass(frozen=True, slots=True)
class _OperationDescriptor:
    """Immutable descriptor capturing command metadata for an operation."""

    raw_tokens: tuple[str, ...]
    command: click.core.Command
    tokens: tuple[str, ...] = field(init=False)
    params: tuple[click.Parameter, ...] = field(init=False)
    help_text: str = field(init=False)
    short_help: str = field(init=False)

    def __post_init__(self) -> None:
        tokens = list(self.raw_tokens) or [self.command.name or "run"]
        object.__setattr__(self, "tokens", tuple(tokens))
        raw_params = getattr(self.command, "params", ())
        if isinstance(raw_params, Sequence) and not isinstance(raw_params, (str, bytes)):
            params = tuple(item for item in raw_params if isinstance(item, click.Parameter))
        else:
            params = ()
        object.__setattr__(self, "params", params)
        help_text = (getattr(self.command, "help", "") or "").strip()
        object.__setattr__(self, "help_text", help_text)
        short_help = str(getattr(self.command, "short_help", "") or "").strip()
        object.__setattr__(self, "short_help", short_help)

    @property
    def kebab_tokens(self) -> tuple[str, ...]:
        """Return command tokens converted to kebab-case.

        Returns
        -------
        tuple[str, ...]
            Tokens in kebab-case format (e.g., "build-artifacts").
        """
        return tuple(snake_to_kebab(token) for token in self.tokens)

    @property
    def path(self) -> str:
        """Return the OpenAPI path for this CLI operation.

        Returns
        -------
        str
            Path string prefixed with "/cli/" and tokens in kebab-case.
        """
        return "/cli/" + "/".join(snake_to_kebab(token) for token in self.tokens)

    @property
    def operation_id(self) -> str:
        """Return the OpenAPI operation ID for this CLI command.

        Returns
        -------
        str
            Operation ID prefixed with "cli." and using dot-separated tokens.
        """
        return "cli." + ".".join(self.tokens)

    @property
    def default_tag(self) -> str:
        """Return the default OpenAPI tag for this operation.

        Returns
        -------
        str
            First token from the command tokens, used as the default tag.
        """
        return self.tokens[0]

    def summary(self, op_meta: JSONMapping) -> str:
        """Extract or generate a summary string for the operation.

        Parameters
        ----------
        op_meta : JSONMapping
            Operation metadata dictionary that may contain a "summary" key.

        Returns
        -------
        str
            Summary string from metadata, short help, first line of help text, or default.
        """
        summary_value = op_meta.get("summary") or self.short_help
        if summary_value:
            return str(summary_value).strip()
        if self.help_text:
            return self.help_text.split("\n", 1)[0]
        return "Run CLI command"

    def description(self, op_meta: JSONMapping) -> str:
        """Extract or generate a description string for the operation.

        Parameters
        ----------
        op_meta : JSONMapping
            Operation metadata dictionary that may contain a "description" key.

        Returns
        -------
        str
            Description string from metadata or full help text.
        """
        return str(op_meta.get("description") or self.help_text)


@dataclass(frozen=True, slots=True)
class OperationContext:
    """Context bundle shared across OpenAPI operation builders."""

    bin_name: str
    augment: AugmentMetadataModel
    interface_id: str | None
    interface_meta: RegistryInterfaceModel | None

    def build_operation(
        self, tokens: Sequence[str], command: click.core.Command
    ) -> tuple[str, dict[str, object], list[str]]:
        """Build an OpenAPI operation payload for the supplied command.

        Parameters
        ----------
        tokens : Sequence[str]
            Command tokens representing the command path.
        command : click.core.Command
            Click command object to convert to an OpenAPI operation.

        Returns
        -------
        tuple[str, dict[str, object], list[str]]
            The OpenAPI path, operation payload, and associated tags.
        """
        descriptor = _OperationDescriptor(tuple(tokens), command)
        override = _augment_lookup(self.augment, descriptor.operation_id, descriptor.tokens)
        op_meta = _operation_metadata(
            self.interface_meta, descriptor.tokens, descriptor.operation_id
        )
        tags = _select_operation_tags(
            override, op_meta, self.interface_meta, descriptor.default_tag
        )
        params = list(descriptor.params)
        request_schema, has_properties = _request_schema_for_command(params)
        x_cli_block = _build_x_cli_block(descriptor, params, op_meta, self)
        _apply_override_to_x_cli(x_cli_block, override)
        operation: dict[str, object] = {
            "operationId": descriptor.operation_id,
            "tags": list(tags),
            "summary": descriptor.summary(op_meta),
            "description": descriptor.description(op_meta),
            "x-cli": x_cli_block,
            "requestBody": {
                "required": has_properties,
                "content": {"application/json": {"schema": request_schema}},
            },
            "responses": {
                "200": {
                    "description": "CLI result",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "stdout": {"type": "string"},
                                    "stderr": {"type": "string"},
                                    "exitCode": {"type": "integer"},
                                    "artifacts": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["exitCode"],
                            }
                        }
                    },
                }
            },
        }
        problem_details = _collect_problem_details(op_meta, self.interface_meta, override)
        if problem_details:
            operation["x-problemDetails"] = problem_details
        interface_extension = _interface_metadata(self.interface_meta)
        if interface_extension:
            operation["x-kgf-interface"] = interface_extension
        return descriptor.path, operation, tags


@dataclass(frozen=True, slots=True)
class CLIConfig:
    """Configuration describing the CLI and metadata sources."""

    bin_name: str
    title: str
    version: str
    augment: AugmentMetadataModel
    interface_id: str | None = None
    interface_meta: RegistryInterfaceModel | None = None

    @property
    def augment_payload(self) -> Mapping[str, object]:
        """Return raw augment metadata payload as a mapping."""
        return self.augment.payload

    @property
    def operation_context(self) -> OperationContext:
        """Return a lightweight context object for building operations."""
        return OperationContext(
            bin_name=self.bin_name,
            augment=self.augment,
            interface_id=self.interface_id,
            interface_meta=self.interface_meta,
        )


def _build_x_cli_block(
    descriptor: _OperationDescriptor,
    params: Sequence[click.Parameter],
    op_meta: JSONMapping,
    context: OperationContext,
) -> dict[str, object]:
    kebab_tokens = list(descriptor.kebab_tokens)
    example = build_example(context.bin_name, kebab_tokens, params)
    block: dict[str, object] = {
        "bin": context.bin_name,
        "command": " ".join(kebab_tokens),
        "examples": [example],
        "exitCodes": [{"code": 0, "meaning": "success"}],
    }
    if context.interface_meta:
        block.setdefault("x-interface", context.interface_meta.identifier)
    handler = op_meta.get("handler")
    if isinstance(handler, (str, bytes)):
        block["x-handler"] = handler
    env_values = op_meta.get("env")
    if isinstance(env_values, Sequence) and not isinstance(env_values, (str, bytes)):
        block["x-env"] = [str(value) for value in env_values]
    code_samples = op_meta.get("code_samples")
    if isinstance(code_samples, Sequence) and not isinstance(code_samples, (str, bytes)):
        sample_block = cast("list[object]", block.setdefault("x-codeSamples", []))
        sample_block.extend(code_samples)
    examples = _ensure_str_list(op_meta.get("examples"))
    if examples:
        example_list = cast("list[str]", block.setdefault("examples", []))
        example_list.extend(examples)
    problem_details = _ensure_str_list(op_meta.get("problem_details"))
    if problem_details:
        problem_list = cast("list[str]", block.setdefault("x-problemDetails", []))
        problem_list.extend(problem_details)
    return block


def _augment_document_tags(document: dict[str, object], referenced_tags: set[str]) -> None:
    existing_tags = document.get("tags")
    iterable_tags = (
        existing_tags
        if isinstance(existing_tags, Sequence) and not isinstance(existing_tags, (str, bytes))
        else []
    )
    existing = {entry.get("name") for entry in iterable_tags if isinstance(entry, Mapping)}
    for tag in sorted(referenced_tags):
        if tag not in existing:
            tag_list = cast("list[dict[str, object]]", document.setdefault("tags", []))
            tag_list.append({"name": tag, "description": f"Commands for {tag}."})


@dataclass(frozen=True)
class _RegistryOperationEntry:
    path: str
    operation_id: str
    tags: set[str]
    document: dict[str, object]


@dataclass(frozen=True)
class _OperationDocumentParams:
    operation_id: str
    tags: Sequence[str]
    summary: str
    description: str
    cli_extension: Mapping[str, object]
    problem_details: Sequence[str]
    interface_extension: Mapping[str, object] | None


@dataclass(frozen=True)
class _InterfaceOperationContext:
    interface: RegistryInterfaceModel
    bin_name: str
    interface_extension: Mapping[str, object] | None
    augment: AugmentMetadataModel


def _existing_operation_ids(paths_section: Mapping[str, object]) -> set[str]:
    operation_ids: set[str] = set()
    for entry in paths_section.values():
        if not isinstance(entry, Mapping):
            continue
        for operation in entry.values():
            if isinstance(operation, Mapping):
                op_id = operation.get("operationId")
                if isinstance(op_id, str):
                    operation_ids.add(op_id)
    return operation_ids


def _operation_tokens(operation_id: str, fallback: str) -> tuple[list[str], list[str]]:
    tokens = [part.strip() for part in operation_id.split(".") if part.strip()]
    if tokens and tokens[0] == "cli":
        tokens = tokens[1:]
    if not tokens:
        tokens = [fallback.replace("-", "_")]
    sanitized = [token.replace("-", "_") for token in tokens]
    command_tokens = [snake_to_kebab(token) for token in sanitized]
    return sanitized, command_tokens


def _coerce_str_list(value: object) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _build_cli_extension(
    *,
    bin_name: str,
    command_tokens: Sequence[str],
    metadata: Mapping[str, object],
) -> dict[str, object]:
    command_string = " ".join(command_tokens).strip()
    example_command = f"{bin_name} {command_string}".strip()
    extension: dict[str, object] = {
        "bin": bin_name,
        "command": command_string or bin_name,
        "examples": [example_command] if example_command else [bin_name],
        "exitCodes": [{"code": 0, "meaning": "success"}],
    }
    handler = metadata.get("handler")
    if isinstance(handler, (str, bytes)) and handler:
        extension["x-handler"] = str(handler)
    env_values = metadata.get("env") or metadata.get("x-env")
    if isinstance(env_values, Sequence) and not isinstance(env_values, (str, bytes)):
        extension["x-env"] = [str(value) for value in env_values]
    code_samples = metadata.get("code_samples") or metadata.get("x-codeSamples")
    if isinstance(code_samples, Sequence) and not isinstance(code_samples, (str, bytes)):
        samples = [cast("Mapping[str, object]", item) for item in code_samples]
        extension["x-codeSamples"] = samples
    examples = _coerce_str_list(metadata.get("examples"))
    if examples:
        example_list = cast("list[str]", extension.setdefault("examples", []))
        example_list.extend(examples)
    return extension


def _registry_operation_document(params: _OperationDocumentParams) -> dict[str, object]:
    operation: dict[str, object] = {
        "operationId": params.operation_id,
        "tags": list(params.tags),
        "summary": params.summary,
        "description": params.description,
        "x-cli": dict(params.cli_extension),
        "requestBody": {
            "required": False,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "additionalProperties": True,
                    }
                }
            },
        },
        "responses": {
            "200": {
                "description": "CLI result",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "stdout": {"type": "string"},
                                "stderr": {"type": "string"},
                                "exitCode": {"type": "integer"},
                                "artifacts": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["exitCode"],
                        }
                    }
                },
            }
        },
    }
    if params.problem_details:
        operation["x-problemDetails"] = list(params.problem_details)
    if params.interface_extension:
        operation["x-kgf-interface"] = params.interface_extension
    return operation


def _build_registry_operation_entry(
    *,
    context: _InterfaceOperationContext,
    op_key: str,
    operation_model: RegistryOperationModel,
    existing_operation_ids: set[str],
) -> _RegistryOperationEntry | None:
    payload = operation_model.to_payload(op_key)
    operation_id = str(payload.get("operation_id") or op_key)
    if not operation_id or operation_id in existing_operation_ids:
        return None

    sanitized_tokens, command_tokens = _operation_tokens(operation_id, op_key)
    path = "/cli/" + "/".join(command_tokens)

    override_model = context.augment.operation_override(operation_id, tokens=sanitized_tokens)
    override_payload = (
        override_model.to_payload()
        if override_model is not None
        else context.augment.get_operation(operation_id)
    )

    merged_meta: dict[str, object] = {str(k): v for k, v in payload.items()}
    if isinstance(override_payload, Mapping):
        merged_meta.update({str(k): v for k, v in override_payload.items()})

    tags = _select_operation_tags(
        override_model,
        merged_meta,
        context.interface,
        sanitized_tokens[0] if sanitized_tokens else context.interface.identifier,
    )

    return _RegistryOperationEntry(
        path=path,
        operation_id=operation_id,
        tags=set(tags),
        document=_registry_operation_document(
            _OperationDocumentParams(
                operation_id=operation_id,
                tags=tags,
                summary=str(merged_meta.get("summary") or "Run CLI command"),
                description=str(merged_meta.get("description") or ""),
                cli_extension=_build_cli_extension(
                    bin_name=context.bin_name,
                    command_tokens=command_tokens,
                    metadata=merged_meta,
                ),
                problem_details=_coerce_str_list(
                    merged_meta.get("problem_details") or merged_meta.get("x-problemDetails")
                ),
                interface_extension=context.interface_extension,
            )
        ),
    )


def _ensure_registry_operations(
    document: dict[str, object],
    config: CLIConfig,
    registry: RegistryMetadataModel | None,
    referenced_tags: set[str],
) -> None:
    if registry is None:
        return

    paths_section = document.setdefault("paths", {})
    if not isinstance(paths_section, dict):
        return

    existing_operation_ids = _existing_operation_ids(paths_section)
    augment = config.augment

    for interface in registry.interfaces.values():
        bin_name = interface.binary or config.bin_name
        interface_extension = _interface_metadata(interface)
        context = _InterfaceOperationContext(
            interface=interface,
            bin_name=bin_name,
            interface_extension=interface_extension,
            augment=augment,
        )

        for key, op_model in interface.operations.items():
            entry = _build_registry_operation_entry(
                context=context,
                op_key=key,
                operation_model=op_model,
                existing_operation_ids=existing_operation_ids,
            )
            if entry is None:
                continue

            path_entry = paths_section.setdefault(entry.path, {})
            if not isinstance(path_entry, dict) or "post" in path_entry:
                continue

            path_entry["post"] = entry.document
            existing_operation_ids.add(entry.operation_id)
            referenced_tags.update(entry.tags)


def make_openapi(
    click_cmd: click.core.Command,
    config: CLIConfig,
    registry: RegistryMetadataModel | None = None,
) -> dict[str, object]:
    """Produce an OpenAPI 3.1 document representing the CLI.

    Parameters
    ----------
    click_cmd : click.core.Command
        Root click command or group to traverse.
    config : CLIConfig
        Configuration object containing title, version, augment metadata,
        interface settings, and operation context.
    registry : RegistryMetadataModel | None, optional
        Optional registry metadata used to enrich operations with CLI facets.

    Returns
    -------
    dict[str, object]
        Complete OpenAPI 3.1 document dictionary with paths, operations,
        tags, and extensions.
    """
    document = _initial_document(
        config.title,
        config.version,
        config.augment,
        config.interface_meta,
    )
    context = config.operation_context
    referenced_tags: set[str] = set()

    for tokens, command in walk_commands(click_cmd, []):
        path, operation, tags = context.build_operation(tokens, command)
        paths_section = document.setdefault("paths", {})
        if not isinstance(paths_section, dict):
            paths_section = {}
            document["paths"] = paths_section
        path_entry = paths_section.setdefault(path, {})
        if isinstance(path_entry, dict):
            path_entry["post"] = operation
        referenced_tags.update(tags)

    _ensure_registry_operations(document, config, registry, referenced_tags)

    _augment_document_tags(document, referenced_tags)
    return document


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse CLI arguments for the OpenAPI generator.

    Parameters
    ----------
    argv : Sequence[str]
        Command-line arguments to parse.

    Returns
    -------
    argparse.Namespace
        Parsed arguments namespace containing app, bin, title, version,
        augment, out, interface-id, and registry attributes.
    """
    parser = argparse.ArgumentParser(description="Generate OpenAPI spec for a Typer/Click CLI.")
    parser.add_argument(
        "--app", required=True, help="Import path to Typer or Click app (pkg.mod:attr)"
    )
    parser.add_argument("--bin", default="kgf", help="Binary name displayed in examples")
    parser.add_argument("--title", default="KGFoundry CLI", help="OpenAPI info.title value")
    parser.add_argument("--version", default="0.0.0", help="OpenAPI info.version value")
    parser.add_argument(
        "--augment",
        default="openapi/_augment_cli.yaml",
        help="YAML file with tag metadata and per-operation overrides",
    )
    parser.add_argument(
        "--out",
        default="openapi/openapi-cli.yaml",
        help="Destination path of the generated OpenAPI YAML",
    )
    parser.add_argument(
        "--interface-id",
        default=None,
        help="Interface identifier from api_registry.yaml for metadata enrichment",
    )
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY_PATH),
        help="Path to api_registry.yaml containing interface metadata",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for generating the CLI OpenAPI specification.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Command-line arguments, defaults to sys.argv.

    Returns
    -------
    int
        ``0`` when the OpenAPI document is written successfully.
    """
    args = parse_args(argv if argv is not None else sys.argv[1:])

    app_obj = import_object(args.app)
    click_cmd = to_click_command(app_obj)
    settings = CLIToolSettings(
        bin_name=args.bin,
        title=args.title,
        version=args.version,
        augment_path=Path(args.augment),
        registry_path=Path(args.registry),
        interface_id=args.interface_id,
    )

    try:
        tooling_context = load_cli_tooling_context(settings)
    except CLIConfigError as exc:
        LOGGER.exception(
            "Failed to load CLI tooling context",
            extra={"status": "error", "detail": exc.problem.get("detail")},
        )
        click.echo(render_problem(exc.problem), err=True)
        return 1

    cli_config = cast("CLIConfig", tooling_context.cli_config)
    registry = getattr(tooling_context, "registry", None)
    spec = make_openapi(click_cmd, cli_config, registry)
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(spec, handle, sort_keys=False)

    click.echo(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entrypoint
    sys.exit(main())
