from __future__ import annotations

import importlib
import importlib.machinery
import sys
import types


def ensure_faiss_stub() -> None:
    """Register a minimal ``faiss`` module stub for environments without FAISS."""
    try:
        module = importlib.import_module("faiss")
    except (AttributeError, ImportError, ModuleNotFoundError, OSError, RuntimeError):
        module = None
    else:
        required_attrs = ("normalize_L2", "IndexFlatIP", "write_index")
        if all(hasattr(module, attr) for attr in required_attrs):
            return
        sys.modules.pop("faiss", None)

    if "faiss" in sys.modules:
        return

    module = types.ModuleType("faiss")
    module.__spec__ = importlib.machinery.ModuleSpec("faiss", loader=None)
    sys.modules["faiss"] = module


ensure_faiss_stub()
