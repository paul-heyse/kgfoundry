"""Overview of check navmap.

This module bundles check navmap logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

from __future__ import annotations

import ast
import copy
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TypedDict, cast
from uuid import uuid4

from packaging.version import InvalidVersion, Version

from tools import JsonValue, ToolExecutionError, get_logger
from tools._shared.cli import (
    CliEnvelope,
    CliEnvelopeBuilder,
    CliErrorStatus,
    CliStatus,
    render_cli_envelope,
)
from tools._shared.logging import LoggerAdapter, with_fields
from tools._shared.problem_details import (
    ProblemDetailsDict,
    ProblemDetailsParams,
    build_problem_details,
)
from tools.navmap import cli_context
from tools.navmap.build_navmap import NavmapError as BuildNavmapError
from tools.navmap.build_navmap import build_index

LOGGER = get_logger(__name__)

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
INDEX = REPO / "site" / "_build" / "navmap" / "navmap.json"

# Regexes
SECTION_RE = re.compile(r"^\s*#\s*\[nav:section\s+([a-z0-9]+(?:-[a-z0-9]+)*)\]\s*$")
ANCHOR_RE = re.compile(r"^\s*#\s*\[nav:anchor\s+([A-Za-z_]\w*)\]\s*$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")
STABILITY = {"stable", "beta", "experimental", "deprecated", "internal", "frozen"}


CLI_COMMAND = cli_context.CLI_COMMAND
CLI_SETTINGS = cli_context.get_cli_settings()
CLI_OPERATION_IDS = cli_context.CLI_OPERATION_IDS
CLI_INTERFACE_ID = cli_context.CLI_INTERFACE_ID
CLI_ENVELOPE_DIR = cli_context.REPO_ROOT / "site" / "_build" / "cli"
SUBCOMMAND_CHECK = "check"
CLI_PROBLEM_TYPE = "https://kgfoundry.dev/problems/navmap/check"


class NavmapError(Exception):
    """Base exception for navmap parsing issues."""


class NavmapLiteralError(NavmapError):
    """Raised when a navmap literal cannot be parsed safely."""


class NavmapPlaceholderError(NavmapError):
    """Raised when placeholder expansion fails."""


class AllPlaceholder:
    """Sentinel for ``__all__`` placeholders."""

    __slots__ = ()


@dataclass(slots=True, frozen=True)
class AllDictTemplate:
    """Sentinel for ``{name: TEMPLATE for name in __all__}`` structures.

    This class serves as a marker in navmap templates to indicate that a dictionary
    should be expanded to include all symbols listed in a module's ``__all__``
    attribute. When resolving navmaps, this template is replaced with a dictionary
    mapping each exported symbol name to the template value.

    Attributes
    ----------
    template : NavTree
        Template navmap tree structure that will be applied to each symbol
        listed in ``__all__`` when the navmap is resolved.
    """

    template: NavTree


NavPrimitive = str | int | float | bool | None
type NavTree = (
    NavPrimitive | list[NavTree] | dict[str, NavTree] | set[str] | AllDictTemplate | AllPlaceholder
)
type ResolvedNavValue = (
    NavPrimitive | list[ResolvedNavValue] | dict[str, ResolvedNavValue] | set[str]
)

PLACEHOLDER_ALL = AllPlaceholder()


class SymbolMetaDict(TypedDict, total=False):
    """Metadata requirements for a single symbol."""

    owner: str
    stability: str
    since: str
    deprecated_in: str


class ModuleEntryDict(TypedDict, total=False):
    """Minimal navmap subset used by the checker."""

    path: str
    exports: list[str]
    sections: list[dict[str, ResolvedNavValue]]
    section_lines: dict[str, int]
    anchors: dict[str, int]
    symbols: dict[str, SymbolMetaDict]


class NavIndexDict(TypedDict, total=False):
    """Serialized navmap index structure."""

    commit: str
    policy_version: str
    link_mode: str
    modules: dict[str, ModuleEntryDict]


def _eval_nav_literal(node: ast.AST) -> NavTree:
    """Return the navmap literal represented by ``node``.

    Parameters
    ----------
    node : ast.AST
        AST node to evaluate as a navmap literal.

    Returns
    -------
    NavTree
        Evaluated navmap literal value.

    Raises
    ------
    NavmapLiteralError
        If the node type is not supported for navmap literals.
    """
    if isinstance(node, ast.Constant):
        return _eval_constant(node)
    if isinstance(node, ast.Name):
        return _eval_name(node)
    if isinstance(node, (ast.List, ast.Tuple)):
        return _eval_sequence(node.elts)
    if isinstance(node, ast.Set):
        return _eval_set(node)
    if isinstance(node, ast.Dict):
        return _eval_dict(node)
    if isinstance(node, ast.DictComp):
        return _eval_dict_comprehension(node)
    message = f"Unsupported navmap literal node: {ast.dump(node)}"
    raise NavmapLiteralError(message)


def _eval_constant(node: ast.Constant) -> NavTree:
    """Return the literal value encoded by ``node`` when supported.

    Parameters
    ----------
    node : ast.Constant
        Constant AST node to evaluate.

    Returns
    -------
    NavTree
        Constant value if supported (str, int, float, bool, | None).

    Raises
    ------
    NavmapLiteralError
        If the constant value type is not supported.
    """
    value = node.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    message = f"Unsupported constant in navmap literal: {value!r}"
    raise NavmapLiteralError(message)


def _eval_name(node: ast.Name) -> NavTree:
    """Resolve placeholder names used inside navmap literals.

    Parameters
    ----------
    node : ast.Name
        Name AST node to resolve.

    Returns
    -------
    NavTree
        Placeholder instance if name is ``__all__``.

    Raises
    ------
    NavmapLiteralError
        If the name is not a supported placeholder.
    """
    if node.id == "__all__":
        return PLACEHOLDER_ALL
    message = f"Unsupported name in navmap literal: {node.id!r}"
    raise NavmapLiteralError(message)


def _eval_sequence(nodes: Sequence[ast.AST]) -> list[NavTree]:
    """Return a list of evaluated navmap literals for ``nodes``.

    Parameters
    ----------
    nodes : Sequence[ast.AST]
        Sequence of AST nodes to evaluate.

    Returns
    -------
    list[NavTree]
        List of evaluated navmap literal values.
    """
    return [_literal_eval_navmap(child) for child in nodes]


def _eval_set(node: ast.Set) -> set[str]:
    """Evaluate a set literal into navmap values.

    Parameters
    ----------
    node : ast.Set
        Set AST node to evaluate.

    Returns
    -------
    set[str]
        Set of string values.

    Raises
    ------
    NavmapLiteralError
        If any set element is not a string.
    """
    evaluated: set[str] = set()
    for element in node.elts:
        value = _literal_eval_navmap(element)
        if not isinstance(value, str):
            message = "Navmap set entries must be strings."
            raise NavmapLiteralError(message)
        evaluated.add(value)
    return evaluated


def _eval_dict(node: ast.Dict) -> dict[str, NavTree]:
    """Evaluate a dict literal, enforcing string keys.

    Parameters
    ----------
    node : ast.Dict
        Dictionary AST node to evaluate.

    Returns
    -------
    dict[str, NavTree]
        Dictionary with string keys and navmap literal values.

    Raises
    ------
    NavmapLiteralError
        If any key is not a string.
    """
    result: dict[str, NavTree] = {}
    for key_node, value_node in zip(node.keys, node.values, strict=False):
        key = _literal_eval_navmap(key_node)
        if not isinstance(key, str):
            message = "Navmap dictionary keys must be strings."
            raise NavmapLiteralError(message)
        result[key] = _literal_eval_navmap(value_node)
    return result


def _eval_dict_comprehension(node: ast.DictComp) -> AllDictTemplate:
    """Evaluate supported dict comprehensions into ``AllDictTemplate`` placeholders.

    Parameters
    ----------
    node : ast.DictComp
        Dictionary comprehension AST node to evaluate.

    Returns
    -------
    AllDictTemplate
        Template instance for placeholder expansion.

    Raises
    ------
    NavmapLiteralError
        If the comprehension structure does not match requirements (single
        generator, no filters, non-async, target is a simple name, iterator
        is ``__all__``).
    """
    if len(node.generators) != 1:
        message = "Navmap dict comprehension must contain exactly one generator."
        raise NavmapLiteralError(message)
    generator = node.generators[0]
    if generator.ifs:
        message = "Navmap dict comprehension may not include filters."
        raise NavmapLiteralError(message)
    if generator.is_async:
        message = "Navmap dict comprehension may not be async."
        raise NavmapLiteralError(message)
    target = generator.target
    iterator = generator.iter
    if not isinstance(target, ast.Name):
        message = "Navmap dict comprehension target must be a simple name."
        raise NavmapLiteralError(message)
    if not isinstance(iterator, ast.Name) or iterator.id != "__all__":
        message = "Navmap dict comprehension iterator must be __all__."
        raise NavmapLiteralError(message)
    template = _literal_eval_navmap(node.value)
    return AllDictTemplate(template)


def _literal_eval_navmap(node: ast.AST | None) -> NavTree:
    """Evaluate ``node`` into a navmap literal.

    Parameters
    ----------
    node : ast.AST | None
        AST node to evaluate, | None for empty literals.

    Returns
    -------
    NavTree
        Evaluated navmap literal value.

    Raises
    ------
    NavmapLiteralError
        If node is None or evaluation fails.
    """
    if node is None:
        message = "Navmap literal must not be empty."
        raise NavmapLiteralError(message)
    return _eval_nav_literal(node)


def _dedupe_str_list(items: Sequence[str]) -> list[str]:
    """Return ``items`` with original ordering and duplicates removed.

    Parameters
    ----------
    items : Sequence[str]
        String items to deduplicate.

    Returns
    -------
    list[str]
        Deduplicated list preserving original order.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _expand_all_placeholder(exports: Sequence[str]) -> list[ResolvedNavValue]:
    """Return concrete export lists for ``__all__`` placeholders.

    Parameters
    ----------
    exports : Sequence[str]
        Export names to deduplicate and return.

    Returns
    -------
    list[ResolvedNavValue]
        Deduplicated list of export names.
    """
    unique_exports = _dedupe_str_list(exports)
    resolved: list[ResolvedNavValue] = []
    resolved.extend(unique_exports)
    return resolved


def _expand_dict_template(template: NavTree, exports: Sequence[str]) -> dict[str, ResolvedNavValue]:
    """Expand ``AllDictTemplate`` placeholders.

    Parameters
    ----------
    template : NavTree
        Template to expand for each export.
    exports : Sequence[str]
        Export names to use as dictionary keys.

    Returns
    -------
    dict[str, ResolvedNavValue]
        Dictionary mapping export names to expanded template values.
    """
    expanded: dict[str, ResolvedNavValue] = {}
    for name in exports:
        expanded[name] = _expand_nav_value(template, exports)
    return expanded


def _expand_list(values: Sequence[NavTree], exports: Sequence[str]) -> list[ResolvedNavValue]:
    """Expand navmap lists, flattening nested lists that arise from placeholders.

    Parameters
    ----------
    values : Sequence[NavTree]
        List values to expand.
    exports : Sequence[str]
        Export names for placeholder resolution.

    Returns
    -------
    list[ResolvedNavValue]
        Expanded list with nested lists flattened.
    """
    expanded: list[ResolvedNavValue] = []
    for entry in values:
        resolved = _expand_nav_value(entry, exports)
        if isinstance(resolved, list):
            expanded.extend(resolved)
        else:
            expanded.append(resolved)
    return expanded


def _expand_dict(values: dict[str, NavTree], exports: Sequence[str]) -> dict[str, ResolvedNavValue]:
    """Expand navmap dict values recursively.

    Parameters
    ----------
    values : dict[str, NavTree]
        Dictionary with values to expand.
    exports : Sequence[str]
        Export names for placeholder resolution.

    Returns
    -------
    dict[str, ResolvedNavValue]
        Dictionary with expanded values.
    """
    return {key: _expand_nav_value(sub_value, exports) for key, sub_value in values.items()}


def _expand_set(values: set[str], exports: Sequence[str]) -> set[str]:
    """Expand navmap sets and ensure all members resolve to strings.

    Parameters
    ----------
    values : set[str]
        Set values to expand.
    exports : Sequence[str]
        Export names for placeholder resolution.

    Returns
    -------
    set[str]
        Set of expanded string values.

    Raises
    ------
    NavmapPlaceholderError
        If expansion produces non-string values.
    """
    resolved: set[str] = set()
    for entry in values:
        expanded = _expand_nav_value(entry, exports)
        if isinstance(expanded, list):
            for item in expanded:
                if isinstance(item, str):
                    resolved.add(item)
                else:
                    message = "Navmap sets may only contain strings after expansion."
                    raise NavmapPlaceholderError(message)
        elif isinstance(expanded, str):
            resolved.add(expanded)
        else:
            message = "Navmap sets must resolve to strings."
            raise NavmapPlaceholderError(message)
    return resolved


def _expand_nav_value(value: NavTree, exports: Sequence[str]) -> ResolvedNavValue:
    """Expand navmap placeholders for ``value`` using ``exports``.

    Parameters
    ----------
    value : NavTree
        Value tree to expand.
    exports : Sequence[str]
        Export names for placeholder resolution.

    Returns
    -------
    ResolvedNavValue
        Expanded value with placeholders resolved.

    Raises
    ------
    NavmapPlaceholderError
        If placeholder expansion fails or produces invalid types.
    """
    if isinstance(value, AllPlaceholder):
        return _expand_all_placeholder(exports)
    if isinstance(value, AllDictTemplate):
        return _expand_dict_template(value.template, exports)
    if isinstance(value, list):
        return _expand_list(value, exports)
    if isinstance(value, dict):
        return _expand_dict(value, exports)
    if isinstance(value, set):
        if not all(isinstance(item, str) for item in value):
            message = "Navmap sets must contain only strings."
            raise NavmapPlaceholderError(message)
        str_values: set[str] = set(value)
        return _expand_set(str_values, exports)
    return value


def _parse_module(py: Path) -> ast.Module | None:
    """Return an AST for ``py`` or ``None`` when parsing fails.

    Parameters
    ----------
    py : Path
        Python file to parse.

    Returns
    -------
    ast.Module | None
        Parsed AST module, | None if file cannot be read or parsed.
    """
    try:
        source = py.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _extract_navmap_literal(module: ast.Module) -> dict[str, NavTree] | None:
    """Return the literal ``__navmap__`` declaration from ``module``.

    Parameters
    ----------
    module : ast.Module
        Module AST to extract navmap literal from.

    Returns
    -------
    dict[str, NavTree] | None
        Navmap literal dictionary if found, None otherwise.
    """
    nav_literal: dict[str, NavTree] | None = None
    for node in module.body:
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "__navmap__" in targets:
                try:
                    candidate = _literal_eval_navmap(node.value)
                except NavmapLiteralError:
                    continue
                if isinstance(candidate, dict):
                    nav_literal = candidate
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id != "__navmap__" or node.value is None:
                continue
            try:
                candidate = _literal_eval_navmap(node.value)
            except NavmapLiteralError:
                continue
            if isinstance(candidate, dict):
                nav_literal = candidate
    return nav_literal


def _exports_from_nav_literal(nav_literal: dict[str, NavTree]) -> list[str]:
    """Return export hints embedded within ``nav_literal``.

    Parameters
    ----------
    nav_literal : dict[str, NavTree]
        Navmap literal dictionary to extract exports from.

    Returns
    -------
    list[str]
        List of export names, empty if not present.
    """
    exports_literal = nav_literal.get("exports")
    if not isinstance(exports_literal, list):
        return []
    exports = [item for item in exports_literal if isinstance(item, str)]
    return _dedupe_str_list(exports)


def _resolve_navmap_literal(
    nav_literal: dict[str, NavTree], exports: Sequence[str]
) -> dict[str, ResolvedNavValue]:
    """Expand placeholders and normalize exports inside ``nav_literal``.

    Parameters
    ----------
    nav_literal : dict[str, NavTree]
        Navmap literal dictionary to resolve.
    exports : Sequence[str]
        Export names for placeholder resolution.

    Returns
    -------
    dict[str, ResolvedNavValue]
        Resolved navmap dictionary with placeholders expanded.
    """
    try:
        resolved = _expand_nav_value(nav_literal, exports)
    except NavmapPlaceholderError:
        return {}
    if not isinstance(resolved, dict):
        return {}
    nav_exports = resolved.get("exports")
    if isinstance(nav_exports, list):
        string_exports = [item for item in nav_exports if isinstance(item, str)]
        resolved_exports: list[ResolvedNavValue] = []
        resolved_exports.extend(_dedupe_str_list(string_exports))
        resolved["exports"] = resolved_exports
    return resolved


def _read_text(py: Path) -> list[str]:
    """Return file contents as a list of lines, or an empty list on failure.

    Parameters
    ----------
    py : Path
        File to read.

    Returns
    -------
    list[str]
        List of lines, empty if file cannot be read.
    """
    try:
        return py.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def _candidate_sidecars(py: Path) -> list[Path]:
    """Return potential nav sidecar files for ``py`` in priority order.

    Parameters
    ----------
    py : Path
        Python module to inspect for nav metadata.

    Returns
    -------
    list[Path]
        Candidate sidecar paths with duplicates removed while preserving order.
    """
    candidates: list[Path] = []
    if py.name == "__init__.py":
        candidates.append(py.parent / "_nav.json")
        module_sidecar = py.with_name(f"{py.stem}._nav.json")
        if module_sidecar.name != "__init__._nav.json":
            candidates.append(module_sidecar)
    else:
        candidates.append(py.with_name(f"{py.stem}._nav.json"))

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def _load_nav_sidecar(py: Path) -> dict[str, ResolvedNavValue]:
    """Return navigation metadata loaded from JSON sidecars when available.

    Parameters
    ----------
    py : Path
        Python module to inspect for nav metadata.

    Returns
    -------
    dict[str, ResolvedNavValue]
        Nav metadata from the first matching sidecar, or an empty dict when absent.
    """
    for candidate in _candidate_sidecars(py):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Failed to read nav sidecar %s: %s", candidate, exc)
            continue
        if not isinstance(payload, dict):
            LOGGER.warning("Nav sidecar %s did not contain an object", candidate)
            continue
        nav_copy = cast("dict[str, ResolvedNavValue]", copy.deepcopy(payload))
        exports = nav_copy.get("exports")
        if isinstance(exports, list):
            deduped_strings = _dedupe_str_list([item for item in exports if isinstance(item, str)])
            normalized_exports: list[ResolvedNavValue] = [
                cast("ResolvedNavValue", item) for item in deduped_strings
            ]
            nav_copy["exports"] = cast("ResolvedNavValue", normalized_exports)
        elif exports:
            nav_copy["exports"] = cast("ResolvedNavValue", exports)
        return nav_copy
    return {}


def _scan_inline(py: Path) -> tuple[dict[str, int], dict[str, int]]:
    """Scan file for inline navigation markers.

    Parameters
    ----------
    py : Path
        Python file to scan.

    Returns
    -------
    tuple[dict[str, int], dict[str, int]]
        Tuple of section ID to line number mapping and anchor symbol to
        line number mapping (both 1-based).
    """
    sections: dict[str, int] = {}
    anchors: dict[str, int] = {}
    for i, line in enumerate(_read_text(py), 1):
        m = SECTION_RE.match(line)
        if m:
            sections[m.group(1)] = i
        m = ANCHOR_RE.match(line)
        if m:
            anchors[m.group(1)] = i
    return sections, anchors


def _definition_anchors(py: Path) -> dict[str, int]:
    """Return symbol-to-line mapping derived from top-level definitions.

    Parameters
    ----------
    py : Path
        Python module being analysed.

    Returns
    -------
    dict[str, int]
        Mapping of symbol names to their definition line numbers.
    """
    module = _parse_module(py)
    if module is None:
        return {}
    anchors: dict[str, int] = {}
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            anchors.setdefault(node.name, getattr(node, "lineno", 0))
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    anchors.setdefault(target.id, getattr(node, "lineno", 0))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            anchors.setdefault(node.target.id, getattr(node, "lineno", 0))
    return anchors


def _has_anchor(symbol: str, anchors_inline: dict[str, int], auto_anchors: dict[str, int]) -> bool:
    """Return ``True`` when ``symbol`` has either inline or inferred anchors.

    Parameters
    ----------
    symbol : str
        Symbol name to inspect.
    anchors_inline : dict[str, int]
        Explicit `[nav:anchor]` markers collected from the source file.
    auto_anchors : dict[str, int]
        Anchors inferred from top-level definitions in the module.

    Returns
    -------
    bool
        ``True`` when a positive line number exists for the symbol, ``False`` otherwise.
    """
    anchor_line = anchors_inline.get(symbol)
    if isinstance(anchor_line, int) and anchor_line > 0:
        return True
    anchor_line = auto_anchors.get(symbol)
    return isinstance(anchor_line, int) and anchor_line > 0


def _validate_section_symbols(
    py: Path,
    sid: str,
    symbols_value: Sequence[object],
    anchors_inline: dict[str, int],
    auto_anchors: dict[str, int],
) -> list[str]:
    """Validate symbols listed in a navmap section.

    Parameters
    ----------
    py : Path
        Python file being validated.
    sid : str
        Section identifier (e.g., ``"public-api"``).
    symbols_value : Sequence[object]
        Raw symbols array extracted from the navmap structure.
    anchors_inline : dict[str, int]
        Explicit inline anchor markers discovered in the file.
    auto_anchors : dict[str, int]
        Anchors inferred from top-level definitions in the module.

    Returns
    -------
    list[str]
        Validation error messages (empty list when all symbols pass).
    """
    errors: list[str] = []
    for symbol in symbols_value:
        if not isinstance(symbol, str) or not IDENT_RE.match(symbol):
            errors.append(f"{py}: invalid symbol name '{symbol}' in section '{sid}'")
            continue
        if symbol not in auto_anchors and symbol not in anchors_inline:
            continue
        if not _has_anchor(symbol, anchors_inline, auto_anchors):
            errors.append(f"{py}: missing [nav:anchor] for section symbol '{symbol}'")
    return errors


def _parse_navmap_dict(py: Path) -> dict[str, ResolvedNavValue]:
    """Return the literal ``__navmap__`` dictionary for ``py`` if one exists.

    Parameters
    ----------
    py : Path
        Python file to parse.

    Returns
    -------
    dict[str, ResolvedNavValue]
        Navmap dictionary if found, empty dict otherwise.
    """
    module = _parse_module(py)
    nav_map: dict[str, ResolvedNavValue] = {}
    if module is not None:
        nav_literal = _extract_navmap_literal(module)
        if nav_literal is not None:
            exports = _parse_all(py)
            if not exports:
                exports = _exports_from_nav_literal(nav_literal)
            nav_map = _resolve_navmap_literal(nav_literal, exports)
            if nav_map:
                return nav_map
    return _load_nav_sidecar(py)


def _literal_string_sequence(node: ast.AST | None) -> list[str] | None:
    """Return a list of identifier/constant strings from ``node`` when possible.

    Parameters
    ----------
    node : ast.AST | None
        AST node to extract strings from.

    Returns
    -------
    list[str] | None
        List of strings if node is a list/tuple of constants or names,
        None otherwise.
    """
    if node is None:
        return None
    if isinstance(node, (ast.List, ast.Tuple)):
        strings: list[str] = []
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                strings.append(element.value)
            elif isinstance(element, ast.Name) and IDENT_RE.match(element.id):
                strings.append(element.id)
            else:
                return None
        return strings
    return None


def _extract_all_literal(module: ast.Module) -> list[str]:
    """Return the literal ``__all__`` declaration within ``module`` when present.

    Parameters
    ----------
    module : ast.Module
        Module AST to extract exports from.

    Returns
    -------
    list[str]
        List of export names, empty if not found.
    """
    for node in module.body:
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "__all__" in targets:
                value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "__all__":
                value = node.value
        if value is None:
            continue
        strings = _literal_string_sequence(value)
        if strings is not None:
            return _dedupe_str_list(strings)
    return []


def _parse_all(py: Path) -> list[str]:
    """Parse ``__all__`` declaration from Python file.

    Parameters
    ----------
    py : Path
        Python file to parse.

    Returns
    -------
    list[str]
        List of export names, empty if not found.
    """
    module = _parse_module(py)
    if module is None:
        return []
    return _extract_all_literal(module)


def _exports_for(py: Path, nav: dict[str, ResolvedNavValue]) -> list[str]:
    """Derive the export list from ``__navmap__`` or ``__all__`` definitions.

    Parameters
    ----------
    py : Path
        Python file to parse for exports.
    nav : dict[str, ResolvedNavValue]
        Resolved navmap dictionary.

    Returns
    -------
    list[str]
        List of export names.
    """
    nav_exports = nav.get("exports")
    if isinstance(nav_exports, list):
        strings = [item for item in nav_exports if isinstance(item, str)]
        if strings:
            return _dedupe_str_list(strings)
    all_literal = _parse_all(py)
    if all_literal:
        return _dedupe_str_list(all_literal)
    return []


def _sections_list(value: ResolvedNavValue | None) -> list[dict[str, ResolvedNavValue]]:
    """Return section entries when ``value`` is a list of dictionaries.

    Parameters
    ----------
    value : ResolvedNavValue | None
        Value to extract sections from.

    Returns
    -------
    list[dict[str, ResolvedNavValue]]
        List of section dictionaries, empty if value is not a list.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _symbols_meta_dict(value: ResolvedNavValue | None) -> dict[str, SymbolMetaDict]:
    """Return symbol metadata entries as ``SymbolMetaDict`` instances.

    Parameters
    ----------
    value : ResolvedNavValue | None
        Value to extract symbol metadata from.

    Returns
    -------
    dict[str, SymbolMetaDict]
        Dictionary mapping symbol names to their metadata.
    """
    if not isinstance(value, dict):
        return {}
    result: dict[str, SymbolMetaDict] = {}
    for key, payload in value.items():
        if not isinstance(key, str) or not isinstance(payload, dict):
            continue
        entry: SymbolMetaDict = {}
        owner = payload.get("owner")
        if isinstance(owner, str) and owner:
            entry["owner"] = owner
        stability = payload.get("stability")
        if isinstance(stability, str) and stability:
            entry["stability"] = stability
        since = payload.get("since")
        if isinstance(since, str) and since:
            entry["since"] = since
        deprecated = payload.get("deprecated_in")
        if isinstance(deprecated, str) and deprecated:
            entry["deprecated_in"] = deprecated
        if entry:
            result[key] = entry
    return result


def _validate_sections(
    py: Path, sections_value: ResolvedNavValue | None, anchors_inline: dict[str, int]
) -> list[str]:
    """Validate navmap sections and inline anchor coverage.

    Parameters
    ----------
    py : Path
        Python file being validated.
    sections_value : ResolvedNavValue | None
        Sections value from navmap.
    anchors_inline : dict[str, int]
        Inline anchor markers found in file.

    Returns
    -------
    list[str]
        List of validation error messages.
    """
    errors: list[str] = []
    sections = _sections_list(sections_value)
    if not sections:
        return errors
    first_id = sections[0].get("id")
    if first_id != "public-api":
        errors.append(f"{py}: first navmap section must have id 'public-api'")
    auto_anchors = _definition_anchors(py)
    for section in sections:
        sid = section.get("id")
        symbols_value = section.get("symbols")
        if not isinstance(sid, str) or not sid:
            continue
        if not SLUG_RE.match(sid):
            errors.append(f"{py}: section id '{sid}' is not kebab-case")
        if not isinstance(symbols_value, list):
            continue
        errors.extend(
            _validate_section_symbols(py, sid, symbols_value, anchors_inline, auto_anchors)
        )
    return errors


def _validate_exports_match(
    py: Path, declared_exports: ResolvedNavValue | None, exports: list[str]
) -> list[str]:
    """Validate that declared exports match the discovered export list.

    Parameters
    ----------
    py : Path
        Python file being validated.
    declared_exports : ResolvedNavValue | None
        Exports declared in navmap.
    exports : list[str]
        Actual exports discovered from __all__.

    Returns
    -------
    list[str]
        List of validation error messages.
    """
    if not isinstance(declared_exports, list):
        return []
    declared_set = {item for item in declared_exports if isinstance(item, str)}
    if declared_set == set(exports):
        return []
    return [f"{py}: __navmap__['exports'] does not match __all__/exports set"]


def _validate_symbol_meta(
    py: Path, exports: list[str], symbols_value: ResolvedNavValue | None
) -> list[str]:
    """Validate per-symbol metadata requirements.

    Parameters
    ----------
    py : Path
        Python file being validated.
    exports : list[str]
        List of exported symbols.
    symbols_value : ResolvedNavValue | None
        Symbol metadata from navmap.

    Returns
    -------
    list[str]
        List of validation error messages.
    """
    errors: list[str] = []
    meta = _symbols_meta_dict(symbols_value)
    for name in sorted(exports):
        entry = meta.get(name, {})
        stability = entry.get("stability")
        owner = entry.get("owner")
        if stability not in STABILITY:
            errors.append(f"{py}: symbol '{name}' missing/invalid stability (got {stability!r})")
        if not owner:
            errors.append(f"{py}: symbol '{name}' missing owner (e.g., '@team')")
        since = entry.get("since")
        deprecated_in = entry.get("deprecated_in")
        error_since = _validate_pep440(since)
        if error_since:
            errors.append(f"{py}: symbol '{name}' since invalid: {error_since}")
        error_deprecated = _validate_pep440(deprecated_in)
        if error_deprecated:
            errors.append(f"{py}: symbol '{name}' deprecated_in invalid: {error_deprecated}")
        if Version is None or not since or not deprecated_in:
            continue
        try:
            if Version(str(deprecated_in)) < Version(str(since)):
                errors.append(
                    f"{py}: symbol '{name}' deprecated_in ({deprecated_in}) < since ({since})"
                )
        except InvalidVersion:
            continue
    return errors


def _collect_module_errors() -> list[str]:
    """Run navmap checks across the ``src/`` tree and collect errors.

    Returns
    -------
    list[str]
        List of validation error messages.
    """
    errors: list[str] = []
    for py in sorted(SRC.rglob("*.py")):
        errors.extend(_inspect(py))
    return errors


def _round_trip_line_errors(
    file_path: Path,
    lines: list[str],
    mapping: Mapping[str, int],
    pattern: re.Pattern[str],
    label: str,
) -> list[str]:
    """Return mismatches for ``mapping`` entries compared against ``lines``.

    Parameters
    ----------
    file_path : Path
        File being validated.
    lines : list[str]
        File contents as lines.
    mapping : Mapping[str, int]
        Mapping of keys to line numbers.
    pattern : re.Pattern[str]
        Regex pattern to match expected format.
    label : str
        Label for error messages (e.g., "section", "anchor").

    Returns
    -------
    list[str]
        List of validation error messages.
    """
    errors: list[str] = []
    for key, value in mapping.items():
        if value < 1 or value > len(lines) or not pattern.match(lines[value - 1]):
            errors.append(f"{file_path}: round-trip mismatch for {label} '{key}' at line {value}")
    return errors


def _round_trip_errors(index: NavIndexDict | dict[str, object]) -> list[str]:
    """Validate round-trip data from ``build_navmap`` against source files.

    Parameters
    ----------
    index : NavIndexDict | dict[str, object]
        Navmap index to validate.

    Returns
    -------
    list[str]
        List of validation error messages.
    """
    modules = index.get("modules")
    if not isinstance(modules, dict):
        return []
    errors: list[str] = []
    for entry in modules.values():
        if not isinstance(entry, dict):
            continue
        path_value = entry.get("path")
        if not isinstance(path_value, str):
            continue
        file_path = REPO / path_value
        lines = _read_text(file_path)
        section_lines = entry.get("sectionLines") or entry.get("section_lines")
        if isinstance(section_lines, dict):
            normalized_sections = {
                key: value
                for key, value in section_lines.items()
                if isinstance(key, str) and isinstance(value, int)
            }
            if normalized_sections:
                errors.extend(
                    _round_trip_line_errors(
                        file_path, lines, normalized_sections, SECTION_RE, "section"
                    )
                )
        anchors = entry.get("anchors")
        if isinstance(anchors, dict):
            normalized_anchors = {
                key: value
                for key, value in anchors.items()
                if isinstance(key, str) and isinstance(value, int)
            }
            if normalized_anchors:
                errors.extend(
                    _round_trip_line_errors(
                        file_path, lines, normalized_anchors, ANCHOR_RE, "anchor"
                    )
                )
    return errors


def _module_path(py: Path) -> str | None:
    """Return the dotted module path for ``py`` within ``src/`` if possible.

    Parameters
    ----------
    py : Path
        Python file path.

    Returns
    -------
    str | None
        Dotted module name if path is within src/, None otherwise.
    """
    try:
        rel = py.relative_to(SRC)
    except ValueError:
        return None
    if rel.suffix != ".py":
        return None
    return ".".join(rel.with_suffix("").parts)


def _validate_pep440(field_val: object) -> str | None:
    """Validate PEP 440 version strings and report an error message when invalid.

    Parameters
    ----------
    field_val : object
        Value to validate as PEP 440 version.

    Returns
    -------
    str | None
        Error message if invalid, None if valid or empty.
    """
    if field_val is None:
        return None
    if isinstance(field_val, str) and not field_val.strip():
        return None
    try:
        Version(str(field_val))
    except InvalidVersion:
        return f"non-PEP440 version: {field_val!r}"
    else:
        return None


def _inspect(py: Path) -> list[str]:
    """Validate a module at ``py`` and return collected violation messages.

    Parameters
    ----------
    py : Path
        Python file to validate.

    Returns
    -------
    list[str]
        List of validation error messages.
    """
    errs: list[str] = []
    nav = _parse_navmap_dict(py)
    _, anchors_inline = _scan_inline(py)
    exports = _exports_for(py, nav)

    # If module exports anything, __navmap__ must exist
    if exports and not nav:
        errs.append(f"{py}: module exports symbols but has no __navmap__")
        return errs

    errs.extend(_validate_sections(py, nav.get("sections"), anchors_inline))
    errs.extend(_validate_exports_match(py, nav.get("exports"), exports))
    errs.extend(_validate_symbol_meta(py, exports, nav.get("symbols")))

    return errs


def _coerce_json_value(value: object) -> JsonValue:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_coerce_json_value(item) for item in value]
    if isinstance(value, set):
        return [_coerce_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _coerce_json_value(val) for key, val in value.items()}
    return str(value)


def _prepare_extensions(values: Mapping[str, object] | None = None) -> dict[str, JsonValue]:
    if not values:
        return {}
    return {str(key): _coerce_json_value(val) for key, val in values.items()}


@dataclass(slots=True, frozen=True)
class _ExecutionContext:
    logger: LoggerAdapter
    start: float
    base_extras: dict[str, JsonValue]

    def elapsed(self) -> float:
        return monotonic() - self.start

    def extensions(self, overrides: Mapping[str, object] | None = None) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = dict(self.base_extras)
        payload.update(_prepare_extensions(overrides))
        return payload


def _envelope_path(subcommand: str) -> Path:
    safe_subcommand = subcommand or "root"
    filename = f"{CLI_SETTINGS.bin_name}-{CLI_COMMAND}-{safe_subcommand}.json"
    return CLI_ENVELOPE_DIR / filename


def _emit_envelope(envelope: CliEnvelope, *, logger: LoggerAdapter, subcommand: str) -> Path:
    path = _envelope_path(subcommand)
    CLI_ENVELOPE_DIR.mkdir(parents=True, exist_ok=True)
    rendered = render_cli_envelope(envelope)
    path.write_text(rendered + "\n", encoding="utf-8")
    logger.debug(
        "CLI envelope written", extra={"status": envelope.status, "cli_envelope": str(path)}
    )
    return path


def _run_status_from_error(error_status: CliErrorStatus) -> CliStatus:
    return cast(
        "CliStatus",
        error_status if error_status in {"config", "violation"} else "error",
    )


def _build_problem(
    context: _ExecutionContext,
    *,
    detail: str,
    status: int,
    extras: Mapping[str, object] | None = None,
) -> ProblemDetailsDict:
    return build_problem_details(
        ProblemDetailsParams(
            type=CLI_PROBLEM_TYPE,
            title="Navmap validation failed",
            status=status,
            detail=detail,
            instance=f"urn:cli:{CLI_INTERFACE_ID}:{SUBCOMMAND_CHECK}",
            extensions=context.extensions(extras),
        )
    )


@dataclass(slots=True, frozen=True)
class _FailureOptions:
    extras: Mapping[str, object] | None = None
    exc: BaseException | None = None


def _record_failure(
    context: _ExecutionContext,
    *,
    detail: str,
    status: int,
    error_status: CliErrorStatus,
    options: _FailureOptions | None = None,
) -> int:
    failure_extras = options.extras if options else None
    exc = options.exc if options else None
    problem = _build_problem(context, detail=detail, status=status, extras=failure_extras)
    builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND,
        status=_run_status_from_error(error_status),
        subcommand=SUBCOMMAND_CHECK,
    )
    builder.add_error(status=error_status, message=detail, problem=problem)
    builder.set_problem(problem)
    envelope = builder.finish(duration_seconds=context.elapsed())
    path = _emit_envelope(envelope, logger=context.logger, subcommand=SUBCOMMAND_CHECK)
    log_extra: dict[str, JsonValue] = {
        "status": envelope.status,
        "cli_envelope": str(path),
        "duration_seconds": envelope.duration_seconds,
    }
    log_extra.update(context.extensions(failure_extras))
    context.logger.error("Command failed", extra=log_extra, exc_info=exc)
    if failure_extras and (errors := failure_extras.get("errors")) and isinstance(errors, list):
        for message in errors[:10]:
            context.logger.error("Validation error", extra={"detail": _coerce_json_value(message)})
    return 1


def _finish_success(context: _ExecutionContext, builder: CliEnvelopeBuilder) -> int:
    envelope = builder.finish(duration_seconds=context.elapsed())
    path = _emit_envelope(envelope, logger=context.logger, subcommand=SUBCOMMAND_CHECK)
    log_extra: dict[str, JsonValue] = {
        "status": envelope.status,
        "cli_envelope": str(path),
        "duration_seconds": envelope.duration_seconds,
    }
    log_extra.update(context.base_extras)
    context.logger.info("Command completed", extra=log_extra)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run navmap validation checks and emit structured CLI envelopes.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Optional CLI arguments forwarded from the command line.

    Returns
    -------
    int
        Exit code (``0`` on success, non-zero when validation fails).
    """
    del argv
    correlation_id = uuid4().hex
    base_extras = _prepare_extensions(
        {
            "index_path": INDEX,
            "command": CLI_COMMAND,
            "subcommand": SUBCOMMAND_CHECK,
            "bin_name": CLI_SETTINGS.bin_name,
            "correlation_id": correlation_id,
        }
    )
    logger = with_fields(
        LOGGER,
        command=CLI_COMMAND,
        subcommand=SUBCOMMAND_CHECK,
        bin_name=CLI_SETTINGS.bin_name,
        correlation_id=correlation_id,
        index_path=str(INDEX),
    )
    logger.info("Command started", extra={"status": "start"})
    context = _ExecutionContext(logger=logger, start=monotonic(), base_extras=base_extras)
    builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND,
        status=cast("CliStatus", "success"),
        subcommand=SUBCOMMAND_CHECK,
    )

    errors = _collect_module_errors()
    if errors:
        error_sample = errors[:20]
        extras = {
            "error_count": len(errors),
            "errors": error_sample,
            "errors_truncated": max(len(errors) - len(error_sample), 0),
        }
        detail = error_sample[0] if error_sample else "Navmap validation errors detected."
        return _record_failure(
            context,
            detail=detail,
            status=422,
            error_status="violation",
            options=_FailureOptions(extras=extras),
        )

    try:
        index = build_index(json_path=INDEX)
    except BuildNavmapError as exc:
        detail = "Navmap round-trip build failed"
        extras = {"error": str(exc)}
        return _record_failure(
            context,
            detail=detail,
            status=500,
            error_status="error",
            options=_FailureOptions(extras=extras, exc=exc),
        )
    except ToolExecutionError as exc:
        detail = str(exc)
        return _record_failure(
            context,
            detail=detail,
            status=500,
            error_status="error",
            options=_FailureOptions(extras={"error": detail}, exc=exc),
        )
    except (RuntimeError, ValueError, OSError) as exc:  # pragma: no cover - defensive catch
        detail = str(exc)
        return _record_failure(
            context,
            detail=detail,
            status=500,
            error_status="error",
            options=_FailureOptions(extras={"error": detail}, exc=exc),
        )

    rt_errs = _round_trip_errors(index)
    if rt_errs:
        error_sample = rt_errs[:20]
        extras = {
            "error_count": len(rt_errs),
            "errors": error_sample,
            "errors_truncated": max(len(rt_errs) - len(error_sample), 0),
        }
        detail = error_sample[0] if error_sample else "Navmap round-trip validation failed."
        return _record_failure(
            context,
            detail=detail,
            status=422,
            error_status="violation",
            options=_FailureOptions(extras=extras),
        )

    builder.add_file(
        path=str(SRC),
        status="success",
        message="Validated navmap metadata across source modules",
    )
    builder.add_file(
        path=str(INDEX),
        status="success",
        message="Round-trip navmap index matches inline metadata",
    )

    return _finish_success(context, builder)


if __name__ == "__main__":
    sys.exit(main())
