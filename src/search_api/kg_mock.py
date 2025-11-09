"""Overview of kg mock.

This module bundles kg mock logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

from typing import Final, TypedDict

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "detect_query_concepts",
    "kg_boost",
    "linked_concepts_for_text",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


class ConceptMeta(TypedDict):
    """Metadata for knowledge graph concepts used by mock scoring."""

    label: str
    """Human-readable concept label.

    Alias: none; name ``label``.
    """
    keywords: list[str]
    """Keywords associated with the concept.

    Alias: none; name ``keywords``.
    """


CONCEPTS: Final[dict[str, ConceptMeta]] = {
    "urn:concept:toy:LLM": {
        "label": "Large Language Model",
        "keywords": ["llm", "language model", "transformer"],
    },
    "urn:concept:toy:Alignment": {
        "label": "Alignment",
        "keywords": ["alignment", "safety", "rlhf"],
    },
}


# [nav:anchor detect_query_concepts]
def detect_query_concepts(query: str) -> set[str]:
    """Detect knowledge graph concepts mentioned in a query.

    Searches for concept keywords in the query text and returns matching
    concept IDs from the mock knowledge graph.

    Parameters
    ----------
    query : str
        Query text to analyze for concept mentions.

    Returns
    -------
    set[str]
        Set of concept IDs that match keywords in the query.
    """
    lowered = query.lower()
    hits: set[str] = set()
    for concept_id, meta in CONCEPTS.items():
        if any(keyword in lowered for keyword in meta["keywords"]):
            hits.add(concept_id)
    return hits


# [nav:anchor linked_concepts_for_text]
def linked_concepts_for_text(text: str) -> list[str]:
    """Find knowledge graph concepts linked to text content.

    Searches for concept keywords in the text and returns matching
    concept IDs from the mock knowledge graph.

    Parameters
    ----------
    text : str
        Text content to analyze for concept mentions.

    Returns
    -------
    list[str]
        List of concept IDs that match keywords in the text.
    """
    lowered = text.lower()
    hits = []
    for concept_id, meta in CONCEPTS.items():
        if any(keyword in lowered for keyword in meta["keywords"]):
            hits.append(concept_id)
    return hits


# [nav:anchor kg_boost]
def kg_boost(
    query_concepts: list[str],
    chunk_concepts: list[str],
    direct: float = 0.08,
    one_hop: float = 0.04,
) -> float:
    """Calculate knowledge graph boost score for a chunk.

    Computes a boost score based on concept overlap between query and chunk.
    Returns direct boost if there are direct concept matches, otherwise 0.0.
    The one_hop parameter is reserved for future graph traversal heuristics.

    Parameters
    ----------
    query_concepts : list[str]
        List of concept IDs extracted from the query.
    chunk_concepts : list[str]
        List of concept IDs linked to the chunk.
    direct : float, optional
        Boost amount for direct concept matches. Defaults to 0.08.
    one_hop : float, optional
        Boost amount for one-hop concept matches (currently unused).
        Defaults to 0.04.

    Returns
    -------
    float
        Boost score (direct if concepts overlap, otherwise 0.0).
    """
    _ = one_hop  # placeholder for future graph traversal heuristics
    return direct if set(query_concepts) & set(chunk_concepts) else 0.0
