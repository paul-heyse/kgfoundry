# SPDX-License-Identifier: MIT
"""LibCST-powered index utilities (imports, defs, exports, docstrings)."""

from __future__ import annotations

from collections.abc import Collection, Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol, cast

import libcst as cst
from libcst import matchers as m
from libcst import metadata as cst_metadata
from libcst.helpers import (
    get_full_name_for_node,
)

try:  # pragma: no cover - optional dependency
    from docstring_parser import parse as parse_docstring
except ImportError:  # pragma: no cover - optional dependency
    parse_docstring = None


class NodeHandler(Protocol):
    """Callable signature for node-dispatch handlers."""

    def __call__(self, visitor: _IndexVisitor, node: cst.CSTNode, *, is_top_level: bool) -> None:
        """Process `node` with awareness of top-level status."""
        ...


@dataclass(slots=True, frozen=True)
class ImportEntry:
    """Normalized metadata for a single import statement."""

    module: str | None
    names: list[str]
    aliases: dict[str, str]
    is_star: bool
    level: int


@dataclass(slots=True, frozen=True)
class DefEntry:
    """Top-level function/class definition summary."""

    kind: str  # "class" | "function" | "variable"
    name: str
    lineno: int


@dataclass(slots=True, frozen=True)
class ModuleIndex:
    """Aggregate module metadata returned by :func:`index_module`."""

    path: str
    imports: list[ImportEntry] = field(default_factory=list)
    defs: list[DefEntry] = field(default_factory=list)
    exports: set[str] = field(default_factory=set)
    docstring: str | None = None
    doc_summary: str | None = None
    doc_metrics: dict[str, bool] = field(
        default_factory=lambda: {
            "has_summary": False,
            "param_parity": True,
            "examples_present": False,
        }
    )
    doc_items: list[dict[str, Any]] = field(default_factory=list)
    annotation_ratio: dict[str, float] = field(
        default_factory=lambda: {"params": 1.0, "returns": 1.0}
    )
    untyped_defs: int = 0
    side_effects: dict[str, bool] = field(
        default_factory=lambda: {
            "filesystem": False,
            "network": False,
            "subprocess": False,
            "database": False,
        }
    )
    raises: list[str] = field(default_factory=list)
    complexity: dict[str, int] = field(
        default_factory=lambda: {"branches": 0, "cyclomatic": 1, "loc": 0}
    )
    parse_ok: bool = True
    errors: list[str] = field(default_factory=list)


def _extract_module_docstring(node: cst.Module) -> str | None:
    """Return the module docstring if present.

    Parameters
    ----------
    node : cst.Module
        LibCST module node to extract docstring from.

    Returns
    -------
    str | None
        Module docstring text when available, or None if no docstring exists.
    """
    if not node.body:
        return None
    first_stmt = node.body[0]
    if not isinstance(first_stmt, cst.SimpleStatementLine):
        return None
    expr = first_stmt.body[0] if first_stmt.body else None
    if isinstance(expr, cst.Expr) and isinstance(expr.value, cst.SimpleString):
        with suppress(ValueError):
            evaluated = expr.value.evaluated_value
            if isinstance(evaluated, bytes):
                return evaluated.decode("utf-8", "ignore")
            if isinstance(evaluated, str):
                return evaluated
            return str(evaluated)
    return None


def _literal_string_values(node: cst.BaseExpression) -> Iterator[str]:
    """Yield literal string values from constant containers.

    Parameters
    ----------
    node : cst.BaseExpression
        LibCST expression node (list, tuple, set, or string literal) containing
        literal string values to extract.

    Yields
    ------
    str
        Literal names included in ``__all__`` definitions.
    """
    literal = _string_literal_value(node)
    if literal is not None:
        yield literal
        return
    containers = (cst.List, cst.Tuple, cst.Set)
    if isinstance(node, containers):
        for raw_element in node.elements:
            element_value = getattr(raw_element, "value", None)
            literal_value = _string_literal_value(element_value)
            if literal_value is not None:
                yield literal_value


def _string_literal_value(node: cst.BaseExpression | None) -> str | None:
    """Extract the evaluated string value from a LibCST string literal node.

    Parameters
    ----------
    node : cst.BaseExpression | None
        LibCST expression node that may be a string literal. If None or not a
        SimpleString node, returns None.

    Returns
    -------
    str | None
        Evaluated string value from the literal, or None if the node is not a
        string literal or evaluation fails. Handles both string and bytes
        literals, decoding bytes to UTF-8 strings when necessary.
    """
    if isinstance(node, cst.SimpleString):
        with suppress(ValueError):
            evaluated = node.evaluated_value
            if isinstance(evaluated, bytes):
                return evaluated.decode("utf-8", "ignore")
            if isinstance(evaluated, str):
                return evaluated
            return str(evaluated)
    return None


def _extract_def_docstring(body: cst.BaseSuite) -> str | None:
    """Extract the docstring from a function or class body suite.

    Parameters
    ----------
    body : cst.BaseSuite
        LibCST suite node representing the body of a function or class definition.
        The docstring is expected to be the first statement in the body if present.

    Returns
    -------
    str | None
        Docstring text if found as the first statement in the body, or None if
        no docstring is present. Handles both string and bytes literals, decoding
        bytes to UTF-8 strings when necessary.
    """
    if not getattr(body, "body", None):
        return None
    first_stmt = body.body[0]
    if isinstance(first_stmt, cst.SimpleStatementLine) and first_stmt.body:
        expr = first_stmt.body[0]
        if isinstance(expr, cst.Expr) and isinstance(expr.value, cst.SimpleString):
            with suppress(ValueError):
                evaluated = expr.value.evaluated_value
                if isinstance(evaluated, bytes):
                    return evaluated.decode("utf-8", "ignore")
                if isinstance(evaluated, str):
                    return evaluated
                return str(evaluated)
    return None


def _summarize_docstring(text: str, max_length: int = 200) -> str:
    """Extract a one-line summary from a docstring.

    Parameters
    ----------
    text : str
        Full docstring text to summarize. May be empty or multi-line.
    max_length : int, optional
        Maximum length for the summary string. If the summary exceeds this length,
        it is truncated with "..." appended. Defaults to 200.

    Returns
    -------
    str
        One-line summary extracted from the first line of the docstring or from
        the parsed short_description if docstring_parser is available. The summary
        is truncated to max_length characters if necessary. Returns an empty string
        if text is empty.
    """
    summary = text.strip().splitlines()[0].strip() if text else ""
    if parse_docstring is not None:
        with suppress(Exception):
            parsed = parse_docstring(text)
            if parsed.short_description:
                summary = parsed.short_description.strip()
    if len(summary) > max_length:
        summary = summary[: max_length - 3] + "..."
    return summary


def _analyze_docstring(
    text: str | None,
    param_names: list[str],
) -> tuple[str | None, bool, bool, bool]:
    """Analyze a docstring for completeness and quality metrics.

    Parameters
    ----------
    text : str | None
        Docstring text to analyze, or None if no docstring exists. If None,
        returns a tuple indicating no summary, no summary present, no parameter
        parity, and no examples.
    param_names : list[str]
        List of parameter names from the function signature (excluding "self"
        and "cls"). Used to check if all parameters are documented in the
        docstring.

    Returns
    -------
    tuple[str | None, bool, bool, bool]
        Tuple containing:
        - Summary string (one-line) or None if no summary found
        - Whether a summary is present (has_summary)
        - Whether all parameters are documented (param_parity)
        - Whether examples are present in the docstring (has_examples)
    """
    if not text:
        return None, False, False, False
    summary = _summarize_docstring(text)
    has_summary = bool(summary)
    documented_params: set[str] = set()
    has_examples = ">>>" in text or "examples" in text.lower()
    if parse_docstring is not None:
        with suppress(Exception):
            parsed = parse_docstring(text)
            if parsed.short_description:
                summary = parsed.short_description.strip()
                has_summary = True
            documented_params = {param.arg_name for param in parsed.params if param.arg_name}
            has_examples = has_examples or bool(parsed.examples)
    filtered_params = [name for name in param_names if name not in {"self", "cls"}]
    if filtered_params:
        parity = bool(documented_params) and set(filtered_params).issubset(documented_params)
    else:
        parity = True
    return (summary or None, has_summary, parity, has_examples)


def _iter_params(params: cst.Parameters) -> Iterator[cst.Param]:
    """Iterate over all parameter nodes in a LibCST Parameters object.

    Parameters
    ----------
    params : cst.Parameters
        LibCST Parameters node containing function parameters. Includes
        positional-only, regular, keyword-only, *args, and **kwargs parameters.

    Yields
    ------
    cst.Param
        Each parameter node found in the Parameters object, including
        positional-only, regular, keyword-only, *args, and **kwargs parameters
        if present. Only yields actual Param nodes, skipping None values.
    """
    for collection in (
        params.posonly_params,
        params.params,
        params.kwonly_params,
    ):
        for param in collection:
            if isinstance(param, cst.Param):
                yield param
    if isinstance(params.star_arg, cst.Param):
        yield params.star_arg
    if isinstance(params.star_kwarg, cst.Param):
        yield params.star_kwarg


def _exception_name(expr: cst.BaseExpression | None) -> str | None:
    """Extract exception name from LibCST expression node.

    Parameters
    ----------
    expr : cst.BaseExpression | None
        LibCST expression node representing an exception type, or None.

    Returns
    -------
    str | None
        Dot-separated exception name (e.g., "ValueError" or "kgfoundry.errors.KgFoundryError"),
        or None if the expression cannot be resolved to a name.
    """
    if expr is None:
        return None
    if isinstance(expr, cst.Name):
        return expr.value
    if isinstance(expr, cst.Attribute):
        parts = []
        current: cst.BaseExpression | None = expr
        while isinstance(current, cst.Attribute):
            parts.append(current.attr.value)
            current = current.value
        if isinstance(current, cst.Name):
            parts.append(current.value)
            return ".".join(reversed(parts))
    return None


def _infer_side_effects(imports: set[str], code: str) -> dict[str, bool]:
    """Infer side-effect categories from imported modules and code patterns.

    Analyzes imported module names and code content to detect potential side
    effects in four categories: filesystem operations, network operations,
    subprocess execution, and database access. Uses heuristics based on module
    name prefixes and code patterns (e.g., "open(" for filesystem, "requests."
    for network).

    Parameters
    ----------
    imports : set[str]
        Set of imported module names (e.g., {"os", "pathlib", "requests"}).
        Used to detect side-effect categories based on module name prefixes.
    code : str
        Source code content to analyze for side-effect patterns. The code is
        lowercased for pattern matching (e.g., detecting "open(" or "requests.").

    Returns
    -------
    dict[str, bool]
        Dictionary with keys "filesystem", "network", "subprocess", "database"
        and boolean values indicating whether each category of side effect is
        detected. True means the category is likely present, False means it
        is not detected.

    Notes
    -----
    This function uses heuristics and may produce false positives or false
    negatives. It checks module name prefixes (e.g., "os", "pathlib" for
    filesystem) and code patterns (e.g., "open(" for filesystem, "requests."
    for network). Time complexity: O(n + m) where n is the number of imports
    and m is the length of the code string.
    """
    lowered = code.lower()

    def has_any(prefixes: tuple[str, ...]) -> bool:
        """Check if any imported module matches the given prefixes.

        This helper function checks whether any module in the imports set starts
        with any of the provided prefixes. Used to detect side-effect categories
        (filesystem, network, subprocess, database) based on imported module names.

        Parameters
        ----------
        prefixes : tuple[str, ...]
            Tuple of module name prefixes to check against (e.g., ("os", "pathlib")
            for filesystem operations). The function checks if any imported module
            starts with any of these prefixes.

        Returns
        -------
        bool
            True if any imported module name starts with any of the provided
            prefixes, False otherwise. Returns False if imports is empty or no
            matches are found.

        Notes
        -----
        This is a nested helper function used within _infer_side_effects() to
        categorize side effects. Time complexity: O(n * m) where n is the number
        of imports and m is the number of prefixes, but typically very fast due
        to short module names and small prefix sets.
        """
        return any(mod.startswith(prefix) for prefix in prefixes for mod in imports)

    filesystem = has_any(("os", "pathlib", "shutil", "tarfile", "zipfile")) or "open(" in lowered
    network = (
        has_any(("http", "urllib", "requests", "httpx", "aiohttp", "socket"))
        or "requests." in lowered
    )
    subprocess = has_any(("subprocess", "asyncio")) or "subprocess." in lowered
    database = has_any(("sqlite3", "duckdb", "psycopg", "sqlalchemy", "pymongo", "redis"))

    return {
        "filesystem": filesystem,
        "network": network,
        "subprocess": subprocess,
        "database": database,
    }


class _IndexVisitor(cst.CSTVisitor):
    """Collect module metadata via a single LibCST traversal."""

    METADATA_DEPENDENCIES = (
        cst_metadata.PositionProvider,
        cst_metadata.ScopeProvider,
        cst_metadata.QualifiedNameProvider,
    )
    NODE_HANDLERS: ClassVar[dict[type[cst.CSTNode], NodeHandler]]

    def __init__(self, code: str) -> None:
        """Initialize index visitor with source code.

        Parameters
        ----------
        code : str
            Source code text to analyze. Used for computing metrics like LOC
            and inferring side effects.
        """
        self.imports: list[ImportEntry] = []
        self.defs: list[DefEntry] = []
        self.exports: set[str] = set()
        self.docstring: str | None = None
        self.doc_summary: str | None = None
        self.doc_metrics: dict[str, bool] = {
            "has_summary": False,
            "param_parity": True,
            "examples_present": False,
        }
        self.doc_items: list[dict[str, Any]] = []
        self.annotation_ratio: dict[str, float] = {"params": 1.0, "returns": 1.0}
        self.untyped_defs = 0
        self.side_effects = _infer_side_effects(set(), code)
        self.complexity: dict[str, int] = {
            "branches": 0,
            "cyclomatic": 1,
            "loc": max(1, code.count("\n") + 1),
        }
        self.raises: list[str] = []
        self._class_depth = 0
        self._function_depth = 0
        self._code = code
        self._branch_count = 0
        self._raise_names: set[str] = set()
        self._imported_modules: set[str] = set()
        self._annotation_counts = {
            "params_total": 0,
            "params_annotated": 0,
            "returns_total": 0,
            "returns_annotated": 0,
        }
        self._untyped_defs = 0

    def on_visit(self, node: cst.CSTNode) -> bool:
        """Visit a LibCST node during AST traversal and collect metadata.

        This method is called by LibCST for each node during AST traversal. It
        handles various node types (Module, Import, ImportFrom, FunctionDef,
        ClassDef, Assign, etc.) to extract imports, definitions, exports, docstrings,
        complexity metrics, and exception information. The method tracks nesting
        depth for classes and functions and increments branch counts for control
        flow nodes.

        Parameters
        ----------
        node : cst.CSTNode
            LibCST node being visited during AST traversal. The method handles
            multiple node types including statements, expressions, and definitions.

        Returns
        -------
        bool
            Always returns True to continue traversal of child nodes. Returning
            False would stop traversal, which is not desired for this visitor.

        Notes
        -----
        This method implements the LibCST visitor pattern and is called
        automatically during wrapper.visit(). It mutates the visitor's internal
        state (imports, defs, exports, complexity, etc.) as it traverses the AST.
        Time complexity: O(1) per node visit, O(n) total for n nodes in the AST.
        The method is not thread-safe and should be used with a single visitor
        instance per AST traversal.
        """
        branch_nodes: tuple[type[cst.CSTNode], ...] = (
            cst.If,
            cst.For,
            cst.While,
            cst.Try,
            cst.With,
            cst.IfExp,
            cst.BooleanOperation,
        )
        optional_nodes = [
            getattr(cst, "AsyncFor", None),
            getattr(cst, "AsyncWith", None),
            getattr(cst, "Match", None),
        ]
        branch_nodes += tuple(node for node in optional_nodes if isinstance(node, type))
        if isinstance(node, branch_nodes):
            self._branch_count += 1
        if isinstance(node, cst.Raise):
            name = _exception_name(getattr(node, "exc", None))
            if name:
                self._raise_names.add(name)

        is_top_level = self._is_module_scope(node)
        handler = self.NODE_HANDLERS.get(type(node))
        if handler is not None:
            handler(self, node, is_top_level=is_top_level)
        return True

    def on_leave(self, original_node: cst.CSTNode) -> None:
        """Leave a LibCST node after visiting its children.

        This method is called by LibCST after all children of a node have been
        visited. It decrements nesting depth counters for FunctionDef and ClassDef
        nodes to maintain accurate depth tracking for top-level detection.

        Parameters
        ----------
        original_node : cst.CSTNode
            LibCST node being left after traversal of its children. The method
            checks for FunctionDef and ClassDef nodes to update nesting depth.

        Notes
        -----
        This method implements the LibCST visitor pattern and is called
        automatically during wrapper.visit() after children are processed. It
        maintains nesting depth state for accurate top-level definition detection.
        Time complexity: O(1) per node leave. The method is not thread-safe and
        should be used with a single visitor instance per AST traversal.
        """
        if isinstance(original_node, cst.FunctionDef):
            self._function_depth = max(0, self._function_depth - 1)
        elif isinstance(original_node, cst.ClassDef):
            self._class_depth = max(0, self._class_depth - 1)

    def _is_module_scope(self, node: cst.CSTNode) -> bool:
        """Check if a node is at module scope (not nested in class/function).

        Determines whether a LibCST node is at module scope by checking the
        scope metadata provider. Falls back to depth counters if metadata is
        unavailable. Module scope means the node is not nested inside a class
        or function definition.

        Parameters
        ----------
        node : cst.CSTNode
            LibCST node to check for module scope. The node's scope metadata
            is queried to determine if it's in a GlobalScope.

        Returns
        -------
        bool
            True if the node is at module scope (not nested in class/function),
            False if it's nested inside a class or function definition. Returns
            True if scope metadata is unavailable and depth counters indicate
            module level.

        Notes
        -----
        This method uses LibCST's ScopeProvider metadata when available, which
        is more accurate than depth counters. Falls back to checking class_depth
        and function_depth counters if metadata is unavailable (e.g., during
        partial parsing or metadata errors). Time complexity: O(1).
        """
        try:
            scope = self.get_metadata(cst_metadata.ScopeProvider, node)
            return isinstance(scope, cst_metadata.GlobalScope)
        except KeyError:
            return self._class_depth == 0 and self._function_depth == 0

    def _qualified_name(self, node: cst.CSTNode) -> str | None:
        """Extract the qualified name of a LibCST node from metadata.

        Retrieves the fully qualified name (e.g., "module.Class.method") of a
        LibCST node using the QualifiedNameProvider metadata. Prefers LOCAL
        source qualified names over imported ones. Returns the first available
        qualified name if no LOCAL source is found.

        Parameters
        ----------
        node : cst.CSTNode
            LibCST node to extract qualified name from. The node's qualified
            name metadata is queried to determine its fully qualified identifier.

        Returns
        -------
        str | None
            Fully qualified name (e.g., "module.Class.method") if available,
            or None if metadata is unavailable or the node has no qualified name.
            Prefers LOCAL source qualified names over imported ones.

        Notes
        -----
        This method uses LibCST's QualifiedNameProvider metadata to resolve
        fully qualified names. It prioritizes LOCAL source names (defined in
        the current module) over imported names. Returns None if metadata is
        unavailable or the node is not a named entity. Time complexity: O(n)
        where n is the number of qualified names for the node (typically 1).
        """
        try:
            qualnames = self.get_metadata(cst_metadata.QualifiedNameProvider, node)
        except KeyError:
            return None
        if not isinstance(qualnames, Collection):
            return None
        for qualified in qualnames:
            if qualified.source is cst_metadata.QualifiedNameSource.LOCAL:
                return qualified.name
        first = next(iter(qualnames), None)
        return first.name if first else None

    def finalize(self) -> None:
        """Finalize visitor state after AST traversal completes.

        This method computes final metrics and aggregates from the collected
        visitor state. It calculates annotation ratios (params and returns),
        finalizes complexity metrics (branches, cyclomatic complexity, LOC),
        infers side effects from imported modules, and sorts exception names.
        Should be called after wrapper.visit() completes to ensure all metrics
        are properly computed.

        Notes
        -----
        This method mutates the visitor's state to compute final metrics:
        - annotation_ratio: percentage of annotated parameters and return types
        - complexity: final branch count, cyclomatic complexity, and LOC
        - side_effects: inferred side effects from imports and code patterns
        - raises: sorted list of exception names found in raise statements
        Time complexity: O(n) where n is the number of imports for side effect
        inference, plus O(m log m) for sorting m exception names. The method
        should be called exactly once after traversal completes.
        """
        params_total = self._annotation_counts["params_total"]
        params_annotated = self._annotation_counts["params_annotated"]
        returns_total = self._annotation_counts["returns_total"]
        returns_annotated = self._annotation_counts["returns_annotated"]
        self.annotation_ratio = {
            "params": (params_annotated / params_total) if params_total else 1.0,
            "returns": (returns_annotated / returns_total) if returns_total else 1.0,
        }
        self.untyped_defs = self._untyped_defs
        self.side_effects = _infer_side_effects(self._imported_modules, self._code)
        loc_value = self.complexity.get("loc", 0)
        self.complexity = {
            "branches": self._branch_count,
            "cyclomatic": self._branch_count + 1,
            "loc": loc_value,
        }
        self.raises = sorted(self._raise_names)
        if self.doc_summary:
            self.doc_metrics["has_summary"] = True

    def _handle_import(self, node: cst.Import) -> None:
        """Process an import statement node and update visitor state.

        Extracts imported module names and aliases from a LibCST Import node
        (e.g., `import os` or `import os as operating_system`). Resolves import
        aliases, tracks imported modules for side-effect inference, and appends
        an ImportEntry to the visitor's imports list.

        Parameters
        ----------
        node : cst.Import
            LibCST Import node representing an import statement. Contains import
            aliases specifying which modules are imported (e.g., `import os, sys`).

        Notes
        -----
        This method mutates the visitor's state:
        - Updates `_imported_modules` set with imported module names for side-effect
          inference
        - Appends an ImportEntry to the `imports` list with resolved names and aliases
        Import statements have no module name (module=None) and level 0 (absolute imports).
        Time complexity: O(n) where n is the number of import aliases in the node.
        """
        names, aliases = self._resolve_import_aliases(node.names)
        for value in names:
            if value:
                self._imported_modules.add(value)
        self.imports.append(
            ImportEntry(module=None, names=names, aliases=aliases, is_star=False, level=0)
        )

    def _handle_import_from(self, node: cst.ImportFrom) -> None:
        """Process an import-from statement node and update visitor state.

        Extracts imported module name, imported symbols, and import level from
        a LibCST ImportFrom node (e.g., `from os import path` or `from . import module`).
        Handles both regular imports and star imports (`from module import *`).
        Resolves import aliases, tracks imported modules for side-effect inference,
        and appends an ImportEntry to the visitor's imports list.

        Parameters
        ----------
        node : cst.ImportFrom
            LibCST ImportFrom node representing an import-from statement. Contains
            the source module name, import level (for relative imports), and imported
            symbol aliases (or ImportStar for star imports).

        Notes
        -----
        This method mutates the visitor's state:
        - Updates `_imported_modules` set with source module name and fully qualified
          imported symbol names (e.g., "os.path") for side-effect inference
        - Appends an ImportEntry to the `imports` list with resolved module name,
          imported names, aliases, star import flag, and import level
        Import level is computed from the number of dots in relative imports (e.g.,
        `from . import x` has level 1, `from .. import x` has level 2).
        Time complexity: O(n) where n is the number of imported symbols.
        """
        is_star = isinstance(node.names, cst.ImportStar)
        names: list[str] = []
        aliases: dict[str, str] = {}
        if not is_star:
            alias_nodes = cast("Sequence[cst.ImportAlias]", node.names)
            names, aliases = self._resolve_import_aliases(alias_nodes)
        module = self._resolve_module_name(node.module)
        level = len(node.relative or [])
        if module:
            self._imported_modules.add(module)
            for name in names:
                if name:
                    self._imported_modules.add(f"{module}.{name}")
        self.imports.append(
            ImportEntry(
                module=module,
                names=names,
                aliases=aliases,
                is_star=is_star,
                level=level,
            )
        )

    def _handle_function_def(self, node: cst.FunctionDef) -> None:
        """Process a function definition node and update visitor state.

        Extracts function metadata (name, line number) from a LibCST FunctionDef
        node and records it as a module-level definition. Also records function
        documentation metrics (docstring, parameters, return type annotations).

        Parameters
        ----------
        node : cst.FunctionDef
            LibCST FunctionDef node representing a function definition. Contains
            function name, parameters, return type annotation, decorators, and body.

        Notes
        -----
        This method mutates the visitor's state:
        - Appends a DefEntry to the `defs` list with function name and line number
        - Calls `_record_function_doc()` to extract and analyze function docstring,
          parameter documentation, and type annotations
        Only processes top-level function definitions (called from handle_function_node
        when is_top_level=True). Time complexity: O(1) plus O(n) for docstring analysis
        where n is the number of parameters.
        """
        lineno = _lineno(self, node)
        self.defs.append(DefEntry(kind="function", name=node.name.value, lineno=lineno))
        self._record_function_doc(node, lineno)

    def _record_function_doc(self, node: cst.FunctionDef, lineno: int) -> None:
        """Record function documentation and type annotation metrics.

        Analyzes a function definition to extract docstring, parameter documentation,
        type annotations, and documentation quality metrics. Updates visitor state
        with annotation ratios, untyped definition counts, and documentation metrics.
        Appends a doc item entry to the visitor's doc_items list.

        Parameters
        ----------
        node : cst.FunctionDef
            LibCST FunctionDef node representing a function definition. Contains
            function name, parameters, return type annotation, and body (including
            docstring if present).
        lineno : int
            Line number where the function definition starts. Used for error
            reporting and documentation item tracking.

        Notes
        -----
        This method mutates the visitor's state:
        - Updates `_annotation_counts` with parameter and return type annotation
          statistics (total vs annotated)
        - Increments `_untyped_defs` if the function is public and missing type
          annotations
        - Updates `doc_metrics` with documentation quality flags (has_summary,
          param_parity, examples_present)
        - Appends a doc item dictionary to `doc_items` with function metadata
        Only public functions (not starting with "_") affect documentation metrics.
        Time complexity: O(n) where n is the number of parameters for docstring
        analysis and parameter extraction.
        """
        name = node.name.value
        is_public = not name.startswith("_")
        params = list(_iter_params(node.params))
        filtered_params = [
            param.name.value
            for param in params
            if isinstance(param.name, cst.Name) and param.name.value not in {"self", "cls"}
        ]
        annotated = sum(
            1
            for param in params
            if isinstance(param, cst.Param)
            and param.annotation is not None
            and isinstance(param.name, cst.Name)
            and param.name.value not in {"self", "cls"}
        )
        self._annotation_counts["params_total"] += len(filtered_params)
        self._annotation_counts["params_annotated"] += annotated
        self._annotation_counts["returns_total"] += 1
        if node.returns is not None:
            self._annotation_counts["returns_annotated"] += 1
        needs_annotation = bool(filtered_params) and annotated < len(filtered_params)
        needs_annotation = needs_annotation or node.returns is None
        if is_public and needs_annotation:
            self._untyped_defs += 1

        docstring = _extract_def_docstring(node.body)
        summary, has_summary, parity, has_examples = _analyze_docstring(docstring, filtered_params)
        if is_public and (docstring is None or not parity):
            self.doc_metrics["param_parity"] = False
        if is_public and has_summary:
            self.doc_metrics["has_summary"] = True
        if is_public and has_examples:
            self.doc_metrics["examples_present"] = True

        qualname = self._qualified_name(node)
        self.doc_items.append(
            {
                "name": name,
                "qualname": qualname,
                "kind": "function",
                "public": is_public,
                "lineno": lineno,
                "doc_summary": summary,
                "doc_has_summary": has_summary,
                "doc_param_parity": parity if docstring else None,
                "doc_examples_present": has_examples,
            }
        )

    def _handle_class_def(self, node: cst.ClassDef) -> None:
        """Process a class definition node and update visitor state.

        Extracts class metadata (name, line number) from a LibCST ClassDef node
        and records it as a module-level definition. Also records class documentation
        metrics (docstring, examples).

        Parameters
        ----------
        node : cst.ClassDef
            LibCST ClassDef node representing a class definition. Contains class
            name, base classes, decorators, and body (including docstring if present).

        Notes
        -----
        This method mutates the visitor's state:
        - Appends a DefEntry to the `defs` list with class name and line number
        - Calls `_record_class_doc()` to extract and analyze class docstring and
          documentation quality metrics
        Only processes top-level class definitions (called from handle_class_node
        when is_top_level=True). Time complexity: O(1) plus O(1) for docstring analysis.
        """
        lineno = _lineno(self, node)
        self.defs.append(DefEntry(kind="class", name=node.name.value, lineno=lineno))
        self._record_class_doc(node, lineno)

    def _record_class_doc(self, node: cst.ClassDef, lineno: int) -> None:
        """Record class documentation and quality metrics.

        Analyzes a class definition to extract docstring and documentation quality
        metrics (summary presence, examples). Updates visitor state with documentation
        metrics and appends a doc item entry to the visitor's doc_items list.

        Parameters
        ----------
        node : cst.ClassDef
            LibCST ClassDef node representing a class definition. Contains class
            name, base classes, and body (including docstring if present).
        lineno : int
            Line number where the class definition starts. Used for error reporting
            and documentation item tracking.

        Notes
        -----
        This method mutates the visitor's state:
        - Updates `doc_metrics` with documentation quality flags (has_summary,
          examples_present) for public classes
        - Appends a doc item dictionary to `doc_items` with class metadata
        Only public classes (not starting with "_") affect documentation metrics.
        Parameter parity is not checked for classes (doc_param_parity is None).
        Time complexity: O(1) for docstring extraction and analysis.
        """
        name = node.name.value
        is_public = not name.startswith("_")
        docstring = _extract_def_docstring(node.body)
        summary, has_summary, _parity, has_examples = _analyze_docstring(docstring, [])
        if is_public and has_summary:
            self.doc_metrics["has_summary"] = True
        if is_public and has_examples:
            self.doc_metrics["examples_present"] = True

        qualname = self._qualified_name(node)
        self.doc_items.append(
            {
                "name": name,
                "qualname": qualname,
                "kind": "class",
                "public": is_public,
                "lineno": lineno,
                "doc_summary": summary,
                "doc_has_summary": has_summary,
                "doc_param_parity": None,
                "doc_examples_present": has_examples,
            }
        )

    def _handle_assign(self, node: cst.Assign) -> None:
        """Process an assignment node and update visitor state.

        Extracts variable names from a LibCST Assign node and records them as
        module-level variable definitions. Handles `__all__` assignments specially
        to extract explicit export lists. Only processes public variable names
        (not starting with "_").

        Parameters
        ----------
        node : cst.Assign
            LibCST Assign node representing an assignment statement. Contains
            assignment targets and values used to extract variable names and
            __all__ exports.

        Notes
        -----
        This method mutates the visitor's state:
        - Appends DefEntry objects to the `defs` list for public variable names
        - Calls `_extend_exports_from_node()` for `__all__` assignments to extract
          explicit export lists
        Only processes top-level assignments (called from handle_assign_node when
        is_top_level=True). Private variables (starting with "_") are skipped.
        Time complexity: O(n) where n is the number of assignment targets.
        """
        lineno = _lineno(self, node)
        for target in node.targets:
            assign_target = target.target
            if m.matches(assign_target, m.Name("__all__")):
                self._extend_exports_from_node(node.value)
                continue
            if isinstance(assign_target, cst.Name):
                name = assign_target.value
                if name.startswith("_"):
                    continue
                self.defs.append(DefEntry(kind="variable", name=name, lineno=lineno))

    def _handle_ann_assign(self, node: cst.AnnAssign) -> None:
        """Process an annotated assignment node and update visitor state.

        Extracts variable names from a LibCST AnnAssign node and records them
        as module-level typed variable definitions. Skips `__all__` assignments
        and private variable names (starting with "_").

        Parameters
        ----------
        node : cst.AnnAssign
            LibCST AnnAssign node representing an annotated assignment statement.
            Contains assignment target, type annotation, and optional value used
            to extract variable names.

        Notes
        -----
        This method mutates the visitor's state:
        - Appends a DefEntry to the `defs` list for public typed variable names
        Only processes top-level annotated assignments (called from handle_ann_assign_node
        when is_top_level=True). Private variables (starting with "_") and `__all__`
        assignments are skipped. Time complexity: O(1).
        """
        lineno = _lineno(self, node)
        target = node.target
        if isinstance(target, cst.Name):
            name = target.value
            if name == "__all__" or name.startswith("_"):
                return
            self.defs.append(DefEntry(kind="variable", name=name, lineno=lineno))

    def _extend_exports_from_node(self, value: cst.BaseExpression) -> None:
        """Extract export names from a LibCST expression node.

        Recursively extracts literal string values from a LibCST expression node
        representing an `__all__` assignment value. Handles binary operations
        (e.g., `["a"] + ["b"]`), function calls (e.g., `list(["a"])`), and
        literal containers (lists, tuples, sets). Adds extracted names to the
        visitor's exports set.

        Parameters
        ----------
        value : cst.BaseExpression
            LibCST expression node representing the value assigned to `__all__`.
            May be a literal container (list, tuple, set), a binary operation
            (addition), or a function call (list, tuple, set, sorted).

        Notes
        -----
        This method mutates the visitor's state:
        - Adds extracted literal string values to the `exports` set
        Recursively processes binary operations and function calls to extract
        nested literal values. Only processes literal string values, ignoring
        other expression types. Time complexity: O(n) where n is the number of
        literal values in the expression tree.
        """
        if isinstance(value, cst.BinaryOperation) and isinstance(value.operator, cst.Add):
            self._extend_exports_from_node(value.left)
            self._extend_exports_from_node(value.right)
            return
        if isinstance(value, cst.Call) and value.args:
            func_expr = value.func
            if isinstance(func_expr, cst.Name) and func_expr.value in {
                "list",
                "tuple",
                "set",
                "sorted",
            }:
                self._extend_exports_from_node(value.args[0].value)
                return
        for literal in _literal_string_values(value):
            self.exports.add(literal)

    @staticmethod
    def handle_module_node(
        visitor: _IndexVisitor, node: cst.CSTNode, *, is_top_level: bool
    ) -> None:
        """Handle module node during AST traversal.

        This static method processes the root module node during LibCST AST traversal.
        It extracts the module-level docstring and computes a summary for documentation
        metrics. The module docstring is stored in the visitor state and used for
        documentation health analysis.

        Parameters
        ----------
        visitor : _IndexVisitor
            The visitor instance collecting module definitions, imports, and exports.
            The visitor's docstring and doc_summary attributes are updated with
            module-level documentation information.
        node : cst.CSTNode
            The CST node being visited, cast to cst.Module. Contains the module's
            body including the docstring as the first statement if present.
        is_top_level : bool
            Flag indicating module level (always True for module nodes). Unused
            but required by the visitor pattern interface.

        Notes
        -----
        This method is part of the LibCST visitor pattern and is called automatically
        during AST traversal. It extracts module docstrings and computes summaries
        for documentation metrics. If no docstring is present, the method returns
        early without updating visitor state. Thread-safe if the visitor instance
        is thread-safe.
        """
        del is_top_level
        module_node = cast("cst.Module", node)
        visitor.docstring = _extract_module_docstring(module_node)
        if not visitor.docstring:
            return
        visitor.doc_summary = _summarize_docstring(visitor.docstring)
        if visitor.doc_summary:
            visitor.doc_metrics["has_summary"] = True

    @staticmethod
    def handle_import_node(
        visitor: _IndexVisitor, node: cst.CSTNode, *, is_top_level: bool
    ) -> None:
        """Handle import node during AST traversal.

        This static method processes import statements (e.g., `import os`) during
        LibCST AST traversal. It delegates to the visitor's internal handler to
        extract imported module names and track them in the visitor's import list.
        All imports are processed regardless of nesting level to build a complete
        import graph.

        Parameters
        ----------
        visitor : _IndexVisitor
            The visitor instance collecting module definitions, imports, and exports.
            The visitor's imports list is updated with imported module names.
        node : cst.CSTNode
            The CST node being visited, cast to cst.Import. Contains import aliases
            specifying which modules are imported.
        is_top_level : bool
            Flag indicating whether the import is at module level (True) or nested
            inside a function/class (False). Unused but required by the visitor
            pattern interface.

        Notes
        -----
        This method is part of the LibCST visitor pattern and is called automatically
        during AST traversal. It processes all import statements to build a complete
        import graph for dependency analysis. Thread-safe if the visitor instance
        is thread-safe.
        """
        del is_top_level
        visitor._handle_import(cast("cst.Import", node))

    @staticmethod
    def handle_import_from_node(
        visitor: _IndexVisitor, node: cst.CSTNode, *, is_top_level: bool
    ) -> None:
        """Handle import-from node during AST traversal.

        This static method processes import-from statements (e.g., `from os import path`)
        during LibCST AST traversal. It delegates to the visitor's internal handler
        to extract imported module names, imported symbols, and import levels (for
        relative imports). All imports are processed regardless of nesting level to
        build a complete import graph.

        Parameters
        ----------
        visitor : _IndexVisitor
            The visitor instance collecting module definitions, imports, and exports.
            The visitor's imports list is updated with imported module names and
            symbol information.
        node : cst.CSTNode
            The CST node being visited, cast to cst.ImportFrom. Contains the source
            module name, import level (for relative imports), and imported symbol
            aliases.
        is_top_level : bool
            Flag indicating whether the import-from is at module level (True) or
            nested inside a function/class (False). Unused but required by the
            visitor pattern interface.

        Notes
        -----
        This method is part of the LibCST visitor pattern and is called automatically
        during AST traversal. It processes all import-from statements to build a
        complete import graph for dependency analysis, including relative imports.
        Thread-safe if the visitor instance is thread-safe.
        """
        del is_top_level
        visitor._handle_import_from(cast("cst.ImportFrom", node))

    @staticmethod
    def handle_function_node(
        visitor: _IndexVisitor, node: cst.CSTNode, *, is_top_level: bool
    ) -> None:
        """Handle function definition node during AST traversal.

        This static method processes function definitions during LibCST AST traversal.
        For top-level functions, it delegates to the visitor's internal handler to
        extract function metadata (name, parameters, return type, docstring) and
        track them as module-level definitions. The function depth counter is
        incremented to track nesting level for all functions.

        Parameters
        ----------
        visitor : _IndexVisitor
            The visitor instance collecting module definitions, imports, and exports.
            For top-level functions, the visitor's defs list and doc_items list are
            updated with function metadata. The function depth counter is always
            incremented to track nesting.
        node : cst.CSTNode
            The CST node being visited, cast to cst.FunctionDef. Contains function
            name, parameters, return type annotation, decorators, and body.
        is_top_level : bool
            Flag indicating whether the function is at module level (True) or nested
            inside a class/function (False). Only top-level functions are tracked
            as module-level definitions.

        Notes
        -----
        This method is part of the LibCST visitor pattern and is called automatically
        during AST traversal. It processes function definitions to extract metadata
        for top-level functions while tracking nesting depth for all functions.
        Thread-safe if the visitor instance is thread-safe.
        """
        func_node = cast("cst.FunctionDef", node)
        if is_top_level:
            visitor._handle_function_def(func_node)
        visitor._function_depth += 1

    @staticmethod
    def handle_class_node(visitor: _IndexVisitor, node: cst.CSTNode, *, is_top_level: bool) -> None:
        """Handle class definition node during AST traversal.

        This static method processes class definitions during LibCST AST traversal.
        For top-level classes, it delegates to the visitor's internal handler to
        extract class metadata (name, base classes, docstring) and track them as
        module-level definitions. The class depth counter is incremented to track
        nesting level for all classes.

        Parameters
        ----------
        visitor : _IndexVisitor
            The visitor instance collecting module definitions, imports, and exports.
            For top-level classes, the visitor's defs list and doc_items list are
            updated with class metadata. The class depth counter is always incremented
            to track nesting.
        node : cst.CSTNode
            The CST node being visited, cast to cst.ClassDef. Contains class name,
            base classes, decorators, and body including methods and class variables.
        is_top_level : bool
            Flag indicating whether the class is at module level (True) or nested
            inside another class/function (False). Only top-level classes are tracked
            as module-level definitions.

        Notes
        -----
        This method is part of the LibCST visitor pattern and is called automatically
        during AST traversal. It processes class definitions to extract metadata for
        top-level classes while tracking nesting depth for all classes. Thread-safe
        if the visitor instance is thread-safe.
        """
        class_node = cast("cst.ClassDef", node)
        if is_top_level:
            visitor._handle_class_def(class_node)
        visitor._class_depth += 1

    @staticmethod
    def handle_assign_node(
        visitor: _IndexVisitor, node: cst.CSTNode, *, is_top_level: bool
    ) -> None:
        """Handle assignment node during AST traversal.

        This static method processes assignment nodes (e.g., `x = value`) during
        LibCST AST traversal. It delegates to the visitor's internal handler
        only for top-level assignments, which are tracked as module-level variable
        definitions. Nested assignments (inside functions/classes) are ignored
        to focus on module-level exports and definitions.

        Parameters
        ----------
        visitor : _IndexVisitor
            The visitor instance collecting module definitions, imports, and exports.
            The visitor's state is updated with variable definitions found in
            top-level assignments.
        node : cst.CSTNode
            The CST node being visited, cast to cst.Assign. Contains assignment
            targets and values used to extract variable names and __all__ exports.
        is_top_level : bool
            Flag indicating whether the assignment is at module level (True) or
            nested inside a function/class (False). Only top-level assignments
            are processed to track module-level variables.

        Notes
        -----
        This method is part of the LibCST visitor pattern and is called automatically
        during AST traversal. It filters assignments to only process top-level ones,
        ensuring module-level variable definitions are tracked while ignoring
        local variables. The method handles __all__ assignments specially to extract
        explicit export lists. Thread-safe if the visitor instance is thread-safe.
        """
        if is_top_level:
            visitor._handle_assign(cast("cst.Assign", node))

    @staticmethod
    def handle_ann_assign_node(
        visitor: _IndexVisitor, node: cst.CSTNode, *, is_top_level: bool
    ) -> None:
        """Handle annotated assignment node during AST traversal.

        This static method processes annotated assignment nodes (e.g., `x: int = value`)
        during LibCST AST traversal. It delegates to the visitor's internal handler
        only for top-level annotated assignments, which are tracked as module-level
        typed variable definitions. Nested assignments (inside functions/classes) are
        ignored to focus on module-level exports and definitions.

        Parameters
        ----------
        visitor : _IndexVisitor
            The visitor instance collecting module definitions, imports, and exports.
            The visitor's state is updated with typed variable definitions found in
            top-level annotated assignments.
        node : cst.CSTNode
            The CST node being visited, cast to cst.AnnAssign. Contains assignment
            target, type annotation, and optional value used to extract variable names.
        is_top_level : bool
            Flag indicating whether the annotated assignment is at module level (True)
            or nested inside a function/class (False). Only top-level assignments are
            processed to track module-level typed variables.

        Notes
        -----
        This method is part of the LibCST visitor pattern and is called automatically
        during AST traversal. It filters annotated assignments to only process top-level
        ones, ensuring module-level typed variable definitions are tracked while ignoring
        local variables. The method handles __all__ assignments specially to extract
        explicit export lists. Thread-safe if the visitor instance is thread-safe.
        """
        if is_top_level:
            visitor._handle_ann_assign(cast("cst.AnnAssign", node))

    @staticmethod
    def handle_expr_node(visitor: _IndexVisitor, node: cst.CSTNode, *, is_top_level: bool) -> None:
        """Handle expression node during AST traversal.

        This static method processes expression nodes (e.g., `__all__.append("name")`)
        during LibCST AST traversal. It detects calls to `__all__.append()` and
        `__all__.extend()` at module level to extract explicit export lists. Nested
        expressions (inside functions/classes) are ignored to focus on module-level
        exports.

        Parameters
        ----------
        visitor : _IndexVisitor
            The visitor instance collecting module definitions, imports, and exports.
            The visitor's exports set is updated with names added via __all__ method
            calls.
        node : cst.CSTNode
            The CST node being visited, cast to cst.Expr. Contains a call expression
            that may be a __all__ modification (append or extend).
        is_top_level : bool
            Flag indicating whether the expression is at module level (True) or nested
            inside a function/class (False). Only top-level expressions are processed
            to track module-level exports.

        Notes
        -----
        This method is part of the LibCST visitor pattern and is called automatically
        during AST traversal. It handles dynamic __all__ modifications that cannot be
        detected from static assignments. The method only processes calls to __all__
        methods, ignoring other expression statements. Thread-safe if the visitor
        instance is thread-safe.
        """
        if not is_top_level:
            return
        expr = cast("cst.Expr", node)
        value = expr.value
        if not isinstance(value, cst.Call) or not value.args:
            return
        func = value.func
        if m.matches(func, m.Attribute(value=m.Name("__all__"), attr=m.Name("append"))):
            literal = _string_literal_value(value.args[0].value)
            if literal:
                visitor.exports.add(literal)
        elif m.matches(func, m.Attribute(value=m.Name("__all__"), attr=m.Name("extend"))):
            visitor._extend_exports_from_node(value.args[0].value)

    @staticmethod
    def handle_aug_assign_node(
        visitor: _IndexVisitor, node: cst.CSTNode, *, is_top_level: bool
    ) -> None:
        """Handle augmented assignment node during AST traversal.

        This static method processes augmented assignment nodes (e.g., `__all__ += ["name"]`)
        during LibCST AST traversal. It detects augmented assignments to `__all__` at
        module level to extract explicit export list modifications. Nested assignments
        (inside functions/classes) are ignored to focus on module-level exports.

        Parameters
        ----------
        visitor : _IndexVisitor
            The visitor instance collecting module definitions, imports, and exports.
            The visitor's exports set is updated with names added via __all__ augmented
            assignments.
        node : cst.CSTNode
            The CST node being visited, cast to cst.AugAssign. Contains an augmented
            assignment (e.g., +=, -=) that may modify __all__.
        is_top_level : bool
            Flag indicating whether the augmented assignment is at module level (True)
            or nested inside a function/class (False). Only top-level assignments are
            processed to track module-level exports.

        Notes
        -----
        This method is part of the LibCST visitor pattern and is called automatically
        during AST traversal. It handles dynamic __all__ modifications via augmented
        assignments (e.g., `__all__ += ["new_export"]`). The method delegates to
        `_extend_exports_from_node()` to extract literal values from the right-hand
        side expression. Thread-safe if the visitor instance is thread-safe.
        """
        if not is_top_level:
            return
        aug = cast("cst.AugAssign", node)
        if m.matches(aug.target, m.Name("__all__")):
            visitor._extend_exports_from_node(aug.value)

    def _resolve_import_aliases(
        self, alias_nodes: Sequence[cst.ImportAlias]
    ) -> tuple[list[str], dict[str, str]]:
        """Resolve import alias nodes to names and alias mappings.

        Extracts imported symbol names and their aliases from LibCST ImportAlias
        nodes. Handles both simple imports (`import os`) and aliased imports
        (`import os as operating_system`).

        Parameters
        ----------
        alias_nodes : Sequence[cst.ImportAlias]
            Sequence of LibCST ImportAlias nodes from an import statement. Each
            node contains the imported name and optional alias (asname).

        Returns
        -------
        tuple[list[str], dict[str, str]]
            Tuple containing:
            - List of imported symbol names (resolved from ImportAlias.name)
            - Dictionary mapping original names to aliases (only includes entries
              where an alias is present, e.g., {"os": "operating_system"})
        """
        names: list[str] = []
        aliases: dict[str, str] = {}
        for ref in alias_nodes:
            value = self._resolve_alias_target(ref.name)
            names.append(value)
            alias = self._resolve_alias_name(ref.asname)
            if alias:
                aliases[value] = alias
        return names, aliases

    @staticmethod
    def _resolve_alias_name(asname: cst.AsName | None) -> str | None:
        """Extract the alias name from a LibCST AsName node.

        Parameters
        ----------
        asname : cst.AsName | None
            LibCST AsName node representing an import alias (e.g., `as os` in
            `import sys as os`), or None if no alias is present.

        Returns
        -------
        str | None
            Alias name string if asname is a valid AsName with a Name node,
            or None if asname is None or the structure is invalid.
        """
        if isinstance(asname, cst.AsName) and isinstance(asname.name, cst.Name):
            return asname.name.value
        return None

    @staticmethod
    def _resolve_alias_target(ident: cst.BaseExpression) -> str:
        """Resolve an imported identifier expression to its name string.

        Extracts the name of an imported symbol from a LibCST expression node.
        Handles simple names (`os`), dotted names (`os.path`), and attribute
        access patterns.

        Parameters
        ----------
        ident : cst.BaseExpression
            LibCST expression node representing an imported identifier. May be
            a Name, Attribute, or other expression type.

        Returns
        -------
        str
            Resolved name string. For simple names, returns the name value.
            For dotted names, uses LibCST's `get_full_name_for_node()` helper.
            For Attribute nodes, returns the attribute name. Returns an empty
            string if resolution fails.
        """
        dotted = None
        with suppress(Exception):
            dotted = get_full_name_for_node(ident)
        if isinstance(ident, cst.Name):
            return ident.value
        if dotted:
            return dotted
        if isinstance(ident, cst.Attribute):
            return ident.attr.value
        return ""

    @staticmethod
    def _resolve_module_name(module: cst.BaseExpression | None) -> str | None:
        """Resolve a module expression to its fully qualified name string.

        Extracts the module name from a LibCST expression node representing the
        source module in an import-from statement (e.g., `os` in `from os import path`).

        Parameters
        ----------
        module : cst.BaseExpression | None
            LibCST expression node representing the source module name, or None
            for relative imports without an explicit module name.

        Returns
        -------
        str | None
            Fully qualified module name string (e.g., "os.path") if resolution
            succeeds, or None if module is None or resolution fails. Uses LibCST's
            `get_full_name_for_node()` helper for dotted module names.
        """
        if module is None:
            return None
        with suppress(Exception):  # pragma: no cover - LibCST helper may raise
            return get_full_name_for_node(module)
        return None


_IndexVisitor.NODE_HANDLERS = {
    cst.Module: _IndexVisitor.handle_module_node,
    cst.Import: _IndexVisitor.handle_import_node,
    cst.ImportFrom: _IndexVisitor.handle_import_from_node,
    cst.FunctionDef: _IndexVisitor.handle_function_node,
    getattr(cst, "AsyncFunctionDef", cst.FunctionDef): _IndexVisitor.handle_function_node,
    cst.ClassDef: _IndexVisitor.handle_class_node,
    cst.Assign: _IndexVisitor.handle_assign_node,
    cst.AnnAssign: _IndexVisitor.handle_ann_assign_node,
    cst.AugAssign: _IndexVisitor.handle_aug_assign_node,
    cst.Expr: _IndexVisitor.handle_expr_node,
}


def index_module(path: str, code: str) -> ModuleIndex:
    """Return parsed module metadata, falling back to a stub on parse failure.

    Parameters
    ----------
    path : str
        File path of the module being indexed (used for error reporting and
        metadata). May be absolute or relative.
    code : str
        Source code content of the module to parse and index.

    Returns
    -------
    ModuleIndex
        Parsed module metadata containing imports, defs, exports, docstring,
        and parse status. On parse failure, returns a stub with parse_ok=False
        and error details.
    """
    parsed_path = Path(path)
    try:
        wrapper = cst_metadata.MetadataWrapper(cst.parse_module(code))
    except (cst.ParserSyntaxError, RecursionError, ValueError) as exc:  # pragma: no cover
        return ModuleIndex(
            path=str(parsed_path),
            parse_ok=False,
            errors=[f"LibCST parse failed: {exc!r}"],
        )
    visitor = _IndexVisitor(code)
    wrapper.visit(visitor)
    visitor.finalize()
    return ModuleIndex(
        path=str(parsed_path),
        imports=visitor.imports,
        defs=visitor.defs,
        exports=visitor.exports,
        docstring=visitor.docstring,
        doc_summary=visitor.doc_summary,
        doc_metrics=visitor.doc_metrics,
        doc_items=visitor.doc_items,
        annotation_ratio=visitor.annotation_ratio,
        untyped_defs=visitor.untyped_defs,
        side_effects=visitor.side_effects,
        raises=visitor.raises,
        complexity=visitor.complexity,
    )


def _lineno(visitor: _IndexVisitor, node: cst.CSTNode) -> int:
    """Return the starting line number for ``node`` when metadata is available.

    Parameters
    ----------
    visitor : _IndexVisitor
        LibCST visitor instance that provides metadata access via
        ``get_metadata()``.
    node : cst.CSTNode
        LibCST node to extract line number from.

    Returns
    -------
    int
        1-based line number or 0 when metadata is unavailable.
    """
    try:
        pos = visitor.get_metadata(cst_metadata.PositionProvider, node)
        return getattr(getattr(pos, "start", None), "line", 0)
    except (KeyError, AttributeError, TypeError):  # pragma: no cover
        return 0
