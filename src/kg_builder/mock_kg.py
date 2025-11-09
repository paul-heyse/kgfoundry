"""Overview of mock kg.

This module bundles mock kg logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "MockKG",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor MockKG]
class MockKG:
    """In-memory knowledge graph for testing and development.

    Provides a simple dictionary-based implementation of a knowledge graph with concept mentions and
    edges for use in tests and fixtures.

    Creates empty mappings for chunk-to-concepts and concept neighbors.
    """

    def __init__(self) -> None:
        self.chunk2concepts: dict[str, set[str]] = {}
        self.neighbors: dict[str, set[str]] = {}

    def add_mention(self, chunk_id: str, concept_id: str) -> None:
        """Record a concept mention in a chunk.

        Associates a concept with a chunk, creating the mapping if needed.

        Parameters
        ----------
        chunk_id : str
            Chunk identifier.
        concept_id : str
            Concept identifier.
        """
        self.chunk2concepts.setdefault(chunk_id, set()).add(concept_id)

    def add_edge(self, a: str, b: str) -> None:
        """Add a bidirectional edge between two concepts.

        Creates an undirected edge between concepts, adding both to each
        other's neighbor sets.

        Parameters
        ----------
        a : str
            First concept identifier.
        b : str
            Second concept identifier.
        """
        self.neighbors.setdefault(a, set()).add(b)
        self.neighbors.setdefault(b, set()).add(a)

    def linked_concepts(self, chunk_id: str) -> list[str]:
        """Return concepts linked to a chunk.

        Returns all concepts that have been mentioned in the given chunk,
        sorted alphabetically.

        Parameters
        ----------
        chunk_id : str
            Chunk identifier.

        Returns
        -------
        list[str]
            Sorted list of concept IDs linked to the chunk.
        """
        return sorted(self.chunk2concepts.get(chunk_id, set()))

    def one_hop(self, concept_id: str) -> list[str]:
        """Return one-hop neighbors of a concept.

        Returns all concepts directly connected to the given concept via
        edges, sorted alphabetically.

        Parameters
        ----------
        concept_id : str
            Concept identifier.

        Returns
        -------
        list[str]
            Sorted list of neighbor concept IDs.
        """
        return sorted(self.neighbors.get(concept_id, set()))
