"""Generate per-module MkDocs pages using Griffe and the navmap integration.

The script is executed via ``mkdocs-gen-files`` as part of the MkDocs build for
the experimental documentation suite. It loads the KgFoundry packages with
Griffe, derives module relationships, and emits one Markdown file per module.

Integration with the existing Griffe-based navmap generator ensures both
systems rely on the same traversal semantics, extensions, and docstring parser.
Whenever the navmap surface changes the MkDocs pages automatically pick up the
revisions without additional glue code.
"""

from __future__ import annotations

import copy
import importlib
import json
import logging
import posixpath
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeGuard, cast
from urllib.parse import urlparse

import mkdocs_gen_files

from tools._shared.augment_registry import (
    AugmentRegistryError,
    load_registry,
    render_problem_details,
)
from tools.mkdocs_suite.docs._scripts import load_repo_settings
from tools.mkdocs_suite.docs._scripts._operation_links import build_operation_href


class _NavProtocol(Protocol):
    def __setitem__(self, keys: str | Sequence[str], item: str) -> None: ...

    def build_literate_nav(self) -> Sequence[str]: ...


if hasattr(mkdocs_gen_files, "Nav"):

    def _make_nav() -> _NavProtocol:
        instance = mkdocs_gen_files.Nav()  # type: ignore[reportPrivateImportUsage]
        return cast("_NavProtocol", instance)

else:  # pragma: no cover - fallback for older mkdocs-gen-files versions

    class _FallbackNav(dict[str | tuple[str, ...], str]):
        """Fallback navigation helper when mkdocs-gen-files lacks ``Nav``."""

        def __setitem__(self, keys: str | Sequence[str], item: str) -> None:
            if isinstance(keys, tuple):
                normalized: str | tuple[str, ...] = keys
            elif isinstance(keys, Sequence) and not isinstance(keys, (str, bytes)):
                normalized = tuple(keys)
            else:
                normalized = str(keys)
            super().__setitem__(normalized, item)

        def build_literate_nav(self) -> list[str]:
            lines: list[str] = []
            for key, value in self.items():
                label = key[-1] if isinstance(key, tuple) else key
                lines.append(f"- [{label}]({value})\n")
            return lines

    def _make_nav() -> _NavProtocol:
        return cast("_NavProtocol", _FallbackNav())


LOGGER = logging.getLogger(__name__)


@contextmanager
def _suppress_griffe_errors() -> Iterator[None]:
    """Temporarily raise the griffe logger level to suppress known load failures.

    Yields
    ------
    None
        Context manager sentinel used to restore the previous log level.
    """
    griffe_logger = logging.getLogger("griffe")
    previous_disabled = griffe_logger.disabled
    previous_level = griffe_logger.level
    previous_propagate = griffe_logger.propagate
    root_logger = logging.getLogger()
    previous_root_level = root_logger.level
    griffe_logger.disabled = True
    griffe_logger.setLevel(logging.CRITICAL)
    griffe_logger.propagate = False
    root_logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        griffe_logger.disabled = previous_disabled
        griffe_logger.setLevel(previous_level)
        griffe_logger.propagate = previous_propagate
        root_logger.setLevel(previous_root_level)


PROJECT_ROOT = Path(__file__).resolve().parents[4]
TOOLS_ROOT = PROJECT_ROOT / "tools"
SRC_ROOT = PROJECT_ROOT / "src"
SUITE_ROOT = TOOLS_ROOT / "mkdocs_suite"


REPO_URL, DEFAULT_BRANCH = load_repo_settings()

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from kgfoundry_common.navmap_loader import NavMetadataModel
    from kgfoundry_common.navmap_loader import load_nav_metadata as _load_nav_metadata
    from tools._shared.augment_registry import (
        RegistryInterfaceModel,
        RegistryMetadataModel,
    )
    from tools.navmap.griffe_navmap import (
        DEFAULT_EXTENSIONS as _DEFAULT_EXTENSIONS,
    )
    from tools.navmap.griffe_navmap import (
        DEFAULT_SEARCH_PATHS as _DEFAULT_SEARCH_PATHS,
    )
else:
    _griffe_navmap_module_path = TOOLS_ROOT / "navmap" / "griffe_navmap.py"
    _griffe_navmap_spec = importlib.util.spec_from_file_location(
        "tools.mkdocs_suite._griffe_navmap", _griffe_navmap_module_path
    )
    if (
        _griffe_navmap_spec is None or _griffe_navmap_spec.loader is None
    ):  # pragma: no cover - defensive guard
        error_message = f"Unable to load griffe navmap module from {_griffe_navmap_module_path}"
        raise RuntimeError(error_message)
    _griffe_navmap = importlib.util.module_from_spec(_griffe_navmap_spec)
    sys.modules[_griffe_navmap_spec.name] = _griffe_navmap
    loader = cast("importlib.abc.Loader", _griffe_navmap_spec.loader)
    loader.exec_module(_griffe_navmap)

    _nav_loader_path = SRC_ROOT / "kgfoundry_common" / "navmap_loader.py"
    _nav_loader_spec = importlib.util.spec_from_file_location(
        "tools.mkdocs_suite._navmap_loader", _nav_loader_path
    )
    if _nav_loader_spec is None or _nav_loader_spec.loader is None:  # pragma: no cover
        error_message = f"Unable to load navmap loader from {_nav_loader_path}"
        raise RuntimeError(error_message)
    _nav_loader = importlib.util.module_from_spec(_nav_loader_spec)
    sys.modules[_nav_loader_spec.name] = _nav_loader
    loader = cast("importlib.abc.Loader", _nav_loader_spec.loader)
    loader.exec_module(_nav_loader)
    NavMetadataModel = getattr(_nav_loader, "NavMetadataModel", None)

    DEFAULT_EXTENSIONS = list(_griffe_navmap.DEFAULT_EXTENSIONS)
    DEFAULT_SEARCH_PATHS = list(_griffe_navmap.DEFAULT_SEARCH_PATHS)
    load_nav_metadata = _nav_loader.load_nav_metadata

if TYPE_CHECKING:
    DEFAULT_EXTENSIONS = list(_DEFAULT_EXTENSIONS)
    DEFAULT_SEARCH_PATHS = list(_DEFAULT_SEARCH_PATHS)
    load_nav_metadata = _load_nav_metadata


PACKAGE_DENYLIST = frozenset(
    {
        "codeintel",
        "examples",
        "kf_common",
        "kgfoundry",
        "tests",
    }
)
PACKAGE_PRIORITY_ORDER = ("kgfoundry_common",)
API_USAGE_FILE = Path(__file__).with_name("api_usage.json")
REGISTRY_PATH = SUITE_ROOT / "api_registry.yaml"


_griffe = importlib.import_module("griffe")
_load = cast("Callable[..., object]", _griffe.load)
_load_extensions = cast("Callable[..., object]", _griffe.load_extensions)
_GriffeError = getattr(_griffe, "GriffeError", Exception)


def _is_package_directory(path: Path) -> bool:
    """Return ``True`` when ``path`` is a Python package directory.

    Parameters
    ----------
    path : Path
        Directory path to check.

    Returns
    -------
    bool
        ``True`` if ``path`` contains an ``__init__.py`` file.
    """
    return path.is_dir() and (path / "__init__.py").is_file()


def _prioritize_packages(names: Sequence[str]) -> tuple[str, ...]:
    """Return package names ordered with priority entries at the front.

    Parameters
    ----------
    names : Sequence[str]
        Package names to prioritize.

    Returns
    -------
    tuple[str, ...]
        Package names with priority packages at the beginning.
    """
    prioritized = [name for name in PACKAGE_PRIORITY_ORDER if name in names]
    remainder = [name for name in names if name not in PACKAGE_PRIORITY_ORDER]
    return tuple(prioritized + remainder)


def _discover_package_roots(src_root: Path) -> tuple[str, ...]:
    """Return first-party package roots discovered from the repository.

    Parameters
    ----------
    src_root : Path
        Source root directory to search for packages.

    Returns
    -------
    tuple[str, ...]
        Sorted package names filtered by the denylist.
    """
    discovered: dict[str, None] = {}

    try:
        kgfoundry_module = importlib.import_module("kgfoundry")
    except ModuleNotFoundError:
        exports: Sequence[str] = ()
    else:
        exports = tuple(getattr(kgfoundry_module, "__all__", ()))

    for name in exports:
        if name in PACKAGE_DENYLIST:
            continue
        discovered[name] = None

    for candidate in sorted(src_root.iterdir(), key=lambda path: path.name):
        name = candidate.name
        if name in PACKAGE_DENYLIST or name.startswith("_"):
            continue
        if not _is_package_directory(candidate):
            continue
        discovered.setdefault(name, None)

    return _prioritize_packages(tuple(discovered))


@lru_cache(maxsize=1)
def _get_package_roots() -> tuple[str, ...]:
    """Return cached package roots for module collection.

    Returns
    -------
    tuple[str, ...]
        Cached package names discovered from the repository sources.
    """
    return _discover_package_roots(SRC_ROOT)


def get_package_roots() -> tuple[str, ...]:
    """Return discovered package roots for documentation generation.

    Returns
    -------
    tuple[str, ...]
        Cached package names discovered from the repository sources.
    """
    return _get_package_roots()


def reset_package_roots_cache() -> None:
    """Clear cached package roots to force discovery on next access."""
    _get_package_roots.cache_clear()


class _Docstring(Protocol):
    value: str | None


class _GriffeObject(Protocol):
    path: str


class _GriffeWithMembers(_GriffeObject, Protocol):
    members: Mapping[str, object]


class _GriffeModule(_GriffeWithMembers, Protocol):
    docstring: _Docstring | None
    exports: Sequence[object] | None
    relative_filepath: Path | None


class _GriffeAlias(_GriffeObject, Protocol):
    is_imported: bool
    target_path: str | None
    target: object | None


class _GriffeClass(_GriffeWithMembers, Protocol):
    bases: Sequence[object]


class _GriffeFunction(_GriffeWithMembers, Protocol): ...


@dataclass(slots=True, frozen=True)
class _RelationshipTables:
    imports: dict[str, set[str]]
    classes: dict[str, list[str]]
    functions: dict[str, list[str]]
    bases: dict[str, list[str]]


@dataclass(frozen=True, slots=True)
class OperationLink:
    """Link metadata for an OpenAPI or CLI operation."""

    operation_id: str
    href: str | None
    interface_id: str | None
    spec_label: str | None


@dataclass(slots=True, frozen=True)
class ModuleFacts:
    """Aggregated metadata used when rendering module pages."""

    imports: dict[str, set[str]]
    imported_by: dict[str, set[str]]
    exports: dict[str, set[str]]
    classes: dict[str, list[str]]
    functions: dict[str, list[str]]
    bases: dict[str, list[str]]
    api_usage: Mapping[str, list[OperationLink]]
    documented_modules: set[str]
    source_paths: dict[str, Path]


def _is_kind(obj: object, expected: str) -> bool:
    return obj.__class__.__name__ == expected


def _is_module(obj: object) -> TypeGuard[_GriffeModule]:
    return _is_kind(obj, "Module")


def _is_alias(obj: object) -> TypeGuard[_GriffeAlias]:
    return _is_kind(obj, "Alias")


def _is_class(obj: object) -> TypeGuard[_GriffeClass]:
    return _is_kind(obj, "Class")


def _is_function(obj: object) -> TypeGuard[_GriffeFunction]:
    return _is_kind(obj, "Function")


def _first_paragraph(module: _GriffeModule) -> str | None:
    """Return the first paragraph from the module docstring, if present.

    Parameters
    ----------
    module : _GriffeModule
        Griffe module object.

    Returns
    -------
    str | None
        First paragraph of the module docstring when available; otherwise ``None``.
    """
    if module.docstring is None or not module.docstring.value:
        return None
    content = module.docstring.value.strip()
    if not content:
        return None
    return content.split("\n\n", maxsplit=1)[0]


def _discover_extensions(candidates: Iterable[str]) -> tuple[list[str], object | None]:
    """Return available Griffe extensions and a preloaded bundle.

    Parameters
    ----------
    candidates : Iterable[str]
        Extension module names to probe.

    Returns
    -------
    tuple[list[str], object | None]
        A tuple containing the subset of importable extension names and the
        optional bundle returned by ``griffe.load_extensions``.
    """
    names = list(candidates)
    if not names:
        return [], None
    try:
        return names, _load_extensions(*names)
    except ModuleNotFoundError:
        available: list[str] = []
        for name in names:
            try:
                _load_extensions(name)
            except ModuleNotFoundError:
                continue
            available.append(name)
        if not available:
            return [], None
        return available, _load_extensions(*available)


def _collect_modules(extensions_bundle: object) -> dict[str, _GriffeModule]:
    """Load all submodules for the configured package roots.

    Parameters
    ----------
    extensions_bundle : object
        Preloaded extension bundle returned by ``griffe.load_extensions``.

    Returns
    -------
    dict[str, _GriffeModule]
        Mapping of module path to Griffe module objects.
    """
    modules: dict[str, _GriffeModule] = {}
    visited: set[str] = set()
    for package in _get_package_roots():
        try:
            with _suppress_griffe_errors():
                root = _load(
                    package,
                    submodules=True,
                    extensions=extensions_bundle,
                    search_paths=DEFAULT_SEARCH_PATHS,
                    docstring_parser="numpy",
                    resolve_aliases=True,
                    resolve_external=True,
                )
        except _GriffeError as exc:  # pragma: no cover - degradation for broken modules
            LOGGER.warning("Skipping package %s due to Griffe load error: %s", package, exc)
            continue
        if not _is_module(root):  # pragma: no cover - defensive guard
            continue

        def _visit(module: _GriffeModule) -> None:
            if module.path in visited:
                return
            visited.add(module.path)
            modules[module.path] = module
            for child in module.members.values():
                if _is_module(child):
                    _visit(child)

        _visit(root)
    return modules


def collect_modules(extensions_bundle: object) -> dict[str, _GriffeModule]:
    """Public wrapper around module collection to support testing.

    Parameters
    ----------
    extensions_bundle : object
        Griffe extensions bundle for module discovery.

    Returns
    -------
    dict[str, _GriffeModule]
        Dictionary mapping module paths to Griffe module objects.
    """
    return _collect_modules(extensions_bundle)


def _code_permalink(relative_path: Path | None) -> str | None:
    """Return a GitHub permalink for ``relative_path`` when configured.

    Parameters
    ----------
    relative_path : Path | None
        Relative path to the source file.

    Returns
    -------
    str | None
        Fully-qualified repository URL or ``None`` if linking is disabled.
    """
    if relative_path is None or REPO_URL is None:
        return None
    branch = DEFAULT_BRANCH or "main"
    return f"{REPO_URL}/blob/{branch}/{relative_path.as_posix()}"


def _load_api_usage() -> dict[str, list[OperationLink]]:
    """Return optional API usage mappings for deep-linking ReDoc operations.

    Returns
    -------
    dict[str, list[OperationLink]]
        Mapping of symbol paths to operation references derived from JSON.
    """
    if not API_USAGE_FILE.exists():
        return {}
    try:
        raw_mapping = json.loads(API_USAGE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        LOGGER.warning(
            "Skipping API usage map at %s due to invalid JSON: %s",
            API_USAGE_FILE,
            exc,
        )
        return {}
    if not isinstance(raw_mapping, Mapping):
        LOGGER.warning(
            "Skipping API usage map at %s because the payload is not a mapping",
            API_USAGE_FILE,
        )
        return {}
    usage: dict[str, list[OperationLink]] = defaultdict(list)
    for symbol, operations in raw_mapping.items():
        if not isinstance(symbol, str):
            continue
        if isinstance(operations, list):
            for op in operations:
                op_id = str(op)
                usage[symbol].append(OperationLink(op_id, None, None, None))
        elif isinstance(operations, str):
            usage[symbol].append(OperationLink(str(operations), None, None, None))
    return usage


def _symbol_from_handler(handler: object) -> str | None:
    """Return the fully-qualified symbol path for a registry handler string.

    Parameters
    ----------
    handler : object
        Handler string from registry metadata.

    Returns
    -------
    str | None
        Symbol path derived from the handler, or ``None`` when the handler
        cannot be parsed.
    """
    if not isinstance(handler, str) or ":" not in handler:
        return None
    module, attribute = handler.split(":", 1)
    module = module.strip()
    attribute = attribute.strip().replace(":", ".")
    if not module or not attribute:
        return None
    return f"{module}.{attribute}"


def _registry_api_usage(
    registry: RegistryMetadataModel | None,
) -> dict[str, list[OperationLink]]:
    """Derive symbol → operation mappings from the interface registry.

    Parameters
    ----------
    registry : RegistryMetadataModel | None
        Interface registry metadata resolved from the shared facade.

    Returns
    -------
    dict[str, list[OperationLink]]
        Mapping of symbol paths to `OperationLink` records from registry data.
    """
    mapping: dict[str, list[OperationLink]] = defaultdict(list)
    if registry is None:
        return mapping
    for identifier, entry in registry.interfaces.items():
        if not entry.operations:
            continue
        spec_path = entry.spec
        spec_label, _ = _spec_href(spec_path)
        for op_meta in entry.operations.values():
            handler = _symbol_from_handler(op_meta.handler)
            operation_id = op_meta.operation_id
            if not handler or not operation_id:
                continue
            href = _operation_href(spec_path, operation_id)
            mapping[handler].append(OperationLink(operation_id, href, identifier, spec_label))
    return mapping


def _merge_api_usage(
    file_usage: Mapping[str, list[OperationLink]],
    registry_usage: Mapping[str, list[OperationLink]],
) -> dict[str, list[OperationLink]]:
    """Merge API usage derived from JSON files and the interface registry.

    Parameters
    ----------
    file_usage : Mapping[str, list[OperationLink]]
        API usage mappings from JSON files.
    registry_usage : Mapping[str, list[OperationLink]]
        API usage mappings from interface registry.

    Returns
    -------
    dict[str, list[OperationLink]]
        Combined mapping with deduplicated operation references.
    """
    merged: dict[str, dict[tuple[str, str | None], OperationLink]] = defaultdict(dict)
    for symbol, operations in file_usage.items():
        for operation in operations:
            key = (operation.operation_id, operation.href)
            merged[symbol][key] = operation
    for symbol, operations in registry_usage.items():
        for operation in operations:
            key = (operation.operation_id, operation.href)
            merged[symbol][key] = operation
    return {
        symbol: [entry for _, entry in sorted(store.items(), key=lambda item: item[0])]
        for symbol, store in merged.items()
    }


def _load_registry() -> RegistryMetadataModel | None:
    """Return the interface registry payload keyed by identifier.

    Returns
    -------
    RegistryMetadataModel | None
        Typed registry metadata, or ``None`` when the registry file is missing or invalid.
    """
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


def _module_exports(module: _GriffeModule) -> set[str]:
    """Extract export names declared in ``__all__`` for the module.

    Parameters
    ----------
    module : _GriffeModule
        Griffe module object.

    Returns
    -------
    set[str]
        Names explicitly exported via ``__all__``.
    """
    names: set[str] = set()
    exports = module.exports or ()
    for export in exports:
        name = getattr(export, "name", None)
        if isinstance(name, str):
            names.add(name)
    return names


def _register_member(module_path: str, member: object, tables: _RelationshipTables) -> None:
    """Populate relationship tables based on a member from ``module_path``."""
    if _is_alias(member) and member.is_imported:
        target = member.target_path or getattr(member.target, "path", None)
        if isinstance(target, str):
            tables.imports[module_path].add(target)
        return
    if _is_class(member):
        tables.classes[module_path].append(member.path)
        for base in member.bases:
            base_path = getattr(base, "path", None)
            if isinstance(base_path, str):
                tables.bases[member.path].append(base_path)
        return
    if _is_function(member):
        tables.functions[module_path].append(member.path)


def _build_relationships(
    modules: Mapping[str, _GriffeModule], api_usage: Mapping[str, list[OperationLink]]
) -> ModuleFacts:
    """Return imports, exports, symbols, and related API usage facts.

    Parameters
    ----------
    modules : Mapping[str, _GriffeModule]
        Mapping of module paths to Griffe module objects.
    api_usage : Mapping[str, list[OperationLink]]
        Mapping of symbol paths to operation references.

    Returns
    -------
    ModuleFacts
        Aggregated relationship tables used for rendering module pages.
    """
    tables = _RelationshipTables(
        imports=defaultdict(set),
        classes=defaultdict(list),
        functions=defaultdict(list),
        bases=defaultdict(list),
    )
    imports = tables.imports
    exports: dict[str, set[str]] = defaultdict(set)
    source_paths: dict[str, Path] = {}
    for module_path, module in modules.items():
        exports[module_path].update(_module_exports(module))
        for member in module.members.values():
            _register_member(module_path, member, tables)
        relative = getattr(module, "relative_filepath", None)
        if isinstance(relative, Path):
            source_paths[module_path] = relative
    imported_by: dict[str, set[str]] = defaultdict(set)
    for src, targets in imports.items():
        for target in targets:
            imported_by[target].add(src)
    return ModuleFacts(
        imports=dict(imports),
        imported_by=dict(imported_by),
        exports=dict(exports),
        classes=dict(tables.classes),
        functions=dict(tables.functions),
        bases=dict(tables.bases),
        api_usage=api_usage,
        documented_modules=set(modules.keys()),
        source_paths=source_paths,
    )


def _module_doc_path(module_path: str) -> str:
    return posixpath.join("modules", module_path.replace(".", "/") + ".md")


def _relative_module_href(from_module: str, to_module: str) -> str:
    from_path = _module_doc_path(from_module)
    to_path = _module_doc_path(to_module)
    base_dir = posixpath.dirname(from_path) or "."
    return posixpath.relpath(to_path, base_dir)


def _module_parent(module_path: str) -> str | None:
    if "." not in module_path:
        return None
    return module_path.rsplit(".", 1)[0]


def _direct_children(module_path: str, modules: Iterable[str]) -> list[str]:
    prefix = f"{module_path}."
    children: set[str] = set()
    for candidate in modules:
        if candidate.startswith(prefix):
            remainder = candidate[len(prefix) :]
            if remainder and "." not in remainder:
                children.add(candidate)
    return sorted(children)


def _escape_d2(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _module_github_link(module_path: str, facts: ModuleFacts) -> str | None:
    source_path = facts.source_paths.get(module_path)
    if source_path is None:
        return None
    return _code_permalink(source_path)


def _module_diagram_link(
    module_path: str,
    facts: ModuleFacts,
    *,
    inline: bool,
) -> str | None:
    github_link = _module_github_link(module_path, facts)
    if github_link:
        return github_link

    if module_path in facts.documented_modules:
        doc_path = module_path.replace(".", "/") + ".md"
        if inline:
            return f"./{doc_path}"
        return f"../modules/{doc_path}"
    return None


def _diagram_node_statement(name: str, link: str | None) -> str:
    escaped_name = _escape_d2(name)
    statement = f'"{escaped_name}": "{escaped_name}"'
    if link:
        statement += f' {{ link: "{link}" }}'
    return statement


def _module_hierarchy_items(module_path: str, facts: ModuleFacts) -> list[str]:
    items: list[str] = []
    parent = _module_parent(module_path)
    if parent:
        if parent in facts.documented_modules:
            href = _relative_module_href(module_path, parent)
            items.append(f"- **Parent:** [{parent}]({href})")
        else:
            items.append(f"- **Parent:** `{parent}`")

    children = _direct_children(module_path, facts.documented_modules)
    if children:
        child_links: list[str] = []
        for child in children:
            if child in facts.documented_modules:
                href = _relative_module_href(module_path, child)
                child_links.append(f"[{child}]({href})")
            else:
                child_links.append(f"`{child}`")
        items.append(f"- **Children:** {', '.join(child_links)}")
    return items


def _write_synopsis(fd: mkdocs_gen_files.files, nav_dict: Mapping[str, Any]) -> None:
    synopsis = nav_dict.get("synopsis")
    if isinstance(synopsis, str) and synopsis.strip():
        fd.write(synopsis.strip() + "\n\n")


def _write_source_link(
    fd: mkdocs_gen_files.files,
    module_path: str,
    facts: ModuleFacts,
) -> None:
    code_link = _code_permalink(facts.source_paths.get(module_path))
    if code_link:
        fd.write(f"[View source on GitHub]({code_link})\n\n")


def _write_hierarchy_section(
    fd: mkdocs_gen_files.files,
    module_path: str,
    facts: ModuleFacts,
) -> None:
    hierarchy_items = _module_hierarchy_items(module_path, facts)
    if not hierarchy_items:
        return
    fd.write("## Hierarchy\n\n")
    fd.write("\n".join(hierarchy_items) + "\n\n")


def _write_exports_block(fd: mkdocs_gen_files.files, exports: object) -> None:
    if isinstance(exports, Sequence) and exports:
        export_list = ", ".join(f"`{name}`" for name in exports)
        fd.write(f"*Exports:* {export_list}\n\n")


def _write_sections_overview(fd: mkdocs_gen_files.files, sections: object) -> None:
    if not isinstance(sections, Sequence) or not sections:
        return
    fd.write("## Sections\n\n")
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        title = str(section.get("title") or section.get("id") or "Section")
        symbols = section.get("symbols")
        if isinstance(symbols, Sequence) and symbols:
            symbol_list = ", ".join(f"`{symbol}`" for symbol in symbols)
            fd.write(f"- **{title}:** {symbol_list}\n")
        else:
            fd.write(f"- **{title}**\n")
    fd.write("\n")


def _format_module_links(
    current_module: str,
    module_names: Iterable[str],
    documented: set[str],
) -> str:
    """Return a comma-separated list of module names with links where possible.

    Parameters
    ----------
    current_module : str
        Module path for the document that is rendering the links.
    module_names : Iterable[str]
        Iterable of module names to format.
    documented : set[str]
        Set of module names that have documentation pages.

    Returns
    -------
    str
        Comma-separated string where documented modules link to their pages and
        external modules are rendered as inline code.
    """
    links: list[str] = []
    for name in module_names:
        if name in documented:
            href = _relative_module_href(current_module, name)
            links.append(f"[{name}]({href})")
        else:
            links.append(f"`{name}`")
    return ", ".join(links)


def _load_nav_metadata_mapping(module_path: str, exports: Sequence[str]) -> dict[str, Any]:
    try:
        raw_meta = load_nav_metadata(module_path, tuple(exports))
    except (ImportError, SyntaxError) as exc:
        LOGGER.warning(
            "Skipping nav metadata for %s due to import failure",
            module_path,
            exc_info=exc,
            extra={"status": "warning", "module_path": module_path},
        )
        raw_meta = {}
    if NavMetadataModel is not None and isinstance(raw_meta, NavMetadataModel):
        meta = copy.deepcopy(raw_meta.as_mapping())
    elif isinstance(raw_meta, Mapping):
        meta = copy.deepcopy(dict(raw_meta))
    else:
        meta = copy.deepcopy(cast("dict[str, Any]", raw_meta))
    meta = cast("dict[str, Any]", meta)
    meta["exports"] = list(exports)
    return meta


def _synchronise_symbol_metadata(meta: dict[str, Any], exports: Sequence[str]) -> None:
    symbols_meta = meta.get("symbols")
    if not isinstance(symbols_meta, Mapping):
        symbols_meta = {}
    meta["symbols"] = {name: dict(symbols_meta.get(name, {})) for name in exports}


def _ensure_sections(meta: dict[str, Any], exports: Sequence[str]) -> None:
    sections = meta.get("sections")
    if isinstance(sections, list) and sections:
        return
    meta["sections"] = [
        {
            "id": "public-api",
            "title": "Public API",
            "symbols": list(exports),
        }
    ]


def _ensure_synopsis(meta: dict[str, Any], module: _GriffeModule) -> None:
    synopsis = meta.get("synopsis")
    if synopsis:
        return
    first_paragraph = _first_paragraph(module)
    if first_paragraph:
        meta["synopsis"] = first_paragraph


def _merge_relationships(meta: dict[str, Any], module_path: str, facts: ModuleFacts) -> None:
    imports = sorted(facts.imports.get(module_path, set()))
    imported_by = sorted(facts.imported_by.get(module_path, set()))
    relationships: dict[str, list[str]] = {}
    if imports:
        relationships["imports"] = imports
    if imported_by:
        relationships["imported_by"] = imported_by
    existing = meta.get("relationships")
    if isinstance(existing, dict):
        relationships = {**existing, **relationships}
    if relationships:
        meta["relationships"] = relationships


def _nav_metadata_for_module(
    module_path: str, module: _GriffeModule, facts: ModuleFacts
) -> dict[str, Any]:
    """Return nav metadata merged with runtime defaults for ``module_path``.

    Parameters
    ----------
    module_path : str
        Fully qualified module path.
    module : _GriffeModule
        Griffe module object containing symbol metadata.
    facts : ModuleFacts
        Module facts including imports, exports, and relationships.

    Returns
    -------
    dict[str, Any]
        Complete navigation metadata dictionary for the module.
    """
    exports = sorted(_module_exports(module))
    meta = _load_nav_metadata_mapping(module_path, exports)
    _synchronise_symbol_metadata(meta, exports)
    _ensure_sections(meta, exports)
    _ensure_synopsis(meta, module)
    _merge_relationships(meta, module_path, facts)
    return meta


def _write_navmap_json(module_path: str, nav_meta: dict[str, Any]) -> None:
    """Persist nav metadata for ``module_path`` to the MkDocs virtual FS."""
    rel_path = module_path.replace(".", "/") + ".json"
    json_path = f"_data/navmaps/{rel_path}"
    with mkdocs_gen_files.open(json_path, "w") as fd:
        json.dump(nav_meta, fd, indent=2)


def _is_absolute_url(candidate: str) -> bool:
    """Return ``True`` when ``candidate`` is an absolute URL.

    Parameters
    ----------
    candidate : str
        String to check for absolute URL format.

    Returns
    -------
    bool
        ``True`` when ``candidate`` includes both scheme and netloc; otherwise ``False``.
    """
    parsed = urlparse(candidate)
    return bool(parsed.scheme and parsed.netloc)


def _spec_href(spec_path: object) -> tuple[str | None, str | None]:
    """Return a tuple of (label, href) for the provided spec path.

    Parameters
    ----------
    spec_path : object
        Specification file path.

    Returns
    -------
    tuple[str | None, str | None]
        Human-readable label and relative hyperlink for the specification. Both
        values are ``None`` when the spec path cannot be resolved.
    """
    if not isinstance(spec_path, str) or not spec_path:
        return None, None
    if _is_absolute_url(spec_path):
        return spec_path, spec_path
    if spec_path.endswith("openapi-cli.yaml"):
        return "CLI Spec", "api/openapi-cli.md"
    if spec_path.endswith("openapi.yaml"):
        return "HTTP API", "api/index.md"
    return spec_path, spec_path


def _operation_href(spec_path: object, operation_id: str) -> str | None:
    """Return a ReDoc anchor for ``operation_id`` based on ``spec_path``.

    Parameters
    ----------
    spec_path : object
        OpenAPI specification path or identifier.
    operation_id : str
        Operation identifier from the OpenAPI spec.

    Returns
    -------
    str | None
        Resolved hyperlink to the OpenAPI operation or ``None`` when unavailable.
    """
    return build_operation_href(spec_path, operation_id)


def _write_relationships(fd: mkdocs_gen_files.files, module_path: str, facts: ModuleFacts) -> None:
    """Write the relationships section for ``module_path``."""
    outgoing = sorted(facts.imports.get(module_path, set()))
    incoming = sorted(facts.imported_by.get(module_path, set()))
    exported = sorted(facts.exports.get(module_path, set()))
    if not (outgoing or incoming or exported):
        return
    fd.write("## Relationships\n\n")
    if outgoing:
        out_links = _format_module_links(module_path, outgoing, facts.documented_modules)
        fd.write(f"**Imports:** {out_links}\n\n")
    if incoming:
        in_links = _format_module_links(module_path, incoming, facts.documented_modules)
        fd.write(f"**Imported by:** {in_links}\n\n")
    if exported:
        export_list = ", ".join(f"`{name}`" for name in exported)
        fd.write(f"**Exports (`__all__`):** {export_list}\n\n")


def _write_related_operations(
    fd: mkdocs_gen_files.files, module_path: str, facts: ModuleFacts
) -> None:
    """Emit related API operations for symbols in ``module_path``."""
    collected: dict[tuple[str, str | None], OperationLink] = {}
    symbol_paths = facts.classes.get(module_path, []) + facts.functions.get(module_path, [])
    for symbol_path in symbol_paths:
        for operation in facts.api_usage.get(symbol_path, []):
            key = (operation.operation_id, operation.href)
            collected[key] = operation
    if not collected:
        return
    fd.write("## Related API operations\n\n")
    parts: list[str] = []
    for _, operation in sorted(collected.items(), key=lambda item: item[0]):
        label = f"`{operation.operation_id}`"
        if operation.href:
            module_doc = _module_doc_path(module_path)
            module_dir = posixpath.dirname(module_doc) or "."
            href = posixpath.relpath(operation.href, module_dir)
            label = f"[{label}]({href})"
        context: list[str] = []
        if operation.interface_id:
            context.append(operation.interface_id)
        if operation.spec_label and operation.spec_label not in context:
            context.append(operation.spec_label)
        if context:
            label = f"{label} ({' · '.join(context)})"
        parts.append(label)
    fd.write(", ".join(parts) + "\n\n")


def _write_contents(fd: mkdocs_gen_files.files, module_path: str, facts: ModuleFacts) -> None:
    """Render the class and function inventory for ``module_path``."""
    classes = facts.classes.get(module_path, [])
    functions = facts.functions.get(module_path, [])
    if not classes and not functions:
        return
    fd.write("## Contents\n\n")
    for class_path in sorted(classes):
        fd.write(f"### {class_path}\n\n::: {class_path}\n\n")
        base_paths = facts.bases.get(class_path, [])
        if base_paths:
            base_links = ", ".join(sorted(base_paths))
            fd.write(f"*Bases:* {base_links}\n\n")
    for function_path in sorted(functions):
        fd.write(f"### {function_path}\n\n::: {function_path}\n\n")


def _interface_entries(nav_meta: Mapping[str, Any]) -> list[Mapping[str, object]]:
    """Return validated interface entries from nav metadata.

    Parameters
    ----------
    nav_meta : Mapping[str, Any]
        Navigation metadata dictionary.

    Returns
    -------
    list[Mapping[str, object]]
        Normalized interface entries, or an empty list when no metadata is
        present.
    """
    interfaces = nav_meta.get("interfaces")
    if not isinstance(interfaces, list):
        return []
    return [entry for entry in interfaces if isinstance(entry, Mapping)]


def _merge_interface_metadata(
    entry: Mapping[str, object],
    registry: RegistryMetadataModel | None,
    default_identifier: str,
) -> tuple[str, dict[str, object], RegistryInterfaceModel | None]:
    """Return identifier, merged metadata, and registry entry for ``entry``.

    Parameters
    ----------
    entry : Mapping[str, object]
        Interface entry from navigation metadata.
    registry : RegistryMetadataModel | None
        Registry metadata containing interface definitions, if available.
    default_identifier : str
        Default identifier to use if entry lacks 'id' or 'entrypoint' fields.

    Returns
    -------
    tuple[str, dict[str, object], RegistryInterfaceModel | None]
        Computed identifier, merged metadata dictionary, and optional registry model.
    """
    identifier = str(entry.get("id") or entry.get("entrypoint") or default_identifier)
    registry_entry = registry.interface(identifier) if registry else None
    registry_payload: dict[str, object] = {}
    if registry_entry is not None:
        registry_payload = registry_entry.to_payload()
    merged: dict[str, object] = {**registry_payload, **dict(entry)}
    return identifier, merged, registry_entry


def _write_interface_operations(
    fd: mkdocs_gen_files.files,
    identifier: str,
    merged: Mapping[str, object],
    registry_entry: RegistryInterfaceModel | None,
) -> None:
    if registry_entry is None or not registry_entry.operations:
        return
    spec_path = merged.get("spec") or registry_entry.spec
    fd.write("- **Operations:**\n")
    for op_key, op_meta in sorted(registry_entry.operations.items()):
        op_id = op_meta.operation_id or f"{identifier}.{op_key}"
        summary = op_meta.summary or ""
        anchor = _operation_href(spec_path, op_id)
        if anchor:
            fd.write(f"  - [`{op_id}`]({anchor})")
        else:
            fd.write(f"  - `{op_id}`")
        if summary:
            fd.write(f" — {summary}")
        fd.write("\n")


def _mermaid_inheritance(module_path: str, facts: ModuleFacts) -> str:
    """Return a Mermaid class diagram for classes defined in ``module_path``.

    Parameters
    ----------
    module_path : str
        Module path identifier.
    facts : ModuleFacts
        Module relationship facts.

    Returns
    -------
    str
        Rendered Mermaid block or an empty string when no classes exist.
    """
    classes = facts.classes.get(module_path, [])
    if not classes:
        return ""

    def _alias(name: str, counter: dict[str, int]) -> str:
        base = re.sub(r"[^0-9A-Za-z_]", "_", name.rsplit(".", maxsplit=1)[-1]) or "Class"
        if base not in counter:
            counter[base] = 0
            return base
        counter[base] += 1
        return f"{base}_{counter[base]}"

    aliases: dict[str, str] = {}
    alias_counter: dict[str, int] = {}
    lines = ["```mermaid", "classDiagram"]

    def ensure(name: str) -> str:
        if name not in aliases:
            aliases[name] = _alias(name, alias_counter)
            lines.append(f"    class {aliases[name]}")
        return aliases[name]

    for cls in sorted(classes):
        derived = ensure(cls)
        for base in facts.bases.get(cls, []):
            base_alias = ensure(base)
            lines.append(f"    {base_alias} <|-- {derived}")

    lines.append("```")
    return "\n".join(lines)


def _inline_d2_neighborhood(module_path: str, facts: ModuleFacts) -> str:
    """Return a small inline D2 neighborhood diagram for ``module_path``.

    Parameters
    ----------
    module_path : str
        Module path identifier.
    facts : ModuleFacts
        Module relationship facts.

    Returns
    -------
    str
        Rendered D2 block highlighting local imports/importers, or an empty string.
    """
    outgoing = sorted(facts.imports.get(module_path, set()))
    incoming = sorted(facts.imported_by.get(module_path, set()))
    parent = _module_parent(module_path)
    children = _direct_children(module_path, facts.documented_modules)

    if not (outgoing or incoming or parent or children):
        return ""

    lines = ["```d2", "direction: right"]
    written_nodes: set[str] = set()

    def ensure_node(name: str) -> None:
        if name in written_nodes:
            return
        link = _module_diagram_link(name, facts, inline=True)
        lines.append(_diagram_node_statement(name, link))
        written_nodes.add(name)

    ensure_node(module_path)

    for target in outgoing:
        ensure_node(target)
        lines.append(f'"{module_path}" -> "{target}"')

    for source in incoming:
        ensure_node(source)
        lines.append(f'"{source}" -> "{module_path}"')

    if parent:
        ensure_node(parent)
        lines.append(f'"{parent}" -> "{module_path}" {{ style: dashed }}')

    for child in children:
        ensure_node(child)
        lines.append(f'"{module_path}" -> "{child}" {{ style: dashed }}')

    lines.append("```")
    return "\n".join(lines)


def inline_d2_neighborhood(module_path: str, facts: ModuleFacts) -> str:
    """Return the inline D2 neighborhood diagram for ``module_path``.

    Parameters
    ----------
    module_path : str
        Fully qualified module path.
    facts : ModuleFacts
        Module facts including imports and relationships.

    Returns
    -------
    str
        D2 diagram source code as a string.
    """
    return _inline_d2_neighborhood(module_path, facts)


def _write_module_diagram_file(module_path: str, facts: ModuleFacts) -> None:
    """Write a standalone D2 diagram for ``module_path`` to the virtual FS."""
    d2_path = f"diagrams/modules/{module_path}.d2"
    with mkdocs_gen_files.open(d2_path, "w") as handle:
        handle.write("direction: right\n")

        written_nodes: set[str] = set()

        def ensure_node(name: str) -> None:
            if name in written_nodes:
                return
            link = _module_diagram_link(name, facts, inline=False)
            handle.write(_diagram_node_statement(name, link) + "\n")
            written_nodes.add(name)

        ensure_node(module_path)

        for target in sorted(facts.imports.get(module_path, [])):
            ensure_node(target)
            handle.write(f'"{module_path}" -> "{target}"\n')

        for source in sorted(facts.imported_by.get(module_path, [])):
            ensure_node(source)
            handle.write(f'"{source}" -> "{module_path}"\n')

        parent = _module_parent(module_path)
        if parent:
            ensure_node(parent)
            handle.write(f'"{parent}" -> "{module_path}" {{ style: dashed }}\n')

        for child in _direct_children(module_path, facts.documented_modules):
            ensure_node(child)
            handle.write(f'"{module_path}" -> "{child}" {{ style: dashed }}\n')


def _write_autorefs_examples(
    fd: mkdocs_gen_files.files,
    module_path: str,
    facts: ModuleFacts,
) -> None:
    """Emit a short autorefs sample list to demonstrate cross-linking."""
    class_entries = [f"- [{cls}][]" for cls in sorted(facts.classes.get(module_path, []))[:3]]
    function_entries = [
        f"- [{func}][]" for func in sorted(facts.functions.get(module_path, []))[:3]
    ]
    entries = class_entries + function_entries
    if not entries:
        return
    fd.write("## Autorefs Examples\n\n")
    fd.write("\n".join(entries) + "\n\n")


def _write_interfaces(
    fd: mkdocs_gen_files.files,
    module_path: str,
    nav_meta: Mapping[str, Any],
    registry: RegistryMetadataModel | None,
) -> None:
    rows = _interface_entries(nav_meta)
    if not rows:
        return
    fd.write("## Interfaces\n\n")
    for entry in rows:
        identifier, merged, registry_entry = _merge_interface_metadata(entry, registry, module_path)
        fd.write(f"### `{identifier}`\n\n")
        type_value = merged.get("type") or (registry_entry.type if registry_entry else None) or "—"
        fd.write(f"- **Type:** {type_value}\n")
        owner_value = (
            merged.get("owner") or (registry_entry.owner if registry_entry else None) or "—"
        )
        fd.write(f"- **Owner:** {owner_value}\n")
        stability_value = (
            merged.get("stability") or (registry_entry.stability if registry_entry else None) or "—"
        )
        fd.write(f"- **Stability:** {stability_value}\n")
        description = merged.get("description") or (
            registry_entry.description if registry_entry else None
        )
        if description:
            fd.write(f"- **Description:** {description}\n")
        spec_candidate = merged.get("spec") or (registry_entry.spec if registry_entry else None)
        spec_label, spec_href = _spec_href(spec_candidate)
        if spec_href:
            module_doc = _module_doc_path(module_path)
            module_dir = posixpath.dirname(module_doc) or "."
            if _is_absolute_url(spec_href):
                resolved_href = spec_href
            else:
                resolved_href = posixpath.relpath(spec_href, module_dir)
            fd.write(f"- **Spec:** [{spec_label}]({resolved_href})\n")
        elif spec_label:
            fd.write(f"- **Spec:** {spec_label}\n")
        problems = merged.get("problem_details")
        if not problems and registry_entry is not None:
            problems = list(registry_entry.problem_details)
        if isinstance(problems, Sequence) and problems:
            fd.write("- **Problem Details:** " + ", ".join(map(str, problems)) + "\n")
        elif isinstance(problems, str) and problems:
            fd.write(f"- **Problem Details:** {problems}\n")
        _write_interface_operations(fd, identifier, merged, registry_entry)
        fd.write("\n")


def _render_module_page(
    module_path: str,
    nav_meta: Mapping[str, Any],
    facts: ModuleFacts,
    registry: RegistryMetadataModel | None,
    *,
    output_path: str,
) -> None:
    """Generate the Markdown page for ``module_path`` using nav metadata.

    Parameters
    ----------
    module_path : str
        Fully-qualified module import path.
    nav_meta : Mapping[str, Any]
        Navigation metadata derived from ``load_nav_metadata``.
    facts : ModuleFacts
        Aggregated relationship tables for the documentation run.
    registry : RegistryMetadataModel | None
        Typed registry metadata used for interface enrichment.
    output_path : str
        Relative output path for the generated Markdown document.
    """
    nav_dict = dict(nav_meta)
    _write_navmap_json(module_path, nav_dict)

    with mkdocs_gen_files.open(output_path, "w") as fd:
        fd.write(f"# {module_path}\n\n")

        _write_synopsis(fd, nav_dict)
        _write_source_link(fd, module_path, facts)
        _write_hierarchy_section(fd, module_path, facts)
        _write_exports_block(fd, nav_dict.get("exports"))
        _write_sections_overview(fd, nav_dict.get("sections"))
        _write_interfaces(fd, module_path, nav_dict, registry)
        _write_contents(fd, module_path, facts)
        _write_related_operations(fd, module_path, facts)
        _write_relationships(fd, module_path, facts)
        _write_autorefs_examples(fd, module_path, facts)

        mermaid_block = _mermaid_inheritance(module_path, facts)
        if mermaid_block:
            fd.write("## Inheritance\n\n")
            fd.write(mermaid_block + "\n\n")

        neighborhood_block = _inline_d2_neighborhood(module_path, facts)
        if neighborhood_block:
            fd.write("## Neighborhood\n\n")
            fd.write(neighborhood_block + "\n\n")

    _write_module_diagram_file(module_path, facts)


def render_module_pages() -> None:
    """Generate MkDocs pages for every discovered module."""
    registry = _load_registry()
    registry_usage = _registry_api_usage(registry)
    file_usage = _load_api_usage()
    api_usage = _merge_api_usage(file_usage, registry_usage)

    _, extensions_bundle = _discover_extensions(DEFAULT_EXTENSIONS)
    modules = _collect_modules(extensions_bundle)
    facts = _build_relationships(modules, api_usage)
    nav = _make_nav()
    nav["Overview"] = "index.md"

    for module_path, module in sorted(modules.items(), key=lambda item: item[0]):
        nav_meta = _nav_metadata_for_module(module_path, module, facts)
        output_path = f"modules/{module_path.replace('.', '/')}.md"
        _render_module_page(
            module_path,
            nav_meta,
            facts,
            registry,
            output_path=output_path,
        )
        relative_output = module_path.replace(".", "/") + ".md"
        nav[tuple(module_path.split("."))] = relative_output

    with mkdocs_gen_files.open("modules/SUMMARY.md", "w") as nav_handle:
        nav_handle.writelines(nav.build_literate_nav())


render_module_pages()
