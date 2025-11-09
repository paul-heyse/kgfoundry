"""Remove deprecated NavMap metadata from module docstrings."""

from __future__ import annotations

import ast
from pathlib import Path

from tools import get_logger

LOGGER = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def iter_module_nodes(path: Path) -> tuple[ast.Module, ast.Expr | None]:
    """Parse ``path`` and return the module node plus its docstring expression.

    This function parses a Python file and extracts both the complete AST module
    node and the top-level docstring expression (if present). The docstring is
    identified as the first expression statement containing a string constant.

    Parameters
    ----------
    path : Path
        File to parse. The file must contain valid Python syntax.

    Returns
    -------
    tuple[ast.Module, ast.Expr | None]
        The parsed module node paired with the top-level docstring expression or
        ``None`` when no docstring literal is present.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    if not tree.body:
        return tree, None
    first = tree.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return tree, first
    return tree, None


def clean_docstring(text: str) -> str:
    """Remove legacy ``NavMap:`` sections while keeping meaningful text.

    This function strips deprecated NavMap metadata annotations from module
    docstrings while preserving the actual documentation content. It removes
    lines starting with "NavMap:" and any content after them, then collapses
    empty lines and trims whitespace.

    Parameters
    ----------
    text : str
        Original module docstring including the deprecated NavMap annotations.

    Returns
    -------
    str
        Trimmed docstring content with empty lines collapsed. A default
        ``"Module documentation."`` placeholder is returned when the original
        docstring was entirely composed of NavMap metadata.
    """
    lines: list[str] = []
    for raw in text.splitlines():
        if raw.strip().startswith("NavMap:"):
            break
        lines.append(raw.rstrip())
    cleaned = "\n".join(line for line in lines if line.strip())
    return cleaned or "Module documentation."


def rewrite_module(path: Path) -> bool:
    """Rewrite ``path`` in-place when the module docstring encodes NavMap data.

    This function reads a Python module file, checks if its docstring contains
    deprecated NavMap metadata sections, and if so, rewrites the file with the
    cleaned docstring. The cleaning process removes NavMap annotations while
    preserving the actual documentation content.

    Parameters
    ----------
    path : Path
        Module file to update in-place. The file must contain valid Python syntax.

    Returns
    -------
    bool
        ``True`` if the docstring was replaced with cleaned content, ``False``
        when no NavMap section was present or the file had no docstring.
    """
    tree, doc_expr = iter_module_nodes(path)
    if doc_expr is None:
        return False
    doc_text = ast.get_docstring(tree)
    if not doc_text or "NavMap:" not in doc_text:
        return False

    cleaned = clean_docstring(doc_text)
    new_lines = (
        ['"""' + cleaned, '"""'] if "\n" in cleaned else ['"""' + cleaned + '"""']
    )

    original_lines = path.read_text(encoding="utf-8").splitlines()
    start = doc_expr.lineno - 1
    end = doc_expr.end_lineno or doc_expr.lineno
    original_lines[start:end] = new_lines
    path.write_text("\n".join(original_lines) + "\n", encoding="utf-8")
    return True


def main() -> None:
    """Strip legacy NavMap metadata from modules across the source tree."""
    changed = 0
    for file_path in sorted(SRC.rglob("*.py")):
        if rewrite_module(file_path):
            changed += 1
            relative = file_path.relative_to(ROOT)
            LOGGER.info("[navmap] Stripped legacy NavMap section from %s", relative)
    if changed == 0:
        LOGGER.info("[navmap] No NavMap sections found.")


if __name__ == "__main__":
    main()
