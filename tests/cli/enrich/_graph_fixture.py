# SPDX-License-Identifier: MIT
"""Shared graph CLI fixture helpers."""

from __future__ import annotations

from pathlib import Path


def prepare_graph_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Prepare a minimal repository with a simple package for graph tests.

    Returns
    -------
    tuple[Path, Path]
        Repository root and output directory paths.
    """
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    for required in (
        "config",
        "logs",
        ".cache",
        ".tmp",
        "plugins",
        "data",
        "data/faiss",
        "data/vectors",
    ):
        (repo / required).mkdir(parents=True, exist_ok=True)
    (repo / "config" / "app.yml").write_text("", encoding="utf-8")
    package = repo / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text(
        "def callee() -> int:\n"
        "    value = 1\n"
        "    return value\n\n"
        "def caller() -> int:\n"
        "    total = callee()\n"
        "    return total\n",
        encoding="utf-8",
    )
    out_dir = repo / ".out"
    out_dir.mkdir(parents=True, exist_ok=True)
    return repo, out_dir


__all__ = ["prepare_graph_repo"]
