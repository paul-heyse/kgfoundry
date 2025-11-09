"""Overview of fusion.

This module bundles fusion logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "rrf_fuse",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor rrf_fuse]
def rrf_fuse(
    rankers: list[list[tuple[str, float]]], k_rrf: int = 60
) -> dict[str, float]:
    """Fuse multiple ranked lists using Reciprocal Rank Fusion (RRF).

    Combines multiple ranked lists into a single fused ranking by summing
    reciprocal rank scores across all lists. Items appearing in multiple
    lists receive higher scores.

    Parameters
    ----------
    rankers : list[list[tuple[str, float]]]
        List of ranked lists, where each inner list contains (item_id, score)
        tuples sorted by score (descending).
    k_rrf : int, optional
        RRF constant used to dampen the contribution of lower ranks.
        Defaults to 60.

    Returns
    -------
    dict[str, float]
        Dictionary mapping item IDs to their fused RRF scores.
    """
    agg: dict[str, float] = {}
    for ranked in rankers:
        for r, (key, _score) in enumerate(ranked, start=1):
            agg[key] = agg.get(key, 0.0) + 1.0 / (k_rrf + r)
    return agg
