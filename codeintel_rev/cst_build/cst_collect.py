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
    """Configurable knobs for CST extraction.

    Attributes
    ----------
    max_preview_chars : int, optional
        Maximum number of characters to include in text previews. Longer
        previews are truncated. Defaults to 120.
    max_doc_chars : int, optional
        Maximum number of characters to include in docstring snippets. Longer
        docstrings are truncated. Defaults to 240.
    max_parent_depth : int, optional
        Maximum depth of parent node hierarchy to track. Deeper hierarchies
        are truncated. Must be positive. Defaults to 8.
    text_preview_skip_bytes : int, optional
        Skip text preview generation for nodes larger than this size (in bytes).
        Used to avoid memory issues with very large nodes. Defaults to 2_000_000.
    """

    max_preview_chars: int = 120
    max_doc_chars: int = 240
    max_parent_depth: int = 8
    text_preview_skip_bytes: int = 2_000_000


class _CollectorStatsBuilder:
    """Mutable builder used while collecting CST stats."""

    __slots__ = (
        "files_indexed",
        "node_rows",
        "parse_errors",
        "qname_hits",
        "scope_resolved",
    )

    def __init__(
        self,
        *,
        files_indexed: int = 0,
        node_rows: int = 0,
        parse_errors: int = 0,
        qname_hits: int = 0,
        scope_resolved: int = 0,
    ) -> None:
        """Initialize stats builder with counters.

        Parameters
        ----------
        files_indexed : int, optional
            Initial count of files indexed (default: 0).
        node_rows : int, optional
            Initial count of node rows collected (default: 0).
        parse_errors : int, optional
            Initial count of parse errors (default: 0).
        qname_hits : int, optional
            Initial count of qualified name resolution hits (default: 0).
        scope_resolved : int, optional
            Initial count of scope resolution hits (default: 0).
        """
        self.files_indexed = files_indexed
        self.node_rows = node_rows
        self.parse_errors = parse_errors
        self.qname_hits = qname_hits
        self.scope_resolved = scope_resolved

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
        self.parse_errors += count

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
        self.node_rows = count

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
        self.qname_hits += 1

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
        self.scope_resolved += 1

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
        """Initialize CST collector for a repository.

        Parameters
        ----------
        root : Path
            Root directory of the repository to collect from.
        files : Sequence[Path] | None, optional
            Optional list of specific files to process. If None, all Python files
            under root are discovered.
        config : CollectorConfig | None, optional
            Collector configuration. If None, uses default config.
        use_full_repo_manager : bool, optional
            Whether to use FullRepoManager for metadata providers (default: True).
        """
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
        """Wrap parsed module code with LibCST metadata providers.

        This method creates a MetadataWrapper for a module, enabling access to
        metadata providers (parent maps, positions, scopes, qualified names).
        The method attempts to use FullRepoManager if available, falling back
        to per-file parsing if the manager is unavailable or fails. Parse errors
        are tracked in stats_builder.

        Parameters
        ----------
        rel_path : str
            Relative file path from repository root. Used to look up the module
            in FullRepoManager if available.
        code : str
            Source code content of the file. Used for per-file parsing fallback
            when FullRepoManager is unavailable.
        stats_builder : _CollectorStatsBuilder
            Statistics builder for tracking parse errors. Incremented when
            parsing fails.

        Returns
        -------
        cst_metadata.MetadataWrapper | None
            Metadata wrapper containing parsed module and resolved metadata
            providers, or None if parsing fails. The wrapper enables access
            to parent maps, positions, scopes, and qualified names.

        Notes
        -----
        Module wrapping enables metadata resolution by providing access to LibCST
        metadata providers. FullRepoManager provides repository-wide metadata
        resolution, while per-file parsing provides fallback when the manager
        is unavailable. Parse errors are tracked but don't prevent partial
        collection from proceeding.
        """
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
        """Convert absolute path to relative path from collector root.

        This method computes the relative path of a file from the collector's
        root directory, handling cases where the path is outside the root
        (returning absolute path as fallback). The path is normalized to use
        forward slashes for consistency across platforms.

        Parameters
        ----------
        path : Path
            File path to convert to relative form. The path is resolved to
            absolute form before computing relative path.

        Returns
        -------
        str
            Relative path string using forward slashes. If path is within root,
            returns relative path from root. If path is outside root, returns
            absolute path as fallback. Path separators are normalized to forward
            slashes for cross-platform compatibility.

        Notes
        -----
        Relative path computation enables consistent file identification across
        different execution environments. The method handles edge cases where
        files are outside the collector root by returning absolute paths, ensuring
        all files can be identified even when path relationships are unexpected.
        """
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
    """Determine whether a CST node should be emitted as a NodeRecord.

    This function checks if a node type is interesting enough to emit as a
    NodeRecord. Only nodes that represent significant code structures (modules,
    functions, classes, assignments, imports, calls, control flow) are emitted,
    filtering out less significant nodes like expressions, literals, and operators.

    Parameters
    ----------
    node : cst.CSTNode
        LibCST node to check for emission eligibility. The node's type is
        checked against a whitelist of interesting node types.

    Returns
    -------
    bool
        True if the node should be emitted as a NodeRecord, False otherwise.
        Only nodes representing significant code structures (definitions, assignments,
        imports, calls, control flow) return True.

    Notes
    -----
    Node filtering reduces collection output size by focusing on semantically
    significant nodes. This improves indexing efficiency and reduces storage
    requirements while preserving information needed for code navigation and
    search. The whitelist includes nodes that represent code structure, not
    just syntax.
    """
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
    """Extract source code span (line/column range) for a CST node.

    This function retrieves position metadata for a node from the position map
    and converts it to a Span object with start/end line and column coordinates.
    The span represents the exact location of the node in the source file.

    Parameters
    ----------
    position_map : Mapping[cst.CSTNode, object]
        Position metadata map from LibCST PositionProvider. Maps nodes to
        position objects containing start and end coordinates.
    node : cst.CSTNode
        CST node to extract span for. The node must be present in position_map
        for span extraction to succeed.

    Returns
    -------
    Span
        Span object containing start_line, start_col, end_line, and end_col
        coordinates extracted from position metadata. The span represents the
        exact source location of the node.

    Notes
    -----
    Span resolution enables precise source location tracking for nodes, enabling
    navigation, highlighting, and error reporting. The function extracts position
    metadata from LibCST's PositionProvider, which provides accurate line/column
    coordinates for all nodes in the AST.
    """
    position = cast("Any", position_map[node])
    return Span(
        start_line=position.start.line,
        start_col=position.start.column,
        end_line=position.end.line,
        end_col=position.end.column,
    )


def _node_id(path: str, kind: str, name: str | None, span: Span) -> str:
    """Generate a unique identifier for a CST node.

    This function creates a deterministic node identifier by hashing the node's
    path, span coordinates, kind, and name. The identifier is unique within a
    repository and enables stable node identification across collection runs.

    Parameters
    ----------
    path : str
        Relative file path from repository root. Included in hash to ensure
        uniqueness across files.
    kind : str
        Node type name (e.g., "FunctionDef", "ClassDef"). Included in hash
        to distinguish nodes of different types at the same location.
    name : str | None
        Node name (function/class/variable name) or None. Included in hash
        to distinguish nodes with the same type and location but different names.
    span : Span
        Source code span (start_line, start_col, end_line, end_col). Included
        in hash to ensure uniqueness for nodes at different locations.

    Returns
    -------
    str
        Hexadecimal hash string (32 characters) uniquely identifying the node.
        The hash is deterministic, producing the same ID for the same node
        across collection runs.

    Notes
    -----
    Node ID generation enables stable node identification for indexing and
    navigation. The hash combines multiple node attributes to ensure uniqueness
    while remaining deterministic. This enables consistent node references across
    different collection runs and downstream tools.
    """
    digest = blake2s(digest_size=16)
    digest.update(f"{path}:{span.start_line}:{span.start_col}:{kind}:{name or ''}".encode())
    return digest.hexdigest()


def _node_name(node: cst.CSTNode) -> str | None:
    """Extract the name identifier from a CST node if available.

    This function attempts to extract a name from various node types by trying
    multiple extraction strategies: definition names (FunctionDef, ClassDef),
    assignment targets (Assign, AnnAssign), attribute/name nodes, call targets,
    and import aliases. Returns None if no name can be extracted.

    Parameters
    ----------
    node : cst.CSTNode
        CST node to extract name from. The function tries multiple strategies
        to find a name depending on node type.

    Returns
    -------
    str | None
        Extracted name string if available, or None if the node has no extractable
        name. Names are extracted from node attributes (e.g., node.name.value
        for FunctionDef) or by recursively calling _node_name on child nodes.

    Notes
    -----
    Name extraction enables node identification and navigation by providing
    human-readable names for nodes. The function handles multiple node types
    by trying different extraction strategies, ensuring names are extracted
    whenever possible. This supports code navigation, search, and symbol
    resolution features.
    """
    return (
        _definition_or_class_name(node)
        or _assign_target_name(node)
        or _annassign_target_name(node)
        or _attribute_or_name(node)
        or _call_target_name(node)
        or _import_alias_name(node)
    )


def _definition_or_class_name(node: cst.CSTNode) -> str | None:
    """Extract name from FunctionDef or ClassDef nodes.

    This function extracts the name attribute from function or class definition
    nodes, returning the identifier string. For other node types, returns None.

    Parameters
    ----------
    node : cst.CSTNode
        CST node to check for function or class definition. If the node is a
        FunctionDef or ClassDef, its name is extracted.

    Returns
    -------
    str | None
        Function or class name string if node is FunctionDef or ClassDef,
        otherwise None. The name is extracted from node.name.value.

    Notes
    -----
    Definition name extraction is the primary strategy for identifying function
    and class nodes. These nodes always have names, making them easy to identify
    and navigate. The function is used as part of a fallback chain in _node_name
    to extract names from various node types.
    """
    if isinstance(node, (cst.FunctionDef, cst.ClassDef)):
        return node.name.value
    return None


def _assign_target_name(node: cst.CSTNode) -> str | None:
    """Extract target name from Assign node.

    This function extracts the name of the assignment target from an Assign
    node, handling simple name assignments (e.g., `x = value`). For other node
    types or complex assignment targets, returns None.

    Parameters
    ----------
    node : cst.CSTNode
        CST node to check for assignment. If the node is an Assign with a
        simple Name target, the name is extracted.

    Returns
    -------
    str | None
        Assignment target name string if node is Assign with Name target,
        otherwise None. The name is extracted from the first assignment target.

    Notes
    -----
    Assignment target extraction enables identification of variable assignments,
    supporting code navigation and symbol resolution. The function handles only
    simple name assignments (not tuple unpacking or attribute assignments) to
    ensure reliable name extraction. Used as part of a fallback chain in
    _node_name to extract names from various node types.
    """
    if isinstance(node, cst.Assign):
        target = node.targets[0].target if node.targets else None
        if isinstance(target, cst.Name):
            return target.value
    return None


def _annassign_target_name(node: cst.CSTNode) -> str | None:
    """Extract target name from AnnAssign node.

    This function extracts the name of the annotated assignment target from an
    AnnAssign node (e.g., `x: int = value`). For other node types, returns None.

    Parameters
    ----------
    node : cst.CSTNode
        CST node to check for annotated assignment. If the node is an AnnAssign
        with a Name target, the name is extracted.

    Returns
    -------
    str | None
        Annotated assignment target name string if node is AnnAssign with Name
        target, otherwise None. The name is extracted from node.target.value.

    Notes
    -----
    Annotated assignment extraction enables identification of type-annotated
    variable assignments, supporting code navigation and type-aware symbol
    resolution. The function handles only simple name targets (not attribute
    assignments) to ensure reliable name extraction. Used as part of a fallback
    chain in _node_name to extract names from various node types.
    """
    if isinstance(node, cst.AnnAssign) and isinstance(node.target, cst.Name):
        return node.target.value
    return None


def _attribute_or_name(node: cst.CSTNode) -> str | None:
    """Extract name from Attribute or Name nodes.

    This function extracts the identifier from Attribute nodes (attribute name)
    or Name nodes (variable name). For other node types, returns None.

    Parameters
    ----------
    node : cst.CSTNode
        CST node to check for attribute or name. If the node is an Attribute,
        the attribute name is extracted. If the node is a Name, the name value
        is extracted.

    Returns
    -------
    str | None
        Attribute name (for Attribute nodes) or name value (for Name nodes),
        otherwise None. For Attribute nodes, returns node.attr.value. For Name
        nodes, returns node.value.

    Notes
    -----
    Attribute and name extraction enables identification of attribute accesses
    and variable references, supporting code navigation and symbol resolution.
    The function handles both attribute accesses (obj.attr) and simple names
    (var), making it useful for extracting identifiers from various contexts.
    Used as part of a fallback chain in _node_name to extract names from
    various node types.
    """
    if isinstance(node, cst.Attribute):
        return node.attr.value
    if isinstance(node, cst.Name):
        return node.value
    return None


def _call_target_name(node: cst.CSTNode) -> str | None:
    """Extract function name from Call node.

    This function extracts the name of the function being called from a Call
    node by recursively calling _node_name on the function expression. For other
    node types, returns None.

    Parameters
    ----------
    node : cst.CSTNode
        CST node to check for function call. If the node is a Call, the function
        name is extracted from node.func using _node_name.

    Returns
    -------
    str | None
        Function name string if node is Call and function name can be extracted,
        otherwise None. The name is extracted recursively from the function
        expression (which may be a Name, Attribute, etc.).

    Notes
    -----
    Call target extraction enables identification of function calls, supporting
    code navigation and call graph construction. The function handles various
    call target types (simple names, attributes, etc.) by recursively extracting
    names. Used as part of a fallback chain in _node_name to extract names from
    various node types.
    """
    if isinstance(node, cst.Call):
        return _node_name(node.func)
    return None


def _import_alias_name(node: cst.CSTNode) -> str | None:
    """Extract imported name from Import or ImportFrom node.

    This function extracts the imported identifier name from Import or ImportFrom
    nodes, handling both regular imports and import aliases (as clauses). For
    other node types, returns None.

    Parameters
    ----------
    node : cst.CSTNode
        CST node to check for import statement. If the node is Import or ImportFrom,
        the imported name (or alias) is extracted from the first import alias.

    Returns
    -------
    str | None
        Imported name string if node is Import/ImportFrom and name can be extracted,
        otherwise None. Returns the alias name if present (import x as y -> "y"),
        otherwise returns the original name (import x -> "x").

    Notes
    -----
    Import alias extraction enables identification of imported identifiers,
    supporting code navigation and import resolution. The function handles both
    regular imports and aliased imports, extracting the identifier that is
    actually available in the local scope. Used as part of a fallback chain in
    _node_name to extract names from various node types.
    """
    alias: cst.ImportAlias | None = None
    if isinstance(node, cst.Import):
        alias = node.names[0] if node.names else None
    elif isinstance(node, cst.ImportFrom):
        names = node.names
        if isinstance(names, Sequence):
            alias = names[0] if names else None
    if alias is None:
        return None
    target: cst.BaseExpression | cst.Name = alias.asname.name if alias.asname else alias.name
    if isinstance(target, cst.Name):
        return target.value
    if isinstance(target, cst.Attribute):
        return target.attr.value
    return None


def _parent_chain(
    node: cst.CSTNode,
    parent_map: Mapping[cst.CSTNode, cst.CSTNode],
    depth: int,
) -> list[str]:
    """Build a chain of parent node labels from root to current node.

    This function traverses the parent chain from the root module down to the
    current node, collecting parent node labels (kind:name format). The chain
    is limited to the specified depth to prevent excessive nesting. The current
    node is included as the final element in the chain.

    Parameters
    ----------
    node : cst.CSTNode
        Current node to build parent chain for. The chain includes this node
        as the final element.
    parent_map : Mapping[cst.CSTNode, cst.CSTNode]
        Parent metadata map from LibCST ParentNodeProvider. Maps nodes to their
        parent nodes, enabling traversal up the AST.
    depth : int
        Maximum depth to traverse up the parent chain. Limits chain length to
        prevent excessive nesting. Typical values are 5-10 levels.

    Returns
    -------
    list[str]
        List of parent node labels in order from root to current node. Each
        label is formatted as "Kind:name" (e.g., "Module:my_module",
        "ClassDef:MyClass", "FunctionDef:my_method"). The current node is included
        as the final element. Returns ["Module", current_label] if chain is empty.

    Notes
    -----
    Parent chain construction enables hierarchical node identification, showing
    the context in which a node appears (e.g., "Module:my_module > ClassDef:MyClass
    > FunctionDef:my_method"). This supports code navigation, scope resolution,
    and hierarchical search. Depth limiting prevents excessive nesting while
    preserving important context.
    """
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
    """Resolve scope label for a CST node.

    This function retrieves scope metadata for a node and converts it to a
    human-readable scope label (Global, Class, Function, Comprehension). The
    function handles lazy scope resolution and unknown scope types gracefully.

    Parameters
    ----------
    scope_map : Mapping[cst.CSTNode, object]
        Scope metadata map from LibCST ScopeProvider. Maps nodes to scope objects
        (GlobalScope, ClassScope, FunctionScope, ComprehensionScope) or lazy
        resolvers.
    node : cst.CSTNode
        CST node to resolve scope for. The node must be present in scope_map
        for scope resolution to succeed.

    Returns
    -------
    str | None
        Scope label string ("Global", "Class", "Function", "Comprehension") if
        scope is successfully resolved, otherwise None. Returns scope class name
        for unknown scope types.

    Notes
    -----
    Scope resolution enables identification of the lexical scope in which a node
    appears, supporting symbol resolution and code navigation. The function handles
    lazy scope resolution by calling resolvers when needed, and gracefully handles
    missing or unknown scopes by returning None. This supports accurate symbol
    resolution and scope-aware code analysis.
    """
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
    """Extract and summarize module docstring.

    This function retrieves the module-level docstring and summarizes it to
    the specified character limit. The summary is the first line of the docstring,
    truncated if necessary.

    Parameters
    ----------
    module : cst.Module
        LibCST module node to extract docstring from. The module's docstring
        is retrieved using get_docstring().
    max_chars : int
        Maximum number of characters for the summary. The docstring is truncated
        to this length with "..." placeholder if needed.

    Returns
    -------
    str | None
        Summarized module docstring (first line, truncated to max_chars) if
        docstring exists, otherwise None. Returns None if module has no docstring.

    Notes
    -----
    Module docstring extraction enables documentation indexing and search by
    capturing module-level documentation. The summary preserves the first line
    (typically the module description) while limiting length for storage efficiency.
    Used to populate module documentation in node records.
    """
    doc = module.get_docstring()
    if not doc:
        return None
    return _summarize(doc, max_chars)


def _summarize(text: str, max_chars: int) -> str:
    """Summarize text to a single line with character limit.

    This function extracts the first line of text, strips whitespace, and
    truncates it to the specified character limit with "..." placeholder if
    needed. Used for summarizing docstrings and other text content.

    Parameters
    ----------
    text : str
        Text to summarize. The text is split into lines, and the first non-empty
        line is extracted and truncated.
    max_chars : int
        Maximum number of characters for the summary. The text is truncated to
        this length using textwrap.shorten with "..." placeholder.

    Returns
    -------
    str
        Summarized text string (first line, truncated to max_chars). Returns
        empty string if input text is empty. The summary preserves the first
        line's content while limiting length.

    Notes
    -----
    Text summarization enables efficient storage of documentation and text
    content by preserving the most important information (first line) while
    limiting storage size. The function uses textwrap.shorten for intelligent
    truncation that preserves word boundaries when possible.
    """
    if not text:
        return ""
    summary = text.strip().splitlines()[0].strip()
    return shorten(summary, max_chars, placeholder="...")


def _doc_snippet(node: cst.CSTNode, module_doc: str | None, max_chars: int) -> DocSnippet | None:
    """Extract docstring snippet for a node.

    This function extracts docstrings from nodes that support them (Module,
    FunctionDef, ClassDef) and creates DocSnippet objects. For modules, uses
    the provided module_doc. For functions and classes, extracts docstrings
    from the node itself.

    Parameters
    ----------
    node : cst.CSTNode
        CST node to extract docstring from. Only Module, FunctionDef, and
        ClassDef nodes have extractable docstrings.
    module_doc : str | None
        Pre-extracted module docstring to use for Module nodes. If None and
        node is Module, attempts to extract docstring from node.
    max_chars : int
        Maximum number of characters for docstring summary. Docstrings are
        summarized using _summarize before inclusion in DocSnippet.

    Returns
    -------
    DocSnippet | None
        DocSnippet object containing summarized docstring if node has a docstring,
        otherwise None. For Module nodes, uses module_doc. For FunctionDef/ClassDef
        nodes, extracts docstring from node using get_docstring().

    Notes
    -----
    Docstring extraction enables documentation indexing and search by capturing
    docstrings from functions, classes, and modules. Docstrings are summarized
    to limit storage size while preserving essential information. The function
    handles missing docstrings gracefully by returning None.
    """
    if isinstance(node, cst.Module):
        return DocSnippet(module=module_doc) if module_doc else None
    if isinstance(node, (cst.FunctionDef, cst.ClassDef)):
        doc = node.get_docstring()
        if not doc:
            return None
        return DocSnippet(def_=_summarize(doc, max_chars))
    return None


def _preview_text(code: str, span: Span, max_chars: int, *, skip: bool) -> str | None:
    """Extract text preview for a node's source code span.

    This function extracts a single line of source code corresponding to a
    node's span, truncating it to the specified character limit. The preview
    provides a snippet of the actual source code for the node, enabling quick
    identification and context.

    Parameters
    ----------
    code : str
        Complete source code content of the file. Used to extract the line
        corresponding to the node's span.
    span : Span
        Source code span (start_line, start_col, end_line, end_col) indicating
        which line to extract. The start_line is used to select the line.
    max_chars : int
        Maximum number of characters for the preview. The line is truncated
        to this length using textwrap.shorten with "..." placeholder.
    skip : bool
        Flag indicating whether to skip preview extraction. If True, returns
        None immediately without processing. Used to skip previews for large
        files to reduce memory usage.

    Returns
    -------
    str | None
        Text preview string (single line, truncated to max_chars) if skip is
        False and span is valid, otherwise None. The preview is extracted from
        the line at span.start_line, stripped of leading/trailing whitespace.

    Notes
    -----
    Text preview extraction enables quick identification of nodes by showing
    actual source code snippets. The preview is limited to a single line and
    truncated to reduce storage size. Skipping previews for large files reduces
    memory usage and serialization overhead while preserving essential node
    metadata.
    """
    if skip:
        return None
    lines = code.splitlines()
    index = max(0, min(len(lines) - 1, span.start_line - 1))
    return shorten(lines[index].strip(), max_chars, placeholder="...")


def _decorators(module: cst.Module, node: cst.CSTNode) -> list[str] | None:
    """Extract decorator expressions from FunctionDef or ClassDef nodes.

    This function extracts decorator expressions from function or class definitions,
    rendering them as source code strings. Decorators are extracted in order and
    include the full decorator expression (e.g., "@property", "@dataclass(frozen=True)").

    Parameters
    ----------
    module : cst.Module
        LibCST module containing the node. Used to render decorator expressions
        as source code strings using code_for_node().
    node : cst.CSTNode
        CST node to extract decorators from. Only FunctionDef and ClassDef nodes
        have decorators. For other node types, returns None.

    Returns
    -------
    list[str] | None
        List of decorator expression strings if node is FunctionDef/ClassDef and
        has decorators, otherwise None. Each string is the rendered source code
        for a decorator (e.g., "@property", "@dataclass(frozen=True)"). Returns
        None if node has no decorators or rendering fails.

    Notes
    -----
    Decorator extraction enables identification of function/class decorators,
    supporting code analysis and navigation. Decorators are rendered as source
    code strings to preserve their full expression, enabling accurate identification
    of decorator types and arguments. The function handles rendering errors
    gracefully by skipping failed decorators.
    """
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
    """Extract qualified names of functions called in a Call node.

    This function extracts the qualified names of the function being called
    from a Call node by resolving qualified names from the function expression.
    The qualified names are normalized to include module prefixes for local
    references.

    Parameters
    ----------
    qname_map : Mapping[cst.CSTNode, object]
        Qualified name metadata map from LibCST QualifiedNameProvider. Maps
        nodes to qualified name entries (name, source) for resolution.
    module_name : str
        Current module name (dotted path) for normalizing local qualified names.
        Used to add module prefixes to local references.
    node : cst.CSTNode
        CST node to extract call targets from. Only Call nodes have call targets.
        For other node types, returns None.

    Returns
    -------
    list[str] | None
        List of qualified name strings if node is Call and targets can be resolved,
        otherwise None. Qualified names are normalized to include module prefixes
        for local references (e.g., "module.Class.method"). Returns None if node
        is not a Call or no targets can be resolved.

    Notes
    -----
    Call target extraction enables call graph construction and function call
    analysis by identifying which functions are called. Qualified names provide
    fully qualified identifiers (module.Class.method) that enable accurate
    call resolution across module boundaries. The function handles missing
    qualified names gracefully by returning None.
    """
    if not isinstance(node, cst.Call):
        return None
    entries = _qualified_name_entries(qname_map, node.func)
    targets = _normalize_qnames(entries, module_name)
    return targets or None


def _annotation(module: cst.Module, node: cst.CSTNode) -> str | None:
    """Extract type annotation from FunctionDef or AnnAssign nodes.

    This function extracts type annotations from function return types or
    annotated assignment types, rendering them as source code strings. The
    annotations are extracted from the node's annotation attributes and rendered
    using the module's code_for_node() method.

    Parameters
    ----------
    module : cst.Module
        LibCST module containing the node. Used to render annotation expressions
        as source code strings using code_for_node().
    node : cst.CSTNode
        CST node to extract annotation from. Only FunctionDef (return annotation)
        and AnnAssign (type annotation) nodes have extractable annotations. For
        other node types, returns None.

    Returns
    -------
    str | None
        Type annotation string if node has an annotation and rendering succeeds,
        otherwise None. For FunctionDef nodes, returns return type annotation.
        For AnnAssign nodes, returns type annotation. Returns None if node has
        no annotation or rendering fails.

    Notes
    -----
    Annotation extraction enables type-aware code analysis and navigation by
    capturing type information from function signatures and annotated assignments.
    Annotations are rendered as source code strings to preserve their full
    expression, enabling accurate type resolution. The function handles missing
    annotations and rendering errors gracefully by returning None.
    """
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
    """Extract import metadata from Import or ImportFrom nodes.

    This function extracts structured import information from import statements,
    including module names, imported identifiers, aliases, star imports, and
    relative import levels. The metadata is normalized and structured for
    downstream analysis.

    Parameters
    ----------
    module : cst.Module
        LibCST module containing the node. Used to render import expressions
        as source code strings for normalization.
    node : cst.CSTNode
        CST node to extract import metadata from. Only Import and ImportFrom
        nodes have import metadata. For other node types, returns None.

    Returns
    -------
    ImportMetadata | None
        ImportMetadata object containing structured import information if node
        is Import/ImportFrom, otherwise None. The metadata includes module name
        (for ImportFrom), imported names, aliases, star import flag, and relative
        import level. Returns None if node is not an import statement.

    Notes
    -----
    Import metadata extraction enables import resolution and dependency analysis
    by capturing structured information about imports. The metadata distinguishes
    between regular imports, star imports, and relative imports, enabling accurate
    import resolution. Aliases are tracked separately from original names,
    supporting accurate symbol resolution.
    """
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
    """Normalize import alias to identifier and optional alias name.

    This function extracts the imported identifier and optional alias name from
    an ImportAlias node, rendering the identifier as source code. The function
    handles both regular imports (no alias) and aliased imports (as clause).

    Parameters
    ----------
    module : cst.Module
        LibCST module containing the alias. Used to render the alias name
        expression as source code using code_for_node().
    alias : cst.ImportAlias
        Import alias node to normalize. The alias contains the imported name
        and optional asname (alias) clause.

    Returns
    -------
    tuple[str, str | None] | None
        Tuple containing (identifier, alias_name) if normalization succeeds,
        otherwise None. The identifier is the rendered source code for the
        imported name. The alias_name is the alias string if present (from
        as clause), otherwise None. Returns None if rendering fails.

    Notes
    -----
    Alias normalization enables accurate import resolution by extracting both
    the original imported name and any alias assigned to it. This supports
    symbol resolution where imports may be aliased (e.g., `import numpy as np`).
    The function handles rendering errors gracefully by returning None, ensuring
    robust import processing even when complex import expressions fail to render.
    """
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
    """Normalize module expression from ImportFrom to module name string.

    This function renders a module expression from an ImportFrom statement as
    a source code string, producing the module name (e.g., "numpy", "pkg.submodule").
    The expression may be a simple Name or a complex Attribute chain.

    Parameters
    ----------
    module : cst.Module
        LibCST module containing the expression. Used to render the expression
        as source code using code_for_node().
    expr : cst.BaseExpression | None
        Module expression from ImportFrom.node to normalize. May be None for
        relative imports without module name. The expression is rendered as
        source code to produce the module name string.

    Returns
    -------
    str | None
        Module name string if expression exists and rendering succeeds, otherwise
        None. The name is the rendered source code for the expression (e.g.,
        "numpy", "pkg.submodule"). Returns None if expr is None or rendering fails.

    Notes
    -----
    Module expression normalization enables import resolution by extracting the
    module name from ImportFrom statements. The function handles both simple
    module names and qualified module paths (dotted names), rendering them as
    strings for downstream processing. Rendering errors are handled gracefully
    by returning None, ensuring robust import processing.
    """
    if expr is None:
        return None
    try:
        return module.code_for_node(expr)
    except ValueError:
        logger.debug("Failed to render module for import-from %s", expr)
        return None


def _is_public(node: cst.CSTNode, parents: list[str]) -> bool | None:
    """Determine if a node represents a public symbol.

    This function checks whether a node represents a public (non-private) symbol
    by examining its name and parent chain. Only top-level symbols (direct children
    of Module) are checked for public/private status based on name prefix (names
    starting with "_" are private).

    Parameters
    ----------
    node : cst.CSTNode
        CST node to check for public status. The node's name is extracted and
        checked against the parent chain to determine if it's top-level.
    parents : list[str]
        Parent chain from root to current node. Used to determine if the node
        is top-level (first parent is Module). Format: ["Module:name", ...].

    Returns
    -------
    bool | None
        True if node is top-level and name doesn't start with "_" (public),
        False if node is top-level and name starts with "_" (private), None
        if node is not top-level or has no name. Only top-level symbols have
        public/private status determined.

    Notes
    -----
    Public symbol detection enables API surface analysis by identifying which
    symbols are part of the public API (not prefixed with "_"). The function
    only checks top-level symbols because nested symbols don't have public/private
    semantics in Python (they're always accessible within their scope). This
    supports API documentation generation and public symbol indexing.
    """
    name = _node_name(node)
    if not name:
        return None
    top_level = parents and parents[0].startswith("Module")
    if top_level:
        return not name.startswith("_")
    return None


def _resolve_lazy(value: object) -> object:
    """Resolve lazy metadata values by calling callables.

    This function handles lazy metadata resolution by calling callable values
    to obtain actual metadata objects. LibCST metadata providers may return
    lazy resolvers (callables) that must be invoked to get the actual value.
    Non-callable values are returned as-is.

    Parameters
    ----------
    value : object
        Metadata value that may be a callable (lazy resolver) or actual value.
        If callable, the function is called to resolve the value. If not
        callable, the value is returned as-is.

    Returns
    -------
    object
        Resolved metadata value. If value was callable, returns the result
        of calling it. If value was not callable, returns value unchanged.
        If calling fails, returns the original value as fallback.

    Notes
    -----
    Lazy resolution enables efficient metadata computation by deferring expensive
    operations until needed. LibCST metadata providers may return callables that
    compute metadata on-demand. This function handles both lazy and eager metadata
    values, ensuring consistent access patterns. Error handling ensures robust
    operation even when lazy resolvers fail.
    """
    if callable(value):
        try:
            return value()
        except (TypeError, AttributeError):  # pragma: no cover - defensive
            return value
    return value


def _qualified_name_entries(
    qname_map: Mapping[cst.CSTNode, object], node: cst.CSTNode
) -> list[tuple[str, str]]:
    """Extract qualified name entries from qualified name metadata.

    This function retrieves qualified name metadata for a node and extracts
    (name, source) tuples from qualified name objects. Qualified names represent
    fully qualified identifiers (e.g., "module.Class.method") with their source
    (LOCAL, IMPORT, BUILTIN, etc.).

    Parameters
    ----------
    qname_map : Mapping[cst.CSTNode, object]
        Qualified name metadata map from LibCST QualifiedNameProvider. Maps
        nodes to qualified name objects or lazy resolvers. The map may contain
        callable values that need resolution.
    node : cst.CSTNode
        CST node to extract qualified names for. The node must be present in
        qname_map for qualified name extraction to succeed.

    Returns
    -------
    list[tuple[str, str]]
        List of (name, source) tuples extracted from qualified name metadata.
        Each tuple contains a qualified name string (e.g., "module.Class.method")
        and its source string (e.g., "LOCAL", "IMPORT"). Returns empty list if
        node is not in qname_map or has no qualified names.

    Notes
    -----
    Qualified name extraction enables symbol resolution by identifying fully
    qualified identifiers for nodes. Qualified names include module prefixes
    (e.g., "numpy.ndarray") enabling accurate symbol resolution across module
    boundaries. The function handles lazy resolution and missing metadata
    gracefully by returning empty lists.
    """
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
    """Normalize qualified name entries to sorted list of qualified name strings.

    This function processes qualified name entries (name, source) and produces
    a normalized list of qualified name strings. For LOCAL qualified names,
    module prefixes are added to create fully qualified names. Duplicate names
    are removed, and the result is sorted for consistency.

    Parameters
    ----------
    entries : list[tuple[str, str]]
        List of (name, source) tuples from qualified name metadata. Each tuple
        contains a qualified name string and its source (LOCAL, IMPORT, BUILTIN, etc.).
    module_name : str
        Current module name (dotted path) for normalizing LOCAL qualified names.
        Used to add module prefixes to local references (e.g., "module.Class.method").

    Returns
    -------
    list[str]
        Sorted list of normalized qualified name strings. LOCAL names are prefixed
        with module_name if not already prefixed. Duplicate names are removed,
        and the result is sorted alphabetically for consistency.

    Notes
    -----
    Qualified name normalization enables consistent symbol identification by
    ensuring all qualified names include module prefixes. LOCAL names are
    expanded to include module context (e.g., "Class.method" -> "module.Class.method"),
    enabling accurate symbol resolution across module boundaries. Deduplication
    and sorting ensure consistent output for downstream processing.
    """
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
