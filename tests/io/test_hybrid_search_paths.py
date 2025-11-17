"""Unit tests for hybrid search path resolution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from codeintel_rev.app.config_context import ResolvedPaths
from codeintel_rev.config.settings import Settings
from codeintel_rev.io.hybrid_search import HybridSearchEngine

from tests._helpers import assertions


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
    """Verify absolute paths are resolved correctly."""
    repo_root = Path("/repository-root")
    engine = _make_engine(repo_root)

    absolute = "/var/lib/search-index"

    resolved = engine.resolve_path(absolute)

    assertions.expect_equal(resolved, Path(absolute))


def test_resolve_path_relative() -> None:
    """Verify relative paths are resolved against repo root."""
    repo_root = Path("/repository-root")
    engine = _make_engine(repo_root)

    relative = "indices/bm25"

    resolved = engine.resolve_path(relative)

    assertions.expect_equal(resolved, (repo_root / relative).resolve())


def test_resolve_path_expands_user_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify user home expansion (~) works correctly."""
    repo_root = Path("/repository-root")
    engine = _make_engine(repo_root)
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir(parents=True, exist_ok=True)
    original_expanduser = Path.expanduser

    def _expanduser(self: Path) -> Path:
        text = str(self)
        if text.startswith("~"):
            return Path(text.replace("~", str(fake_home), 1))
        return original_expanduser(self)

    monkeypatch.setattr(Path, "expanduser", _expanduser)

    resolved = engine.resolve_path("~/.cache/splade")

    assertions.expect_equal(resolved, fake_home / ".cache/splade")
