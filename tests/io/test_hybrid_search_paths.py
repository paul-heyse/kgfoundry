"""Unit tests for hybrid search path resolution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from codeintel_rev.app.config_context import ResolvedPaths
from codeintel_rev.config.settings import Settings
from codeintel_rev.io.hybrid_search import HybridSearchEngine


def _make_engine(repo_root: Path) -> HybridSearchEngine:
    """Create a ``HybridSearchEngine`` with a minimal settings object.

    Parameters
    ----------
    repo_root : Path
        Repository root directory for the search engine.

    Returns
    -------
    HybridSearchEngine
        Engine instance scoped to ``repo_root`` for path resolution tests.
    """
    settings = cast("Settings", SimpleNamespace(index=SimpleNamespace(rrf_k=60)))
    paths = cast("ResolvedPaths", SimpleNamespace(repo_root=repo_root))
    return HybridSearchEngine(settings=settings, paths=paths)


def test_resolve_path_absolute() -> None:
    repo_root = Path("/repository-root")
    engine = _make_engine(repo_root)

    absolute = "/var/lib/search-index"

    resolved = engine.resolve_path(absolute)

    assert resolved == Path(absolute)


def test_resolve_path_relative() -> None:
    repo_root = Path("/repository-root")
    engine = _make_engine(repo_root)

    relative = "indices/bm25"

    resolved = engine.resolve_path(relative)

    assert resolved == (repo_root / relative).resolve()


def test_resolve_path_expands_user_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = Path("/repository-root")
    engine = _make_engine(repo_root)
    fake_home = tmp_path / "fake-home"
    monkeypatch.setenv("HOME", str(fake_home))

    resolved = engine.resolve_path("~/.cache/splade")

    assert resolved == fake_home / ".cache/splade"
