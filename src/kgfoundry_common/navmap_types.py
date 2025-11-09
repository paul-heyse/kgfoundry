"""Overview of navmap types.

This module bundles navmap types logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "ModuleMeta",
    "NavMap",
    "NavSection",
    "Stability",
    "SymbolMeta",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))

# [nav:anchor Stability]
type Stability = Literal[
    "frozen",
    "stable",
    "experimental",
    "internal",
    "beta",
    "deprecated",
]


# [nav:anchor NavSection]
class NavSection(TypedDict):
    """Navigation section metadata grouped by documentation theme."""

    id: str
    """Unique section identifier.

    Alias: none; name ``id``.
    """
    title: str
    """Human-readable section title.

    Alias: none; name ``title``.
    """
    symbols: list[str]
    """Symbols contained in the section.

    Alias: none; name ``symbols``.
    """


# [nav:anchor SymbolMeta]
class SymbolMeta(TypedDict, total=False):
    """Symbol metadata for navigation, testing, and documentation tooling."""

    since: str
    """Version introducing the symbol.

    Alias: none; name ``since``.
    """
    stability: Stability
    """Current stability classification.

    Alias: none; name ``stability``.
    """
    side_effects: list[Literal["none", "fs", "net", "gpu", "db"]]
    """Declared side effects.

    Alias: none; name ``side_effects``.
    """
    thread_safety: Literal["reentrant", "threadsafe", "not-threadsafe"]
    """Thread-safety guarantee.

    Alias: none; name ``thread_safety``.
    """
    async_ok: bool
    """Whether usage is safe in async contexts.

    Alias: none; name ``async_ok``.
    """
    perf_budget_ms: float
    """Performance budget in milliseconds.

    Alias: none; name ``perf_budget_ms``.
    """
    tests: list[str]
    """Test artefacts verifying the symbol.

    Alias: none; name ``tests``.
    """
    owner: NotRequired[str]
    """Owning team handle.

    Alias: none; name ``owner``.
    """
    deprecated_in: NotRequired[str]
    """Version marking deprecation.

    Alias: none; name ``deprecated_in``.
    """
    replaced_by: NotRequired[str]
    """Replacement symbol path.

    Alias: none; name ``replaced_by``.
    """
    deprecated_msg: NotRequired[str]
    """Deprecation explanation.

    Alias: none; name ``deprecated_msg``.
    """
    contracts: NotRequired[list[str]]
    """Associated contract identifiers.

    Alias: none; name ``contracts``.
    """
    coverage_target: NotRequired[float]
    """Expected coverage target.

    Alias: none; name ``coverage_target``.
    """


# [nav:anchor ModuleMeta]
class ModuleMeta(TypedDict, total=False):
    """Module-level metadata surfaced in navigation artefacts."""

    owner: str
    """Owning team handle.

    Alias: none; name ``owner``.
    """
    stability: Stability
    """Module stability indicator.

    Alias: none; name ``stability``.
    """
    since: str
    """Version introducing the module.

    Alias: none; name ``since``.
    """
    deprecated_in: str
    """Version marking module deprecation.

    Alias: none; name ``deprecated_in``.
    """


# [nav:anchor NavMap]
class NavMap(TypedDict, total=False):
    """Navigation map metadata captured per module for documentation tooling."""

    title: str
    """Module title.

    Alias: none; name ``title``.
    """
    synopsis: str
    """Short summary of the module.

    Alias: none; name ``synopsis``.
    """
    exports: list[str]
    """Public export list.

    Alias: none; name ``exports``.
    """
    sections: list[NavSection]
    """Section definitions.

    Alias: none; name ``sections``.
    """
    see_also: list[str]
    """Related resources.

    Alias: none; name ``see_also``.
    """
    tags: list[str]
    """Tags for categorisation.

    Alias: none; name ``tags``.
    """
    since: str
    """Module introduction version.

    Alias: none; name ``since``.
    """
    deprecated: str
    """Module deprecation version.

    Alias: none; name ``deprecated``.
    """
    symbols: dict[str, SymbolMeta]
    """Symbol metadata mapping.

    Alias: none; name ``symbols``.
    """
    edit_scopes: dict[str, list[str]]
    """Edit scope assignments.

    Alias: none; name ``edit_scopes``.
    """
    deps: list[str]
    """Module dependencies.

    Alias: none; name ``deps``.
    """
    module_meta: ModuleMeta
    """Module-level metadata block.

    Alias: none; name ``module_meta``.
    """
