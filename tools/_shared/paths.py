"""Filesystem helpers for CLI envelope generation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    """Resolved filesystem locations relevant to CLI tooling output."""

    repo_root: Path
    docs_data: Path
    cli_out_root: Path

    @staticmethod
    @lru_cache(maxsize=1)
    def discover(start: Path | None = None) -> Paths:
        """Return the canonical set of project paths.

        Parameters
        ----------
        start : Path | None, optional
            Optional starting point used when traversing up the filesystem
            hierarchy to locate the repository root. Defaults to the current
            module path.

        Returns
        -------
        Paths
            Frozen dataclass containing resolved repository paths.
        """
        current = (start or Path(__file__)).resolve()
        for candidate in (current, *current.parents):
            if (candidate / ".git").exists():
                repo_root = candidate
                break
        else:
            repo_root = Path.cwd()

        docs_data = repo_root / "docs" / "_data"
        cli_out_root = docs_data / "cli"
        return Paths(
            repo_root=repo_root, docs_data=docs_data, cli_out_root=cli_out_root
        )

    def cli_envelope_dir(self, route: list[str]) -> Path:
        """Return the directory path used to store CLI envelope artifacts.

        Parameters
        ----------
        route : list[str]
            Normalised command route segments produced by the CLI runtime.

        Returns
        -------
        Path
            Directory path where envelopes for the command route should be
            persisted.
        """
        base = self.cli_out_root
        for segment in route:
            base /= segment
        return base


__all__ = ["Paths"]
