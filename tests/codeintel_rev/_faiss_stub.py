from __future__ import annotations

import importlib
import importlib.machinery
import sys
import types


def ensure_faiss_stub() -> None:
    """Register a minimal ``faiss`` module stub for environments without FAISS."""
    try:
        importlib.import_module("faiss")
        return
    except Exception:  # pragma: no cover - fallback when FAISS missing/broken
        pass

    if "faiss" in sys.modules:
        return

    module = types.ModuleType("faiss")
    module.__spec__ = importlib.machinery.ModuleSpec("faiss", loader=None)
    sys.modules["faiss"] = module


ensure_faiss_stub()
