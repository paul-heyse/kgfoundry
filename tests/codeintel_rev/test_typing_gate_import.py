from __future__ import annotations

import builtins
from typing import Any

import pytest
from codeintel_rev.typing import gate_import


def test_gate_import_missing_module_includes_extra_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def fake_import(  # type: ignore[override]
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "faiss":
            message = "No module named 'faiss'"
            raise ImportError(message)
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(ImportError) as excinfo:
        gate_import("faiss", "testing extras hint")

    message = str(excinfo.value)
    assert "pip install codeintel-rev[faiss-cpu]" in message
    assert "pip install codeintel-rev[faiss-gpu]" in message
