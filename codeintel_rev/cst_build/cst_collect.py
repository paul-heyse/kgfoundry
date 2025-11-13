# SPDX-License-Identifier: MIT
"""LibCST traversal utilities that emit normalized node records."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import blake2s
from pathlib import Path
from textwrap import shorten
from typing import Any, ClassVar, cast, final

import libcst as cst
from libcst import metadata as cst_metadata
from libcst.metadata import FullRepoManager
from libcst.metadata.base_provider import BaseMetadataProvider
from libcst.metadata.scope_provider import (
    ClassScope,
    ComprehensionScope,
    FunctionScope,
    GlobalScope,
)

from codeintel_rev.cst_build.cst_schema import (
    CollectorStats,
    DocSnippet,
    ImportMetadata,
    NodeRecord,
    Span,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class CollectorConfig:
    """Configurable knobs for CST extraction."""

    max_preview_chars: int = 120
    max_doc_chars: int = 240
    max_parent_depth: int = 8
    text_preview_skip_bytes: int = 2_000_000


@dataclass(slots=True, frozen=True)
class _CollectorStatsBuilder:
    """Mutable builder used while collecting CST stats."""

    files_indexed: int = 0
    node_rows: int = 0
    parse_errors: int = 0
    qname_hits: int = 0
    scope_resolved: int = 0

    def _replace(self, field_name: str, value: int) -> None:
        object.__setattr__(self, field_name, value)

    def increment_parse_errors(self, count: int = 1) -> None:
        """Increment the parse error counter.

        This method increments the parse error count, tracking the number of files
        that failed to parse during CST collection. Used for statistics and error
        reporting.

        Parameters
        ----------
        count : int, optional
            Number of parse errors to add (defaults to 1). Used when multiple
            errors occur in a single operation or when batching error counts.
        """
        self._replace("parse_errors", self.parse_errors + count)

    def set_node_rows(self, count: int) -> None:
        """Set the total number of node rows collected.

        This method sets the node_rows counter to the specified count, representing
        the total number of node records emitted during CST collection. Used to
        track collection output size.

        Parameters
        ----------
        count : int
            Total number of node records collected. Must be non-negative. This count
            represents the number of NodeRecord objects emitted for the processed
            files.
        """
        self._replace("node_rows", count)

    def increment_qname_hits(self) -> None:
        """Increment the qualified name resolution hit counter.

        This method increments the qname_hits counter, tracking the number of nodes
        for which qualified names were successfully resolved. Used to measure the
        effectiveness of qualified name resolution during CST collection.

        Notes
        -----
        Qualified names (qnames) are fully qualified identifiers like "module.Class.method".
        This counter tracks how many nodes had their qnames successfully resolved,
        providing a metric for scope resolution quality.
        """
        self._replace("qname_hits", self.qname_hits + 1)

    def increment_scope_resolved(self) -> None:
        """Increment the scope resolution hit counter.

        This method increments the scope_resolved counter, tracking the number of
        nodes for which scope information was successfully resolved. Used to measure
        the effectiveness of scope resolution during CST collection.

        Notes
        -----
        Scope resolution identifies whether a node belongs to Global, Class, Function,
        or Comprehension scope. This counter tracks how many nodes had their scope
        successfully resolved, providing a metric for scope analysis quality.
        """
        self._replace("scope_resolved", self.scope_resolved + 1)

    def snapshot(self) -> CollectorStats:
        """Return an immutable CollectorStats instance.

        Returns
        -------
        CollectorStats
            Frozen stats object ready for serialization.
        """
        return CollectorStats(
            files_indexed=self.files_indexed,
            node_rows=self.node_rows,
            parse_errors=self.parse_errors,
            qname_hits=self.qname_hits,
            scope_resolved=self.scope_resolved,
        )


@final
class CSTCollector:
    """Collect LibCST node records for a repository."""

    _PROVIDERS: ClassVar[tuple[type[BaseMetadataProvider], ...]] = (
        cst_metadata.ParentNodeProvider,
        cst_metadata.PositionProvider,
        cst_metadata.ScopeProvider,
        cst_metadata.QualifiedNameProvider,
    )

    def __init__(
        self,
        root: Path,
        files: Sequence[Path] | None = None,
        *,
        config: CollectorConfig | None = None,
        use_full_repo_manager: bool = True,
    ) -> None:
        self._root = root.resolve()
        self._config = config or CollectorConfig()
        self._manager: FullRepoManager | None = None
        if use_full_repo_manager:
            self._manager = self._build_repo_manager(files)

    def _build_repo_manager(self, files: Sequence[Path] | None) -> FullRepoManager | None:
        """Build a repo-scoped metadata manager when a file list is available.

        This method creates a FullRepoManager instance for repository-wide metadata
        collection when a file list is provided. The manager is configured with
        LibCST metadata providers and supports pyproject.toml parsing. If file
        list is None or manager creation fails, returns None gracefully.

        Parameters
        ----------
        files : Sequence[Path] | None
            Sequence of file paths to include in the repository manager. If None
            or empty, returns None without creating a manager. The paths are
            converted to relative paths from the collector's root directory.

        Returns
        -------
        FullRepoManager | None
            Configured FullRepoManager instance if files are provided and manager
            creation succeeds, otherwise None. Returns None when files is None/empty
            or when manager creation fails (OSError, ValueError).
        """
        if not files:
            return None
        try:
            rel_paths = [self._relative_path(file) for file in files]
            return FullRepoManager(
                str(self._root),
                rel_paths,
                providers=self._PROVIDERS,
                use_pyproject_toml=True,
            )
        except (OSError, ValueError) as exc:  # pragma: no cover - defensive fallback
            logger.debug("FullRepoManager unavailable: %s", exc)
            return None

    def collect_file(self, path: Path) -> tuple[list[NodeRecord], CollectorStats]:
        """Parse ``path`` and return serialized node records.

        Parameters
        ----------
        path : Path
            File system path to the Python source file to parse.

        Returns
        -------
        tuple[list[NodeRecord], CollectorStats]
            Tuple containing the list of parsed node records and collection statistics.
        """
        stats_builder = _CollectorStatsBuilder(files_indexed=1)
        rel_path = self._relative_path(path)
        try:
            file_size = path.stat().st_size
            code = path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - hardened path
            stats_builder.increment_parse_errors()
            return [_build_parse_error_node(rel_path, str(exc))], stats_builder.snapshot()
        wrapper = self._wrap_module(rel_path, code, stats_builder)
        if wrapper is None:
            return (
                [_build_parse_error_node(rel_path, "Failed to build metadata wrapper.")],
                stats_builder.snapshot(),
            )
        nodes = list(
            self._emit_nodes(
                rel_path=rel_path,
                code=code,
                wrapper=wrapper,
                skip_preview=file_size > self._config.text_preview_skip_bytes,
                stats_builder=stats_builder,
            )
        )
        stats_builder.set_node_rows(len(nodes))
        return nodes, stats_builder.snapshot()

    def _wrap_module(
        self,
        rel_path: str,
        code: str,
        stats_builder: _CollectorStatsBuilder,
    ) -> cst_metadata.MetadataWrapper | None:
        if self._manager is not None:
            try:
                return self._manager.get_metadata_wrapper_for_path(rel_path)
            except KeyError:
                logger.debug(
                    "FullRepoManager missing %s; falling back to per-file parsing", rel_path
                )
            except cst.ParserSyntaxError as exc:
                logger.warning(
                    "FullRepoManager failed to parse %s (%s); retrying with single-file parser",
                    rel_path,
                    exc,
                )
        try:
            module = cst.parse_module(code)
            return cst_metadata.MetadataWrapper(module, unsafe_skip_copy=True)
        except cst.ParserSyntaxError as exc:
            logger.warning("LibCST failed to parse %s: %s", rel_path, exc)
            stats_builder.increment_parse_errors()
            return None

    def _emit_nodes(
        self,
        *,
        rel_path: str,
        code: str,
        wrapper: cst_metadata.MetadataWrapper,
        skip_preview: bool,
        stats_builder: _CollectorStatsBuilder,
    ) -> Iterable[NodeRecord]:
        """Yield NodeRecord rows for ``rel_path``.

        This method traverses the LibCST AST and yields NodeRecord instances for
        each node that should be emitted (functions, classes, assignments, etc.).
        The method resolves metadata (parent maps, positions, scopes, qualified
        names) and builds serialized node records matching the schema contract.

        Parameters
        ----------
        rel_path : str
            Relative file path from the repository root. Used to identify the
            source file in node records and for module name extraction.
        code : str
            Source code content of the file. Used to extract text previews for
            nodes when skip_preview is False. The code is already parsed into
            the CST module in wrapper.
        wrapper : cst_metadata.MetadataWrapper
            LibCST metadata wrapper containing the parsed module and resolved
            metadata providers (parent maps, positions, scopes, qualified names).
            Used to extract node metadata during traversal.
        skip_preview : bool
            Flag indicating whether to skip text preview extraction for nodes.
            When True, text_preview is set to None for all nodes, reducing
            memory usage and serialization size.
        stats_builder : _CollectorStatsBuilder
            Statistics builder instance for tracking collection metrics (node
            counts, parse errors, etc.). Updated during node emission.

        Yields
        ------
        NodeRecord
            Serialized node record matching the schema contract. Each record
            contains node metadata (kind, name, span, parents, scope, qnames)
            and optional text preview. Records are yielded in depth-first
            traversal order.
        """
        parent_map = wrapper.resolve(cst_metadata.ParentNodeProvider)
        position_map = wrapper.resolve(cst_metadata.PositionProvider)
        scope_map = wrapper.resolve(cst_metadata.ScopeProvider)
        qname_map = wrapper.resolve(cst_metadata.QualifiedNameProvider)
        module = wrapper.module
        module_doc = _extract_module_doc(module, self._config.max_doc_chars)
        module_name = _module_name_from_path(rel_path)
        stack: list[cst.CSTNode] = [module]
        while stack:
            node = stack.pop()
            stack.extend(reversed(list(node.children)))
            if not _should_emit(node):
                continue
            span = _resolve_span(position_map, node)
            parents = _parent_chain(node, parent_map, self._config.max_parent_depth)
            qname_entries = _qualified_name_entries(qname_map, node)
            qnames = _normalize_qnames(qname_entries, module_name)
            scope_label = _scope(scope_map, node)
            if qnames:
                stats_builder.increment_qname_hits()
            if scope_label:
                stats_builder.increment_scope_resolved()
            record = NodeRecord(
                path=rel_path,
                node_id=_node_id(rel_path, node.__class__.__name__, _node_name(node), span),
                kind=node.__class__.__name__,
                name=_node_name(node),
                span=span,
                text_preview=_preview_text(
                    code,
                    span,
                    self._config.max_preview_chars,
                    skip=skip_preview,
                ),
                parents=parents,
                scope=scope_label,
                qnames=qnames,
                doc=_doc_snippet(node, module_doc, self._config.max_doc_chars),
                is_public=_is_public(node, parents),
                decorators=_decorators(module, node),
                call_target_qnames=_call_targets(qname_map, module_name, node),
                ann=_annotation(module, node),
                imports=_import_metadata(module, node),
            )
            yield record

    def _relative_path(self, path: Path) -> str:
        try:
            rel = path.resolve().relative_to(self._root)
        except ValueError:
            rel = path.resolve()
        return rel.as_posix()


def index_file(path: Path) -> list[NodeRecord]:
    """Index a single file and return node records.

    Convenience helper used by tests to index a single file.

    Parameters
    ----------
    path : Path
        File system path to the Python source file to index.

    Returns
    -------
    list[NodeRecord]
        List of parsed node records from the file.
    """
    collector = CSTCollector(path.parent, [path], use_full_repo_manager=False)
    rows, _ = collector.collect_file(path)
    return rows


def _should_emit(node: cst.CSTNode) -> bool:
    interesting = (
        cst.Module,
        cst.FunctionDef,
        cst.ClassDef,
        cst.Assign,
        cst.AnnAssign,
        cst.AugAssign,
        cst.Import,
        cst.ImportFrom,
        cst.Call,
        cst.Attribute,
        cst.Name,
        cst.Return,
        cst.Raise,
        cst.If,
        cst.Else,
        cst.For,
        cst.While,
        cst.With,
        cst.Try,
        cst.ExceptHandler,
        cst.Match,
    )
    return isinstance(node, interesting)


def _resolve_span(position_map: Mapping[cst.CSTNode, object], node: cst.CSTNode) -> Span:
    position = cast("Any", position_map[node])
    return Span(
        start_line=position.start.line,
        start_col=position.start.column,
        end_line=position.end.line,
        end_col=position.end.column,
    )


def _node_id(path: str, kind: str, name: str | None, span: Span) -> str:
    digest = blake2s(digest_size=16)
    digest.update(f"{path}:{span.start_line}:{span.start_col}:{kind}:{name or ''}".encode())
    return digest.hexdigest()


def _node_name(node: cst.CSTNode) -> str | None:
    return (
        _definition_or_class_name(node)
        or _assign_target_name(node)
        or _annassign_target_name(node)
        or _attribute_or_name(node)
        or _call_target_name(node)
        or _import_alias_name(node)
    )


def _definition_or_class_name(node: cst.CSTNode) -> str | None:
    if isinstance(node, (cst.FunctionDef, cst.ClassDef)):
        return node.name.value
    return None


def _assign_target_name(node: cst.CSTNode) -> str | None:
    if isinstance(node, cst.Assign):
        target = node.targets[0].target if node.targets else None
        if isinstance(target, cst.Name):
            return target.value
    return None


def _annassign_target_name(node: cst.CSTNode) -> str | None:
    if isinstance(node, cst.AnnAssign) and isinstance(node.target, cst.Name):
        return node.target.value
    return None


def _attribute_or_name(node: cst.CSTNode) -> str | None:
    if isinstance(node, cst.Attribute):
        return node.attr.value
    if isinstance(node, cst.Name):
        return node.value
    return None


def _call_target_name(node: cst.CSTNode) -> str | None:
    if isinstance(node, cst.Call):
        return _node_name(node.func)
    return None


def _import_alias_name(node: cst.CSTNode) -> str | None:
    if isinstance(node, (cst.Import, cst.ImportFrom)):
        alias = node.names[0].name if isinstance(node.names, list) and node.names else None  # type: ignore[arg-type]
        if isinstance(alias, cst.Name):
            return alias.value
    return None


def _parent_chain(
    node: cst.CSTNode,
    parent_map: Mapping[cst.CSTNode, cst.CSTNode],
    depth: int,
) -> list[str]:
    chain: list[str] = []
    current = node
    hops = 0
    while hops < depth:
        parent = parent_map.get(current)
        if parent is None:
            break
        label = parent.__class__.__name__
        parent_name = _node_name(parent)
        chain.append(f"{label}:{parent_name}" if parent_name else label)
        current = parent
        hops += 1
    chain.reverse()
    current_label = (
        f"{node.__class__.__name__}:{_node_name(node)}"
        if _node_name(node)
        else node.__class__.__name__
    )
    chain.append(current_label)
    if not chain:
        return ["Module", current_label]
    return chain


def _scope(scope_map: Mapping[cst.CSTNode, object], node: cst.CSTNode) -> str | None:
    try:
        scope = _resolve_lazy(scope_map[node])
    except KeyError:
        return None

    if isinstance(scope, GlobalScope):
        return "Global"
    if isinstance(scope, ClassScope):
        return "Class"
    if isinstance(scope, FunctionScope):
        return "Function"
    if isinstance(scope, ComprehensionScope):
        return "Comprehension"
    return scope.__class__.__name__


def _extract_module_doc(module: cst.Module, max_chars: int) -> str | None:
    doc = module.get_docstring()
    if not doc:
        return None
    return _summarize(doc, max_chars)


def _summarize(text: str, max_chars: int) -> str:
    if not text:
        return ""
    summary = text.strip().splitlines()[0].strip()
    return shorten(summary, max_chars, placeholder="...")


def _doc_snippet(node: cst.CSTNode, module_doc: str | None, max_chars: int) -> DocSnippet | None:
    if isinstance(node, cst.Module):
        return DocSnippet(module=module_doc) if module_doc else None
    if isinstance(node, (cst.FunctionDef, cst.ClassDef)):
        doc = node.get_docstring()
        if not doc:
            return None
        return DocSnippet(def_=_summarize(doc, max_chars))
    return None


def _preview_text(code: str, span: Span, max_chars: int, *, skip: bool) -> str | None:
    if skip:
        return None
    lines = code.splitlines()
    index = max(0, min(len(lines) - 1, span.start_line - 1))
    return shorten(lines[index].strip(), max_chars, placeholder="...")


def _decorators(module: cst.Module, node: cst.CSTNode) -> list[str] | None:
    decorators: list[str] = []
    decorator_nodes: Sequence[cst.Decorator] = ()
    if isinstance(node, (cst.FunctionDef, cst.ClassDef)):
        decorator_nodes = node.decorators
    nodes_seq = list(decorator_nodes)
    if not nodes_seq:
        return None
    for deco in nodes_seq:
        try:
            decorators.append(module.code_for_node(deco.decorator))
        except ValueError:
            logger.debug("Failed to render decorator %s", deco)
    return decorators or None


def _call_targets(
    qname_map: Mapping[cst.CSTNode, object],
    module_name: str,
    node: cst.CSTNode,
) -> list[str] | None:
    if not isinstance(node, cst.Call):
        return None
    entries = _qualified_name_entries(qname_map, node.func)
    targets = _normalize_qnames(entries, module_name)
    return targets or None


def _annotation(module: cst.Module, node: cst.CSTNode) -> str | None:
    if isinstance(node, cst.FunctionDef):
        if node.returns is None:
            return None
        try:
            return module.code_for_node(node.returns.annotation)
        except ValueError:
            return None
    if isinstance(node, cst.AnnAssign) and node.annotation is not None:
        try:
            return module.code_for_node(node.annotation.annotation)
        except ValueError:
            return None
    return None


def _import_metadata(module: cst.Module, node: cst.CSTNode) -> ImportMetadata | None:
    if isinstance(node, cst.Import):
        names: list[str] = []
        aliases: dict[str, str] = {}
        for alias in node.names:
            rendered = _normalize_alias(module, alias)
            if rendered is None:
                continue
            ident, alias_name = rendered
            names.append(ident)
            if alias_name:
                aliases[ident] = alias_name
        return ImportMetadata(module=None, names=names, aliases=aliases, is_star=False, level=0)
    if isinstance(node, cst.ImportFrom):
        module_name = _normalize_module_expr(module, node.module)
        names: list[str] = []
        aliases: dict[str, str] = {}
        is_star = isinstance(node.names, cst.ImportStar)
        if not is_star and isinstance(node.names, list):
            for alias in node.names:
                rendered = _normalize_alias(module, alias)
                if rendered is None:
                    continue
                ident, alias_name = rendered
                names.append(ident)
                if alias_name:
                    aliases[ident] = alias_name
        level = len(node.relative) if node.relative else 0
        return ImportMetadata(
            module=module_name,
            names=names,
            aliases=aliases,
            is_star=is_star,
            level=level,
        )
    return None


def _normalize_alias(
    module: cst.Module,
    alias: cst.ImportAlias,
) -> tuple[str, str | None] | None:
    try:
        ident = module.code_for_node(alias.name)
    except ValueError:
        logger.debug("Failed to render import alias %s", alias)
        return None
    alias_name = (
        alias.asname.name.value
        if alias.asname and isinstance(alias.asname.name, cst.Name)
        else None
    )
    return ident, alias_name


def _normalize_module_expr(module: cst.Module, expr: cst.BaseExpression | None) -> str | None:
    if expr is None:
        return None
    try:
        return module.code_for_node(expr)
    except ValueError:
        logger.debug("Failed to render module for import-from %s", expr)
        return None


def _is_public(node: cst.CSTNode, parents: list[str]) -> bool | None:
    name = _node_name(node)
    if not name:
        return None
    top_level = parents and parents[0].startswith("Module")
    if top_level:
        return not name.startswith("_")
    return None


def _resolve_lazy(value: object) -> object:
    if callable(value):
        try:
            return value()
        except (TypeError, AttributeError):  # pragma: no cover - defensive
            return value
    return value


def _qualified_name_entries(
    qname_map: Mapping[cst.CSTNode, object], node: cst.CSTNode
) -> list[tuple[str, str]]:
    try:
        qnames = _resolve_lazy(qname_map[node])
    except KeyError:
        return []
    entries: list[tuple[str, str]] = []
    if not isinstance(qnames, Iterable):
        return entries
    for qname in qnames:
        name = getattr(qname, "name", None)
        source_attr = getattr(qname, "source", None)
        if name is None or source_attr is None:
            continue
        entries.append((name, getattr(source_attr, "name", str(source_attr))))
    return entries


def _normalize_qnames(entries: list[tuple[str, str]], module_name: str) -> list[str]:
    names: set[str] = set()
    for raw, source in entries:
        names.add(raw)
        if module_name and source == "LOCAL" and not raw.startswith(f"{module_name}."):
            names.add(f"{module_name}.{raw}")
    return sorted(names)


def _module_name_from_path(rel_path: str) -> str:
    """Convert a relative file path into its dotted module name.

    This function converts a relative file path (e.g., "src/pkg/module.py") into
    a dotted module name (e.g., "src.pkg.module"). It handles Windows path
    separators, strips .py extension, handles __init__.py files, and converts
    path separators to dots.

    Parameters
    ----------
    rel_path : str
        Relative file path from repository root (e.g., "src/pkg/module.py").
        Windows backslashes are normalized to forward slashes. The path may
        include .py extension and __init__.py files.

    Returns
    -------
    str
        Dotted module name (e.g., "src.pkg.module"). Empty string for top-level
        modules or when rel_path is empty. Path separators are converted to dots,
        .py extension is stripped, and __init__ is removed from package paths.
    """
    normalized = rel_path.replace("\\", "/")
    if normalized.endswith(".py"):
        normalized = normalized[:-3]
    if normalized.endswith("/__init__"):
        normalized = normalized[: -len("/__init__")]
    normalized = normalized.strip("/")
    return normalized.replace("/", ".")


def _build_parse_error_node(rel_path: str, message: str) -> NodeRecord:
    """Return a placeholder row describing a parse failure.

    This function creates a synthetic NodeRecord for files that failed to parse.
    The record captures the parse error message and provides a placeholder entry
    in the node collection output, enabling downstream tools to identify and
    report parse failures.

    Parameters
    ----------
    rel_path : str
        Relative file path from repository root where the parse error occurred.
        Used to identify the problematic file in the node record.
    message : str
        Parse error message describing the failure. The message is truncated to
        240 characters and included in the node record's doc snippet and errors
        list. Used for debugging and error reporting.

    Returns
    -------
    NodeRecord
        Synthetic node record with kind="ParseError" capturing the parse issue.
        The record includes the rel_path, a synthetic node_id, an empty span
        (1,0,1,0), the error message in doc and errors fields, and minimal
        metadata (parents=["Module"], scope="Global", empty qnames).
    """
    return NodeRecord(
        path=rel_path,
        node_id=f"{rel_path}:0:0:ParseError",
        kind="ParseError",
        name=None,
        span=Span(1, 0, 1, 0),
        text_preview=None,
        parents=["Module"],
        scope="Global",
        qnames=[],
        doc=DocSnippet(module=shorten(message, 240)) if message else None,
        errors=[message],
    )
