"""Public adapters for bridging tooling namespaces into the ``kgfoundry`` package.

These helpers delegate to the internal :mod:`kgfoundry._namespace_proxy` module while
providing typed, documented entry points for downstream packages. They are the
supported way to expose third-party modules (for example, ``search_client``) under
the ``kgfoundry`` namespace.

Install the ``kgfoundry[tools]`` optional extra to ensure the tooling package is
available in the current environment before importing this module.
"""

# [nav:section public-api]

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING
from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:
    from collections.abc import Iterable, MutableMapping
    from types import ModuleType

_namespace_proxy = import_module("kgfoundry._namespace_proxy")
NamespaceRegistry = getattr(_namespace_proxy, "NamespaceRegistry")
namespace_attach = getattr(_namespace_proxy, "namespace_attach")
namespace_dir = getattr(_namespace_proxy, "namespace_dir")
namespace_exports = getattr(_namespace_proxy, "namespace_exports")
namespace_getattr = getattr(_namespace_proxy, "namespace_getattr")

__all__ = ["NamespaceRegistry", "namespace_attach", "namespace_dir", "namespace_exports", "namespace_getattr"]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor namespace_attach]
def namespace_attach(
    module: ModuleType,
    target: MutableMapping[str, object],
    names: Iterable[str],
) -> None:
    """Populate ``target`` with ``names`` sourced from ``module``.

    Parameters
    ----------
    module : ModuleType
        The module whose attributes are being proxied (for example, a
        third-party package).
    target : MutableMapping[str, object]
        The namespace to populate, typically ``globals()`` of the bridge module.
    names : Iterable[str]
        The attribute names that should be exposed publicly.
    """
    _namespace_attach(module, target, names)


# [nav:anchor namespace_exports]
def namespace_exports(module: ModuleType) -> list[str]:
    """Return the public export list for ``module``.

    The helper respects ``__all__`` when present and otherwise derives a sensible
    default by filtering out private attributes.

    Parameters
    ----------
    module : ModuleType
        The module whose exports are being queried.

    Returns
    -------
    list[str]
        List of public export names.
    """
    return _namespace_exports(module)


# [nav:anchor namespace_dir]
def namespace_dir(module: ModuleType, exports: Iterable[str]) -> list[str]:
    """Compose the ``dir()`` listing for a proxied module.

    Parameters
    ----------
    module : ModuleType
        The module whose attributes are being surfaced.
    exports : Iterable[str]
        The attribute names explicitly exposed by the bridge.

    Returns
    -------
    list[str]
        A sorted list of attribute names that should appear in ``dir()`` output.
    """
    return _namespace_dir(module, exports)


# [nav:anchor namespace_getattr]
def namespace_getattr(module: ModuleType, name: str) -> object:
    """Resolve ``name`` from ``module`` while preserving the original attribute.

    Parameters
    ----------
    module : ModuleType
        The module whose attribute is being accessed.
    name : str
        The attribute name to resolve.

    Returns
    -------
    object
        The attribute value from the module.
    """
    return _namespace_getattr(module, name)


NamespaceRegistry = _NamespaceRegistry
