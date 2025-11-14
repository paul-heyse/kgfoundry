# SPDX-License-Identifier: MIT
"""Tree-sitter outline helpers used for enrichment artifacts."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tree_sitter import Language, Node, Parser, Query

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


LOGGER = logging.getLogger(__name__)
_USE_TS_QUERY = os.getenv("USE_TS_QUERY", "1") not in {"0", "false", "False"}
_OUTLINE_QUERY_PATTERNS: dict[str, str] = {
    "python": """
        (function_definition name: (identifier) @name) @func
        (class_definition name: (identifier) @name) @class
    """,
}
_OUTLINE_QUERY_CACHE: dict[str, Query | None] = {}


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
            language_obj = _get_language(target)
            if isinstance(language_obj, Language):
                return target, language_obj
    if normalized == ".py" and _python_language is not None:
        language_obj = _python_language()
        if isinstance(language_obj, Language):
            return "python", language_obj
    return None


@dataclass(slots=True, frozen=True)
class OutlineNode:
    """Serializable view of a function/class definition."""

    kind: str
    name: str
    start_byte: int
    end_byte: int


@dataclass(slots=True, frozen=True)
class TSOutline:
    """Bundle of outline nodes plus the originating Tree-sitter language."""

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
    parser: Any = Parser()
    parser.set_language(language)
    tree = parser.parse(content)

    nodes: list[OutlineNode] = []
    if _USE_TS_QUERY:
        nodes = _outline_with_query(language_name, language, tree, content)
    if not nodes:
        nodes = _outline_with_dfs(tree.root_node, content)
    return TSOutline(language=language_name, nodes=nodes)


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
    tree: Any,
    content: bytes,
) -> list[OutlineNode]:
    query = _get_outline_query(language_name, language)
    if query is None:
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


def _get_outline_query(language_name: str, language: Language) -> Query | None:
    if language_name in _OUTLINE_QUERY_CACHE:
        return _OUTLINE_QUERY_CACHE[language_name]
    pattern = _OUTLINE_QUERY_PATTERNS.get(language_name)
    if not pattern:
        _OUTLINE_QUERY_CACHE[language_name] = None
        return None
    try:
        query = language.query(pattern)
    except Exception as exc:  # pragma: no cover - query compilation failures are rare
        LOGGER.debug("Tree-sitter query compile failed for %s: %s", language_name, exc)
        _OUTLINE_QUERY_CACHE[language_name] = None
        return None
    _OUTLINE_QUERY_CACHE[language_name] = query
    return query


def _node_text(content: bytes, node: Node) -> str:
    return content[getattr(node, "start_byte", 0) : getattr(node, "end_byte", 0)].decode(
        "utf-8", "ignore"
    )
