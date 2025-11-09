"""Overview of catalog.

This module bundles catalog logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:
    from kgfoundry_common.problem_details import JsonValue


@dataclass(frozen=True)
class Concept:
    """Knowledge graph concept representation.

    Represents a concept in the ontology catalog with an identifier
    and optional human-readable label.

    Attributes
    ----------
    id : str
        Unique concept identifier (typically a URN).
    label : str | None
        Human-readable label for the concept. Defaults to None.
    """

    id: str
    label: str | None = None


__all__ = [
    "OntologyCatalog",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor OntologyCatalog]
class OntologyCatalog:
    """Utility catalog for lightweight ontology lookups.

    Provides a simple in-memory catalog for querying knowledge graph
    concepts. Supports neighbor traversal and concept hydration.

    Initializes the ontology catalog with concepts. Builds an internal index
    mapping concept IDs to concept objects for fast lookup.

    Parameters
    ----------
    concepts : list[Concept]
        List of concepts to include in the catalog.
    """

    def __init__(self, concepts: list[Concept]) -> None:
        self.by_id = {concept.id: concept for concept in concepts}

    def neighbors(self, concept_id: str, depth: int = 1) -> set[str]:
        """Return related concept identifiers up to the requested depth.

        Parameters
        ----------
        concept_id : str
            Concept identifier to find neighbors for.
        depth : int, optional
            Maximum depth to traverse. Defaults to 1.

        Returns
        -------
        set[str]
            Set of related concept identifiers.
        """
        if depth < 1:
            return set()
        concept = self.by_id.get(concept_id)
        if concept is None:
            return set()
        # Relationship edges are not yet modelled; return the seed concept for now so the
        # method remains total while we flesh out the backing data.
        return {concept.id}

    def hydrate(self, concept_id: str) -> dict[str, JsonValue]:
        """Return a JSON-serialisable view of the concept metadata.

        Parameters
        ----------
        concept_id : str
            Concept identifier to hydrate.

        Returns
        -------
        dict[str, JsonValue]
            JSON-serializable dictionary of concept metadata.
        """
        concept = self.by_id.get(concept_id)
        if concept is None:
            return {}
        payload: dict[str, JsonValue] = {"id": concept.id}
        if concept.label is not None:
            payload["label"] = concept.label
        return payload
