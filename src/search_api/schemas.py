"""Overview of schemas.

This module bundles schemas logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, ClassVar

from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.pydantic import BaseModel
from kgfoundry_common.typing import gate_import

if TYPE_CHECKING:
    from pydantic import ConfigDict, Field

    from kgfoundry_common.types import JsonValue
else:
    JsonValue = importlib.import_module("kgfoundry_common.types").JsonValue
    _pydantic = gate_import("pydantic", "search API schemas")
    ConfigDict = _pydantic.ConfigDict
    Field = _pydantic.Field

__all__ = [
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor SearchResponse]
class SearchResponse(BaseModel):
    """Search API response envelope containing ordered results."""

    model_config: ClassVar[object] = ConfigDict(extra="forbid")
    """Pydantic configuration forbidding unexpected fields."""

    results: list[SearchResult] = Field(default_factory=list)
    """Ordered search results.

    Alias: none; name ``results``.
    """


# [nav:anchor SearchRequest]
class SearchRequest(BaseModel):
    """Search API request payload with optional filters and explain flag.

    Attributes
    ----------
    model_config : ClassVar[object]
        Pydantic configuration forbidding extra parameters.
    query : str
        Search query string (at least one character).
    k : int
        Number of results to return.
    filters : dict[str, JsonValue] | None
        Optional filters keyed by field.
    explain : bool
        Include explanation metadata flag.

    Examples
    --------
    >>> from pathlib import Path
    >>> from kgfoundry_common.schema_helpers import assert_model_roundtrip
    >>> example_path = (
    ...     Path(__file__).parent.parent.parent
    ...     / "schema"
    ...     / "examples"
    ...     / "search_api"
    ...     / "search_request.v1.json"
    ... )
    >>> assert_model_roundtrip(SearchRequest, example_path)
    """

    model_config: ClassVar[object] = ConfigDict(extra="forbid")
    """Pydantic configuration forbidding extra parameters."""

    query: str = Field(min_length=1)
    """Search query string (at least one character).

    Alias: none; name ``query``.
    """
    k: int = 10
    """Number of results to return.

    Alias: none; name ``k``.
    """
    filters: dict[str, JsonValue] | None = None
    """Optional filters keyed by field.

    Alias: none; name ``filters``.
    """
    explain: bool = False
    """Include explanation metadata flag.

    Alias: none; name ``explain``.
    """


# [nav:anchor SearchResult]
class SearchResult(BaseModel):
    """Search result model combining identifiers, score, and auxiliary signals.

    Attributes
    ----------
    model_config : ClassVar[object]
        Pydantic configuration forbidding extra fields.
    doc_id : str
        Document identifier.
    chunk_id : str
        Chunk identifier.
    title : str
        Document title.
    section : str
        Section label.
    score : float
        Relevance score.
    signals : dict[str, float]
        Signal scores (dense, sparse, kg).
    spans : dict[str, int]
        Character spans associated with the result.
    concepts : list[dict[str, str]]
        Linked concept metadata.

    Examples
    --------
    >>> from pathlib import Path
    >>> from kgfoundry_common.schema_helpers import assert_model_roundtrip
    >>> example_path = (
    ...     Path(__file__).parent.parent.parent
    ...     / "schema"
    ...     / "examples"
    ...     / "search_api"
    ...     / "search_result.v1.json"
    ... )
    >>> assert_model_roundtrip(SearchResult, example_path)
    """

    model_config: ClassVar[object] = ConfigDict(extra="forbid")
    """Pydantic configuration forbidding extra fields."""

    doc_id: str
    """Document identifier.

    Alias: none; name ``doc_id``.
    """
    chunk_id: str
    """Chunk identifier.

    Alias: none; name ``chunk_id``.
    """
    title: str
    """Document title.

    Alias: none; name ``title``.
    """
    section: str
    """Section label.

    Alias: none; name ``section``.
    """
    score: float
    """Relevance score.

    Alias: none; name ``score``.
    """
    signals: dict[str, float] = Field(default_factory=dict)
    """Signal scores (dense, sparse, kg).

    Alias: none; name ``signals``.
    """
    spans: dict[str, int] = Field(default_factory=dict)
    """Character spans associated with the result.

    Alias: none; name ``spans``.
    """
    concepts: list[dict[str, str]] = Field(default_factory=list)
    """Linked concept metadata.

    Alias: none; name ``concepts``.
    """
