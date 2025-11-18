from __future__ import annotations

import importlib.util
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from importlib.machinery import ModuleSpec


@contextmanager
def with_module_presence(overrides: Mapping[str, ModuleSpec | None]) -> Iterator[None]:
    """Temporarily override module discovery results for `importlib.util.find_spec`.

    Parameters
    ----------
    overrides : Mapping[str, ModuleSpec | None]
        Mapping of module names to the ModuleSpec to return, or ``None`` if the module
        should appear missing.
    """
    original_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str, package: str | None = None) -> ModuleSpec | None:
        if name in overrides:
            return overrides[name]
        return original_find_spec(name, package)

    importlib.util.find_spec = fake_find_spec
    try:
        yield
    finally:
        importlib.util.find_spec = original_find_spec
