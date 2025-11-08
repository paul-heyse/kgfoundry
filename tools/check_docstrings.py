"""Docstring quality checks shared by kgfoundry development workflows."""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from tools._shared.logging import get_logger
from tools._shared.proc import ToolExecutionError, run_tool

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

LOGGER = get_logger(__name__)

REPO = Path(__file__).resolve().parents[1]
TARGETS = [
    REPO / "src",
    REPO / "tools",
    REPO / "docs" / "_scripts",
]


@dataclass(slots=True, frozen=True)
class DocstringArgs:
    """Typed CLI options for the docstring checker."""

    no_todo: bool


def parse_args(argv: Sequence[str] | None = None) -> DocstringArgs:
    """Return parsed CLI arguments for the docstring audit helper.

    The parser currently exposes a single flag, ``--no-todo``, which toggles the
    stricter placeholder validation step executed after Ruff runs.

    Parameters
    ----------
    argv : Sequence[str] | None
        Command-line arguments (None uses sys.argv).

    Returns
    -------
    DocstringArgs
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-todo",
        action="store_true",
        help="Fail if docstrings contain placeholder text such as 'TODO'.",
    )
    namespace = parser.parse_args(argv)
    return DocstringArgs(no_todo=bool(cast("bool", namespace.no_todo)))


def iter_docstrings(path: Path) -> Iterable[tuple[Path, int, str]]:
    """Yield ``(path, lineno, text)`` tuples for every docstring in ``path``.

    The generator emits the file path, starting line number, and raw docstring text for module,
    class, and function definitions, mirroring the locations that Ruff and other documentation tools
    inspect.

    Parameters
    ----------
    path : Path
        File path to scan.

    Yields
    ------
    tuple[Path, int, str]
        (file_path, line_number, docstring_text) tuples.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    if (doc := ast.get_docstring(tree, clean=False)) is not None:
        lineno = tree.body[0].lineno if tree.body else 1
        yield path, lineno, doc
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body:
                yield path, node.body[0].lineno, doc


def check_placeholders() -> int:
    """Return ``0`` when no placeholder keywords are found in docstrings.

    The function scans every Python file in :data:`TARGETS` and records occurrences
    of ``TODO``, ``TBD``, or ``FIXME`` inside docstrings. It prints a summary of the
    offending locations to ``stderr`` and returns ``1`` if any placeholders remain.

    Returns
    -------
    int
        Exit code: 0 if no placeholders found, 1 otherwise.
    """
    errors: list[str] = []
    keywords = {"TODO", "TBD", "FIXME"}

    for target in TARGETS:
        for file_path in target.rglob("*.py"):
            try:
                for _, lineno, doc in iter_docstrings(file_path):
                    if any(key in doc for key in keywords):
                        rel = file_path.relative_to(REPO)
                        errors.append(f"{rel}:{lineno} placeholder text in docstring")
            except SyntaxError:
                continue

    if errors:
        LOGGER.error("Docstring placeholder check failed:\n%s", "\n".join(errors))
        return 1
    return 0


def main() -> None:
    """Run Ruff's docstring checks and optional placeholder validation.

    Raises
    ------
    SystemExit
        Raised with the exit status of :func:`check_placeholders` when
        ``--no-todo`` is provided and placeholder text is detected.
    """
    options = parse_args()

    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--select",
        "D",
        *(str(path) for path in TARGETS if path.exists()),
    ]
    try:
        run_tool(cmd, check=True)
    except ToolExecutionError as exc:
        LOGGER.exception("Docstring lint command failed", extra={"command": cmd})
        raise SystemExit(exc.returncode if exc.returncode is not None else 1) from exc

    if options.no_todo:
        raise SystemExit(check_placeholders())


if __name__ == "__main__":
    main()
