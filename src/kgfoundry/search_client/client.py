"""Expose ``search_client.client`` inside the ``kgfoundry`` namespace."""

# [nav:section public-api]

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import search_client.client as _module
from kgfoundry.tooling_bridge import namespace_dir, namespace_getattr
from kgfoundry_common.navmap_loader import load_nav_metadata
from search_client.client import (
    KGFoundryClient,
    RequestsHttp,
    SupportsHttp,
    SupportsResponse,
)

__all__ = [
    "KGFoundryClient",
    "RequestsHttp",
    "SupportsHttp",
    "SupportsResponse",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


_module_doc = cast("str | None", getattr(_module, "__doc__", None))
if isinstance(_module_doc, str):  # pragma: no branch - simple type guard
    __doc__ = _module_doc

_module_path = cast("Sequence[object] | None", getattr(_module, "__path__", None))
__path__ = [str(item) for item in _module_path] if isinstance(_module_path, Sequence) else []


def __getattr__(name: str) -> object:
    """Return ``name`` from the proxied ``search_client.client`` module.

    Parameters
    ----------
    name : str
        Attribute name to look up.

    Returns
    -------
    object
        Attribute value from the proxied module.
    """
    return namespace_getattr(_module, name)


def __dir__() -> list[str]:
    """Return the combined attribute listing exposed by the namespace bridge.

    Returns
    -------
    list[str]
        Combined list of attributes from the module and exports.
    """
    return namespace_dir(_module, __all__)
