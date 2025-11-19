# SPDX-License-Identifier: MIT
"""Tree-sitter outline helpers used for enrichment artifacts."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol, cast

from tree_sitter import Language, Node, Parser, Query, Tree

LOGGER = logging.getLogger(__name__)

_languages_spec = importlib.util.find_spec("tree_sitter_languages")
if _languages_spec is not None:  # pragma: no cover
    _languages_module = importlib.import_module("tree_sitter_languages")
    _get_language: Any | None = getattr(_languages_module, "get_language", None)
else:  # pragma: no cover
    _get_language = None

try:  # pragma: no cover - optional dependency
    from tree_sitter_python import language as _python_language
except ImportError:  # pragma: no cover
    _python_language = None
_USE_TS_QUERY = os.getenv("USE_TS_QUERY", "1") not in {"0", "false", "False"}
_OUTLINE_QUERY_PATTERNS: dict[str, str] = {
    "python": """
        (function_definition name: (identifier) @name) @func
        (class_definition name: (identifier) @name) @class
    """,
}
_OUTLINE_QUERY_CACHE: dict[str, QueryProtocol | None] = {}


@dataclass(slots=True, frozen=True)
class OutlineConfig:
    """Configuration toggles for outline generation.

    Attributes
    ----------
    use_ts_query : bool, optional
        Whether to use Tree-sitter queries for outline extraction. If False,
        uses AST traversal. Defaults to _USE_TS_QUERY constant value.
    """

    use_ts_query: bool = _USE_TS_QUERY


_OUTLINE_CONFIG_STACK: list[OutlineConfig] = [OutlineConfig()]


@contextmanager
def override_outline_config(**kwargs: object) -> Iterator[None]:
    """Temporarily override outline configuration flags."""
    config = replace(_OUTLINE_CONFIG_STACK[-1], **kwargs)
    _OUTLINE_CONFIG_STACK.append(config)
    try:
        yield
    finally:
        _OUTLINE_CONFIG_STACK.pop()


class QueryProtocol(Protocol):
    """Subset of :class:`tree_sitter.Query` APIs required for outlines."""

    def captures(self, node: Node) -> Sequence[tuple[Node, str]]:
        """Return captures for ``node``."""
        ...


def _as_language(candidate: object | None) -> Language | None:
    """Return a ``Language`` instance for ``candidate`` when possible.

    Extended Summary
    ----------------
    Attempts to coerce a candidate object into a Tree-sitter Language instance.
    Handles None, Language instances, and PyCapsule objects returned by language
    bindings. Used internally for flexible language object handling.

    Parameters
    ----------
    candidate : object | None
        Object to coerce into a Language instance. Can be None, a Language instance,
        or a PyCapsule from language bindings.

    Returns
    -------
    Language | None
        Coerced ``Language`` object, or ``None`` when conversion fails or candidate
        is None.
    """
    if candidate is None:
        return None
    if isinstance(candidate, Language):
        return candidate
    try:
        # ``tree_sitter_python.language()`` returns a PyCapsule that can be
        # wrapped by ``Language`` to obtain the concrete binding.
        converted = Language(candidate)
    except (TypeError, ValueError):
        LOGGER.debug("Failed to coerce Tree-sitter language from %r", candidate)
        return None
    return converted


def _lang_for_ext(ext: str) -> tuple[str, Language] | None:
    """Resolve a Tree-sitter language for ``ext``.

    Parameters
    ----------
    ext : str
        File extension (e.g., ".py", ".json") to resolve a language for.
        The extension is normalized to lowercase before lookup.

    Returns
    -------
    tuple[str, Language] | None
        Language name paired with the Tree-sitter language object when available, or None if no language
        binding exists for the extension.
    """
    normalized = ext.lower()
    if _get_language is not None:
        name_map = {
            ".py": "python",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".md": "markdown",
        }
        target = name_map.get(normalized)
        if target:
            language_obj = _as_language(_get_language(target))
            if language_obj is not None:
                return target, language_obj
    if normalized == ".py" and _python_language is not None:
        language_obj = _as_language(_python_language())
        if language_obj is not None:
            return "python", language_obj
    return None


@dataclass(slots=True, frozen=True)
class OutlineNode:
    """Serializable view of a function/class definition.

    Attributes
    ----------
    kind : str
        Node kind identifier (e.g., "function", "class", "method").
    name : str
        Name of the function, class, or method.
    start_byte : int
        Starting byte offset of the node in the source file.
    end_byte : int
        Ending byte offset of the node in the source file (exclusive).
    """

    kind: str
    name: str
    start_byte: int
    end_byte: int


@dataclass(slots=True, frozen=True)
class TSOutline:
    """Bundle of outline nodes plus the originating Tree-sitter language.

    Attributes
    ----------
    language : str
        Tree-sitter language identifier (e.g., "python", "json", "yaml").
    nodes : list[OutlineNode], optional
        List of outline nodes extracted from the source file. Empty list if
        no nodes were found. Defaults to empty list.
    """

    language: str
    nodes: list[OutlineNode] = field(default_factory=list)


def build_outline(path: str | Path, content: bytes) -> TSOutline | None:
    """Produce a best-effort outline for ``path``'s contents.

    Parameters
    ----------
    path : str | Path
        File system path used to determine the language (via extension).
        The path itself is not read; only the extension is used.
    content : bytes
        Source code content to parse and extract outline from. Must be
        valid UTF-8 encoded text.

    Returns
    -------
    TSOutline | None
        Outline description when a language binding exists, containing
        function and class definitions with byte offsets. Returns None
        if no language binding is available for the file extension.
    """
    lang_info = _lang_for_ext(Path(path).suffix)
    if lang_info is None:
        return None
    language_name, language = lang_info
    parser = Parser()
    _set_parser_language(parser, language)
    tree = parser.parse(content)

    nodes: list[OutlineNode] = []
    config = _OUTLINE_CONFIG_STACK[-1]
    if config.use_ts_query:
        nodes = _outline_with_query(language_name, language, tree, content)
    if not nodes:
        nodes = _outline_with_dfs(tree.root_node, content)
    return TSOutline(language=language_name, nodes=nodes)


def _set_parser_language(parser: Parser, language: Language) -> None:
    """Bind ``parser`` to ``language`` across Tree-sitter releases."""
    setter = getattr(parser, "set_language", None)
    if callable(setter):
        setter(language)
        return
    parser.language = language


def _extract_identifier(content: bytes, node: Node | None) -> str:
    """Return the identifier name for ``node`` if available.

    Parameters
    ----------
    content : bytes
        Source code bytes containing the identifier text.
    node : Node | None
        Tree-sitter node to extract identifier from. When None, returns
        an empty string.

    Returns
    -------
    str
        Identifier name or an empty string when not found.
    """
    if node is None:
        return ""
    for child in getattr(node, "children", []):
        if getattr(child, "type", "") == "identifier":
            start = getattr(child, "start_byte", 0)
            end = getattr(child, "end_byte", start)
            return content[start:end].decode("utf-8", "ignore")
    return ""


def _outline_with_query(
    language_name: str,
    language: Language,
    tree: Tree,
    content: bytes,
) -> list[OutlineNode]:
    """Extract outline nodes using Tree-sitter query patterns.

    Uses Tree-sitter query syntax to efficiently extract function and class
    definitions from a parsed tree. Queries are cached per language for
    performance. Falls back to DFS traversal if query extraction fails.

    Parameters
    ----------
    language_name : str
        Language identifier (e.g., "python") used to select the appropriate
        query pattern and for caching.
    language : Language
        Tree-sitter Language object for the source code language.
    tree : Tree
        Parsed Tree-sitter syntax tree containing the source code structure.
    content : bytes
        Source code bytes used to extract identifier names from captured nodes.

    Returns
    -------
    list[OutlineNode]
        List of outline nodes extracted via query captures. Returns an empty
        list if query compilation fails, query has no captures method, or no
        definitions are found.
    """
    query = _get_outline_query(language_name, language)
    if query is None:
        return []
    if not hasattr(query, "captures"):
        LOGGER.debug("Tree-sitter query missing captures method for %s", language_name)
        return []
    captures = query.captures(tree.root_node)
    name_by_def: dict[int, str] = {}
    def_nodes: list[tuple[str, Node]] = []
    for capture_node, capture_name in captures:
        if capture_name == "name":
            parent = getattr(capture_node, "parent", None)
            if parent is not None:
                name_by_def[parent.id] = _node_text(content, capture_node)
        elif capture_name in {"func", "class"}:
            def_nodes.append((capture_name, capture_node))
    outline_nodes: list[OutlineNode] = []
    for capture_name, node in def_nodes:
        name = name_by_def.get(node.id) or _extract_identifier(content, node)
        outline_nodes.append(
            OutlineNode(
                kind="function_definition" if capture_name == "func" else "class_definition",
                name=name,
                start_byte=getattr(node, "start_byte", 0),
                end_byte=getattr(node, "end_byte", 0),
            )
        )
    return outline_nodes


def _outline_with_dfs(root_node: Node | None, content: bytes) -> list[OutlineNode]:
    """Extract outline nodes using depth-first traversal.

    Traverses the Tree-sitter syntax tree using iterative DFS to find function
    and class definition nodes. This is a fallback method when query-based
    extraction is unavailable or disabled.

    Parameters
    ----------
    root_node : Node | None
        Root node of the Tree-sitter syntax tree to traverse. If None, returns
        an empty list.
    content : bytes
        Source code bytes used to extract identifier names from definition nodes.

    Returns
    -------
    list[OutlineNode]
        List of outline nodes found during traversal. Each node represents a
        function or class definition with its name and byte offsets. Returns
        an empty list if root_node is None or no definitions are found.
    """
    if root_node is None:
        return []
    nodes: list[OutlineNode] = []
    stack = [root_node]
    while stack:
        node = stack.pop()
        node_type = getattr(node, "type", "")
        if node_type in {"function_definition", "class_definition"}:
            nodes.append(
                OutlineNode(
                    kind=node_type,
                    name=_extract_identifier(content, node),
                    start_byte=getattr(node, "start_byte", 0),
                    end_byte=getattr(node, "end_byte", 0),
                )
            )
        children = list(getattr(node, "children", [])) if hasattr(node, "children") else []
        stack.extend(reversed(children))
    return nodes


def _get_outline_query(language_name: str, language: Language) -> QueryProtocol | None:
    """Get or compile a Tree-sitter query for outline extraction.

    Retrieves a cached query for the language or compiles a new one from the
    query pattern. Queries are cached per language to avoid recompilation.
    Returns None if no pattern exists for the language or compilation fails.

    Parameters
    ----------
    language_name : str
        Language identifier (e.g., "python") used to look up the query pattern
        and cache key.
    language : Language
        Tree-sitter Language object used to compile the query pattern.

    Returns
    -------
    QueryProtocol | None
        Compiled Tree-sitter query object if successful, or None if:
        - No query pattern exists for the language
        - Query compilation fails (invalid pattern syntax)
        - Query was previously cached as None (failed compilation)
    """
    if language_name in _OUTLINE_QUERY_CACHE:
        return _OUTLINE_QUERY_CACHE[language_name]
    pattern = _OUTLINE_QUERY_PATTERNS.get(language_name)
    if not pattern:
        _OUTLINE_QUERY_CACHE[language_name] = None
        return None
    try:
        query = cast("QueryProtocol", Query(language, pattern))
    except (ValueError, TypeError) as exc:  # pragma: no cover - query compilation failures are rare
        LOGGER.debug("Tree-sitter query compile failed for %s: %s", language_name, exc)
        _OUTLINE_QUERY_CACHE[language_name] = None
        return None
    _OUTLINE_QUERY_CACHE[language_name] = query
    return query


def _node_text(content: bytes, node: Node) -> str:
    """Extract the text content of a Tree-sitter node from source bytes.

    Parameters
    ----------
    content : bytes
        Source code bytes containing the node's text. Must be valid UTF-8
        encoded text (decoding errors are ignored).
    node : Node
        Tree-sitter node to extract text from. The node's start_byte and
        end_byte attributes define the byte range to extract.

    Returns
    -------
    str
        Decoded text string for the node's byte range. Returns an empty string
        if start_byte is 0 and end_byte is 0 (default values when unavailable).
    """
    return content[getattr(node, "start_byte", 0) : getattr(node, "end_byte", 0)].decode(
        "utf-8", "ignore"
    )
