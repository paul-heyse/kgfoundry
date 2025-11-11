"""Search service endpoints and retrieval adapters.

This package provides typed search APIs with schema validation and
Problem Details error responses. All public APIs are explicitly exported
via `__all__` with full type annotations.

See Also
--------
- `schema/examples/problem_details/search-missing-index.json` - Example error response
- `schema/models/search_request.v1.json` - Request schema
- `schema/models/search_result.v1.json` - Response schema
"""

# [nav:section public-api]

from __future__ import annotations

import sys
from importlib import import_module
from typing import TYPE_CHECKING

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "app",
    "bm25_index",
    "faiss_adapter",
    "fixture_index",
    "fusion",
    "kg_mock",
    "schemas",
    "service",
    "splade_index",
    "types",
]

_ALIASES: dict[str, str] = {name: f"search_api.{name}" for name in __all__}

__navmap__ = load_nav_metadata(__name__, tuple(__all__))


if TYPE_CHECKING:  # pragma: no cover - typing only
    from types import ModuleType

    from search_api import (
        app as _app_module,
    )
    from search_api import (
        bm25_index as _bm25_module,
    )
    from search_api import (
        faiss_adapter as _faiss_module,
    )
    from search_api import (
        fixture_index as _fixture_module,
    )
    from search_api import (
        fusion as _fusion_module,
    )
    from search_api import (
        kg_mock as _kg_mock_module,
    )
    from search_api import (
        schemas as _schemas_module,
    )
    from search_api import (
        service as _service_module,
    )
    from search_api import (
        splade_index as _splade_module,
    )
    from search_api import (
        types as _types_module,
    )

    app = _app_module
    bm25_index = _bm25_module
    faiss_adapter = _faiss_module
    fixture_index = _fixture_module
    fusion = _fusion_module
    kg_mock = _kg_mock_module
    schemas = _schemas_module
    service = _service_module
    splade_index = _splade_module
    types = _types_module


def _load(name: str) -> ModuleType:
    """Lazily load a submodule by name and register it in sys.modules.

    Extended Summary
    ----------------
    Implements lazy module loading for the search_api package. When a submodule
    is accessed via __getattr__, this function imports the module, registers it
    in sys.modules under the package namespace, and returns it. This enables
    lazy loading of heavy dependencies (FAISS, BM25, etc.) until they are
    actually accessed.

    Parameters
    ----------
    name : str
        Submodule name (must be in _ALIASES). Examples: "app", "bm25_index",
        "faiss_adapter".

    Returns
    -------
    ModuleType
        Imported module instance registered in sys.modules.

    Notes
    -----
    Time O(1) amortized after first import. Side effect: modifies sys.modules
    to cache the loaded module. This function is internal to the lazy loading
    mechanism and should not be called directly by users.

    Examples
    --------
    >>> _load("app")
    <module 'search_api.app' from '...'>
    """
    module = import_module(_ALIASES[name])
    sys.modules[f"{__name__}.{name}"] = module
    return module


def __getattr__(name: str) -> ModuleType:
    """Lazily load submodules on attribute access.

    Extended Summary
    ----------------
    Implements PEP 562 __getattr__ for lazy module loading. When a submodule
    (e.g., search_api.app, search_api.bm25_index) is accessed, this function
    validates the name is exported in __all__, then lazily loads the module
    via _load(). This defers import costs until modules are actually used,
    improving startup time and enabling optional dependencies.

    Parameters
    ----------
    name : str
        Attribute name being accessed. Must be in __all__ (validated against
        _ALIASES).

    Returns
    -------
    ModuleType
        Lazily loaded submodule instance.

    Raises
    ------
    AttributeError
        If name is not in __all__ (not a valid submodule name).

    Notes
    -----
    Time O(1) amortized after first access per module. This is a Python
    special method called automatically when attribute access fails. Users
    should access modules normally (e.g., `from search_api import app`) rather
    than calling this directly.

    Examples
    --------
    >>> from search_api import app
    >>> app
    <module 'search_api.app' from '...'>

    >>> search_api.invalid_module
    Traceback (most recent call call):
        ...
    AttributeError: module 'search_api' has no attribute 'invalid_module'
    """
    if name not in _ALIASES:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message)
    return _load(name)


def __dir__() -> list[str]:
    """Return sorted list of public module names.

    Extended Summary
    ----------------
    Implements PEP 562 __dir__ to provide autocomplete and introspection
    support. Returns a sorted list of all public submodule names defined in
    __all__, enabling IDE autocomplete and dir() introspection.

    Returns
    -------
    list[str]
        Sorted list of public submodule names (same as __all__).

    Notes
    -----
    Time O(n log n) where n is the number of exported modules. This is a
    Python special method called by dir() and IDE autocomplete. The returned
    list matches __all__ but is sorted for consistent ordering.

    Examples
    --------
    >>> sorted(__dir__())
    ['app', 'bm25_index', 'faiss_adapter', 'fixture_index', ...]

    >>> import search_api
    >>> "app" in dir(search_api)
    True
    """
    return sorted(set(__all__))
