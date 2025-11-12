# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Language, Parser  # type: ignore[import-not-found]

try:
    # Prefer the language pack for robust multi-language coverage
    from tree_sitter_languages import (
        get_language as _get_language,  # type: ignore[import-not-found]
    )

    def _lang_for_ext(ext: str) -> Language | None:
        name = {
            ".py": "python",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".md": "markdown",
        }.get(ext.lower())
        return _get_language(name) if name else None
except Exception:  # pragma: no cover
    # Fallback: rely on python only
    from tree_sitter_python import language as _py_lang  # type: ignore[import-not-found]

    def _lang_for_ext(ext: str) -> Language | None:
        return _py_lang() if ext.lower() == ".py" else None


@dataclass
class OutlineNode:
    kind: str
    name: str
    start_byte: int
    end_byte: int


@dataclass
class TSOutline:
    language: str
    nodes: list[OutlineNode] = field(default_factory=list)


def build_outline(path: str | Path, content: bytes) -> TSOutline | None:
    p = Path(path)
    lang = _lang_for_ext(p.suffix)
    if not lang:
        return None
    parser = Parser()
    parser.set_language(lang)
    tree = parser.parse(content)

    # Light-weight visitor for Python; for other languages we just return an empty outline
    outline = TSOutline(language=str(lang))
    cursor = tree.walk()
    stack = [cursor.node]

    while stack:
        node = stack.pop()
        # Python-focused outline (best-effort; extend as needed)
        if node.type in {"function_definition", "class_definition"}:
            # Heuristic: first child with type 'identifier' is the name
            name = ""
            for ch in node.children:
                if ch.type == "identifier":
                    name = content[ch.start_byte : ch.end_byte].decode("utf-8", "ignore")
                    break
            outline.nodes.append(
                OutlineNode(
                    kind=node.type, name=name, start_byte=node.start_byte, end_byte=node.end_byte
                )
            )
        # DFS
        stack.extend(reversed(node.children))
    return outline
