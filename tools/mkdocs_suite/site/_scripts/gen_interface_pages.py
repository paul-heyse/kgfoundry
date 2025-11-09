"""Render an interface catalog sourced from nav sidecars and registry metadata."""

from __future__ import annotations

import importlib
import json
import logging
import posixpath
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import mkdocs_gen_files

from tools._shared.augment_registry import (
    AugmentRegistryError,
    load_registry,
    render_problem_details,
)
from tools.mkdocs_suite.docs._scripts import load_repo_settings
from tools.mkdocs_suite.docs._scripts._operation_links import (
    build_operation_href,
)

if TYPE_CHECKING:
    from tools._shared.augment_registry import (
        RegistryInterfaceModel,
        RegistryMetadataModel,
        RegistryOperationModel,
    )

SUITE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]
REGISTRY_PATH = SUITE_ROOT / "api_registry.yaml"
INTERFACES_DOC_PATH = "api/interfaces.md"

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())


REPO_URL, DEFAULT_BRANCH = load_repo_settings()


def _load_registry() -> RegistryMetadataModel | None:
    try:
        registry = load_registry(REGISTRY_PATH)
    except AugmentRegistryError as exc:
        LOGGER.exception(
            "Failed to load interface registry",
            extra={"status": "error", "path": str(REGISTRY_PATH)},
        )
        LOGGER.debug("Registry problem details: %s", render_problem_details(exc))
        return None
    return registry


def _ensure_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []


def _escape_table_text(value: object) -> str:
    """Escape Markdown table control characters in ``value``.

    Parameters
    ----------
    value : object
        Value to escape, will be converted to string.

    Returns
    -------
    str
        Escaped string safe for use in Markdown table cells.
    """
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("`", "\\`")
    return text.replace("\n", "<br />")


def _normalized_module_path(nav_path: Path, src_root: Path) -> str:
    try:
        relative_parent = nav_path.parent.relative_to(src_root)
    except ValueError:  # pragma: no cover - defensive guard
        return nav_path.parent.name
    parts = [part for part in relative_parent.parts if part not in {"", "."}]
    return ".".join(parts) if parts else nav_path.parent.name


def _collect_nav_interfaces() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    src_root = REPO_ROOT / "src"
    if not src_root.exists():
        return records
    for nav_path in src_root.glob("**/_nav.json"):
        normalized_module = _normalized_module_path(nav_path, src_root)
        with nav_path.open("r", encoding="utf-8") as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError as error:
                LOGGER.warning(
                    "Failed to decode nav metadata from %s: %s", nav_path, error
                )
                continue
        interfaces = data.get("interfaces") or []
        if not isinstance(interfaces, list):
            continue
        for entry in interfaces:
            if not isinstance(entry, dict):
                continue
            record = dict(entry)
            module_value = record.get("module")
            if not isinstance(module_value, str) or not module_value.strip():
                record["module"] = normalized_module
            record["_nav_module_path"] = normalized_module
            records.append(record)
    return records


def collect_nav_interfaces() -> list[dict[str, object]]:
    """Return interface metadata discovered from nav sidecars.

    Returns
    -------
    list[dict[str, object]]
        List of interface dictionaries extracted from nav sidecar files.
    """
    return _collect_nav_interfaces()


def _module_doc_link(module: object) -> str:
    if not isinstance(module, str) or not module:
        return "—"
    safe_label = _escape_table_text(module)
    if _resolve_source_path(module) is None:
        return safe_label
    module_doc = posixpath.join("modules", module.replace(".", "/") + ".md")
    base_dir = posixpath.dirname(INTERFACES_DOC_PATH)
    href = posixpath.relpath(module_doc, base_dir or ".")
    return f"[{safe_label}]({href})"


def _operation_href(spec_path: object, operation_id: str) -> str | None:
    href = build_operation_href(spec_path, operation_id)
    if href is None:
        return None
    base_dir = posixpath.dirname(INTERFACES_DOC_PATH) or "."
    return posixpath.relpath(href, base_dir)


def _parse_handler_module(handler: object) -> str | None:
    if not isinstance(handler, str) or ":" not in handler:
        return None
    module, _ = handler.split(":", 1)
    module = module.strip()
    return module or None


@lru_cache(maxsize=512)
def _resolve_source_path(module_path: str) -> Path | None:
    candidate = Path("src") / Path(module_path.replace(".", "/") + ".py")
    package_init = Path("src") / Path(module_path.replace(".", "/")) / "__init__.py"
    for option in (candidate, package_init):
        if (REPO_ROOT / option).exists():
            return option
    return None


def _code_link_for_module(module_path: str | None) -> str | None:
    if not module_path:
        return None
    rel_path = _resolve_source_path(module_path)
    if rel_path is None or REPO_URL is None:
        return None
    branch = DEFAULT_BRANCH or "main"
    return f"{REPO_URL}/blob/{branch}/{rel_path.as_posix()}"


def _spec_link(record: dict[str, object]) -> str:
    spec_path = record.get("spec")
    if not isinstance(spec_path, str) or not spec_path:
        return "—"
    if spec_path.endswith("openapi-cli.yaml"):
        return "[CLI Spec](../api/openapi-cli.md)"
    if spec_path.endswith("openapi.yaml"):
        return "[HTTP API](../api/index.md)"
    docs_path = SUITE_ROOT / "docs" / spec_path
    if docs_path.exists():
        rel = Path("..") / spec_path
        safe_label = _escape_table_text(spec_path)
        return f"[{safe_label}]({rel.as_posix()})"
    return _escape_table_text(spec_path)


def _problem_details(
    record: Mapping[str, object],
    interface: RegistryInterfaceModel | None = None,
) -> str:
    details = record.get("problem_details")
    if isinstance(details, list):
        return ", ".join(str(item) for item in details)
    if isinstance(details, str):
        return details
    if interface is not None and interface.problem_details:
        return ", ".join(interface.problem_details)
    return "—"


def _problem_summary(
    record: Mapping[str, object],
    interface_model: RegistryInterfaceModel | None,
) -> str:
    details = record.get("problem_details")
    if isinstance(details, list):
        return ", ".join(str(item) for item in details)
    if isinstance(details, str):
        return details
    if interface_model and interface_model.problem_details:
        return ", ".join(interface_model.problem_details)
    return "—"


def _write_catalog_intro(handle: mkdocs_gen_files.files) -> None:
    """Emit the static intro blurb for the interface catalog page."""
    handle.write("# Interface Catalog\n\n")
    handle.write(
        "This catalog is generated from `_nav.json` sidecars and the shared interface registry.\n\n"
    )


def _write_interface_table(
    handle: mkdocs_gen_files.files,
    interfaces: list[dict[str, object]],
    registry: RegistryMetadataModel | None,
) -> set[str]:
    """Render the overview table and return the set of discovered interface IDs.

    Parameters
    ----------
    handle : mkdocs_gen_files.files
        File handle for writing markdown content.
    interfaces : list[dict[str, object]]
        List of interface dictionaries from nav metadata.
    registry : RegistryMetadataModel | None
        Typed registry metadata resolved from the shared augment/registry facade.

    Returns
    -------
    set[str]
        Normalized identifiers sourced from nav sidecars that will have detail
        sections rendered later in the document.
    """
    handle.write(
        "| Interface | Type | Module | Owner | Stability | Spec | Description | Problem Details |\n"
    )
    handle.write(
        "| --------- | ---- | ------ | ----- | -------- | ---- | ----------- | ---------------- |\n"
    )

    interface_ids: set[str] = set()
    for record in interfaces:
        identifier_value = str(record.get("id") or record.get("entrypoint") or "—")
        interface_model = registry.interface(identifier_value) if registry else None
        description_value = (
            record.get("description")
            or (interface_model.description if interface_model else None)
            or "—"
        )
        spec_candidate = record.get("spec") or (
            interface_model.spec if interface_model else None
        )
        spec_cell = _spec_link({"spec": spec_candidate})
        owner_value = record.get("owner") or (
            interface_model.owner if interface_model else None
        )
        if isinstance(owner_value, list):
            owner_value = ", ".join(str(item) for item in owner_value)
        stability_value = (
            record.get("stability")
            or (interface_model.stability if interface_model else None)
            or "—"
        )
        module_path = (
            record.get("module")
            or (interface_model.module if interface_model else None)
            or record.get("_nav_module_path")
        )
        row = "| {id} | {type} | {module} | {owner} | {stability} | {spec} | {desc} | {problems} |".format(
            id=_escape_table_text(identifier_value),
            type=_escape_table_text(
                record.get("type")
                or (interface_model.type if interface_model else "—")
                or "—"
            ),
            module=_module_doc_link(module_path),
            owner=_escape_table_text(owner_value or "—"),
            stability=_escape_table_text(stability_value),
            spec=spec_cell,
            desc=_escape_table_text(description_value),
            problems=_escape_table_text(_problem_details(record, interface_model)),
        )
        handle.write(row + "\n")
        if record.get("id"):
            interface_ids.add(str(record["id"]))
    return interface_ids


def write_interface_table(
    handle: mkdocs_gen_files.files,
    interfaces: list[dict[str, object]],
    registry: RegistryMetadataModel | None,
) -> set[str]:
    """Public wrapper around the interface table writer for testing support.

    Parameters
    ----------
    handle : mkdocs_gen_files.files
        File handle for writing markdown content.
    interfaces : list[dict[str, object]]
        List of interface dictionaries from nav metadata.
    registry : RegistryMetadataModel | None
        Typed registry metadata resolved from the shared augment/registry facade.

    Returns
    -------
    set[str]
        Normalized identifiers sourced from nav sidecars that will have detail
        sections rendered later in the document.
    """
    return _write_interface_table(handle, interfaces, registry)


def _write_optional_list(
    handle: mkdocs_gen_files.files, label: str, values: list[str]
) -> None:
    """Write a bullet list line when values are present."""
    if values:
        handle.write(f"  - {label}: {', '.join(values)}\n")


def _write_optional_line(
    handle: mkdocs_gen_files.files, label: str, value: object
) -> None:
    """Write a bullet list line when ``value`` is truthy."""
    if value:
        handle.write(f"  - {label}: `{value}`\n")


def _write_code_samples(handle: mkdocs_gen_files.files, samples: object) -> None:
    """Emit code samples for an operation when provided in the registry."""
    if not isinstance(samples, list) or not samples:
        return
    handle.write("  - Code Samples:\n")
    for sample in samples:
        if isinstance(sample, Mapping):
            lang = sample.get("lang", "")
            source = sample.get("source", "")
            handle.write(f"    * ({lang}) `{source}`\n")


def _operations_block(
    handle: mkdocs_gen_files.files,
    operations: Mapping[str, RegistryOperationModel] | None,
    spec_path: str | None,
) -> None:
    """Render operation metadata if the registry entry exposes operations."""
    if not operations:
        return
    handle.write("\n### Operations\n\n")
    for op_key, op_meta in operations.items():
        op_id = op_meta.operation_id or f"cli.{op_key.replace('-', '_')}"
        summary = op_meta.summary or ""
        href = _operation_href(spec_path, op_id)
        if href:
            handle.write(f"- [`{op_id}`]({href}) — {summary}\n")
        else:
            handle.write(f"- `{op_id}` — {summary}\n")
        module_path = _parse_handler_module(op_meta.handler)
        if module_path:
            handle.write(f"    - Module docs: {_module_doc_link(module_path)}\n")
            code_link = _code_link_for_module(module_path)
            if code_link:
                handle.write(f"    - Source: [{module_path}]({code_link})\n")
        _write_optional_list(handle, "Tags", list(op_meta.tags))
        _write_optional_line(handle, "Handler", op_meta.handler)
        _write_optional_list(handle, "Env", list(op_meta.env))
        _write_optional_list(handle, "Problem Details", list(op_meta.problem_details))
        _write_code_samples(handle, op_meta.extras.get("code_samples"))


def _write_interface_details(
    handle: mkdocs_gen_files.files,
    interface_ids: set[str],
    interfaces: list[dict[str, object]],
    registry: RegistryMetadataModel | None,
) -> None:
    """Write detailed sections per interface identifier."""
    lookup = {str(record["id"]): record for record in interfaces if record.get("id")}
    for identifier in sorted(interface_ids):
        nav_meta = lookup.get(identifier, {})
        interface_model = registry.interface(identifier) if registry else None
        if interface_model is None and registry is not None:
            try:
                interface_model = registry.interfaces.get(identifier)
            except AttributeError:  # pragma: no cover - defensive
                interface_model = None

        handle.write(f"## {identifier}\n\n")
        handle.write(
            "* **Type:** {type}\n".format(
                type=nav_meta.get("type")
                or (interface_model.type if interface_model else None)
                or "—"
            )
        )
        module_value = (
            nav_meta.get("module")
            or (interface_model.module if interface_model else None)
            or nav_meta.get("_nav_module_path")
        )
        module_doc = _module_doc_link(module_value)
        handle.write(f"* **Module:** {module_doc}\n")
        module_source = (
            _code_link_for_module(module_value)
            if isinstance(module_value, str)
            else None
        )
        if module_source:
            handle.write(f"* **Source:** [{module_value}]({module_source})\n")
        handle.write(
            "* **Owner:** {owner}\n".format(
                owner=nav_meta.get("owner")
                or (interface_model.owner if interface_model else None)
                or "—"
            )
        )
        handle.write(
            "* **Stability:** {stability}\n".format(
                stability=nav_meta.get("stability")
                or (interface_model.stability if interface_model else None)
                or "—"
            )
        )
        description = nav_meta.get("description") or (
            interface_model.description if interface_model else None
        )
        if description:
            handle.write(f"* **Description:** {description}\n")

        spec_path = (
            interface_model.spec
            if interface_model and interface_model.spec
            else nav_meta.get("spec")
        )
        operations = interface_model.operations if interface_model else None
        _operations_block(
            handle, operations, spec_path if isinstance(spec_path, str) else None
        )
        handle.write("\n")


def render_interface_catalog() -> None:
    globals()["mkdocs_gen_files"] = importlib.import_module("mkdocs_gen_files")
    registry = _load_registry()
    interfaces = _collect_nav_interfaces()
    if registry is not None:
        nav_lookup: dict[str, dict[str, object]] = {}
        for record in interfaces:
            candidate_id = record.get("id")
            if isinstance(candidate_id, str) and candidate_id.strip():
                nav_lookup[candidate_id] = record
        for identifier, interface_model in registry.interfaces.items():
            key = str(identifier)
            if key in nav_lookup:
                continue
            placeholder: dict[str, object] = {"id": key}
            if interface_model.type:
                placeholder["type"] = interface_model.type
            interfaces.append(placeholder)
    interfaces.sort(key=lambda item: (str(item.get("type")), str(item.get("id"))))

    with mkdocs_gen_files.open("api/interfaces.md", "w") as handle:
        _write_catalog_intro(handle)
        interface_ids = _write_interface_table(handle, interfaces, registry)
        if registry is not None:
            interface_ids.update(str(key) for key in registry.interfaces)
        handle.write("\n")
        _write_interface_details(handle, interface_ids, interfaces, registry)


render_interface_catalog()
