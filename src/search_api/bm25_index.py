"""Overview of bm25 index.

This module bundles bm25 index logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, cast

from kgfoundry_common.errors import ConfigurationError, DeserializationError
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.safe_pickle_v2 import (
    UnsafeSerializationError,
    load_unsigned_legacy,
)
from kgfoundry_common.serialization import (
    deserialize_json,
    serialize_json,
)
from kgfoundry_common.typing import gate_import
from registry.duckdb_helpers import fetch_all, fetch_one

if TYPE_CHECKING:
    from collections.abc import Iterable

    from kgfoundry_common.problem_details import JsonValue

__all__ = [
    "BM25Doc",
    "BM25Index",
    "toks",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@lru_cache(maxsize=1)
def _duckdb_module() -> ModuleType:
    """Return duckdb module loaded lazily for typing gate compliance.

    Returns
    -------
    ModuleType
        Imported :mod:`duckdb` module reference.
    """
    return cast("ModuleType", gate_import("duckdb", "BM25 index hydration"))


def _validate_parquet_path(
    path: str | Path,
    *,
    allowed_roots: list[Path] | None = None,
    must_exist: bool = True,
) -> Path:
    """Validate and resolve parquet path against allowlist to prevent path traversal.

    Parameters
    ----------
    path : str | Path
        Path to validate (may be relative or absolute).
    allowed_roots : list[Path] | None, optional
        List of allowed root directories. If None, uses environment variable
        PARQUET_ROOT or default /data/parquet.
    must_exist : bool, optional
        If True, require path to exist. If False, only validate it's within
        allowed directory. Defaults to True.

    Returns
    -------
    Path
        Resolved absolute path that is within an allowed directory.

    Raises
    ------
    ConfigurationError
        If path resolves outside allowed directories or contains invalid characters.
    ValueError
        If path cannot be resolved or (when must_exist=True) is not accessible.

    Notes
    -----
    This function prevents path traversal attacks by:
    1. Resolving paths to absolute paths using Path.resolve()
    2. Checking resolved path is within allowed root directories
    3. Validating path exists and is accessible (when must_exist=True)
    4. Rejecting paths with unsafe patterns (.., symlinks outside allowed roots)

    Examples
    --------
    >>> from pathlib import Path
    >>> _validate_parquet_path("/data/parquet/chunks", allowed_roots=[Path("/data/parquet")])
    Path('/data/parquet/chunks')

    >>> _validate_parquet_path("../../../etc/passwd", allowed_roots=[Path("/data/parquet")])
    Traceback (most recent call last):
        ...
    ConfigurationError: Path resolves outside allowed directories
    """
    candidate = Path(path).expanduser()

    # Resolve to absolute path to prevent path traversal
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        msg = f"Invalid parquet path: {path}"
        raise ValueError(msg) from exc

    # Determine allowed roots
    if allowed_roots is None:
        parquet_root_env = os.getenv("PARQUET_ROOT", "/data/parquet")
        allowed_roots = [Path(parquet_root_env).resolve()]

    # Validate path is within allowed directory
    is_allowed = False
    for allowed_root in allowed_roots:
        allowed_resolved = allowed_root.resolve()
        try:
            # Check if resolved path is within allowed root
            resolved.relative_to(allowed_resolved)
            is_allowed = True
            break
        except ValueError:
            # Path is not relative to this allowed root, continue checking
            continue

    if not is_allowed:
        allowed_str = ", ".join(str(root) for root in allowed_roots)
        msg = (
            "Path resolves outside allowed directories. "
            f"Resolved: {resolved}, Allowed roots: {allowed_str}"
        )
        raise ConfigurationError(msg)

    # Verify path exists and is accessible (if required)
    if must_exist and not resolved.exists():
        msg = f"Parquet path does not exist: {resolved}"
        raise ValueError(msg)

    return resolved


def _as_str(value: object) -> str:
    """Convert a value to a string, handling None and non-string types.

    Extended Summary
    ----------------
    Normalizes database query results to strings for consistent processing in
    BM25 index loading. Handles None values by returning empty strings,
    preserves string values unchanged, and converts other types via str().
    This helper ensures type safety when reading from DuckDB which may return
    various types (str, None, int, etc.) for text fields.

    Parameters
    ----------
    value : object
        Value to convert. May be str, None, or any other type.

    Returns
    -------
    str
        String representation of the value. Empty string if value is None.

    Notes
    -----
    Time O(1) for strings and None; O(n) for other types where n is the
    string representation length. This function is internal to BM25 index
    loading and should not be used outside this module.

    Examples
    --------
    >>> _as_str("hello")
    'hello'
    >>> _as_str(None)
    ''
    >>> _as_str(123)
    '123'
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


# [nav:anchor toks]
def toks(text: str) -> list[str]:
    """Extract tokens from text using word boundary regex.

    Tokenizes input text by finding all sequences of alphanumeric characters
    (using regex pattern ``[A-Za-z0-9]+``) and converting them to lowercase.
    Used for BM25 indexing and query processing.

    Parameters
    ----------
    text : str
        Input text to tokenize. May be empty or None (treated as empty).

    Returns
    -------
    list[str]
        List of lowercase tokens extracted from the text. Empty list if input
        is empty or contains no alphanumeric sequences.

    Examples
    --------
    >>> toks("Hello World 123")
    ['hello', 'world', '123']
    >>> toks("")
    []
    """
    # re.findall returns list[str] when pattern has no groups
    matches: list[str] = TOKEN_RE.findall(text or "")
    return [token.lower() for token in matches]


# [nav:anchor BM25Doc]
@dataclass(frozen=True)
class BM25Doc:
    """Document representation for BM25 indexing and retrieval.

    Stores term frequency statistics and document metadata for a single
    document chunk. Inline attribute docstrings describe alias usage.

    See Also
    --------
    BM25Index : BM25 index using these document representations.
    """

    chunk_id: str
    """Unique identifier for the chunk.

    Alias: none; name ``chunk_id``.
    """
    doc_id: str
    """Parent document identifier.

    Alias: none; name ``doc_id``.
    """
    title: str
    """Document title used for term weighting.

    Alias: none; name ``title``.
    """
    section: str
    """Section label where the chunk appears.

    Alias: none; name ``section``.
    """
    tf: dict[str, float]
    """Term frequency mapping per token.

    Alias: none; name ``tf``.
    """
    dl: float
    """BM25 document length (sum of term frequencies).

    Alias: none; name ``dl``.
    """


# [nav:anchor BM25Index]
class BM25Index:
    r"""BM25 ranking function implementation for text search.

    Implements the Best Matching 25 (BM25) ranking algorithm for document
    retrieval. BM25 computes relevance scores based on term frequency (TF),
    inverse document frequency (IDF), and document length normalization.

    Parameters
    ----------
    k1 : float, optional
        Term frequency saturation parameter. Controls how quickly term frequency
        saturates. Higher values allow more influence from repeated terms.
        Defaults to 0.9.
    b : float, optional
        Document length normalization parameter. Controls the degree of length
        normalization. Values closer to 1.0 normalize more aggressively.
        Defaults to 0.4.

    Notes
    -----
    BM25 scoring formula:
    :math:`score(D, Q) = \sum_{t \in Q} IDF(t) \cdot `
    :math:`\frac{TF(t, D) \cdot (k1 + 1)}{TF(t, D) + k1 \cdot (1 - b + b \cdot \frac{|D|}{avgdl})}`

    Where:
    - :math:`TF(t, D)` is the term frequency of term :math:`t` in document :math:`D`
    - :math:`IDF(t)` is the inverse document frequency of term :math:`t`
    - :math:`|D|` is the document length
    - :math:`avgdl` is the average document length

    See Also
    --------
    BM25Doc : Document representation used by this index.
    toks : Tokenization function used for indexing and queries.
    """

    def __init__(self, k1: float = 0.9, b: float = 0.4) -> None:
        """Initialize BM25 index with ranking parameters.

        Extended Summary
        ----------------
        Constructs an empty BM25 index instance with configurable ranking
        parameters. The index starts with no documents and must be populated
        via :meth:`build_from_duckdb` or :meth:`load` before use. Parameters
        k1 and b control term frequency saturation and document length
        normalization in the BM25 scoring formula.

        Parameters
        ----------
        k1 : float, optional
            Term frequency saturation parameter. Controls how quickly term
            frequency saturates in scoring. Higher values (e.g., 1.2-2.0) allow
            more influence from repeated query terms. Lower values (e.g., 0.5-0.9)
            saturate quickly, reducing the impact of term repetition. Defaults to 0.9.
        b : float, optional
            Document length normalization parameter. Controls the degree of length
            normalization. Values closer to 1.0 normalize more aggressively,
            penalizing longer documents. Values closer to 0.0 reduce normalization.
            Defaults to 0.4.

        Notes
        -----
        Time O(1). The index is initially empty (no documents, no term frequencies).
        After initialization, documents must be added via build_from_duckdb() or
        load() before search operations will work. The parameters k1 and b are
        stored and used in all subsequent scoring operations.

        Examples
        --------
        >>> index = BM25Index(k1=1.2, b=0.75)
        >>> index.k1
        1.2
        >>> len(index.docs)
        0
        """
        self.k1 = k1
        self.b = b
        self.docs: list[BM25Doc] = []
        self.df: dict[str, int] = {}
        self.N = 0
        self.avgdl = 0.0

    @classmethod
    def build_from_duckdb(cls, db_path: str) -> BM25Index:
        """Build BM25 index from DuckDB database.

        Queries a DuckDB database for the most recent chunks dataset and
        builds a BM25 index from the parquet files. Reads chunk text, document
        titles, and sections, then computes term frequencies and document
        frequencies.

        Parameters
        ----------
        db_path : str
            Path to DuckDB database file containing datasets and documents tables.

        Returns
        -------
        BM25Index
            Initialized BM25 index with documents loaded from DuckDB.

        Raises
        ------
        TypeError
            If parquet_root value in the database is not a string.

        Notes
        -----
        The method queries for the most recent chunks dataset ordered by
        created_at. If no dataset is found, returns an empty index. Path
        validation prevents path traversal attacks by ensuring resolved paths
        are within allowed directories. Errors raised by
        :func:`_validate_parquet_path` propagate unchanged.
        """
        index = cls()
        con = _duckdb_module().connect(db_path)
        try:
            dataset = fetch_one(
                con,
                "SELECT parquet_root FROM datasets "
                "WHERE kind='chunks' ORDER BY created_at DESC LIMIT 1",
            )
            if dataset is None:
                return index
            root_obj = dataset[0]
            if not isinstance(root_obj, str):
                msg = f"Invalid parquet_root type: {type(root_obj)}"
                raise TypeError(msg)
            # Validate and resolve path to prevent path traversal
            # For pattern matching, we validate the root directory exists
            root_path = _validate_parquet_path(root_obj, must_exist=True)
            parquet_pattern = str(root_path / "*" / "*.parquet")
            sql = """
                SELECT c.chunk_id, c.doc_id, coalesce(c.section,''), c.text, coalesce(d.title,'')
                FROM read_parquet(?, union_by_name=true) AS c
                LEFT JOIN documents d ON c.doc_id = d.doc_id
            """
            raw_rows = fetch_all(con, sql, [parquet_pattern])
            typed_rows: list[tuple[str, str, str, str, str]] = [
                (
                    _as_str(chunk_id_val),
                    _as_str(doc_id_val),
                    _as_str(section_val),
                    _as_str(text_val),
                    _as_str(title_val),
                )
                for chunk_id_val, doc_id_val, section_val, text_val, title_val in raw_rows
            ]
        finally:
            con.close()
        index._build(typed_rows)
        return index

    def _build(self, rows: Iterable[tuple[str, str, str, str, str]]) -> None:
        """Build index from document rows.

        Processes an iterable of document rows, tokenizes text fields, computes
        term frequencies with weighted scoring (title 2.0, section 1.2, body
        1.0), and updates document frequency statistics.

        Parameters
        ----------
        rows : Iterable[tuple[str, str, str, str, str]]
            Iterable of tuples containing (chunk_id, doc_id, section, body, title).
            Each tuple represents one document chunk to index.

        Notes
        -----
        This method clears existing index state before building. Term frequencies
        are computed separately for title, section, and body fields with different
        weights. The average document length (avgdl) is computed after processing
        all rows.
        """
        self.docs.clear()
        self.df.clear()
        dl_sum = 0.0
        for chunk_id, doc_id, section, body, title in rows:
            tf: dict[str, float] = {}
            for term in toks(body or ""):
                tf[term] = tf.get(term, 0.0) + 1.0
            for term in toks(title or ""):
                tf[term] = tf.get(term, 0.0) + 2.0
            for term in toks(section or ""):
                tf[term] = tf.get(term, 0.0) + 1.2
            dl = sum(tf.values())
            self.docs.append(
                BM25Doc(
                    chunk_id=chunk_id,
                    doc_id=doc_id or "urn:doc:fixture",
                    title=title or "Fixture",
                    section=section or "",
                    tf=tf,
                    dl=dl,
                )
            )
            dl_sum += dl
            for term in set(tf.keys()):
                self.df[term] = self.df.get(term, 0) + 1
        self.N = len(self.docs)
        self.avgdl = (dl_sum / self.N) if self.N > 0 else 0.0

    @classmethod
    def from_parquet(cls, path: str, *, k1: float = 0.9, b: float = 0.4) -> BM25Index:
        """Build BM25 index from a single parquet file.

        Creates a BM25 index by reading document chunks from a parquet file.
        Uses DuckDB to read the parquet file and extracts chunk_id, doc_id,
        section, and text fields for indexing.

        Parameters
        ----------
        path : str
            Path to parquet file containing document chunks. Must exist and be
            within allowed directories (validated to prevent path traversal).
        k1 : float, optional
            Term frequency saturation parameter. Defaults to 0.9.
        b : float, optional
            Document length normalization parameter. Defaults to 0.4.

        Returns
        -------
        BM25Index
            Initialized BM25 index with documents loaded from parquet file.

        Notes
        -----
        Path validation prevents path traversal attacks. The method uses an
        in-memory DuckDB connection to read the parquet file. Title fields are
        not included from parquet (defaults to empty string). Errors raised by
        :func:`_validate_parquet_path` propagate unchanged.
        """
        index = cls(k1=k1, b=b)
        con = _duckdb_module().connect(database=":memory:")
        try:
            # Validate and resolve path to prevent path traversal
            resolved_path = _validate_parquet_path(path)
            sql = """
                SELECT chunk_id,
                       coalesce(doc_id, chunk_id) AS doc_id,
                       coalesce(section,'') AS section,
                       text,
                       '' AS title
                FROM read_parquet(?, union_by_name=true)
            """
            rows = fetch_all(con, sql, [str(resolved_path)])
            typed_rows: list[tuple[str, str, str, str, str]] = [
                (
                    _as_str(chunk_id_val),
                    _as_str(doc_id_val),
                    _as_str(section_val),
                    _as_str(text_val),
                    "",
                )
                for chunk_id_val, doc_id_val, section_val, text_val, *_ in rows
            ]
        finally:
            con.close()
        index._build(typed_rows)
        return index

    def save(self, path: str) -> None:
        """Save BM25 index metadata to JSON with schema validation and checksum.

        Serializes index metadata (parameters, document frequencies, and document
        list) to JSON format, validates it against the BM25 metadata schema, and
        writes a SHA256 checksum file for integrity verification.

        Parameters
        ----------
        path : str
            Output file path for JSON metadata. A `.sha256` checksum file will
            be written alongside it.

        Notes
        -----
        The serialized payload includes: k1, b, N (document count), avgdl (average
        document length), df (document frequency dictionary), and docs (list of
        BM25Doc data dictionaries). Exceptions raised by :func:`serialize_json`
        propagate unchanged.

        Examples
        --------
        >>> index = BM25Index(k1=0.9, b=0.4)
        >>> index.N = 100
        >>> index.save("/tmp/index.json")
        """
        path_obj = Path(path)
        schema_path = (
            Path(__file__).parent.parent.parent / "schema" / "models" / "bm25_metadata.v1.json"
        )
        # Convert docs to JSON-serializable format
        docs_data = [
            {
                "chunk_id": doc.chunk_id,
                "doc_id": doc.doc_id,
                "title": doc.title,
                "section": doc.section,
                "tf": doc.tf,
                "dl": doc.dl,
            }
            for doc in self.docs
        ]
        payload = {
            "k1": self.k1,
            "b": self.b,
            "N": self.N,
            "avgdl": self.avgdl,
            "df": self.df,
            "docs": docs_data,
        }
        serialize_json(payload, schema_path, path_obj)

    @classmethod
    def load(cls, path: str) -> BM25Index:
        """Load BM25 index metadata from JSON with schema validation and checksum verification.

        Deserializes index metadata from JSON, verifies the SHA256 checksum (if
        present), validates against the BM25 metadata schema, and reconstructs
        the index instance. Supports legacy pickle format as fallback.

        Parameters
        ----------
        path : str
            Path to JSON metadata file. A `.sha256` checksum file will be
            verified if present.

        Returns
        -------
        BM25Index
            Reconstructed BM25 index instance with all metadata loaded.

        Notes
        -----
        The method attempts to load from JSON first. If the file has a `.pkl`
        extension and JSON loading fails, it falls back to legacy pickle format
        (with validation). All document frequencies, term frequencies, and
        document metadata are reconstructed from the payload. Exceptions raised
        by :func:`deserialize_json` or legacy payload loaders propagate
        unchanged.

        Examples
        --------
        >>> index = BM25Index.load("/tmp/index.json")
        >>> assert index.N > 0
        """
        path_obj = Path(path)
        schema_path = (
            Path(__file__).parent.parent.parent / "schema" / "models" / "bm25_metadata.v1.json"
        )
        payload = cls._load_payload(path_obj, schema_path)
        return cls._index_from_payload(payload)

    @staticmethod
    def _coerce_payload(raw: object) -> dict[str, JsonValue]:
        """Coerce raw deserialized object to typed payload dictionary.

        Extended Summary
        ----------------
        Validates and casts a deserialized object to a dictionary with string
        keys and JSON-compatible values. Returns empty dictionary if input is
        not a dict, ensuring type safety for payload processing. This helper
        normalizes deserialized data (from JSON or pickle) into a consistent
        dictionary format for index reconstruction.

        Parameters
        ----------
        raw : object
            Raw deserialized object from JSON or pickle. May be dict, list, or
            other types.

        Returns
        -------
        dict[str, JsonValue]
            Typed payload dictionary. Empty dict if input is not a dictionary.

        Notes
        -----
        Time O(1). This function is internal to BM25 index loading and should
        not be used outside this module. The cast preserves type information
        for static type checkers while allowing runtime flexibility.

        Examples
        --------
        >>> BM25Index._coerce_payload({"k1": 0.9, "b": 0.4})
        {'k1': 0.9, 'b': 0.4}
        >>> BM25Index._coerce_payload([])
        {}
        >>> BM25Index._coerce_payload(None)
        {}
        """
        if not isinstance(raw, dict):
            return {}
        return cast("dict[str, JsonValue]", raw)

    @classmethod
    def _load_payload(cls, metadata_path: Path, schema_path: Path) -> dict[str, JsonValue]:
        """Load and validate index metadata payload from JSON or legacy pickle.

        Extended Summary
        ----------------
        Attempts to deserialize index metadata from JSON with schema validation.
        If JSON loading fails and the file has a .pkl extension, falls back to
        legacy pickle format (with validation). This method provides backward
        compatibility with older BM25 index serializations while preferring the
        safer JSON format.

        Parameters
        ----------
        metadata_path : Path
            Path to metadata file (JSON or pickle). If .pkl extension, legacy
            format is attempted on JSON failure.
        schema_path : Path
            Path to JSON Schema file for validation (used for JSON format only).

        Returns
        -------
        dict[str, JsonValue]
            Validated payload dictionary with index metadata (k1, b, N, avgdl,
            df, docs).

        Raises
        ------
        DeserializationError
            If JSON deserialization fails (and file is not .pkl) or if legacy
            pickle validation fails. Wraps underlying serialization errors with
            context.

        Notes
        -----
        Time O(file size). Side effects: reads file from disk. JSON format is
        preferred; pickle fallback is only used for .pkl files when JSON fails.
        All payloads are validated and coerced via _coerce_payload().

        Examples
        --------
        >>> schema = Path("schema/models/bm25_metadata.v1.json")
        >>> payload = BM25Index._load_payload(Path("index.json"), schema)
        >>> "k1" in payload
        True
        """
        try:
            return cls._coerce_payload(deserialize_json(metadata_path, schema_path))
        except DeserializationError:
            if metadata_path.suffix != ".pkl":
                raise
            return cls._load_legacy_payload(metadata_path)

    @classmethod
    def _load_legacy_payload(cls, metadata_path: Path) -> dict[str, JsonValue]:
        """Load legacy pickle format with validation.

        Extended Summary
        ----------------
        Deserializes BM25 index metadata from legacy pickle format with
        security validation. Uses load_unsigned_legacy() to validate pickle
        contents and prevent code execution attacks. Converts validated pickle
        data to typed payload dictionary.

        Parameters
        ----------
        metadata_path : Path
            Path to .pkl file containing legacy BM25 index metadata.

        Returns
        -------
        dict[str, JsonValue]
            Validated payload dictionary with index metadata.

        Raises
        ------
        DeserializationError
            If pickle validation fails (unsafe content detected) or file cannot
            be read. Wraps UnsafeSerializationError with context.

        Notes
        -----
        Time O(file size). Side effects: reads and validates pickle file. This
        method is only called for .pkl files when JSON loading fails. The
        pickle format is deprecated in favor of JSON + schema validation.

        Examples
        --------
        >>> payload = BM25Index._load_legacy_payload(Path("legacy_index.pkl"))
        >>> isinstance(payload, dict)
        True
        """
        with metadata_path.open("rb") as handle:
            try:
                legacy_payload_raw: object = load_unsigned_legacy(handle)
            except UnsafeSerializationError as legacy_exc:
                message = f"Legacy BM25 pickle failed validation: {legacy_exc}"
                raise DeserializationError(message) from legacy_exc
        return cls._coerce_payload(legacy_payload_raw)

    @classmethod
    def _index_from_payload(cls, payload: dict[str, JsonValue]) -> BM25Index:
        """Reconstruct BM25 index instance from validated payload dictionary.

        Extended Summary
        ----------------
        Creates a BM25Index instance and populates it with metadata from a
        validated payload dictionary. Extracts ranking parameters (k1, b),
        collection statistics (N, avgdl), document frequencies (df), and
        document list (docs) with defensive type coercion. Missing or invalid
        values use sensible defaults (k1=0.9, b=0.4, N=0, avgdl=0.0).

        Parameters
        ----------
        payload : dict[str, JsonValue]
            Validated payload dictionary containing index metadata. Expected
            keys: "k1" (float), "b" (float), "N" (int), "avgdl" (float),
            "df" (dict[str, int]), "docs" (list[dict]).

        Returns
        -------
        BM25Index
            Fully reconstructed BM25 index instance with all metadata loaded.
            Documents are reconstructed via _docs_from_payload().

        Notes
        -----
        Time O(n + m) where n is the number of documents and m is the number
        of unique terms in df. Side effects: creates new index instance and
        populates instance attributes. Type coercion handles JSON number types
        (int/float) gracefully, defaulting to safe values for invalid types.

        Examples
        --------
        >>> payload = {"k1": 1.2, "b": 0.75, "N": 100, "avgdl": 50.0, "df": {}, "docs": []}
        >>> index = BM25Index._index_from_payload(payload)
        >>> index.k1 == 1.2
        True
        >>> index.N == 100
        True
        """
        k1_val = payload.get("k1", 0.9)
        b_val = payload.get("b", 0.4)
        index = cls(
            k1=float(k1_val) if isinstance(k1_val, (int, float)) else 0.9,
            b=float(b_val) if isinstance(b_val, (int, float)) else 0.4,
        )
        n_val = payload.get("N", 0)
        avgdl_val = payload.get("avgdl", 0.0)
        index.N = int(n_val) if isinstance(n_val, (int, float)) else 0
        index.avgdl = float(avgdl_val) if isinstance(avgdl_val, (int, float)) else 0.0

        df_val = payload.get("df", {})
        index.df = (
            {k: int(v) if isinstance(v, (int, float)) else 0 for k, v in df_val.items()}
            if isinstance(df_val, dict)
            else {}
        )

        index.docs = cls._docs_from_payload(payload.get("docs", []))
        return index

    @staticmethod
    def _docs_from_payload(raw_docs: object) -> list[BM25Doc]:
        """Reconstruct BM25Doc instances from raw payload list.

        Extended Summary
        ----------------
        Validates and converts a list of document dictionaries into BM25Doc
        instances. Handles type coercion for all fields (chunk_id, doc_id, title,
        section, tf, dl) with defensive defaults. Skips invalid entries (non-dict
        items) rather than failing, ensuring robust deserialization.

        Parameters
        ----------
        raw_docs : object
            Raw document list from payload. May be list of dicts, non-list, or
            None. Each dict should contain: "chunk_id" (str), "doc_id" (str),
            "title" (str), "section" (str), "tf" (dict[str, float]), "dl" (float).

        Returns
        -------
        list[BM25Doc]
            List of reconstructed BM25Doc instances. Empty list if input is not
            a list or contains no valid entries.

        Notes
        -----
        Time O(n * m) where n is the number of documents and m is the average
        number of terms per document. This function is internal to BM25 index
        loading and should not be used outside this module. Invalid entries
        (non-dict items) are silently skipped to ensure partial recovery from
        corrupted payloads.

        Examples
        --------
        >>> raw = [
        ...     {
        ...         "chunk_id": "c1",
        ...         "doc_id": "d1",
        ...         "title": "Title",
        ...         "section": "",
        ...         "tf": {"hello": 2.0},
        ...         "dl": 2.0,
        ...     }
        ... ]
        >>> docs = BM25Index._docs_from_payload(raw)
        >>> len(docs) == 1
        True
        >>> docs[0].chunk_id == "c1"
        True
        """
        if not isinstance(raw_docs, list):
            return []

        docs: list[BM25Doc] = []
        for entry in raw_docs:
            if not isinstance(entry, dict):
                continue
            chunk_id = entry.get("chunk_id", "")
            doc_id = entry.get("doc_id", "")
            title = entry.get("title", "")
            section = entry.get("section", "")
            tf_value: object = entry.get("tf", {})
            doc_length = entry.get("dl", 0.0)
            docs.append(
                BM25Doc(
                    chunk_id=str(chunk_id) if isinstance(chunk_id, str) else "",
                    doc_id=str(doc_id) if isinstance(doc_id, str) else "",
                    title=str(title) if isinstance(title, str) else "",
                    section=str(section) if isinstance(section, str) else "",
                    tf=(cast("dict[str, float]", tf_value) if isinstance(tf_value, dict) else {}),
                    dl=(float(doc_length) if isinstance(doc_length, (int, float)) else 0.0),
                )
            )
        return docs

    def _idf(self, term: str) -> float:
        """Compute inverse document frequency (IDF) for a term.

        Calculates IDF using the formula: log((N - df + 0.5) / (df + 0.5) + 1.0)
        where N is the total number of documents and df is the document frequency.

        Parameters
        ----------
        term : str
            Token string to compute IDF for.

        Returns
        -------
        float
            IDF score for the term. Returns 0.0 if term is not in any document
            or if the index is empty.

        Notes
        -----
        Uses the standard BM25 IDF formula with smoothing to avoid division by
        zero. The 0.5 smoothing factor prevents negative IDF values for terms
        appearing in all documents.
        """
        df = self.df.get(term, 0)
        if self.N == 0 or df == 0:
            return 0.0
        return math.log((self.N - df + 0.5) / (df + 0.5) + 1.0)

    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """Search index and return top-k results ranked by BM25 score.

        Tokenizes the query, computes BM25 relevance scores for all documents,
        and returns the top-k results sorted by score in descending order.

        Parameters
        ----------
        query : str
            Search query string to tokenize and match against documents.
        k : int, optional
            Maximum number of results to return. Defaults to 10.

        Returns
        -------
        list[tuple[str, float]]
            List of (chunk_id, score) tuples sorted by score descending. Only
            includes documents with score > 0.0. Returns empty list if index is
            empty or no documents match.

        Notes
        -----
        BM25 scoring combines term frequency (TF), inverse document frequency
        (IDF), and document length normalization. Documents with higher scores
        are more relevant to the query.
        """
        if self.N == 0:
            return []
        terms = toks(query)
        scores = [0.0] * self.N
        for i, doc in enumerate(self.docs):
            score = 0.0
            for term in terms:
                tf = doc.tf.get(term, 0.0)
                if tf <= 0.0:
                    continue
                idf = self._idf(term)
                denom = tf + self.k1 * (1.0 - self.b + self.b * (doc.dl / (self.avgdl or 1.0)))
                score += idf * ((tf * (self.k1 + 1.0)) / denom)
            scores[i] = score

        # Explicitly type sorted callable to avoid Any
        def key_func(item: tuple[int, float]) -> float:
            """Extract score from (index, score) tuple for sorting.

            Parameters
            ----------
            item : tuple[int, float]
                Tuple of (index, score).

            Returns
            -------
            float
                Score value.
            """
            return item[1]

        ranked: list[tuple[int, float]] = sorted(enumerate(scores), key=key_func, reverse=True)
        return [(self.docs[index].chunk_id, score) for index, score in ranked[:k] if score > 0.0]

    def doc(self, index: int) -> BM25Doc:
        """Get document at the specified index.

        Parameters
        ----------
        index : int
            Zero-based index of the document to retrieve.

        Returns
        -------
        BM25Doc
            Document at the specified index.

        Raises
        ------
        IndexError
            If index is out of range (negative or >= len(docs)).
        """
        if index < 0 or index >= len(self.docs):
            msg = f"Document index {index} out of range for {len(self.docs)} documents"
            raise IndexError(msg)
        return self.docs[index]
