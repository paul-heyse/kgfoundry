# SPDX-License-Identifier: MIT
"""Tree-sitter outline helpers used for enrichment artifacts."""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tree_sitter import Language, Node, Parser  # type: ignore[import-not-found]

_languages_spec = importlib.util.find_spec("tree_sitter_languages")
if _languages_spec is not None:  # pragma: no cover
    _languages_module = importlib.import_module("tree_sitter_languages")
    _get_language: Any | None = getattr(_languages_module, "get_language", None)
else:  # pragma: no cover
    _get_language = None

try:  # pragma: no cover - optional dependency
    from tree_sitter_python import language as _python_language  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    _python_language = None  # type: ignore[assignment]


def _lang_for_ext(ext: str) -> Language | None:
    """Resolve a Tree-sitter language for ``ext``.

    Returns
    -------
    Language | None
        Tree-sitter language object when available.
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
                return language_obj
    if normalized == ".py" and _python_language is not None:
        language_obj = _python_language()
        if isinstance(language_obj, Language):
            return language_obj
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

    Returns
    -------
    TSOutline | None
        Outline description when a language binding exists.
    """
    language = _lang_for_ext(Path(path).suffix)
    if language is None:
        return None
    parser: Any = Parser()
    parser.set_language(language)
    tree = parser.parse(content)

    outline = TSOutline(language=str(language))
    cursor = tree.walk()
    current_node = getattr(cursor, "node", None)
    if current_node is None:
        return outline
    stack = [current_node]
    while stack:
        node = stack.pop()
        if node is None:
            continue
        node_type = getattr(node, "type", "")
        if node_type in {"function_definition", "class_definition"}:
            outline.nodes.append(
                OutlineNode(
                    kind=node_type,
                    name=_extract_identifier(content, node),
                    start_byte=getattr(node, "start_byte", 0),
                    end_byte=getattr(node, "end_byte", 0),
                )
            )
        children = list(getattr(node, "children", [])) if hasattr(node, "children") else []
        stack.extend(reversed(children))
    return outline


def _extract_identifier(content: bytes, node: Node | None) -> str:
    """Return the identifier name for ``node`` if available.

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
