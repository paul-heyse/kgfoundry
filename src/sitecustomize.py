"""Editable-install sitecustomize hook for spawn-based multiprocessing."""

from __future__ import annotations

import multiprocessing as _multiprocessing
from contextlib import suppress

try:
    from codeintel_rev.runtime.site_spawn import configure_spawn_start_method
except (ImportError, ModuleNotFoundError, AttributeError):  # pragma: no cover

    def configure_spawn_start_method() -> None:
        """Fallback spawn enforcement when package imports fail."""
        with suppress(RuntimeError):
            _multiprocessing.set_start_method("spawn", force=True)


configure_spawn_start_method()
