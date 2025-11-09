"""Overview of kgfoundry.

This module bundles kgfoundry logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import sys
from importlib import import_module
from typing import TYPE_CHECKING as _TYPE_CHECKING

from kgfoundry_common.navmap_loader import load_nav_metadata

_ALIASES: dict[str, str] = {
    "docling_kg": "kgfoundry.docling_kg",
    "download": "kgfoundry.download",
    "embeddings_dense": "kgfoundry.embeddings_dense",
    "embeddings_sparse": "kgfoundry.embeddings_sparse",
    "kg_builder": "kgfoundry.kg_builder",
    "kgfoundry_common": "kgfoundry_common",
    "linking": "kgfoundry.linking",
    "observability": "kgfoundry.observability",
    "ontology": "kgfoundry.ontology",
    "orchestration": "kgfoundry.orchestration",
    "registry": "kgfoundry.registry",
    "search_api": "kgfoundry.search_api",
    "search_client": "kgfoundry.search_client",
    "vectorstore_faiss": "kgfoundry.vectorstore_faiss",
}

__all__ = [
    "docling_kg",
    "download",
    "embeddings_dense",
    "embeddings_sparse",
    "kg_builder",
    "kgfoundry_common",
    "linking",
    "observability",
    "ontology",
    "orchestration",
    "registry",
    "search_api",
    "search_client",
    "vectorstore_faiss",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# Remove the helper introduced by ``from __future__ import annotations`` so Griffe
# does not interpret it as a public alias (it points to ``__future__.annotations``).
globals().pop("annotations", None)

# Provide a benign placeholder so static analysers see a concrete value rather than
# the ``__future__`` alias (the name is not exported via ``__all__``).
annotations = None

if __debug__:
    expected: set[str] = set(_ALIASES)
    configured: set[str] = set(__all__)
    if expected != configured:
        missing = sorted(expected.difference(configured))
        extra = sorted(configured.difference(expected))
        message = f"kgfoundry exports mismatch. missing={missing!r} extra={extra!r}"
        raise RuntimeError(message)

if _TYPE_CHECKING:
    from importlib import import_module as _import_module
    from types import ModuleType

    kgfoundry_common: ModuleType = _import_module("kgfoundry_common")
    docling_kg: ModuleType = _import_module("kgfoundry.docling_kg")
    download: ModuleType = _import_module("kgfoundry.download")
    embeddings_dense: ModuleType = _import_module("kgfoundry.embeddings_dense")
    embeddings_sparse: ModuleType = _import_module("kgfoundry.embeddings_sparse")
    kg_builder: ModuleType = _import_module("kgfoundry.kg_builder")
    linking: ModuleType = _import_module("kgfoundry.linking")
    observability: ModuleType = _import_module("kgfoundry.observability")
    ontology: ModuleType = _import_module("kgfoundry.ontology")
    orchestration: ModuleType = _import_module("kgfoundry.orchestration")
    registry: ModuleType = _import_module("kgfoundry.registry")
    search_api: ModuleType = _import_module("kgfoundry.search_api")
    search_client: ModuleType = _import_module("kgfoundry.search_client")
    vectorstore_faiss: ModuleType = _import_module("kgfoundry.vectorstore_faiss")

del _TYPE_CHECKING


def _load(name: str) -> object:
    """Load a module by alias name.

    Dynamically imports a module using its alias from the _ALIASES mapping
    and registers it in sys.modules under the kgfoundry namespace.

    Parameters
    ----------
    name : str
        Alias name of the module to load (e.g., "docling_kg", "search_api").

    Returns
    -------
    object
        The imported module object.
    """
    module = import_module(_ALIASES[name])
    sys.modules[f"{__name__}.{name}"] = module
    return module


def __getattr__(name: str) -> object:
    """Provide lazy module loading for namespace bridge.

    Implements lazy loading for submodules in the kgfoundry package.
    When a submodule is accessed (e.g., `kgfoundry.docling_kg`), it is
    dynamically imported and cached in sys.modules.

    Parameters
    ----------
    name : str
        Submodule name to import (e.g., "docling_kg", "search_api").

    Returns
    -------
    object
        Imported module object.

    Raises
    ------
    AttributeError
        If the requested name is not in the _ALIASES dictionary.
    """
    if name not in _ALIASES:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message) from None
    return _load(name)


def __dir__() -> list[str]:
    """Return the combined attribute listing.

    Returns the sorted union of exports and implementation attributes
    from the namespace bridge.

    Returns
    -------
    list[str]
        Sorted union of exports and implementation attributes.
    """
    return sorted(set(__all__))


def _ensure_namespace_alias(name: str) -> None:
    """Ensure a namespace alias is loaded in sys.modules.

    Checks if the namespace alias is already loaded, and if not,
    loads it using _load(). Used internally to ensure modules are
    available when needed.

    Parameters
    ----------
    name : str
        Alias name of the module to ensure is loaded.
    """
    if f"{__name__}.{name}" not in sys.modules:
        _load(name)
