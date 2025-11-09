"""Overview of update navmaps.

This module bundles update navmaps logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def iter_python_files() -> list[Path]:
    """Compute iter python files.

    Carry out the iter python files operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Returns
    -------
    list[Path]
        Sorted list of Path objects pointing to Python source files found
        in the project, excluding directories and non-Python files.
    """
    search_root = SRC if SRC.exists() else ROOT
    return sorted(path for path in search_root.rglob("*.py") if path.is_file())


def module_docstring(path: Path) -> str | None:
    """Compute module docstring.

    Carry out the module docstring operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Parameters
    ----------
    path : Path
        Description for ``path``.

    Returns
    -------
    str | None
        Description of return value.

    Examples
    --------
    >>> from tools.update_navmaps import module_docstring
    >>> result = module_docstring(...)
    >>> result  # doctest: +ELLIPSIS
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return None
    return ast.get_docstring(tree)


def main() -> None:
    """Compute main.

    Carry out the main operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Raises
    ------
    SystemExit
        Raised when validation fails.

    Examples
    --------
    >>> from tools.update_navmaps import main
    >>> main()  # doctest: +ELLIPSIS
    """
    offenders: list[Path] = []
    for file_path in iter_python_files():
        doc = module_docstring(file_path)
        if doc and "NavMap:" in doc:
            offenders.append(file_path)
    if offenders:
        joined = "\n".join(str(path) for path in offenders)
        message = f"Module docstrings must not contain 'NavMap:' sections. Found violations in:\n{joined}"
        raise SystemExit(message)


if __name__ == "__main__":
    main()
