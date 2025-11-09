"""Generate CLI diagrams using shared CLI tooling context.

This script leverages :mod:`tools._shared.cli_tooling` to load augment metadata
and registry configuration, ensuring diagrams reflect the same operation
context as the OpenAPI generator.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, cast

import mkdocs_gen_files

from tools._shared.cli_tooling import (
    CLIConfigError,
    CLIToolSettings,
    load_cli_tooling_context,
)
from tools._shared.problem_details import (
    ProblemDetailsParams,
    build_problem_details,
    render_problem,
)
from tools.typer_to_openapi_cli import import_object, to_click_command, walk_commands

if TYPE_CHECKING:  # pragma: no cover - typing aid
    from click.core import Command

    from tools._shared.augment_registry import RegistryInterfaceModel
    from tools._shared.cli_tooling import CLIToolingContext
    from tools.typer_to_openapi_cli import CLIConfig, OperationContext

OperationEntry = tuple[str, str, str | None, str, tuple[str, ...]]

__all__ = ["OperationEntry", "collect_operations", "main", "write_diagram"]

LOGGER = logging.getLogger(__name__)


RECOVERABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    ImportError,
    ModuleNotFoundError,
    AttributeError,
    TypeError,
    RuntimeError,
)

DOCS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = DOCS_ROOT.parents[2]
AUGMENT_PATH = REPO_ROOT / "openapi" / "_augment_cli.yaml"
REGISTRY_PATH = REPO_ROOT / "tools" / "mkdocs_suite" / "api_registry.yaml"
REDOC_PAGE = "api/openapi-cli.md"
DIAGRAM_INDEX_PATH = "diagrams/index.md"
CLI_INDEX_ENTRY = "- [CLI by Tag](./cli_by_tag.d2)\n"

DEFAULT_INTERFACE_ID = "orchestration-cli"
DEFAULT_BIN_NAME = "kgf"
DEFAULT_TITLE = "KGFoundry CLI"
DEFAULT_VERSION = "0.0.0"


def _log_diagram_warning(message: str, exc: Exception) -> None:
    """Log a warning describing why the CLI diagram cannot be produced."""
    LOGGER.warning(message, exc_info=exc, extra={"status": "warning"})


def _escape_d2(value: str) -> str:
    """Escape characters that would break D2 string literals.

    Parameters
    ----------
    value : str
        Input string to escape.

    Returns
    -------
    str
        Escaped string safe for use in D2 diagram syntax.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _operation_anchor(operation_id: str | None) -> str:
    anchor = (operation_id or "").strip()
    return f"../{REDOC_PAGE}#operation/{anchor}"


def _default_cli_settings(interface_id: str | None) -> CLIToolSettings:
    return CLIToolSettings(
        bin_name=DEFAULT_BIN_NAME,
        title=DEFAULT_TITLE,
        version=DEFAULT_VERSION,
        augment_path=AUGMENT_PATH,
        registry_path=REGISTRY_PATH,
        interface_id=interface_id or DEFAULT_INTERFACE_ID,
    )


def _load_click_command(
    context: CLIToolingContext,
    target_interface: str | None,
) -> object:
    cli_config = cast("CLIConfig", context.cli_config)
    interface_id_candidate = target_interface or cli_config.interface_id
    if interface_id_candidate is None:
        _raise_diagram_error(
            "CLI interface identifier is not configured.",
            instance="urn:cli-diagram:missing-interface",
        )
    interface_id = cast("str", interface_id_candidate)
    resolved_interface = _resolve_interface_metadata(
        interface_id,
        registry_interface=context.registry.interface(interface_id),
        config_interface=cli_config.interface_meta,
    )
    entrypoint_str = _require_entrypoint(interface_id, resolved_interface.entrypoint)
    app_obj = import_object(entrypoint_str)
    return to_click_command(app_obj)


def _resolve_interface_metadata(
    interface_id: str,
    *,
    registry_interface: RegistryInterfaceModel | None,
    config_interface: RegistryInterfaceModel | None,
) -> RegistryInterfaceModel:
    if registry_interface is not None:
        return registry_interface
    if config_interface is not None:
        return config_interface
    _raise_diagram_error(
        f"Interface '{interface_id}' metadata is unavailable.",
        instance="urn:cli-diagram:missing-metadata",
        extras={"interface_id": interface_id},
    )
    message = (
        "Interface metadata resolution should be unreachable after raising a CLI diagram error."
    )
    raise RuntimeError(message)


def _require_entrypoint(interface_id: str, entrypoint: str | None) -> str:
    if entrypoint is None:
        _raise_diagram_error(
            f"Interface '{interface_id}' is missing an 'entrypoint' attribute.",
            instance="urn:cli-diagram:missing-entrypoint",
            extras={"interface_id": interface_id},
        )
    entrypoint_not_none = cast("str", entrypoint)
    entrypoint_str = entrypoint_not_none.strip()
    if not entrypoint_str:
        _raise_diagram_error(
            f"Interface '{interface_id}' is missing an 'entrypoint' attribute.",
            instance="urn:cli-diagram:missing-entrypoint",
            extras={"interface_id": interface_id},
        )
    return entrypoint_str


def _write_diagram(
    operations: list[OperationEntry],
) -> None:
    diagram_path = "diagrams/cli_by_tag.d2"
    with mkdocs_gen_files.open(diagram_path, "w") as handle:
        handle.write('direction: right\nCLI: "CLI" {\n')
        unique_tags = sorted({tag for *_, tags in operations for tag in tags})
        handle.write(
            "\n".join(f'  "{_escape_d2(tag)}": "{_escape_d2(tag)}" {{}}' for tag in unique_tags)
        )
        if unique_tags:
            handle.write("\n")
        written_nodes: set[str] = set()
        for method, path, operation_id, summary, tags in operations:
            node_id = f"{method} {path}"
            escaped_node_id = _escape_d2(node_id)
            label_base = f"{node_id}\n{summary}" if summary else node_id
            if node_id not in written_nodes:
                escaped_label = _escape_d2(label_base)
                link_attr = (
                    f' {{ link: "{_escape_d2(_operation_anchor(operation_id))}" }}'
                    if operation_id
                    else ""
                )
                handle.write(f'  "{escaped_node_id}": "{escaped_label}"{link_attr}\n')
                written_nodes.add(node_id)
            for tag in tags:
                handle.write(f'  "{_escape_d2(tag)}" -> "{escaped_node_id}"\n')
        handle.write("}\n")


def collect_operations(
    context: CLIToolingContext | None = None,
    *,
    interface_id: str | None = None,
    click_cmd: object | None = None,
) -> list[OperationEntry]:
    """Return CLI operations derived from the shared CLI tooling context.

    Parameters
    ----------
    context : CLIToolingContext | None, optional
        Pre-loaded tooling context. When ``None``, the default repository configuration is loaded automatically.
    interface_id : str | None, optional
        Interface identifier to resolve. Defaults to the repository's CLI
        interface when omitted.
    click_cmd : object | None, optional
        Pre-resolved click command tree. When omitted the function imports the
        entrypoint declared in the registry metadata.

    Returns
    -------
    list[OperationEntry]
        List of operation tuples containing method, path, operation identifier,
        summary, and canonical tags. The method is always ``POST`` because CLI
        invocations map to action-style HTTP operations in the documentation.

    Raises
    ------
    CLIConfigError
        When CLI configuration is invalid or required metadata is missing.
    """
    if context is None:
        settings = _default_cli_settings(interface_id)
        try:
            context = load_cli_tooling_context(settings)
        except CLIConfigError:
            raise
        except RECOVERABLE_EXCEPTIONS as exc:
            _log_diagram_warning(
                "Skipping CLI diagram generation; unable to load CLI tooling context.",
                exc,
            )
            return []
        interface_id = settings.interface_id

    if context is None:
        return []

    cli_config = cast("CLIConfig", context.cli_config)
    resolved_interface = interface_id or cli_config.interface_id
    try:
        command_candidate = click_cmd or _load_click_command(context, resolved_interface)
    except CLIConfigError:
        raise
    except RECOVERABLE_EXCEPTIONS as exc:
        _log_diagram_warning(
            "Skipping CLI diagram generation; unable to resolve CLI entrypoint.",
            exc,
        )
        return []
    operation_context = cli_config.operation_context

    return _build_operations(operation_context, cast("Command", command_candidate))


def write_diagram(operations: Sequence[OperationEntry]) -> None:
    """Emit a D2 diagram linking CLI tags to operations."""
    _write_diagram(list(operations))


def update_cli_index_entry(*, enabled: bool) -> None:
    """Ensure the diagrams index links to the CLI diagram when available."""
    entry_token = CLI_INDEX_ENTRY.strip()
    entry_line = CLI_INDEX_ENTRY if CLI_INDEX_ENTRY.endswith("\n") else f"{CLI_INDEX_ENTRY}\n"
    try:
        with mkdocs_gen_files.open(DIAGRAM_INDEX_PATH, "r") as handle:
            existing_lines = handle.read().splitlines(keepends=True)
    except FileNotFoundError:
        existing_lines = []

    filtered_lines = [line for line in existing_lines if line.strip() != entry_token]
    bullet_start = next(
        (index for index, line in enumerate(filtered_lines) if line.lstrip().startswith("- ")),
        len(filtered_lines),
    )
    prefix_lines = filtered_lines[:bullet_start]
    bullet_lines = filtered_lines[bullet_start:]

    bullet_lines = [line for line in bullet_lines if line.strip() != entry_token]

    if enabled and not any(line.strip() == entry_token for line in bullet_lines):
        insert_at = len(bullet_lines)
        while insert_at > 0 and not bullet_lines[insert_at - 1].strip():
            insert_at -= 1
        bullet_lines.insert(insert_at, entry_line)

    if not prefix_lines and not bullet_lines:
        return

    prefix_text = "".join(prefix_lines)
    bullet_text = "".join(bullet_lines)

    if bullet_text and prefix_text:
        if prefix_text.endswith("\n"):
            if not prefix_text.endswith("\n\n"):
                prefix_text += "\n"
        else:
            prefix_text += "\n\n"

    content = prefix_text + bullet_text
    if content and not content.endswith("\n"):
        content += "\n"
    with mkdocs_gen_files.open(DIAGRAM_INDEX_PATH, "w") as handle:
        handle.write(content)


def main() -> None:
    operations: list[OperationEntry] | None
    try:
        operations = collect_operations()
    except CLIConfigError as exc:
        LOGGER.exception(
            "Failed to collect CLI operations for diagram generation",
            extra={"status": "error"},
        )
        LOGGER.debug("CLI diagram problem details: %s", render_problem(exc.problem))
        operations = None
    diagram_written = False
    if operations:
        write_diagram(operations)
        diagram_written = True
    elif operations == []:
        LOGGER.info("No CLI operations discovered in configuration")
    update_cli_index_entry(enabled=diagram_written)


if __name__ == "__main__":  # pragma: no cover - executed by mkdocs
    main()


def _raise_diagram_error(
    detail: str,
    *,
    instance: str,
    status: int = 500,
    extras: Mapping[str, str] | None = None,
) -> NoReturn:
    problem = build_problem_details(
        ProblemDetailsParams(
            type="https://kgfoundry.dev/problems/cli-diagram",
            title="CLI diagram generation error",
            status=status,
            detail=detail,
            instance=instance,
            extensions=extras,
        )
    )
    LOGGER.error(detail, extra={**({} if extras is None else dict(extras)), "status": "error"})
    raise CLIConfigError(problem)


def _build_operations(
    operation_context: OperationContext,
    command: Command,
) -> list[OperationEntry]:
    operations: list[OperationEntry] = []
    for tokens, command_obj in walk_commands(command, []):
        path, operation, fallback_tags = operation_context.build_operation(tokens, command_obj)
        operation_id_raw = str(operation.get("operationId") or "").strip()
        operation_id = operation_id_raw or None
        summary = str(operation.get("summary") or "").strip()
        raw_tags = operation.get("tags")
        if isinstance(raw_tags, Sequence) and not isinstance(raw_tags, (str, bytes)):
            tag_candidates = [str(tag) for tag in raw_tags]
        else:
            tag_candidates = fallback_tags or ["cli"]
        tag_tuple = tuple(dict.fromkeys(tag_candidates))
        operations.append(("POST", path, operation_id, summary, tag_tuple))
    return operations
