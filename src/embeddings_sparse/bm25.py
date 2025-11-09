"""Overview of bm25.

This module bundles bm25 logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, cast

from kgfoundry_common.errors import DeserializationError
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.safe_pickle_v2 import (
    UnsafeSerializationError,
    load_unsigned_legacy,
)
from kgfoundry_common.serialization import deserialize_json, serialize_json

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from re import Pattern

    from kgfoundry_common.problem_details import JsonValue

logger = logging.getLogger(__name__)

_BM25_SCHEMA_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2] / "schema" / "models" / "bm25_metadata.v1.json"
)

_DEFAULT_FIELD_BOOSTS: Final[dict[str, float]] = {
    "title": 2.0,
    "section": 1.2,
    "body": 1.0,
}


def _normalize_field_boosts(boosts: Mapping[str, float] | None) -> dict[str, float]:
    if boosts is None:
        return dict(_DEFAULT_FIELD_BOOSTS)
    normalized: dict[str, float] = {}
    for field_name, value in boosts.items():
        normalized[str(field_name)] = float(value)
    return normalized


__all__ = [
    "BM25Doc",
    "LuceneBM25",
    "PurePythonBM25",
    "get_bm25",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


def _load_json_metadata(metadata_path: Path, schema_path: Path) -> dict[str, JsonValue]:
    data_raw = deserialize_json(metadata_path, schema_path)
    if not isinstance(data_raw, dict):
        msg = f"Invalid index data format: expected dict, got {type(data_raw)}"
        raise DeserializationError(msg)
    return cast("dict[str, JsonValue]", data_raw)


TOKEN_RE: Pattern[str] = re.compile(r"[A-Za-z0-9_]+")


def _default_int_dict() -> defaultdict[str, int]:
    return defaultdict(int)


class LuceneHitProtocol(Protocol):
    """Protocol describing a single Lucene BM25 hit."""

    docid: str
    score: float


class LuceneSearcherProtocol(Protocol):
    """Protocol for Lucene searchers supporting BM25 configuration."""

    def set_bm25(self, k1: float, b: float) -> None:
        """Configure the BM25 parameters used by the underlying index."""
        ...

    def search(self, query: str, k: int) -> Sequence[LuceneHitProtocol]:
        """Return the top ``k`` hits for ``query`` using the active BM25 settings."""
        ...


class LuceneIndexerProtocol(Protocol):
    """Protocol for Lucene index writers used by the BM25 adapters."""

    def add_doc_dict(self, doc: Mapping[str, str]) -> None:
        """Add a document mapping to the Lucene index."""
        ...

    def close(self) -> None:
        """Finalize the index writer and flush in-memory buffers."""
        ...


class LuceneSearcherFactory(Protocol):
    """Factory protocol for creating Lucene BM25 searchers."""

    def __call__(self, index_dir: str) -> LuceneSearcherProtocol:
        """Return a searcher bound to ``index_dir``."""
        ...


class LuceneIndexerFactory(Protocol):
    """Factory protocol for instantiating Lucene BM25 indexers."""

    def __call__(self, index_dir: str) -> LuceneIndexerProtocol:
        """Create an indexer that writes into ``index_dir``."""
        ...


def _score_value(item: tuple[str, float]) -> float:
    return item[1]


# [nav:anchor BM25Doc]
@dataclass(frozen=True)
class BM25Doc:
    """Represent a document stored in the in-memory BM25 index.

    Stores document metadata, term frequencies, and field content for BM25
    scoring. Used by both PurePythonBM25 and LuceneBM25 implementations.

    Attributes
    ----------
    doc_id : str
        Unique document identifier.
    length : int
        Total number of tokens in the document (sum of all term frequencies).
    fields : dict[str, str]
        Document field content dictionary containing "title", "section", and
        "body" fields.
    term_freqs : dict[str, int]
        Term frequency dictionary mapping token strings to their occurrence
        counts in this document. Defaults to empty dict.
    """

    doc_id: str
    length: int
    fields: dict[str, str]
    term_freqs: dict[str, int] = field(default_factory=dict)


# [nav:anchor PurePythonBM25]
class PurePythonBM25:
    """Pure Python BM25 implementation backed by simple in-memory data structures.

    Implements BM25 ranking algorithm using Python dictionaries and lists
    without external dependencies. Suitable for small to medium-sized indexes
    that fit in memory.

    Sets up BM25 scoring parameters and initializes empty data structures
    for documents, postings, and document frequencies.

    Parameters
    ----------
    index_dir : str
        Directory path where index metadata will be stored. Created if it
        doesn't exist.
    k1 : float, optional
        Term frequency saturation parameter. Controls how quickly term frequency
        saturates. Higher values allow more influence from repeated terms.
        Defaults to 0.9.
    b : float, optional
        Document length normalization parameter. Controls the degree of length
        normalization. Values closer to 1.0 normalize more aggressively.
        Defaults to 0.4.
    field_boosts : Mapping[str, float] | None, optional
        Optional mapping of field names to boost weights. Fields with higher
        boosts contribute more to relevance scores. Normalized and merged with
        default boosts. Defaults to None (uses default boosts: title=2.0, section=1.2, body=1.0).

    Notes
    -----
    The implementation uses in-memory data structures and is suitable for
    indexes that fit in RAM. For larger indexes, consider using LuceneBM25
    which uses Pyserini's disk-backed Lucene index.
    """

    def __init__(
        self,
        index_dir: str,
        k1: float = 0.9,
        b: float = 0.4,
        field_boosts: Mapping[str, float] | None = None,
    ) -> None:
        self.index_dir = index_dir
        self.k1 = k1
        self.b = b
        self.field_boosts = _normalize_field_boosts(field_boosts)
        self.df: dict[str, int] = {}
        self.postings: dict[str, dict[str, int]] = {}
        self.docs: dict[str, BM25Doc] = {}
        self.N = 0
        self.avgdl = 0.0

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text with a simple alphanumeric regex.

        Extracts alphanumeric sequences (including underscores) from text and
        converts them to lowercase for case-insensitive matching.

        Parameters
        ----------
        text : str
            Input text to tokenize. May be empty.

        Returns
        -------
        list[str]
            List of lowercase tokens extracted from the text. Empty list if
            input contains no alphanumeric sequences.
        """
        matches = cast("list[str]", TOKEN_RE.findall(text))
        return [token.lower() for token in matches]

    def _create_doc(
        self,
        doc_id: str,
        fields: Mapping[str, str],
        df: defaultdict[str, int],
        postings: defaultdict[str, defaultdict[str, int]],
    ) -> BM25Doc:
        title = fields.get("title", "")
        section = fields.get("section", "")
        body = fields.get("body", "")
        text = " ".join(part for part in (title, section, body) if part)
        tokens = self._tokenize(text)
        seen: set[str] = set()
        term_freqs: defaultdict[str, int] = defaultdict(int)
        for token in tokens:
            term_freqs[token] += 1
            postings[token][doc_id] += 1
            if token not in seen:
                df[token] += 1
                seen.add(token)
        return BM25Doc(
            doc_id=doc_id,
            length=len(tokens),
            fields={"title": title, "section": section, "body": body},
            term_freqs={term: int(count) for term, count in term_freqs.items()},
        )

    def build(self, docs_iterable: Iterable[tuple[str, dict[str, str]]]) -> None:
        """Build postings and document statistics for the BM25 index.

        Processes an iterable of documents, computes term frequencies and
        document frequencies, and serializes the index metadata to disk with
        schema validation.

        Parameters
        ----------
        docs_iterable : Iterable[tuple[str, dict[str, str]]]
            Iterable of (doc_id, fields) tuples. Each fields dictionary should
            contain "title", "section", and "body" keys with string values.

        Notes
        -----
        This method clears any existing index state and rebuilds from scratch.
        After processing all documents, it computes average document length
        and writes metadata to `pure_bm25.json` in the index directory with
        schema validation and checksum verification.
        """
        Path(self.index_dir).mkdir(parents=True, exist_ok=True)
        df: defaultdict[str, int] = defaultdict(int)
        postings: defaultdict[str, defaultdict[str, int]] = defaultdict(_default_int_dict)
        docs: dict[str, BM25Doc] = {}
        lengths: list[int] = []
        for doc_id, fields in docs_iterable:
            doc = self._create_doc(doc_id, fields, df, postings)
            docs[doc_id] = doc
            lengths.append(doc.length)
        self.N = len(docs)
        self.avgdl = (sum(lengths) / self.N) if self.N else 0.0
        self.df = dict(df)
        self.postings = {term: dict(term_postings) for term, term_postings in postings.items()}
        self.docs = docs
        metadata_path = Path(self.index_dir) / "pure_bm25.json"
        serialize_json(self._metadata_payload(), _BM25_SCHEMA_PATH, metadata_path)

    def load(self) -> None:
        """Load an existing BM25 index from disk.

        Performs schema validation and checksum verification.
        """
        payload = self._read_metadata()
        self._initialize_from_payload(payload)

    def _metadata_payload(self) -> dict[str, JsonValue]:
        docs_data: list[JsonValue] = [
            {
                "chunk_id": doc_id,
                "doc_id": doc_id,
                "title": doc.fields.get("title", ""),
                "section": doc.fields.get("section", ""),
                "body": doc.fields.get("body", ""),
                "tf": {term: int(freq) for term, freq in doc.term_freqs.items()},
                "dl": float(doc.length),
            }
            for doc_id, doc in self.docs.items()
        ]
        payload: dict[str, JsonValue] = {
            "k1": float(self.k1),
            "b": float(self.b),
            "field_boosts": {
                field_name: float(weight) for field_name, weight in self.field_boosts.items()
            },
            "df": {term: int(count) for term, count in self.df.items()},
            "postings": {
                term: {doc_id: int(freq) for doc_id, freq in posting.items()}
                for term, posting in self.postings.items()
            },
            "docs": docs_data,
            "N": int(self.N),
            "avgdl": float(self.avgdl),
        }
        return payload

    def _read_metadata(self) -> dict[str, JsonValue]:
        metadata_path = Path(self.index_dir) / "pure_bm25.json"
        legacy_path = Path(self.index_dir) / "pure_bm25.pkl"

        if metadata_path.exists():
            try:
                return _load_json_metadata(metadata_path, _BM25_SCHEMA_PATH)
            except DeserializationError as exc:
                logger.warning("Failed to load JSON index, trying legacy pickle: %s", exc)
                if legacy_path.exists():
                    return self._load_legacy_payload(legacy_path)
                raise

        if legacy_path.exists():
            payload = self._load_legacy_payload(legacy_path)
            logger.warning("Loaded legacy pickle index. Consider migrating to JSON format.")
            return payload

        msg = f"Index metadata not found at {metadata_path} or {legacy_path}"
        raise FileNotFoundError(msg)

    @staticmethod
    def _load_legacy_payload(legacy_path: Path) -> dict[str, JsonValue]:
        with legacy_path.open("rb") as handle:
            try:
                payload = load_unsigned_legacy(handle)
            except UnsafeSerializationError as legacy_exc:
                msg = f"Legacy pickle data failed allow-list validation: {legacy_exc}"
                raise DeserializationError(msg) from legacy_exc
        if not isinstance(payload, dict):
            msg = f"Invalid pickle data format: expected dict, got {type(payload)}"
            raise DeserializationError(msg)
        return cast("dict[str, JsonValue]", payload)

    def _initialize_from_payload(self, data: Mapping[str, JsonValue]) -> None:
        self._apply_scalar_metadata(data)
        self.docs = self._build_docs_from_metadata(data)
        postings_val = data.get("postings", {})
        self.postings = (
            cast("dict[str, dict[str, int]]", postings_val)
            if isinstance(postings_val, dict)
            else {}
        )

    def _apply_scalar_metadata(self, data: Mapping[str, JsonValue]) -> None:
        k1_val = data.get("k1", 0.9)
        b_val = data.get("b", 0.4)
        self.k1 = float(k1_val) if isinstance(k1_val, (int, float)) else 0.9
        self.b = float(b_val) if isinstance(b_val, (int, float)) else 0.4
        field_boosts_val = data.get("field_boosts", _DEFAULT_FIELD_BOOSTS)
        if isinstance(field_boosts_val, Mapping):
            self.field_boosts = _normalize_field_boosts(
                cast("Mapping[str, float]", field_boosts_val)
            )
        else:
            self.field_boosts = dict(_DEFAULT_FIELD_BOOSTS)
        df_val = data.get("df", {})
        self.df = cast("dict[str, int]", df_val) if isinstance(df_val, dict) else {}
        n_val = data.get("N", 0)
        avgdl_val = data.get("avgdl", 0.0)
        self.N = int(n_val) if isinstance(n_val, (int, float)) else 0
        self.avgdl = float(avgdl_val) if isinstance(avgdl_val, (int, float)) else 0.0

    @staticmethod
    def _build_docs_from_metadata(data: Mapping[str, JsonValue]) -> dict[str, BM25Doc]:
        docs_data_raw = data.get("docs", [])
        if isinstance(docs_data_raw, list) and docs_data_raw:
            docs: dict[str, BM25Doc] = {}
            for doc_value in docs_data_raw:
                if not isinstance(doc_value, dict):
                    continue
                doc_id_raw = doc_value.get("doc_id") or doc_value.get("chunk_id")
                doc_id = str(doc_id_raw) if doc_id_raw is not None else ""
                if not doc_id:
                    continue
                length_val = doc_value.get("dl", doc_value.get("length", 0))
                length = int(length_val) if isinstance(length_val, (int, float)) else 0
                title = str(doc_value.get("title", ""))
                section = str(doc_value.get("section", ""))
                body = str(doc_value.get("body", ""))
                tf_raw = doc_value.get("tf", doc_value.get("term_freqs", {}))
                tf_map = (
                    {
                        str(term): int(freq)
                        for term, freq in cast("dict[object, object]", tf_raw).items()
                        if isinstance(term, str) and isinstance(freq, (int, float))
                    }
                    if isinstance(tf_raw, dict)
                    else {}
                )
                docs[doc_id] = BM25Doc(
                    doc_id=doc_id,
                    length=length,
                    fields={"title": title, "section": section, "body": body},
                    term_freqs=tf_map,
                )
            return docs

        docs_val = data.get("docs", {})
        if isinstance(docs_val, dict):
            return cast("dict[str, BM25Doc]", docs_val)
        return {}

    def _idf(self, term: str) -> float:
        """Compute the inverse document frequency for a given term.

        Calculates IDF using the BM25 formula: log((N - df + 0.5) / (df + 0.5) + 1.0)
        where N is the total number of documents and df is the document frequency.

        Parameters
        ----------
        term : str
            Token string to compute IDF for.

        Returns
        -------
        float
            IDF score for the term. Returns 0.0 if the term does not appear
            in any document or if the index is empty.

        Notes
        -----
        Uses the standard BM25 IDF formula with smoothing to avoid division by
        zero. The 0.5 smoothing factor prevents negative IDF values for terms
        appearing in all documents.
        """
        n_t = self.df.get(term, 0)
        if n_t == 0:
            return 0.0
        # BM25 idf variant
        return math.log((self.N - n_t + 0.5) / (n_t + 0.5) + 1.0)

    def search(
        self,
        query: str,
        k: int,
        fields: Mapping[str, str] | None = None,
    ) -> list[tuple[str, float]]:
        """Score documents stored in the in-memory BM25 index.

        Tokenizes the query (and optional field values), computes BM25 relevance
        scores for all documents, and returns the top-k results sorted by score
        in descending order.

        Parameters
        ----------
        query : str
            Search query string to tokenize and match against documents.
        k : int
            Maximum number of results to return.
        fields : Mapping[str, str] | None, optional
            Optional field mapping for query expansion. If provided, field
            values are tokenized and added to the query tokens. Defaults to None.

        Returns
        -------
        list[tuple[str, float]]
            List of (doc_id, score) tuples sorted by score descending. Only
            includes documents with score > 0.0. Returns empty list if index is
            empty or no documents match.

        Notes
        -----
        BM25 scoring combines term frequency (TF), inverse document frequency
        (IDF), and document length normalization. The implementation uses naive
        field weighting where terms from different fields contribute equally
        to the final score.
        """
        # naive field weighting at score aggregation (title/section/body contributions)
        tokens = self._tokenize(query)
        if fields:
            for text in fields.values():
                tokens.extend(self._tokenize(text))
        scores: defaultdict[str, float] = defaultdict(float)
        for term in tokens:
            idf = self._idf(term)
            postings = self.postings.get(term)
            if not postings:
                continue
            for doc_id, tf in postings.items():
                doc = self.docs[doc_id]
                dl = doc.length or 1
                denom = tf + self.k1 * (1 - self.b + self.b * (dl / self.avgdl))
                contrib = idf * ((tf * (self.k1 + 1)) / (denom))
                scores[doc_id] += contrib
        ranked_scores: list[tuple[str, float]] = [
            (doc_id, score) for doc_id, score in scores.items()
        ]
        ranked_scores.sort(key=_score_value, reverse=True)
        return ranked_scores[:k]


# [nav:anchor LuceneBM25]
class LuceneBM25:
    """Wrap Pyserini's Lucene BM25 indexer with project defaults.

    Provides a BM25 implementation backed by Apache Lucene via Pyserini.
    Suitable for large indexes that benefit from disk-backed storage and
    optimized search performance.

    Initializes the Lucene-backed BM25 adapter with index directory and scoring parameters.

    Parameters
    ----------
    index_dir : str
        Path to the Lucene index directory on disk.
    k1 : float, optional
        BM25 term saturation parameter forwarded to Pyserini. Controls how quickly
        term frequency saturates. Higher values allow more influence from repeated terms.
        Defaults to 0.9.
    b : float, optional
        BM25 document length normalization parameter. Controls the degree of length
        normalization. Values closer to 1.0 normalize more aggressively.
        Defaults to 0.4.
    field_boosts : Mapping[str, float] | None, optional
        Optional mapping of field names to boost weights. Used when composing
        Lucene query strings with field-specific boosts. Normalized and merged with
        default boosts. Defaults to None (uses default boosts: title=2.0, section=1.2, body=1.0).

    Notes
    -----
    Requires the optional ``pyserini`` dependency. Import errors propagate as
    :class:`RuntimeError` when helper factories are loaded. The searcher is
    lazy-initialized on first search call to avoid unnecessary index loading.
    """

    def __init__(
        self,
        index_dir: str,
        k1: float = 0.9,
        b: float = 0.4,
        field_boosts: Mapping[str, float] | None = None,
    ) -> None:
        self.index_dir = index_dir
        self.k1 = k1
        self.b = b
        self.field_boosts = _normalize_field_boosts(field_boosts)
        self._indexer_factory = _load_lucene_indexer_factory()
        self._searcher_factory = _load_lucene_searcher_factory()
        self._searcher: LuceneSearcherProtocol | None = None

    def build(self, docs_iterable: Iterable[tuple[str, dict[str, str]]]) -> None:
        """Stream documents into a Lucene index using Pyserini."""
        Path(self.index_dir).mkdir(parents=True, exist_ok=True)
        indexer = self._indexer_factory(self.index_dir)
        try:
            for doc_id, fields in docs_iterable:
                indexer.add_doc_dict(self._build_lucene_doc(doc_id, fields))
        finally:
            indexer.close()

    def load(self) -> None:
        """Ensure a Lucene searcher can be constructed for the configured index."""
        self._searcher = None
        self._ensure_searcher()

    def search(
        self,
        query: str,
        k: int,
        fields: Mapping[str, str] | None = None,
    ) -> list[tuple[str, float]]:
        """Execute a Lucene BM25 query using the configured searcher.

        Parameters
        ----------
        query : str
            Query string to search.
        k : int
            Number of top results to return.
        fields : Mapping[str, str] | None, optional
            Optional field mapping for query construction.

        Returns
        -------
        list[tuple[str, float]]
            List of (document_id, score) tuples.
        """
        searcher = self._ensure_searcher()
        query_string = self._compose_query(query, fields)
        hits: Sequence[LuceneHitProtocol] = searcher.search(query_string, k)
        return [(hit.docid, float(hit.score)) for hit in hits]

    def _ensure_searcher(self) -> LuceneSearcherProtocol:
        if self._searcher is None:
            searcher = self._searcher_factory(self.index_dir)
            searcher.set_bm25(self.k1, self.b)
            self._searcher = searcher
        return self._searcher

    def _build_lucene_doc(self, doc_id: str, fields: Mapping[str, str]) -> dict[str, str]:
        doc: dict[str, str] = {"id": doc_id, "contents": self._compose_contents(fields)}
        for key, value in fields.items():
            doc[key] = str(value)
        return doc

    @staticmethod
    def _compose_contents(fields: Mapping[str, str]) -> str:
        ordered_fields = ("title", "section", "body")
        parts = [str(fields.get(name, "")) for name in ordered_fields]
        extras = [str(value) for key, value in fields.items() if key not in ordered_fields]
        text_parts = [part for part in (*parts, *extras) if part]
        return " ".join(text_parts)

    def _compose_query(self, query: str, fields: Mapping[str, str] | None) -> str:
        components: list[str] = []
        if query:
            components.append(query)
        if fields:
            for field_name, boost in self.field_boosts.items():
                field_value = fields.get(field_name)
                if field_value:
                    components.append(f"{field_name}:( {field_value} )^{boost}")
        return " ".join(components) if components else query


def _load_lucene_indexer_factory() -> LuceneIndexerFactory:
    try:
        module = import_module("pyserini.index.lucene")
    except Exception as exc:  # pragma: no cover - depends on optional dependency
        msg = "pyserini.index.lucene module is unavailable"
        raise RuntimeError(msg) from exc
    candidate_callable = cast(
        "LuceneIndexerFactory | None",
        getattr(module, "LuceneIndexer", None),
    )
    if candidate_callable is None:  # pragma: no cover - defensive branch
        msg = "pyserini index module is missing 'LuceneIndexer'"
        raise TypeError(msg)
    return candidate_callable


def _load_lucene_searcher_factory() -> LuceneSearcherFactory:
    try:
        module = import_module("pyserini.search.lucene")
    except Exception as exc:  # pragma: no cover - depends on optional dependency
        msg = "pyserini.search.lucene module is unavailable"
        raise RuntimeError(msg) from exc
    candidate_callable = cast(
        "LuceneSearcherFactory | None",
        getattr(module, "LuceneSearcher", None),
    )
    if candidate_callable is None:  # pragma: no cover - defensive branch
        msg = "pyserini search module is missing 'LuceneSearcher'"
        raise TypeError(msg)
    return candidate_callable


# [nav:anchor get_bm25]
def get_bm25(
    backend: str,
    index_dir: str,
    *,
    k1: float = 0.9,
    b: float = 0.4,
    load_existing: bool = True,
) -> PurePythonBM25 | LuceneBM25:
    """Return a BM25 index implementation for the requested backend.

    Parameters
    ----------
    backend : str
        Backend name ("pure" or "lucene").
    index_dir : str
        Directory path for the index.
    k1 : float, optional
        BM25 k1 parameter (default: 0.9).
    b : float, optional
        BM25 b parameter (default: 0.4).
    load_existing : bool, optional
        Whether to load existing index if available (default: True).

    Returns
    -------
    PurePythonBM25 | LuceneBM25
        BM25 index instance.

    Raises
    ------
    ValueError
        If backend is not one of the supported values.
    """
    normalized_backend = backend.strip().lower()
    if normalized_backend == "pure":
        index: PurePythonBM25 | LuceneBM25 = PurePythonBM25(
            index_dir=index_dir,
            k1=k1,
            b=b,
        )
    elif normalized_backend == "lucene":
        index = LuceneBM25(
            index_dir=index_dir,
            k1=k1,
            b=b,
        )
    else:
        msg = f"Unsupported BM25 backend '{backend}'"
        raise ValueError(msg)

    if load_existing:
        index.load()

    return index
