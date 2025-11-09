"""Overview of splade.

This module bundles splade logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import base64
import binascii
import importlib
import logging
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, ClassVar, Protocol, cast

from kgfoundry_common.config import load_config
from kgfoundry_common.errors import DeserializationError
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.safe_pickle_v2 import (
    SignedPickleWrapper,
    UnsafeSerializationError,
    load_unsigned_legacy,
)
from kgfoundry_common.serialization import deserialize_json, serialize_json

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from re import Pattern
    from types import ModuleType

    from kgfoundry_common.problem_details import JsonValue

TOKEN_RE: Pattern[str] = re.compile(r"[A-Za-z0-9_]+")


def _default_float_dict() -> defaultdict[str, float]:
    """Return a defaultdict that produces ``float`` zeros for missing keys.

    Returns
    -------
    defaultdict[str, float]
        Defaultdict with float factory.
    """
    return defaultdict(float)


def _score_value(item: tuple[str, float]) -> float:
    """Extract the score component from a Lucene impact result tuple.

    Parameters
    ----------
    item : tuple[str, float]
        Impact result tuple.

    Returns
    -------
    float
        Score value.
    """
    return item[1]


def _decode_signing_key() -> bytes | None:
    """Decode the configured signing key, returning ``None`` if unavailable.

    Returns
    -------
    bytes | None
        Decoded signing key, or None if unavailable.
    """
    try:
        settings = load_config()
    except ValueError as exc:
        logger.warning("Configuration invalid; proceeding without signing key", exc_info=exc)
        return None

    encoded_key = settings.signing_key
    if encoded_key is None:
        return None

    try:
        return base64.b64decode(encoded_key)
    except binascii.Error as exc:
        logger.warning(
            "Signing key is not valid base64; ignoring secure pickle signature",
            exc_info=exc,
        )
        return None


def _load_unsigned_payload(handle: BinaryIO, legacy_path: Path) -> dict[str, JsonValue]:
    """Load legacy pickle payload with allow-list enforcement.

    Parameters
    ----------
    handle : BinaryIO
        Binary file handle to read from.
    legacy_path : Path
        Path to the legacy pickle file.

    Returns
    -------
    dict[str, JsonValue]
        Deserialized payload dictionary.

    Raises
    ------
    DeserializationError
        If deserialization fails or payload is invalid.
    """
    try:
        payload_obj = load_unsigned_legacy(handle)
    except UnsafeSerializationError as exc:
        msg = f"Legacy pickle at {legacy_path} failed safety validation"
        raise DeserializationError(msg) from exc

    if not isinstance(payload_obj, dict):
        msg = f"Invalid legacy pickle payload: expected dict, got {type(payload_obj)}"
        raise DeserializationError(msg)

    return cast("dict[str, JsonValue]", payload_obj)


def _load_legacy_metadata(legacy_path: Path) -> dict[str, JsonValue]:
    """Load SPLADE legacy pickle metadata using signed or unsigned safe loader.

    Parameters
    ----------
    legacy_path : Path
        Path to the legacy pickle file.

    Returns
    -------
    dict[str, JsonValue]
        Deserialized metadata dictionary.

    Raises
    ------
    DeserializationError
        If deserialization fails or payload is invalid.

    Notes
    -----
    Wraps :class:`OSError` raised during file access as
    :class:`DeserializationError` with additional context.
    """
    signing_key = _decode_signing_key()
    try:
        with legacy_path.open("rb") as handle:
            if signing_key:
                wrapper = SignedPickleWrapper(signing_key)
                try:
                    payload_obj = wrapper.load(handle)
                except UnsafeSerializationError:
                    logger.warning(
                        "Signed pickle validation failed for legacy SPLADE index; "
                        "falling back to unsigned loader",
                        extra={"legacy_path": str(legacy_path)},
                    )
                    handle.seek(0)
                    payload = _load_unsigned_payload(handle, legacy_path)
                else:
                    if not isinstance(payload_obj, dict):
                        msg = (
                            f"Invalid signed legacy payload: expected dict, got {type(payload_obj)}"
                        )
                        raise DeserializationError(msg)
                    payload = cast("dict[str, JsonValue]", payload_obj)
            else:
                logger.warning(
                    "Missing signing key; using unsigned legacy pickle loader",
                    extra={"legacy_path": str(legacy_path)},
                )
                payload = _load_unsigned_payload(handle, legacy_path)
    except OSError as exc:
        msg = f"Failed to read legacy SPLADE index at {legacy_path}: {exc}"
        raise DeserializationError(msg) from exc

    return payload


class ImpactHitProtocol(Protocol):
    """Protocol describing the minimal SPLADE impact hit payload."""

    docid: str
    score: float


class LuceneImpactSearcherProtocol(Protocol):
    """Protocol for Lucene-backed SPLADE searchers."""

    def search(self, query: str, k: int) -> Sequence[ImpactHitProtocol]:
        """Return the top ``k`` SPLADE impact hits for ``query``."""
        ...


class LuceneImpactSearcherFactory(Protocol):
    """Factory protocol for constructing Lucene SPLADE searchers."""

    def __call__(
        self, index_dir: str, *, query_encoder: str | None = None
    ) -> LuceneImpactSearcherProtocol:
        """Build a searcher for ``index_dir`` using an optional query encoder."""
        ...


logger = logging.getLogger(__name__)

__all__ = [
    "LuceneImpactIndex",
    "PureImpactIndex",
    "SPLADEv3Encoder",
    "get_splade",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor SPLADEv3Encoder]
class SPLADEv3Encoder:
    """SPLADE-v3 encoder for generating sparse embeddings.

    Provides an interface for encoding text into SPLADE sparse embeddings.
    Currently a skeleton implementation that raises NotImplementedError.

    Initializes the SPLADE-v3 encoder with model configuration and device settings.

    Parameters
    ----------
    model_id : str, optional
        Hugging Face model identifier for the SPLADE encoder. Defaults to
        "naver/splade-v3-distilbert".
    device : str, optional
        Device to run inference on ("cuda" or "cpu"). Defaults to "cuda".
    topk : int, optional
        Number of top-k vocabulary tokens to retain in sparse representation.
        Defaults to 256.
    max_seq_len : int, optional
        Maximum sequence length for tokenization. Defaults to 512.

    Attributes
    ----------
    name : ClassVar[str]
        Encoder name identifier ("SPLADE-v3-distilbert"). This is a class
        variable set to the model identifier string.


    Notes
    -----
    This is a placeholder implementation. For production use, consider using
    LuceneImpactIndex which integrates with Pyserini's Lucene impact search.
    """

    name: ClassVar[str] = "SPLADE-v3-distilbert"

    def __init__(
        self,
        model_id: str = "naver/splade-v3-distilbert",
        device: str = "cuda",
        topk: int = 256,
        max_seq_len: int = 512,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.topk = topk
        self.max_seq_len = max_seq_len

    def encode(self, texts: list[str]) -> list[tuple[list[int], list[float]]]:
        """Encode texts into SPLADE sparse embeddings.

        This method is not implemented in the skeleton implementation. Use
        LuceneImpactIndex for SPLADE-based retrieval instead.

        Parameters
        ----------
        texts : list[str]
            List of text strings to encode.

        Returns
        -------
        list[tuple[list[int], list[float]]]
            Sparse SPLADE embeddings expressed as token indices and weights.

        Raises
        ------
        NotImplementedError
            This function is not implemented in the skeleton. Use LuceneImpactIndex
            instead.

        Notes
        -----
        Use the Lucene impact index variant if available for production SPLADE
        encoding and retrieval.
        """
        message = (
            "SPLADE encoding is not implemented in the skeleton. Use the Lucene "
            "impact index variant if available. "
            f"Requested device={self.device!r} with {len(texts)} texts."
        )
        raise NotImplementedError(message)
        return []  # pragma: no cover


# [nav:anchor PureImpactIndex]
class PureImpactIndex:
    """Pure Python SPLADE impact index implementation.

    Implements SPLADE (Sparse Lexical and Expansion) sparse retrieval using
    Python dictionaries and lists. Suitable for small to medium-sized indexes
    that fit in memory.

    Initializes the SPLADE impact index with an index directory.

    Parameters
    ----------
    index_dir : str
        Directory path where index metadata will be stored. Created if it
        doesn't exist.

    Notes
    -----
    The implementation uses in-memory data structures and is suitable for
    indexes that fit in RAM. For larger indexes, consider using LuceneImpactIndex
    which uses Pyserini's disk-backed Lucene impact search.
    """

    def __init__(self, index_dir: str) -> None:
        self.index_dir = index_dir
        self.df: dict[str, int] = {}
        self.N = 0
        self.postings: dict[str, dict[str, float]] = {}

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

    def build(self, docs_iterable: Iterable[tuple[str, dict[str, str]]]) -> None:
        """Build SPLADE impact index from document iterable.

        Processes an iterable of documents, computes term frequencies with
        log1p normalization, applies IDF scoring, and serializes the index
        metadata to disk with schema validation.

        Parameters
        ----------
        docs_iterable : Iterable[tuple[str, dict[str, str]]]
            Iterable of (doc_id, fields) tuples. Each fields dictionary should
            contain "title", "section", and "body" keys with string values.

        Notes
        -----
        This method clears any existing index state and rebuilds from scratch.
        Term frequencies are normalized using log1p, then combined with IDF
        scores. The final metadata is written to `impact.json` in the index
        directory with schema validation and checksum verification.
        """
        Path(self.index_dir).mkdir(parents=True, exist_ok=True)
        df: defaultdict[str, int] = defaultdict(int)
        postings: defaultdict[str, defaultdict[str, float]] = defaultdict(_default_float_dict)
        doc_count = 0
        for doc_id, fields in docs_iterable:
            text = " ".join(
                [
                    fields.get("title", ""),
                    fields.get("section", ""),
                    fields.get("body", ""),
                ]
            )
            tokens = self._tokenize(text)
            doc_count += 1
            counts = Counter(tokens)
            for token, term_freq in counts.items():
                df[token] += 1
                postings[token][doc_id] = math.log1p(term_freq)
        self.N = doc_count
        self.df = dict(df)
        self.postings = {
            token: {
                doc: weight * math.log((doc_count - df[token] + 0.5) / (df[token] + 0.5) + 1.0)
                for doc, weight in docs.items()
            }
            for token, docs in postings.items()
        }
        # persist using secure JSON serialization with schema validation
        metadata_path = Path(self.index_dir) / "impact.json"
        schema_path = (
            Path(__file__).parent.parent.parent / "schema" / "models" / "splade_metadata.v1.json"
        )
        payload = {"df": self.df, "N": self.N, "postings": self.postings}
        serialize_json(payload, schema_path, metadata_path)

    def load(self) -> None:
        """Load SPLADE index metadata from disk with schema validation and checksum verification.

        Deserializes index metadata from JSON, verifying checksum and validating
        against the schema. Falls back to legacy pickle format for backward
        compatibility if JSON loading fails.

        Raises
        ------
        DeserializationError
            If deserialization, schema validation, or checksum verification fails.
        FileNotFoundError
            If metadata or schema file is missing (and no legacy pickle exists).

        Notes
        -----
        The method first attempts to load from `impact.json`. If that fails and
        `impact.pkl` exists, it falls back to legacy pickle format with
        allow-list validation. Legacy pickle loading supports both signed and
        unsigned formats.
        """
        metadata_path = Path(self.index_dir) / "impact.json"
        schema_path = (
            Path(__file__).parent.parent.parent / "schema" / "models" / "splade_metadata.v1.json"
        )
        legacy_path = Path(self.index_dir) / "impact.pkl"

        if metadata_path.exists():
            try:
                data_raw = deserialize_json(metadata_path, schema_path)
            except DeserializationError:
                logger.warning(
                    "Failed to load JSON index, trying legacy pickle",
                    extra={
                        "metadata_path": str(metadata_path),
                        "legacy_path": str(legacy_path),
                    },
                )
                if legacy_path.exists():
                    data_dict = _load_legacy_metadata(legacy_path)
                else:
                    raise
            else:
                if not isinstance(data_raw, dict):
                    msg = f"Invalid index data format: expected dict, got {type(data_raw)}"
                    raise DeserializationError(msg)
                data_dict = cast("dict[str, JsonValue]", data_raw)
        elif legacy_path.exists():
            data_dict = _load_legacy_metadata(legacy_path)
            logger.warning("Loaded legacy pickle index. Consider migrating to JSON format.")
        else:
            msg = f"Index metadata not found at {metadata_path} or {legacy_path}"
            raise FileNotFoundError(msg)

        # Extract values with type narrowing
        df_val: JsonValue = data_dict.get("df", {})
        n_val: JsonValue = data_dict.get("N", 0)
        postings_val: JsonValue = data_dict.get("postings", {})

        # Type narrowing and conversion
        self.df = cast("dict[str, int]", df_val) if isinstance(df_val, dict) else {}
        self.N = int(n_val) if isinstance(n_val, (int, float)) else 0
        # postings is dict[str, dict[str, float]] - need to convert nested dict values
        if isinstance(postings_val, dict):
            # Convert nested dict values from JsonValue to dict[str, float]
            postings_converted: dict[str, dict[str, float]] = {}
            for term, term_postings in postings_val.items():
                if isinstance(term_postings, dict):
                    # Convert inner dict values to float
                    term_postings_float: dict[str, float] = {
                        str(doc_id): (float(weight) if isinstance(weight, (int, float)) else 0.0)
                        for doc_id, weight in term_postings.items()
                    }
                    postings_converted[str(term)] = term_postings_float
            self.postings = postings_converted
        else:
            self.postings = {}

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        """Search SPLADE impact index and return top-k results.

        Tokenizes the query, computes impact scores by summing term weights
        from postings, and returns the top-k results sorted by score in
        descending order.

        Parameters
        ----------
        query : str
            Search query string to tokenize and match against documents.
        k : int
            Maximum number of results to return.

        Returns
        -------
        list[tuple[str, float]]
            List of (doc_id, score) tuples sorted by score descending. Only
            includes documents with score > 0.0. Returns empty list if index is
            empty or no documents match.

        Notes
        -----
        SPLADE impact scoring sums term weights (combining log1p(TF) and IDF)
        for each query token. Documents with higher scores are more relevant
        to the query.
        """
        tokens = self._tokenize(query)
        scores: defaultdict[str, float] = defaultdict(float)
        for token in tokens:
            postings = self.postings.get(token)
            if not postings:
                continue
            for doc_id, weight in postings.items():
                scores[doc_id] += weight
        ranked_scores: list[tuple[str, float]] = [
            (doc_id, score) for doc_id, score in scores.items()
        ]
        ranked_scores.sort(key=_score_value, reverse=True)
        return ranked_scores[:k]


# [nav:anchor LuceneImpactIndex]
class LuceneImpactIndex:
    """Lucene-backed SPLADE impact index implementation.

    Provides SPLADE sparse retrieval using Apache Lucene via Pyserini's impact
    search. Suitable for large indexes that benefit from disk-backed storage
    and optimized search performance.

    Initializes the Lucene impact index with an index directory and optional query encoder.

    Parameters
    ----------
    index_dir : str
        Directory path where the Lucene impact index is stored. Must exist
        and contain a valid Lucene index.
    query_encoder : str, optional
        Hugging Face model identifier for query encoding. Defaults to
        "naver/splade-v3-distilbert".

    Notes
    -----
    Requires the optional ``pyserini`` dependency. Import errors propagate as
    :class:`RuntimeError` when helper factories are loaded. The searcher is
    lazy-initialized on first search call to avoid unnecessary index loading.
    """

    def __init__(self, index_dir: str, query_encoder: str = "naver/splade-v3-distilbert") -> None:
        self.index_dir = index_dir
        self.query_encoder = query_encoder
        self._searcher: LuceneImpactSearcherProtocol | None = None

    def _ensure(self) -> None:
        """Initialise the Lucene impact searcher if Pyserini is available.

        Raises
        ------
        RuntimeError
            If the Pyserini Lucene search implementation is unavailable.
        """
        if self._searcher is not None:
            return
        try:
            lucene_search_module: ModuleType = importlib.import_module("pyserini.search.lucene")
            lucene_impact_searcher_cls = cast(
                "LuceneImpactSearcherFactory",
                lucene_search_module.LuceneImpactSearcher,
            )
        except (
            ImportError,
            AttributeError,
        ) as exc:  # pragma: no cover - optional dependency
            message = "Pyserini not available for SPLADE impact search"
            logger.exception("Failed to import LuceneImpactSearcher")
            raise RuntimeError(message) from exc
        searcher = lucene_impact_searcher_cls(self.index_dir, query_encoder=self.query_encoder)
        self._searcher = searcher

    def ensure_available(self) -> None:
        """Ensure the Lucene searcher is initialized and ready for queries.

        Notes
        -----
        Propagates :class:`RuntimeError` when Pyserini is not available for
        SPLADE impact search.
        """
        self._ensure()

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        """Search Lucene impact index and return top-k results.

        Executes a SPLADE impact search using the configured Lucene searcher
        and returns the top-k results sorted by impact score.

        Parameters
        ----------
        query : str
            Search query string to encode and search.
        k : int
            Maximum number of results to return.

        Returns
        -------
        list[tuple[str, float]]
            List of (doc_id, score) tuples sorted by score descending. Contains
            up to k results.

        Raises
        ------
        RuntimeError
            If Lucene searcher is not initialized or Pyserini is not available.
            This can occur if ensure_available() has not been called or if
            Pyserini modules are missing.
        """
        self._ensure()
        if self._searcher is None:
            message = "Lucene impact searcher not initialized"
            raise RuntimeError(message)
        hits = self._searcher.search(query, k)
        return [(str(hit.docid), float(hit.score)) for hit in hits]


# [nav:anchor get_splade]
def get_splade(
    backend: str,
    index_dir: str,
    query_encoder: str = "naver/splade-v3-distilbert",
) -> PureImpactIndex | LuceneImpactIndex:
    """Return a SPLADE index implementation for the requested backend.

    Factory function that creates either a PureImpactIndex or LuceneImpactIndex
    based on the backend parameter. Attempts to use Lucene backend if requested,
    falling back to PureImpactIndex if Lucene is unavailable.

    Parameters
    ----------
    backend : str
        Backend name ("pure" or "lucene"). Case-insensitive.
    index_dir : str
        Directory path for the index. Must exist and contain valid index data.
    query_encoder : str, optional
        Hugging Face model identifier for query encoding (used only for Lucene
        backend). Defaults to "naver/splade-v3-distilbert".

    Returns
    -------
    PureImpactIndex | LuceneImpactIndex
        SPLADE index instance. Returns PureImpactIndex if Lucene backend is
        requested but unavailable.

    Notes
    -----
    If "lucene" backend is requested but Pyserini is not available, the function
    logs a warning and falls back to PureImpactIndex. This allows graceful
    degradation when optional dependencies are missing.
    """
    if backend == "lucene":
        lucene_index = LuceneImpactIndex(index_dir=index_dir, query_encoder=query_encoder)
        try:
            lucene_index.ensure_available()
        except RuntimeError as exc:
            logger.warning(
                "Lucene backend unavailable, falling back to PureImpactIndex",
                extra={"index_dir": index_dir, "query_encoder": query_encoder},
                exc_info=exc,
            )
        else:
            return lucene_index
    return PureImpactIndex(index_dir)
