"""Vulture allowlist for kgfoundry.

This file marks *intentionally* "unused" symbols as used so Vulture
doesn't flag them. Keep justifications next to each entry.
Regenerate candidates with::

    vulture src tools stubs --make-whitelist > vulture_whitelist.py

and then prune/curate the results.

Note: This file is executed by Vulture's parser (not at runtime), so it's safe
to import and alias names to signal usage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import ModuleType

# --- Pydantic validators / dynamic attrs ---
try:
    import pydantic as _pydantic_module
except ImportError:  # pragma: no cover
    pydantic_module: ModuleType | None = None
else:
    pydantic_module = _pydantic_module

if pydantic_module is not None:
    root_validator: object | None = getattr(pydantic_module, "root_validator", None)
    validator: object | None = getattr(pydantic_module, "validator", None)
else:
    root_validator = None
    validator = None

# --- Click entry points that may be discovered dynamically ---
try:
    import click as _click_module
except ImportError:  # pragma: no cover
    click_module: ModuleType | None = None
else:
    click_module = _click_module

# --- Examples of symbols referenced via registries or __all__ ---
# Adjust to your actual modules.
try:
    from kgfoundry import __all__ as _kgfoundry_all
except ImportError:  # pragma: no cover
    kgfoundry_all: Sequence[object] = ()
else:
    kgfoundry_all = tuple(_kgfoundry_all)

# Group the references to make it obvious to Vulture that they're used.
WHITELIST_SENTINEL: tuple[object | None, object | None, ModuleType | None, Sequence[object]] = (
    root_validator,
    validator,
    click_module,
    kgfoundry_all,
)

# If you have plugin registries with module-level side effects (for
# example, entry-point registration), import those modules here so Vulture
# treats the dynamic usage as intentional.
