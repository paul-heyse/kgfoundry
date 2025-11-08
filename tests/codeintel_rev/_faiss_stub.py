from __future__ import annotations

import sys
import types


def ensure_faiss_stub() -> None:
    """Register a minimal ``faiss`` module stub for test environments."""
    sys.modules.setdefault("faiss", types.ModuleType("faiss"))


ensure_faiss_stub()
