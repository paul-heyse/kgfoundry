"""Overview of build navmap.

This module bundles build navmap logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from tools import (
    JsonValue,
    ToolExecutionError,
    get_logger,
    run_tool,
    validate_tools_payload,
    with_fields,
)
from tools._shared.cli import (
    CliEnvelope,
    CliEnvelopeBuilder,
    CliErrorStatus,
    render_cli_envelope,
)
from tools._shared.logging import LoggerAdapter
from tools._shared.problem_details import (
    ProblemDetailsDict,
    ProblemDetailsParams,
    build_problem_details,
)
from tools.drift_preview import write_html_diff
from tools.navmap import cli_context
from tools.navmap.document_models import NAVMAP_SCHEMA, navmap_document_from_index
from tools.navmap.models import nav_index_from_dict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tools.navmap.models import (
        ModuleEntryDict,
        ModuleMetaDict,
        NavIndexDict,
        NavSectionDict,
        SymbolMetaDict,
    )

LOGGER = get_logger(__name__)

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
OUT = REPO / "site" / "_build" / "navmap"
OUT.mkdir(parents=True, exist_ok=True)
INDEX_PATH = OUT / "navmap.json"
DRIFT_DIR = REPO / "docs" / "_build" / "drift"
NAVMAP_DIFF_PATH = DRIFT_DIR / "navmap.html"

CLI_COMMAND = cli_context.CLI_COMMAND
CLI_SETTINGS = cli_context.get_cli_settings()
CLI_CONFIG = cli_context.get_cli_config()
CLI_OPERATION_IDS = cli_context.CLI_OPERATION_IDS
CLI_INTERFACE_ID = cli_context.CLI_INTERFACE_ID
CLI_ENVELOPE_DIR = cli_context.REPO_ROOT / "site" / "_build" / "cli"
SUBCOMMAND_BUILD = "build"
CLI_PROBLEM_TYPE = "https://kgfoundry.dev/problems/navmap/build"


def _prepare_extras(values: Mapping[str, object]) -> dict[str, JsonValue]:
    prepared: dict[str, JsonValue] = {}
    for key, value in values.items():
        if isinstance(value, Path):
            prepared[str(key)] = str(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            prepared[str(key)] = value
        else:
            prepared[str(key)] = str(value)
    return prepared


def _envelope_path(subcommand: str) -> Path:
    safe_subcommand = subcommand or "root"
    filename = f"{CLI_SETTINGS.bin_name}-{CLI_COMMAND}-{safe_subcommand}.json"
    return CLI_ENVELOPE_DIR / filename


def _emit_envelope(
    envelope: CliEnvelope, *, logger: LoggerAdapter, subcommand: str
) -> Path:
    path = _envelope_path(subcommand)
    CLI_ENVELOPE_DIR.mkdir(parents=True, exist_ok=True)
    rendered = render_cli_envelope(envelope)
    path.write_text(rendered + "\n", encoding="utf-8")
    logger.debug(
        "CLI envelope written",
        extra={"status": envelope.status, "cli_envelope": str(path)},
    )
    return path


def _build_problem(
    *,
    detail: str,
    status: int,
    extras: dict[str, object] | None = None,
) -> ProblemDetailsDict:
    return build_problem_details(
        ProblemDetailsParams(
            type=CLI_PROBLEM_TYPE,
            title="Navmap build failed",
            status=status,
            detail=detail,
            instance=f"urn:cli:{CLI_INTERFACE_ID}:{SUBCOMMAND_BUILD}",
            extensions=_prepare_extras(extras or {}),
        )
    )


@dataclass(slots=True, frozen=True)
class _ExecutionContext:
    logger: LoggerAdapter
    start: float
    extras: dict[str, object]

    def elapsed(self) -> float:
        return monotonic() - self.start


def _record_failure(
    context: _ExecutionContext,
    *,
    detail: str,
    status: int,
    error_status: CliErrorStatus,
    exc: BaseException | None = None,
) -> int:
    problem = _build_problem(detail=detail, status=status, extras=context.extras)
    failure_builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND,
        status=error_status if error_status in {"config", "violation"} else "error",
        subcommand=SUBCOMMAND_BUILD,
    )
    failure_builder = failure_builder.add_error(
        status=error_status, message=detail, problem=problem
    )
    failure_builder = failure_builder.set_problem(problem)
    envelope = failure_builder.finish(duration_seconds=context.elapsed())
    path = _emit_envelope(envelope, logger=context.logger, subcommand=SUBCOMMAND_BUILD)
    log_extra = {
        "status": envelope.status,
        "cli_envelope": str(path),
        "duration_seconds": envelope.duration_seconds,
        **_prepare_extras(context.extras),
    }
    context.logger.error("Command failed", extra=log_extra, exc_info=exc)
    sys.stderr.write(detail + "\n")
    return 2 if error_status in {"config", "violation"} else 1


if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Link settings
G_ORG = os.getenv("DOCS_GITHUB_ORG")
G_REPO = os.getenv("DOCS_GITHUB_REPO")
G_SHA = os.getenv("DOCS_GITHUB_SHA")
LINK_MODE = os.getenv("DOCS_LINK_MODE", "editor").lower()  # editor|github|both
EDITOR_MODE = os.getenv("DOCS_EDITOR", "vscode").lower()

SECTION_RE = re.compile(r"^\s*#\s*\[nav:section\s+([a-z0-9]+(?:-[a-z0-9]+)*)\]\s*$")
ANCHOR_RE = re.compile(r"^\s*#\s*\[nav:anchor\s+([A-Za-z_]\w*)\]\s*$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")


class AllPlaceholder:
    """Sentinel used to expand ``__all__`` placeholders."""

    __slots__ = ()


PLACEHOLDER_ALL = AllPlaceholder()


class NavmapError(Exception):
    """Base exception for navmap parsing issues."""


class NavmapLiteralError(NavmapError):
    """Raised when literal evaluation encounters unsupported constructs."""


class NavmapPlaceholderError(NavmapError):
    """Raised when placeholder expansion fails."""


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
    NavPrimitive
    | list[NavTree]
    | dict[str, NavTree]
    | set[str]
    | AllDictTemplate
    | AllPlaceholder
)
type ResolvedNavValue = (
    NavPrimitive | list[ResolvedNavValue] | dict[str, ResolvedNavValue] | set[str]
)


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
    """Return the value encoded by ``node`` when supported.

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
    """Evaluate a sequence of AST nodes into navmap literal values.

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
    """Evaluate a set literal used inside navmap structures.

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
        key_literal = _literal_eval_navmap(key_node)
        if not isinstance(key_literal, str):
            message = "Navmap dictionary keys must be strings."
            raise NavmapLiteralError(message)
        result[key_literal] = _literal_eval_navmap(value_node)
    return result


def _eval_dict_comprehension(node: ast.DictComp) -> AllDictTemplate:
    """Evaluate supported dict comprehensions into :class:`AllDictTemplate`.

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
    """Return the navmap literal represented by ``node``.

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


def _expand_all_placeholder(exports: Sequence[str]) -> list[ResolvedNavValue]:
    """Return a deduplicated list of exports for ``__all__`` placeholders.

    Parameters
    ----------
    exports : Sequence[str]
        Export names to deduplicate and return.

    Returns
    -------
    list[ResolvedNavValue]
        Deduplicated list of export names.
    """
    return cast("list[ResolvedNavValue]", _dedupe_exports(exports))


def _expand_all_dict_template(
    template: NavTree, exports: Sequence[str]
) -> dict[str, ResolvedNavValue]:
    """Expand ``AllDictTemplate`` instances into concrete symbol mappings.

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
        expanded[name] = _replace_placeholders(template, exports)
    return expanded


def _expand_list(
    values: Sequence[NavTree], exports: Sequence[str]
) -> list[ResolvedNavValue]:
    """Expand placeholder-aware lists while flattening nested sequences.

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
        resolved = _replace_placeholders(entry, exports)
        if isinstance(resolved, list):
            expanded.extend(resolved)
        else:
            expanded.append(resolved)
    return expanded


def _expand_dict(
    values: dict[str, NavTree], exports: Sequence[str]
) -> dict[str, ResolvedNavValue]:
    """Expand placeholders within dictionary values.

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
    return {
        key: _replace_placeholders(sub_value, exports)
        for key, sub_value in values.items()
    }


def _expand_set(values: set[str], exports: Sequence[str]) -> set[str]:
    """Expand placeholders within sets, enforcing string membership.

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
    unique_items: set[str] = set()
    for entry in values:
        resolved = _replace_placeholders(entry, exports)
        if isinstance(resolved, list):
            for value in resolved:
                if isinstance(value, str):
                    unique_items.add(value)
                else:
                    message = "Navmap sets may only contain strings after expansion."
                    raise NavmapPlaceholderError(message)
        elif isinstance(resolved, str):
            unique_items.add(resolved)
        else:
            message = "Navmap sets must resolve to strings."
            raise NavmapPlaceholderError(message)
    return unique_items


def _replace_placeholders(value: NavTree, exports: Sequence[str]) -> ResolvedNavValue:
    """Resolve navmap placeholders using the provided export list.

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
        return _expand_all_dict_template(value.template, exports)
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


@dataclass(frozen=True)
class ModuleInfo:
    """Model the ModuleInfo.

    Represent the moduleinfo data structure used throughout the project. The class encapsulates
    behaviour behind a well-defined interface for collaborating components. Instances are typically
    created by factories or runtime orchestrators documented nearby.
    """

    module: str
    path: Path
    exports: list[str]
    sections: dict[str, int]  # id -> lineno (1-based)
    anchors: dict[str, int]  # symbol -> lineno (1-based)
    nav_sections: list[NavSectionDict]
    navmap_dict: dict[str, ResolvedNavValue]  # parsed __navmap__ (may be {})


def _rel(p: Path) -> str:
    """Return ``p`` relative to the repository root when possible.

    Parameters
    ----------
    p : Path
        Path to relativize.

    Returns
    -------
    str
        Relative path string, or absolute path if not within repository.
    """
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def _git_sha() -> str:
    """Return the current Git commit hash, falling back to environment overrides.

    Returns
    -------
    str
        Git commit hash, or 'HEAD' if resolution fails.
    """
    if G_SHA:
        return G_SHA
    try:
        result = run_tool(["git", "rev-parse", "HEAD"], timeout=10.0, cwd=REPO)
        return result.stdout.strip()
    except ToolExecutionError:
        LOGGER.warning("Failed to resolve git SHA, using 'HEAD'")
        return "HEAD"


def _gh_link(path: Path, start: int | None, end: int | None) -> str | None:
    """Commit-stable GitHub permalink using #L anchors.

    Parameters
    ----------
    path : Path
        File path to link.
    start : int | None
        Starting line number for fragment anchor.
    end : int | None
        Ending line number for fragment anchor.

    Returns
    -------
    str | None
        GitHub permalink URL, | None if org/repo not configured.
    """
    if not (G_ORG and G_REPO):
        return None
    sha = _git_sha()
    frag = ""
    if start and end and end >= start:
        frag = f"#L{start}-L{end}"
    elif start:
        frag = f"#L{start}"
    return f"https://github.com/{G_ORG}/{G_REPO}/blob/{sha}/{_rel(path)}{frag}"


def _editor_link(path: Path, line: int | None = None) -> str | None:
    """Build an editor deep link respecting ``DOCS_EDITOR`` mode.

    Parameters
    ----------
    path : Path
        File path to link.
    line : int | None, optional
        Line number for editor navigation, by default None.

    Returns
    -------
    str | None
        Editor deep link URL, | None if editor mode not supported.
    """
    if EDITOR_MODE == "relative":
        try:
            rel_path = path.relative_to(REPO).as_posix()
        except ValueError:
            rel_path = path.as_posix()
        suffix = f":{line}:1" if line else ""
        return f"./{rel_path}{suffix}"
    if EDITOR_MODE == "vscode":
        abs_path = path if path.is_absolute() else (REPO / path).resolve()
        suffix = f":{line}:1" if line else ""
        return f"vscode://file/{abs_path}{suffix}"
    return None


def _module_name(py: Path) -> str | None:
    """Return the dotted module name for ``py``.

    Parameters
    ----------
    py : Path
        Python file path to convert to module name.

    Returns
    -------
    str | None
        Dotted module name if path is within src/, None otherwise.
    """
    if py.suffix != ".py":
        return None
    try:
        rel = py.relative_to(SRC)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if not parts:
        return None
    return ".".join(parts)


def _literal_list_of_strs(node: ast.AST | None) -> list[str] | None:
    """Best-effort get list/tuple of strings from AST node.

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
        vals = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                vals.append(elt.value)
            elif isinstance(elt, ast.Name) and IDENT_RE.match(elt.id):
                vals.append(elt.id)
            else:
                return None
        return vals
    return None


def _parse_module(py: Path) -> ast.Module | None:
    """Return the parsed AST for ``py`` or ``None`` when parsing fails.

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


def _maybe_extract_exports(node: ast.AST) -> list[str] | None:
    """Return a literal ``__all__`` declaration when present.

    Parameters
    ----------
    node : ast.AST
        AST node to extract exports from.

    Returns
    -------
    list[str] | None
        List of export names if node represents a literal list/tuple,
        None otherwise.
    """
    return _literal_list_of_strs(node)


def _maybe_extract_navmap(node: ast.AST) -> dict[str, NavTree] | None:
    """Return a literal ``__navmap__`` dictionary when supported constructs are used.

    Parameters
    ----------
    node : ast.AST
        AST node to extract navmap literal from.

    Returns
    -------
    dict[str, NavTree] | None
        Navmap dictionary if node can be evaluated as a navmap literal,
        None otherwise.
    """
    try:
        literal = _literal_eval_navmap(node)
    except NavmapLiteralError:
        return None
    if isinstance(literal, dict):
        return literal
    return None


def _process_assign_targets(
    node: ast.Assign, exports: list[str], nav_literal: dict[str, NavTree] | None
) -> tuple[list[str], dict[str, NavTree] | None]:
    """Update exports/navmap literals based on assignment targets.

    Parameters
    ----------
    node : ast.Assign
        Assignment AST node to process.
    exports : list[str]
        Current exports list to potentially update.
    nav_literal : dict[str, NavTree] | None
        Current navmap literal to potentially update.

    Returns
    -------
    tuple[list[str], dict[str, NavTree] | None]
        Updated exports and navmap literal tuple.
    """
    target_names = [
        target.id for target in node.targets if isinstance(target, ast.Name)
    ]
    if "__all__" in target_names:
        extracted = _maybe_extract_exports(node.value)
        if extracted is not None:
            exports = extracted
    if "__navmap__" in target_names:
        nav_candidate = _maybe_extract_navmap(node.value)
        if nav_candidate is not None:
            nav_literal = nav_candidate
    return exports, nav_literal


def _process_ann_assign(
    node: ast.AnnAssign, exports: list[str], nav_literal: dict[str, NavTree] | None
) -> tuple[list[str], dict[str, NavTree] | None]:
    """Update exports/navmap literals for annotated assignments.

    Parameters
    ----------
    node : ast.AnnAssign
        Annotated assignment AST node to process.
    exports : list[str]
        Current exports list to potentially update.
    nav_literal : dict[str, NavTree] | None
        Current navmap literal to potentially update.

    Returns
    -------
    tuple[list[str], dict[str, NavTree] | None]
        Updated exports and navmap literal tuple.
    """
    target = node.target
    if not isinstance(target, ast.Name) or node.value is None:
        return exports, nav_literal
    if target.id == "__all__":
        extracted = _maybe_extract_exports(node.value)
        if extracted is not None:
            exports = extracted
    if target.id == "__navmap__":
        nav_candidate = _maybe_extract_navmap(node.value)
        if nav_candidate is not None:
            nav_literal = nav_candidate
    return exports, nav_literal


def _gather_module_literals(
    module: ast.Module,
) -> tuple[list[str], dict[str, NavTree] | None]:
    """Return literal ``__all__`` and ``__navmap__`` values declared in ``module``.

    Parameters
    ----------
    module : ast.Module
        Module AST to extract literals from.

    Returns
    -------
    tuple[list[str], dict[str, NavTree] | None]
        Tuple of exports list and navmap literal dictionary.
    """
    exports: list[str] = []
    nav_literal: dict[str, NavTree] | None = None
    for node in module.body:
        if isinstance(node, ast.Assign):
            exports, nav_literal = _process_assign_targets(node, exports, nav_literal)
            continue
        if isinstance(node, ast.AnnAssign):
            exports, nav_literal = _process_ann_assign(node, exports, nav_literal)
    return exports, nav_literal


def _dedupe_exports(exports: Sequence[str]) -> list[str]:
    """Return exports with original ordering preserved and duplicates removed.

    Parameters
    ----------
    exports : Sequence[str]
        Export names to deduplicate.

    Returns
    -------
    list[str]
        Deduplicated list preserving original order.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for item in exports:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _exports_from_navmap(nav_literal: dict[str, NavTree]) -> list[str]:
    """Return export hints defined within the navmap literal.

    Parameters
    ----------
    nav_literal : dict[str, NavTree]
        Navmap literal dictionary to extract exports from.

    Returns
    -------
    list[str]
        List of export names, empty if not present in navmap.
    """
    raw_exports = nav_literal.get("exports")
    if not isinstance(raw_exports, list):
        return []
    string_exports = [item for item in raw_exports if isinstance(item, str)]
    return _dedupe_exports(string_exports)


def _resolve_navmap_literal(
    nav_literal: dict[str, NavTree], exports: Sequence[str]
) -> dict[str, ResolvedNavValue]:
    """Return the navmap literal with placeholders expanded.

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
        resolved = _replace_placeholders(nav_literal, exports)
    except NavmapPlaceholderError:
        return {}
    if isinstance(resolved, dict):
        return resolved
    return {}


def _resolve_navmap(
    nav_literal: dict[str, NavTree] | None, exports: list[str]
) -> tuple[dict[str, ResolvedNavValue], list[str]]:
    """Resolve navmap placeholders and potentially update exports.

    Parameters
    ----------
    nav_literal : dict[str, NavTree] | None
        Navmap literal to resolve, | None.
    exports : list[str]
        Current exports list.

    Returns
    -------
    tuple[dict[str, ResolvedNavValue], list[str]]
        Tuple of resolved navmap dictionary and updated exports list.
    """
    if not nav_literal:
        return {}, exports
    exports_hint = exports or _exports_from_navmap(nav_literal)
    nav_map = _resolve_navmap_literal(nav_literal, exports_hint)
    if not nav_map:
        return {}, exports
    nav_exports = nav_map.get("exports")
    if isinstance(nav_exports, list):
        exports = _dedupe_exports(
            [item for item in nav_exports if isinstance(item, str)]
        )
    return nav_map, exports


def _parse_py(py: Path) -> tuple[dict[str, ResolvedNavValue], list[str]]:
    """Parse Python file and extract navmap metadata.

    Parameters
    ----------
    py : Path
        Python file to parse.

    Returns
    -------
    tuple[dict[str, ResolvedNavValue], list[str]]
        Tuple of navmap dictionary and exports list.
    """
    module = _parse_module(py)
    if module is None:
        return {}, []
    exports, nav_literal = _gather_module_literals(module)
    exports = _dedupe_exports(exports)
    nav_map, exports = _resolve_navmap(nav_literal, exports)
    return nav_map, exports


def _load_runtime_navmap(
    module_name: str, exports: list[str], source: Path
) -> tuple[dict[str, ResolvedNavValue], list[str]]:
    """Load navigation metadata from JSON sidecars when AST parsing fails.

    Parameters
    ----------
    module_name : str
        Fully qualified module name used for logging.
    exports : list[str]
        Export list discovered from ``__all__`` literals (may be empty).
    source : Path
        Filesystem path to the Python module being processed.

    Returns
    -------
    tuple[dict[str, ResolvedNavValue], list[str]]
        Tuple containing the navmap dictionary (if discovered) and the deduped export list.
    """
    sidecar_candidates: list[Path] = []
    if source.name == "__init__.py":
        sidecar_candidates.append(source.parent / "_nav.json")
    module_sidecar = source.with_name(f"{source.stem}._nav.json")
    sidecar_candidates.append(module_sidecar)

    seen: set[Path] = set()
    for candidate in sidecar_candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if not candidate.is_file():
            continue
        try:
            nav_data = json.loads(candidate.read_text(encoding="utf-8"))
        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:  # pragma: no cover - filesystem noise
            LOGGER.warning("Failed to read nav sidecar %s: %s", candidate, exc)
            continue
        if not isinstance(nav_data, dict):
            LOGGER.warning("Nav sidecar %s did not contain an object", candidate)
            continue
        nav_copy: dict[str, ResolvedNavValue] = copy.deepcopy(nav_data)
        nav_exports = nav_copy.get("exports")
        if isinstance(nav_exports, list):
            exports = _dedupe_exports(
                [item for item in nav_exports if isinstance(item, str)]
            )
            nav_copy["exports"] = cast("ResolvedNavValue", list(exports))
        elif exports:
            nav_copy["exports"] = cast("ResolvedNavValue", list(exports))
        return nav_copy, exports

    LOGGER.debug("No nav sidecar discovered for module %s", module_name)
    return {}, exports


def _scan_inline_markers(py: Path) -> tuple[dict[str, int], dict[str, int]]:
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
    try:
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            m = SECTION_RE.match(line)
            if m:
                sid = m.group(1)
                sections[sid] = i
            m = ANCHOR_RE.match(line)
            if m:
                anchors[m.group(1)] = i
    except (OSError, UnicodeDecodeError) as exc:
        LOGGER.debug("Failed to scan inline markers: %s", exc)
    return sections, anchors


def _kebab(s: str) -> str:
    """Normalize ``s`` into a kebab-case identifier string.

    Parameters
    ----------
    s : str
        String to normalize.

    Returns
    -------
    str
        Kebab-case identifier string.
    """
    s = s.lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)
    return re.sub(r"-{2,}", "-", s).strip("-")


def _collect_module(py: Path) -> ModuleInfo | None:
    """Parse Python file and return gathered navmap metadata if it is a module.

    Parameters
    ----------
    py : Path
        Python file to collect metadata from.

    Returns
    -------
    ModuleInfo | None
        Module metadata if file is a valid module, None otherwise.
    """
    mod = _module_name(py)
    if not mod:
        return None
    navmap_dict, exports = _parse_py(py)
    if not navmap_dict:
        navmap_dict, exports = _load_runtime_navmap(mod, exports, py)
    sections, anchors = _scan_inline_markers(py)

    # Normalize sections to kebab-case and ensure symbol lists are unique & stable
    nav_sections: list[NavSectionDict] = []
    raw_sections = navmap_dict.get("sections")
    if isinstance(raw_sections, list):
        for section in raw_sections:
            if not isinstance(section, dict):
                continue
            raw_id = section.get("id", "")
            sid = _kebab(str(raw_id))
            raw_symbols = section.get("symbols", [])
            if isinstance(raw_symbols, list):
                filtered_symbols = _dedupe_exports(
                    [sym for sym in raw_symbols if isinstance(sym, str)]
                )
            else:
                filtered_symbols = []
            nav_sections.append({"id": sid, "symbols": filtered_symbols})
    # Stable, deduped exports
    raw_exports = navmap_dict.get("exports")
    if isinstance(raw_exports, list):
        nav_exports = _dedupe_exports(
            [item for item in raw_exports if isinstance(item, str)]
        )
    else:
        nav_exports = _dedupe_exports(exports)
    exports = nav_exports

    return ModuleInfo(
        module=mod,
        path=py,
        exports=exports,
        sections=sections,
        anchors=anchors,
        nav_sections=nav_sections,
        navmap_dict=navmap_dict,
    )


def _build_links(info: ModuleInfo) -> dict[str, str]:
    """Return source links for a module entry based on configured link mode.

    Parameters
    ----------
    info : ModuleInfo
        Module metadata to build links for.

    Returns
    -------
    dict[str, str]
        Dictionary of link type to URL mapping.
    """
    links: dict[str, str] = {}
    if LINK_MODE in {"editor", "both"}:
        editor_link = _editor_link(info.path)
        if editor_link:
            links["source"] = editor_link
    if LINK_MODE in {"github", "both"}:
        github_link = _gh_link(info.path, None, None)
        if github_link:
            links["github"] = github_link
    return links


def _module_meta_fields(navmap: dict[str, ResolvedNavValue]) -> ModuleMetaDict:
    """Extract module-level metadata fields from navmap.

    Parameters
    ----------
    navmap : dict[str, ResolvedNavValue]
        Resolved navmap dictionary.

    Returns
    -------
    ModuleMetaDict
        Module metadata dictionary.
    """
    module_meta: ModuleMetaDict = {}
    owner = navmap.get("owner")
    if isinstance(owner, str) and owner:
        module_meta["owner"] = owner
    stability = navmap.get("stability")
    if isinstance(stability, str) and stability:
        module_meta["stability"] = stability
    since = navmap.get("since")
    if isinstance(since, str) and since:
        module_meta["since"] = since
    deprecated_in = navmap.get("deprecated_in")
    if isinstance(deprecated_in, str) and deprecated_in:
        module_meta["deprecated_in"] = deprecated_in
    return module_meta


def _symbol_meta_fields(
    navmap: dict[str, ResolvedNavValue],
) -> dict[str, SymbolMetaDict]:
    """Extract per-symbol metadata declarations from navmap.

    Parameters
    ----------
    navmap : dict[str, ResolvedNavValue]
        Resolved navmap dictionary.

    Returns
    -------
    dict[str, SymbolMetaDict]
        Dictionary mapping symbol names to their metadata.
    """
    raw_symbols = navmap.get("symbols")
    if not isinstance(raw_symbols, dict):
        return {}
    symbols_meta: dict[str, SymbolMetaDict] = {}
    for name, payload in raw_symbols.items():
        if not isinstance(name, str) or not isinstance(payload, dict):
            continue
        filtered: SymbolMetaDict = {}
        owner = payload.get("owner")
        if isinstance(owner, str) and owner:
            filtered["owner"] = owner
        stability = payload.get("stability")
        if isinstance(stability, str) and stability:
            filtered["stability"] = stability
        since = payload.get("since")
        if isinstance(since, str) and since:
            filtered["since"] = since
        deprecated_in = payload.get("deprecated_in")
        if isinstance(deprecated_in, str) and deprecated_in:
            filtered["deprecated_in"] = deprecated_in
        symbols_meta[name] = filtered
    return symbols_meta


def _merge_symbol_meta(
    module_meta: ModuleMetaDict, symbol_meta: SymbolMetaDict | None
) -> SymbolMetaDict:
    """Merge symbol metadata with module defaults applied.

    Parameters
    ----------
    module_meta : ModuleMetaDict
        Module-level metadata defaults.
    symbol_meta : SymbolMetaDict | None
        Symbol-specific metadata, | None.

    Returns
    -------
    SymbolMetaDict
        Merged metadata with module defaults filling missing fields.
    """
    merged: SymbolMetaDict = {}
    owner = symbol_meta.get("owner") if symbol_meta else None
    if not isinstance(owner, str) or not owner:
        owner = module_meta.get("owner")
    if isinstance(owner, str) and owner:
        merged["owner"] = owner
    stability = symbol_meta.get("stability") if symbol_meta else None
    if not isinstance(stability, str) or not stability:
        stability = module_meta.get("stability")
    if isinstance(stability, str) and stability:
        merged["stability"] = stability
    since = symbol_meta.get("since") if symbol_meta else None
    if not isinstance(since, str) or not since:
        since = module_meta.get("since")
    if isinstance(since, str) and since:
        merged["since"] = since
    deprecated_in = symbol_meta.get("deprecated_in") if symbol_meta else None
    if not isinstance(deprecated_in, str) or not deprecated_in:
        deprecated_in = module_meta.get("deprecated_in")
    if isinstance(deprecated_in, str) and deprecated_in:
        merged["deprecated_in"] = deprecated_in
    return merged


def _apply_symbol_defaults(
    symbols_meta: dict[str, SymbolMetaDict],
    module_meta: ModuleMetaDict,
    exports: Sequence[str],
) -> dict[str, SymbolMetaDict]:
    """Apply module-level defaults to symbol metadata.

    Parameters
    ----------
    symbols_meta : dict[str, SymbolMetaDict]
        Existing symbol metadata dictionary.
    module_meta : ModuleMetaDict
        Module-level metadata defaults.
    exports : Sequence[str]
        List of exported symbols.

    Returns
    -------
    dict[str, SymbolMetaDict]
        Updated symbol metadata dictionary with defaults applied.
    """
    if symbols_meta:
        return {
            name: _merge_symbol_meta(module_meta, meta)
            for name, meta in symbols_meta.items()
        }
    return {export: _merge_symbol_meta(module_meta, None) for export in exports}


def _string_list(value: ResolvedNavValue | None) -> list[str]:
    """Return a string-only list coerced from ``value``.

    Parameters
    ----------
    value : ResolvedNavValue | None
        Value to coerce to string list.

    Returns
    -------
    list[str]
        List of strings, empty if value is not a list.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _string_value(value: ResolvedNavValue | None) -> str:
    """Return ``value`` when it is a string, otherwise an empty string.

    Parameters
    ----------
    value : ResolvedNavValue | None
        Value to extract string from.

    Returns
    -------
    str
        String value if present, empty string otherwise.
    """
    if isinstance(value, str):
        return value
    return ""


def _module_entry(info: ModuleInfo) -> ModuleEntryDict:
    """Return the serialized navmap entry for ``info``.

    Parameters
    ----------
    info : ModuleInfo
        Module metadata to serialize.

    Returns
    -------
    ModuleEntryDict
        Serialized module entry dictionary.
    """
    module_meta = _module_meta_fields(info.navmap_dict)
    symbols_meta = _symbol_meta_fields(info.navmap_dict)
    symbols = _apply_symbol_defaults(symbols_meta, module_meta, info.exports)
    return {
        "path": _rel(info.path),
        "exports": _dedupe_exports(info.exports),
        "sections": info.nav_sections,
        "section_lines": info.sections,
        "anchors": info.anchors,
        "links": _build_links(info),
        "meta": symbols,
        "module_meta": module_meta,
        "tags": _string_list(info.navmap_dict.get("tags")),
        "synopsis": _string_value(info.navmap_dict.get("synopsis")),
        "see_also": _string_list(info.navmap_dict.get("see_also")),
        "deps": _string_list(info.navmap_dict.get("deps")),
    }


def _collect_module_entries(files: Sequence[Path]) -> dict[str, ModuleEntryDict]:
    """Return serialized module entries for the provided Python files.

    Parameters
    ----------
    files : Sequence[Path]
        Python files to process.

    Returns
    -------
    dict[str, ModuleEntryDict]
        Dictionary mapping module names to their serialized entries.
    """
    modules: dict[str, ModuleEntryDict] = {}
    for py in files:
        info = _collect_module(py)
        if info is None:
            continue
        modules[info.module] = _module_entry(info)
    return modules


def collect_module_info(path: Path) -> ModuleInfo | None:
    """Return raw navmap metadata for ``path`` if it should be indexed.

    Parameters
    ----------
    path : Path
        Python file path to collect metadata from.

    Returns
    -------
    ModuleInfo | None
        Module metadata if path is a valid module, None otherwise.
    """
    return _collect_module(path)


def _discover_py_files(root: Path = SRC) -> list[Path]:
    """Return every Python source file under ``root`` sorted lexicographically.

    Parameters
    ----------
    root : Path, optional
        Root directory to search, by default SRC.

    Returns
    -------
    list[Path]
        Sorted list of Python file paths.
    """
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def build_index(root: Path = SRC, json_path: Path | None = None) -> dict[str, object]:
    """Build the navmap index and optionally persist it to disk.

    Parameters
    ----------
    root : Path, optional
        Directory to scan for Python modules, by default ``SRC``.
    json_path : Path | None
        Override destination for the generated JSON document, by default ``None`` which causes ``INDEX_PATH`` to be used.

    Returns
    -------
    dict[str, object]
        Serialized navmap document complying with ``navmap_document.json``.

    Examples
    --------
    >>> from tools.navmap.build_navmap import build_index
    >>> result = build_index()
    >>> result  # doctest: +ELLIPSIS
    """
    files = _discover_py_files(root)
    modules = _collect_module_entries(files)
    commit = _git_sha()
    policy_version = "1"
    link_mode = LINK_MODE
    index_dict: NavIndexDict = {
        "commit": commit,
        "policy_version": policy_version,
        "link_mode": link_mode,
        "modules": modules,
    }

    nav_index = nav_index_from_dict(index_dict)
    document = navmap_document_from_index(
        nav_index,
        commit=commit,
        policy_version=policy_version,
        link_mode=link_mode,
    )

    payload: dict[str, object] = document.model_dump(by_alias=True, exclude_none=True)
    validate_tools_payload(payload, NAVMAP_SCHEMA)

    out = json_path or INDEX_PATH
    previous = out.read_text(encoding="utf-8") if out.exists() else ""
    out.parent.mkdir(parents=True, exist_ok=True)
    encoded_text = json.dumps(payload, indent=2)
    out.write_text(encoded_text, encoding="utf-8")
    if previous and previous != encoded_text:
        write_html_diff(previous, encoded_text, NAVMAP_DIFF_PATH, "Navmap drift")
    else:
        NAVMAP_DIFF_PATH.unlink(missing_ok=True)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the navmap index and optionally override the output path.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Command-line arguments, by default None.

    Returns
    -------
    int
        Exit code (0 on success).
    """
    override = cli_context.get_operation_override(SUBCOMMAND_BUILD)
    description = (
        override.description
        if override and override.description
        else "Build the navigation index JSON"
    )
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--write",
        type=Path,
        metavar="PATH",
        help="Destination for the generated navmap JSON",
        default=None,
    )
    args = parser.parse_args(argv)

    target = cast("Path | None", args.write)
    return _run_build(target)


def _run_build(write_path: Path | None) -> int:
    extras: dict[str, object] = {"output_path": str(write_path or INDEX_PATH)}
    correlation_id = uuid4().hex
    logger = with_fields(
        LOGGER,
        command=CLI_COMMAND,
        subcommand=SUBCOMMAND_BUILD,
        bin_name=CLI_SETTINGS.bin_name,
        correlation_id=correlation_id,
        **_prepare_extras(extras),
    )
    logger.info("Command started", extra={"status": "start"})
    context = _ExecutionContext(logger=logger, start=monotonic(), extras=extras)
    builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND,
        status="success",
        subcommand=SUBCOMMAND_BUILD,
    )
    try:
        _ = build_index(json_path=write_path)
        destination = write_path or INDEX_PATH
        builder = builder.add_file(
            path=str(destination),
            status="success",
            message="Navmap JSON generated",
        )
        if NAVMAP_DIFF_PATH.exists():
            builder = builder.add_file(
                path=str(NAVMAP_DIFF_PATH),
                status="success",
                message="Navmap drift report",
            )
        envelope = builder.finish(duration_seconds=context.elapsed())
    except ToolExecutionError as exc:
        return _record_failure(
            context,
            detail=str(exc),
            status=500,
            error_status="error",
            exc=exc,
        )
    except KeyboardInterrupt as exc:  # pragma: no cover - manual interruption
        return _record_failure(
            context,
            detail="Navmap build cancelled by user",
            status=499,
            error_status="config",
            exc=exc,
        )
    except (
        RuntimeError,
        ValueError,
        OSError,
    ) as exc:  # pragma: no cover - defensive catch
        return _record_failure(
            context,
            detail=str(exc),
            status=500,
            error_status="error",
            exc=exc,
        )
    else:
        _emit_envelope(envelope, logger=logger, subcommand=SUBCOMMAND_BUILD)
        logger.info(
            "Command completed",
            extra={
                "status": "success",
                "duration_seconds": envelope.duration_seconds,
                **_prepare_extras(extras),
            },
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
