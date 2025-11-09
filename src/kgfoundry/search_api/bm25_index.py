"""Expose ``search_api.bm25_index`` inside the ``kgfoundry`` namespace."""

# [nav:section public-api]

from __future__ import annotations

from typing import cast

import search_api.bm25_index as _module
from kgfoundry.namespace_bridge import (
    namespace_attach,
    namespace_dir,
    namespace_getattr,
)
from kgfoundry_common.navmap_loader import load_nav_metadata
from search_api.bm25_index import BM25Doc, BM25Index, toks

__all__ = [
    "BM25Doc",
    "BM25Index",
    "toks",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


_namespace = cast("dict[str, object]", globals())
namespace_attach(_module, _namespace, __all__)


def __getattr__(name: str) -> object:
    """Forward attribute lookups to the underlying module.

    Provides a fallback for unknown attribute lookups, delegating
    to the namespace bridge helper.

    Parameters
    ----------
    name : str
        Attribute name to look up.

    Returns
    -------
    object
        Attribute value from the underlying module.
    """
    return namespace_getattr(_module, name)


def __dir__() -> list[str]:
    """Return the combined attribute listing.

    Returns
    -------
    list[str]
        Sorted union of exports and implementation attributes.
    """
    return namespace_dir(_module, __all__)
