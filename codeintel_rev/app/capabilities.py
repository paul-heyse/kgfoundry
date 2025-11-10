"""Capability snapshot helpers for conditional tool registration."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

__all__ = ["Capabilities"]


def _has_module(name: str) -> bool:
    """Return True when the given module can be imported.

    Returns
    -------
    bool
        ``True`` if ``name`` resolves to an importable module.
    """
    return importlib.util.find_spec(name) is not None


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Lightweight capability flags derived from the application context."""

    faiss_index: bool = False
    duckdb: bool = False
    scip_index: bool = False
    vllm_client: bool = False

    @property
    def has_semantic(self) -> bool:
        """Return True when semantic tools can be safely registered.

        Returns
        -------
        bool
            ``True`` when FAISS, DuckDB, and vLLM capabilities are present.
        """
        return self.faiss_index and self.duckdb and self.vllm_client

    @property
    def has_symbols(self) -> bool:
        """Return True when symbol navigation tools can be registered.

        Returns
        -------
        bool
            ``True`` when DuckDB and SCIP resources are present.
        """
        return self.duckdb and self.scip_index

    @classmethod
    def from_context(cls, context: ApplicationContext) -> Capabilities:
        """Build a capability snapshot from the current application context.

        Returns
        -------
        Capabilities
            Snapshot derived from the supplied context.
        """
        paths = getattr(context, "paths", None)
        faiss_path = getattr(paths, "faiss_index", None)
        duckdb_path = getattr(paths, "duckdb_path", None)
        scip_path = getattr(paths, "scip_index", None)
        faiss_ready = bool(faiss_path and faiss_path.exists() and _has_module("faiss"))
        duckdb_ready = bool(duckdb_path and duckdb_path.exists())
        scip_ready = bool(scip_path and scip_path.exists())
        vllm_ready = getattr(context, "vllm_client", None) is not None
        return cls(
            faiss_index=faiss_ready,
            duckdb=duckdb_ready,
            scip_index=scip_ready,
            vllm_client=vllm_ready,
        )
