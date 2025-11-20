# SPDX-License-Identifier: MIT
"""Static call graph construction for Python sources."""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from codeintel_rev.enrich.function_index import FunctionInfo, collect_function_info
from codeintel_rev.enrich.graph.io import write_call_edges, write_call_nodes
from codeintel_rev.ids.goid import GOID

LOGGER = logging.getLogger(__name__)


class CallNodeRow(TypedDict):
    """Serialized representation of a call graph node."""

    goid_h128: int
    language: str
    kind: str
    arity: int
    is_public: bool
    rel_path: str


class CallEdgeRow(TypedDict, total=False):
    """Serialized representation of a call graph edge."""

    caller_goid_h128: int
    callee_goid_h128: int | None
    callsite_path: str
    callsite_line: int | None
    callsite_col: int | None
    language: str
    kind: str
    resolved_via: str
    confidence: float
    evidence_json: dict[str, object] | None


@dataclass(slots=True)
class CallGraphArtifacts:
    """Materialized call graph rows."""

    goids: list[GOID]
    nodes: list[CallNodeRow]
    edges: list[CallEdgeRow]


@dataclass(slots=True, frozen=True)
class _ImportResolver:
    """Per-module import bindings for call graph resolution."""

    module_name: str
    module_aliases: dict[str, str]
    attr_aliases: dict[str, tuple[str, str]]

    @classmethod
    def from_file(
        cls,
        file_path: Path,
        module_name: str,
        known_modules: set[str],
    ) -> _ImportResolver:
        """Build import resolver by parsing AST from a source file.

        Parameters
        ----------
        file_path : Path
            Path to Python source file to parse for import statements.
        module_name : str
            Canonical module name for the file being parsed.
        known_modules : set[str]
            Set of known module names in the repository, used for validating
            imported module references.

        Returns
        -------
        _ImportResolver
            Resolver instance with populated module and attribute aliases.
            Returns empty resolver if file cannot be read or parsed.
        """
        try:
            source = file_path.read_text(encoding="utf-8")
        except OSError:
            return cls.empty(module_name)
        try:
            tree = ast.parse(source, filename=str(file_path), type_comments=True)
        except SyntaxError:
            return cls.empty(module_name)
        collector = _ImportCollector(module_name, known_modules)
        collector.visit(tree)
        return cls(
            module_name=module_name,
            module_aliases=collector.module_aliases,
            attr_aliases=collector.attr_aliases,
        )

    @classmethod
    def empty(cls, module_name: str) -> _ImportResolver:
        """Create an empty import resolver with no aliases.

        Parameters
        ----------
        module_name : str
            Canonical module name for the resolver.

        Returns
        -------
        _ImportResolver
            Resolver instance with empty alias dictionaries.
        """
        return cls(module_name=module_name, module_aliases={}, attr_aliases={})

    def resolve_module_alias(self, name: str) -> str | None:
        """Resolve a local name to its canonical module name.

        Parameters
        ----------
        name : str
            Local name or alias used in import statements.

        Returns
        -------
        str | None
            Canonical module name if the alias exists, None otherwise.
        """
        return self.module_aliases.get(name)

    def resolve_attr_alias(self, name: str) -> tuple[str, str] | None:
        """Resolve a local attribute name to its module and original name.

        Parameters
        ----------
        name : str
            Local name or alias used in import-from statements.

        Returns
        -------
        tuple[str, str] | None
            Tuple of (module_name, original_name) if the alias exists,
            None otherwise.
        """
        return self.attr_aliases.get(name)


class _ImportCollector(ast.NodeVisitor):
    """Collect import aliases for a module."""

    def __init__(self, module_name: str, known_modules: set[str]) -> None:
        self.module_name = module_name
        self.known_modules = known_modules
        self.module_aliases: dict[str, str] = {}
        self.attr_aliases: dict[str, tuple[str, str]] = {}

    def visit_Import(self, node: ast.Import) -> None:
        """Visit import statements and record module aliases.

        Parameters
        ----------
        node : ast.Import
            AST import node containing module names and optional aliases.

        Notes
        -----
        Records mappings from local binding names to canonical module names.
        For imports with aliases (e.g., `import foo as bar`), maps the alias
        to the full module name. For imports without aliases, maps the first
        segment of the module name to the full module name.
        """
        for alias in node.names:
            target = alias.name
            binding = alias.asname or target.split(".")[0]
            if not binding:
                continue
            if alias.asname:
                self.module_aliases[binding] = target
            else:
                self.module_aliases.setdefault(binding, binding)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Visit import-from statements and record attribute aliases.

        Parameters
        ----------
        node : ast.ImportFrom
            AST import-from node containing module path, relative level,
            and imported names with optional aliases.

        Notes
        -----
        Records mappings from local binding names to (module_name, original_name)
        tuples. Also records module aliases when imported names correspond to
        known modules in the repository. Wildcard imports (`from x import *`)
        are skipped.
        """
        names = node.names
        if names is None:
            return
        level = node.level or 0
        module = node.module or ""
        base = _resolve_relative_module(self.module_name, level, module)
        for alias in names:
            if alias.name == "*":
                continue
            target_name = alias.name
            binding = alias.asname or target_name
            self.attr_aliases[binding] = (base, target_name)
            qualified = _normalize_module_path(base, target_name)
            if qualified and qualified in self.known_modules:
                self.module_aliases[binding] = qualified


@dataclass(slots=True)
class _ResolutionContext:
    module_functions: dict[str, dict[str, FunctionInfo]]
    class_methods: dict[tuple[str, str], dict[str, FunctionInfo]]
    global_functions: dict[str, dict[str, FunctionInfo]]
    global_class_methods: dict[tuple[str, str], dict[str, FunctionInfo]]
    module_name_map: dict[str, str]
    import_resolvers: dict[str, _ImportResolver]
    known_modules: set[str]

    @classmethod
    def build(
        cls,
        *,
        functions: Sequence[FunctionInfo],
        files: Sequence[Path],
        repo_root: Path,
    ) -> _ResolutionContext:
        """Build resolution context from function info and file paths.

        Parameters
        ----------
        functions : Sequence[FunctionInfo]
            Sequence of function information objects extracted from source files.
        files : Sequence[Path]
            Sequence of Python source file paths.
        repo_root : Path
            Repository root directory for path normalization.

        Returns
        -------
        _ResolutionContext
            Context instance with populated function maps, module name mappings,
            and import resolvers.
        """
        rel_paths = {file_path: _relative_path(repo_root, file_path) for file_path in files}
        module_name_map = {
            rel_path: _module_name_from_rel_path(rel_path) for rel_path in rel_paths.values()
        }
        known_modules = {name for name in module_name_map.values() if name}
        module_funcs: dict[str, dict[str, FunctionInfo]] = {}
        class_methods: dict[tuple[str, str], dict[str, FunctionInfo]] = {}
        global_module_functions: dict[str, dict[str, FunctionInfo]] = {}
        global_class_methods: dict[tuple[str, str], dict[str, FunctionInfo]] = {}
        for info in functions:
            if not info.node.name:
                continue
            if info.kind == "function" and not info.enclosing_functions:
                module_funcs.setdefault(info.rel_path, {})[info.node.name] = info
            if info.kind == "method" and info.class_stack:
                class_key_rel = (info.rel_path, ".".join(info.class_stack))
                class_methods.setdefault(class_key_rel, {})[info.node.name] = info
            module_name = module_name_map.get(info.rel_path) or _module_name_from_rel_path(
                info.rel_path
            )
            if module_name and info.kind == "function" and not info.enclosing_functions:
                global_module_functions.setdefault(module_name, {})[info.node.name] = info
            if module_name and info.kind == "method":
                class_key = (module_name, ".".join(info.class_stack))
                global_class_methods.setdefault(class_key, {})[info.node.name] = info
        import_resolvers: dict[str, _ImportResolver] = {}
        for file_path, rel_path in rel_paths.items():
            module_name = module_name_map.get(rel_path) or _module_name_from_rel_path(rel_path)
            if module_name in import_resolvers:
                continue
            import_resolvers[module_name] = _ImportResolver.from_file(
                file_path, module_name, known_modules
            )
        return cls(
            module_functions=module_funcs,
            class_methods=class_methods,
            global_functions=global_module_functions,
            global_class_methods=global_class_methods,
            module_name_map=module_name_map,
            import_resolvers=import_resolvers,
            known_modules=known_modules,
        )


@dataclass(slots=True, frozen=True)
class _CollectorInputs:
    module_functions: Mapping[str, FunctionInfo]
    class_methods: Mapping[tuple[str, str], Mapping[str, FunctionInfo]]
    module_name: str
    global_functions: Mapping[str, Mapping[str, FunctionInfo]]
    global_class_methods: Mapping[tuple[str, str], Mapping[str, FunctionInfo]]
    import_resolver: _ImportResolver | None
    known_modules: set[str]


class CallGraphBuilder:
    """Build a static call graph for Python files."""

    def __init__(self, *, repo_root: Path, repo: str, commit: str) -> None:
        self.repo_root = repo_root
        self.repo = repo
        self.commit = commit

    def build(self, files: Sequence[Path]) -> CallGraphArtifacts:
        """Return call graph nodes/edges for ``files``.

        Parameters
        ----------
        files : Sequence[Path]
            Python source files to analyze.

        Returns
        -------
        CallGraphArtifacts
            Materialized GOIDs, node rows, and edge rows for the analyzed files.
        """
        functions = collect_function_info(self.repo_root, files, repo=self.repo, commit=self.commit)
        context = _ResolutionContext.build(
            functions=functions, files=files, repo_root=self.repo_root
        )
        node_map: dict[int, CallNodeRow] = {}
        edges: list[CallEdgeRow] = []
        for info in functions:
            node_map.setdefault(
                info.goid.h128,
                CallNodeRow(
                    goid_h128=info.goid.h128,
                    language="python",
                    kind="method" if info.class_stack else "function",
                    arity=len(getattr(info.node.args, "args", []) or []),
                    is_public=info.is_public,
                    rel_path=info.rel_path,
                ),
            )
            module_name = context.module_name_map.get(info.rel_path) or _module_name_from_rel_path(
                info.rel_path
            )
            inputs = _CollectorInputs(
                module_functions=context.module_functions.get(info.rel_path, {}),
                class_methods=context.class_methods,
                module_name=module_name,
                global_functions=context.global_functions,
                global_class_methods=context.global_class_methods,
                import_resolver=context.import_resolvers.get(module_name),
                known_modules=context.known_modules,
            )
            collector = _CallCollector(
                function=info,
                inputs=inputs,
                edge_sink=edges,
            )
            collector.visit(info.node)

        nodes = [node_map[key] for key in sorted(node_map)]
        edges_sorted = sorted(
            edges,
            key=lambda edge: (
                edge.get("callsite_path") or "",
                edge.get("callsite_line") or -1,
                edge.get("callsite_col") or -1,
            ),
        )
        goids = [
            entry.goid
            for entry in sorted(functions, key=lambda entry: (entry.rel_path, entry.qualname))
        ]
        return CallGraphArtifacts(goids=goids, nodes=nodes, edges=edges_sorted)

    @staticmethod
    def write_artifacts(
        artifacts: CallGraphArtifacts,
        out_dir: Path,
    ) -> tuple[Path, Path]:
        """Write call node/edge Parquet datasets.

        Parameters
        ----------
        artifacts : CallGraphArtifacts
            Call graph artifacts container holding nodes and edges to write.
        out_dir : Path
            Output directory where the "graphs" subdirectory will be created.

        Returns
        -------
        tuple[Path, Path]
            Tuple containing paths to the written nodes file and edges file.
            Files are written as Parquet if available, with JSONL fallback.
        """
        graphs_dir = out_dir / "graphs"
        nodes_path = write_call_nodes(
            artifacts.nodes,
            graphs_dir / "call_nodes.parquet",
            jsonl_fallback=graphs_dir / "call_nodes.jsonl",
        )
        edges_path = write_call_edges(
            artifacts.edges,
            graphs_dir / "call_edges.parquet",
            jsonl_fallback=graphs_dir / "call_edges.jsonl",
        )
        return nodes_path, edges_path


class _CallCollector(ast.NodeVisitor):
    """Collect call expressions for a single function."""

    def __init__(
        self,
        *,
        function: FunctionInfo,
        inputs: _CollectorInputs,
        edge_sink: list[CallEdgeRow],
    ) -> None:
        self.function = function
        self._root = function.node
        self._module_funcs = inputs.module_functions
        self._class_methods = inputs.class_methods
        self._module_name = inputs.module_name
        self._global_functions = inputs.global_functions
        self._global_class_methods = inputs.global_class_methods
        self._imports = inputs.import_resolver or _ImportResolver.empty(inputs.module_name)
        self._known_modules = inputs.known_modules
        self._edges = edge_sink

    def visit_Call(self, node: ast.Call) -> None:
        """Visit a function call expression and record call graph edges.

        Parameters
        ----------
        node : ast.Call
            AST call node representing a function invocation. The callee
            expression is resolved to determine the target function.

        Notes
        -----
        This method resolves the callee function using symbol resolution
        heuristics and records a call edge in the graph. The edge includes
        callsite location, resolution strategy, and confidence score.
        """
        callee, resolved_via, call_kind = self._resolve_callee(node.func)
        evidence: dict[str, object] = {"expr": _safe_unparse(node.func), "resolver": resolved_via}
        edge: CallEdgeRow = {
            "caller_goid_h128": self.function.goid.h128,
            "callee_goid_h128": callee.goid.h128 if callee else None,
            "callsite_path": self.function.rel_path,
            "callsite_line": getattr(node, "lineno", None),
            "callsite_col": getattr(node, "col_offset", None),
            "language": "python",
            "kind": call_kind,
            "resolved_via": resolved_via,
            "confidence": _confidence_for_resolution(resolved_via),
            "evidence_json": evidence,
        }
        self._edges.append(edge)
        super().generic_visit(node)

    def generic_visit(self, node: ast.AST) -> None:
        """Visit AST nodes with selective traversal control.

        Extended Summary
        ----------------
        This method overrides the base class generic visitor to prevent traversal
        into nested function, async function, and class definitions. This ensures
        that call graph collection only processes calls within the current function
        scope and does not descend into nested scopes that would create incorrect
        call edges. The root function node itself is always visited to allow
        processing of its direct children.

        Parameters
        ----------
        node : ast.AST
            AST node being visited. If this is a nested function, async function,
            or class definition (and not the root function being analyzed), traversal
            stops to prevent incorrect call graph edges.

        Notes
        -----
        This method implements a selective traversal strategy where nested scopes
        are skipped to maintain accurate call graph boundaries. Only calls within
        the immediate function body are recorded, preventing false edges from
        nested function definitions. The root function node is always processed
        to allow its direct call expressions to be collected.
        """
        if node is not self._root and isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            return
        super().generic_visit(node)

    def _resolve_callee(
        self,
        func: ast.expr,
    ) -> tuple[FunctionInfo | None, str, str]:
        if isinstance(func, ast.Name):
            return self._resolve_name_call(func.id)
        if isinstance(func, ast.Attribute):
            chain = _attribute_chain(func)
            if chain:
                return self._resolve_attribute_chain(chain)
        return None, "unresolved", "attr"

    def _resolve_attribute(
        self,
        base_name: str,
        attr: str,
    ) -> tuple[FunctionInfo | None, str, str]:
        if base_name == "self" and self.function.class_stack:
            class_key = (self.function.rel_path, ".".join(self.function.class_stack))
            candidate = self._class_methods.get(class_key, {}).get(attr)
            if candidate:
                return candidate, "class-self", "method"
            return None, "class-self", "method"
        class_key = (self.function.rel_path, base_name)
        candidate = self._class_methods.get(class_key, {}).get(attr)
        if candidate:
            return candidate, "class-attr", "attr_call"
        return None, "unresolved", "attr_call"

    def _resolve_name_call(self, name: str) -> tuple[FunctionInfo | None, str, str]:
        local = self._module_funcs.get(name)
        if local:
            return local, "local-symbol", "direct"
        imported = self._imports.resolve_attr_alias(name)
        if imported is not None:
            module, target = imported
            candidate = self._lookup_module_function(module, target)
            if candidate:
                return candidate, "imported-function", "direct"
        return None, "unresolved", "direct"

    def _resolve_attribute_chain(
        self,
        names: list[str],
    ) -> tuple[FunctionInfo | None, str, str]:
        unresolved: tuple[FunctionInfo | None, str, str] = (None, "unresolved", "attr")
        if not names:
            return unresolved
        base = names[0]
        remainder = names[1:]
        resolved: tuple[FunctionInfo | None, str, str] = unresolved
        if base == "self":
            resolved = (
                self._resolve_attribute(base, remainder[0])
                if remainder
                else (None, "class-self", "method")
            )
        else:
            attr_alias = self._imports.resolve_attr_alias(base)
            if attr_alias is not None:
                module, target = attr_alias
                expanded = [target, *remainder]
                resolved = self._resolve_module_attribute(module, expanded, "imported-attr")
            else:
                module_alias = self._imports.resolve_module_alias(base)
                if module_alias is not None:
                    resolved = self._resolve_module_attribute(
                        module_alias, remainder, "imported-module"
                    )
                elif remainder:
                    local_candidate = self._resolve_attribute(base, remainder[0])
                    if local_candidate[0]:
                        resolved = local_candidate
                else:
                    module_candidate = self._lookup_module_function(self._module_name, base)
                    if module_candidate:
                        resolved = (module_candidate, "local-symbol", "attr_call")
        return resolved

    def _resolve_module_attribute(
        self,
        module_name: str,
        attr_chain: list[str],
        strategy: str,
    ) -> tuple[FunctionInfo | None, str, str]:
        if not attr_chain:
            return None, strategy, "attr"
        module_cursor = module_name
        idx = 0
        while idx < len(attr_chain):
            candidate_module = _normalize_module_path(module_cursor, attr_chain[idx])
            if candidate_module in self._known_modules:
                module_cursor = candidate_module
                idx += 1
            else:
                break
        remainder = attr_chain[idx:]
        if not remainder:
            return None, strategy, "attr"
        if len(remainder) == 1:
            func = self._lookup_module_function(module_cursor, remainder[0])
            if func:
                return func, strategy, "direct"
        class_chain = remainder[:-1]
        method_name = remainder[-1]
        if class_chain:
            candidate = self._lookup_module_method(module_cursor, class_chain, method_name)
            if candidate:
                return candidate, strategy, "method"
        # Fallback to treating last segment as function
        func = self._lookup_module_function(module_cursor, remainder[-1])
        if func:
            return func, strategy, "attr_call"
        return None, strategy, "attr"

    def _lookup_module_function(self, module_name: str, func_name: str) -> FunctionInfo | None:
        if not func_name:
            return None
        return self._global_functions.get(module_name, {}).get(func_name)

    def _lookup_module_method(
        self,
        module_name: str,
        class_chain: Iterable[str],
        method_name: str,
    ) -> FunctionInfo | None:
        class_key = (module_name, ".".join(class_chain))
        return self._global_class_methods.get(class_key, {}).get(method_name)


def _outer_name(expr: ast.Attribute) -> str | None:
    """Return the left-most identifier for a nested attribute.

    Parameters
    ----------
    expr : ast.Attribute
        AST attribute expression to extract the base name from.

    Returns
    -------
    str | None
        Left-most identifier name if the attribute chain starts with a Name
        node, or None if the chain structure is unexpected.
    """
    current: ast.AST = expr
    while isinstance(current, ast.Attribute):
        current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return None


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError, TypeError):  # pragma: no cover - ast.unparse fallback
        return node.__class__.__name__


def _confidence_for_resolution(strategy: str) -> float:
    return {
        "local-symbol": 0.95,
        "class-self": 0.9,
        "class-attr": 0.8,
        "imported-function": 0.85,
        "imported-module": 0.8,
        "imported-attr": 0.78,
    }.get(strategy, 0.25)


def _relative_path(repo_root: Path, file_path: Path) -> str:
    try:
        return file_path.relative_to(repo_root).as_posix()
    except ValueError:  # pragma: no cover - defensive
        return file_path.as_posix()


def _module_name_from_rel_path(rel_path: str) -> str:
    if not rel_path:
        return ""
    candidate = Path(rel_path)
    if candidate.suffix == ".py":
        candidate = candidate.with_suffix("")
    parts = list(candidate.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _normalize_module_path(base: str, addition: str) -> str:
    if not addition:
        return base
    if not base:
        return addition
    return f"{base}.{addition}"


def _resolve_relative_module(module_name: str, level: int, target: str | None) -> str:
    target_parts = [segment for segment in (target or "").split(".") if segment]
    if level <= 0:
        return ".".join(target_parts)
    parts = [segment for segment in module_name.split(".") if segment]
    prefix_len = max(len(parts) - level, 0)
    prefix = parts[:prefix_len]
    return ".".join([*prefix, *target_parts])


def _attribute_chain(expr: ast.AST) -> list[str] | None:
    if isinstance(expr, ast.Name):
        return [expr.id]
    if not isinstance(expr, ast.Attribute):
        return None
    parts: list[str] = [expr.attr]
    current = expr.value
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return list(reversed(parts))
    return None


__all__ = ["CallEdgeRow", "CallGraphArtifacts", "CallGraphBuilder", "CallNodeRow"]
