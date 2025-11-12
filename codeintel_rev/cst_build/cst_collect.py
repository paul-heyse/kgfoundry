# SPDX-License-Identifier: MIT
"""LibCST traversal utilities that emit normalized node records."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import blake2s
from pathlib import Path
from textwrap import shorten
from typing import ClassVar, final

import libcst as cst
from libcst import metadata as cst_metadata
from libcst.metadata import FullRepoManager
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


@final
class CSTCollector:
    """Collect LibCST node records for a repository."""

    _PROVIDERS: ClassVar[tuple[type[object], ...]] = (
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
        self._manager = None
        if use_full_repo_manager:
            self._manager = self._build_repo_manager(files)

    def _build_repo_manager(self, files: Sequence[Path] | None) -> FullRepoManager | None:
        """Build a repo-scoped metadata manager when a file list is available.

        Returns
        -------
        FullRepoManager | None
            Configured manager if the environment supports it, otherwise ``None``.
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
        stats = CollectorStats(files_indexed=1)
        rel_path = self._relative_path(path)
        try:
            file_size = path.stat().st_size
            code = path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - hardened path
            stats.parse_errors = 1
            return [_build_parse_error_node(rel_path, str(exc))], stats
        wrapper = self._wrap_module(rel_path, code, stats)
        if wrapper is None:
            return [_build_parse_error_node(rel_path, "Failed to build metadata wrapper.")], stats
        nodes = list(
            self._emit_nodes(
                rel_path=rel_path,
                code=code,
                wrapper=wrapper,
                skip_preview=file_size > self._config.text_preview_skip_bytes,
                stats=stats,
            )
        )
        stats.node_rows = len(nodes)
        return nodes, stats

    def _wrap_module(
        self,
        rel_path: str,
        code: str,
        stats: CollectorStats,
    ) -> cst_metadata.MetadataWrapper | None:
        if self._manager is not None:
            try:
                return self._manager.get_metadata_wrapper_for_path(rel_path)
            except KeyError:
                logger.debug("FullRepoManager missing %s; falling back to per-file parsing", rel_path)
        try:
            module = cst.parse_module(code)
            return cst_metadata.MetadataWrapper(module, unsafe_skip_copy=True)
        except cst.ParserSyntaxError as exc:
            logger.warning("LibCST failed to parse %s: %s", rel_path, exc)
            stats.parse_errors = 1
            return None

    def _emit_nodes(
        self,
        *,
        rel_path: str,
        code: str,
        wrapper: cst_metadata.MetadataWrapper,
        skip_preview: bool,
        stats: CollectorStats,
    ) -> Iterable[NodeRecord]:
        """Yield NodeRecord rows for ``rel_path``.

        Yields
        ------
        NodeRecord
            Serialized node record matching the schema contract.
        """
        parent_map = wrapper.resolve(cst_metadata.ParentNodeProvider)
        position_map = wrapper.resolve(cst_metadata.PositionProvider)
        scope_map = wrapper.resolve(cst_metadata.ScopeProvider)
        qname_map = wrapper.resolve(cst_metadata.QualifiedNameProvider)
        module = wrapper.module
        module_doc = _extract_module_doc(module, self._config.max_doc_chars)
        module_name = _module_name_from_path(rel_path)
        stack = [module]
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
                stats.qname_hits += 1
            if scope_label:
                stats.scope_resolved += 1
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


def _resolve_span(
    position_map: Mapping[cst.CSTNode, cst_metadata.Position], node: cst.CSTNode
) -> Span:
    position = _resolve_lazy(position_map[node])
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
    parent_map: dict[cst.CSTNode, cst.CSTNode],
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
    decorator_nodes: list[cst.Decorator] = []
    if isinstance(node, (cst.FunctionDef, cst.ClassDef)):
        decorator_nodes = node.decorators
    if not decorator_nodes:
        return None
    for deco in decorator_nodes:
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
    if value.__class__.__name__ == "LazyValue":  # pragma: no cover - lib internals
        try:
            return value()
        except (TypeError, AttributeError):
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
    for qname in qnames:
        source = getattr(qname.source, "name", str(qname.source))
        entries.append((qname.name, source))
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

    Returns
    -------
    str
        Dotted module path (empty string for top-level modules).
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

    Returns
    -------
    NodeRecord
        Synthetic node record capturing the parse issue.
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
