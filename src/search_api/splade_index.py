"""Overview of splade index.

This module bundles splade index logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Final, cast

from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.typing import gate_import

if TYPE_CHECKING:
    from collections.abc import Sequence

    from duckdb import DuckDBPyConnection


__all__ = [
    "SpladeDoc",
    "SpladeIndex",
    "tok",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


TOKEN = re.compile(r"[A-Za-z0-9]+")
PARQUET_ROW_WIDTH: Final = 4


@lru_cache(maxsize=1)
def _duckdb_module() -> ModuleType:
    """Return duckdb module resolved lazily for SPLADE index ingestion.

    Returns
    -------
    ModuleType
        Imported :mod:`duckdb` module reference.
    """
    return cast("ModuleType", gate_import("duckdb", "splade index loading"))


# [nav:anchor tok]
def tok(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric tokens.

    Extracts alphanumeric sequences from the input text and converts them
    to lowercase. Uses a regex pattern to match alphanumeric characters.

    Parameters
    ----------
    text : str
        Input text to tokenize. Empty strings are handled gracefully.

    Returns
    -------
    list[str]
        List of lowercase alphanumeric tokens extracted from the text.
    """
    # re.findall returns list[str] when pattern has no groups
    matches: list[str] = TOKEN.findall(text or "")
    return [token.lower() for token in matches]


# [nav:anchor SpladeDoc]
@dataclass(frozen=True)
class SpladeDoc:
    """Document fixture for SPLADE index backed by sparse retrieval data."""

    chunk_id: str
    """Chunk identifier.

    Alias: none; name ``chunk_id``.
    """
    doc_id: str
    """Document identifier.

    Alias: none; name ``doc_id``.
    """
    section: str
    """Section label within the document.

    Alias: none; name ``section``.
    """
    text: str
    """Chunk text content.

    Alias: none; name ``text``.
    """


# [nav:anchor SpladeIndex]
class SpladeIndex:
    """In-memory SPLADE index for tests and tutorials.

    Extended Summary
    ----------------
    Simple in-memory search index that loads document chunks from a DuckDB
    catalog and builds document frequency (DF) indexes for sparse retrieval.
    Used primarily for testing and tutorials as an example SPLADE index.
    Constructs a SPLADE index instance and immediately loads document
    chunks from the DuckDB catalog. The index builds in-memory document
    frequency (DF) structures for sparse retrieval during tests and tutorials.
    If the database file does not exist or contains no chunks dataset, the
    index remains empty but functional. The sparse_root parameter is retained
    for interface compatibility but currently unused.

    Parameters
    ----------
    db_path : str
        Path to DuckDB catalog database file. Must exist for documents
        to be loaded.
    chunks_dataset_root : str | None, optional
        Optional override path to chunks dataset root directory. If None,
        queries the catalog for the latest chunks dataset. Defaults to None.
    sparse_root : str | None, optional
        Optional sparse embeddings root (retained for interface compatibility).
        Currently unused and ignored. Defaults to None.

    Notes
    -----
    Initialization triggers synchronous I/O to load documents and build
    indexes. Time complexity is O(n * m) where n is the number of documents
    and m is the average tokens per document. Memory usage is O(v) for DF
    where v is vocabulary size, plus O(n) for document storage.

    Examples
    --------
    >>> index = SpladeIndex(db_path="/tmp/catalog.duckdb")
    >>> len(index.docs) >= 0
    True
    """

    def __init__(
        self,
        db_path: str,
        chunks_dataset_root: str | None = None,
        sparse_root: str | None = None,
    ) -> None:
        _ = sparse_root  # retained for interface compatibility
        self.db_path = db_path
        self.docs: list[SpladeDoc] = []
        self.df: dict[str, int] = {}
        self.N = 0
        self._load(chunks_dataset_root)

    def _load(self, chunks_root: str | None) -> None:
        """Load documents from DuckDB catalog and build document frequency index.

        Extended Summary
        ----------------
        Connects to the DuckDB database, resolves the chunks dataset root path
        (either from parameter or catalog query), reads all chunk rows from
        parquet files, populates the documents list, and recomputes document
        frequencies. This method orchestrates the I/O-heavy initialization work
        for the SPLADE index.

        Parameters
        ----------
        chunks_root : str | None
            Optional override path to chunks dataset root. If None, queries the
            catalog for the latest chunks dataset.

        Notes
        -----
        Time O(n) where n is the total number of chunks. Memory O(n) for document
        storage plus O(v) for vocabulary. Performs synchronous I/O via DuckDB
        connection. If the database file does not exist, the method returns early
        leaving the index empty.

        Examples
        --------
        >>> index = SpladeIndex(db_path="/tmp/catalog.duckdb")
        >>> # _load is called automatically during __init__
        >>> index.N >= 0
        True
        """
        if not Path(self.db_path).exists():
            return

        duckdb_module = _duckdb_module()
        connection: DuckDBPyConnection = duckdb_module.connect(self.db_path)
        try:
            root = self._resolve_chunks_root(connection, chunks_root)
            rows = self._read_chunk_rows(connection, root) if root is not None else []
        finally:
            connection.close()

        self._populate_docs(rows)
        self._recompute_document_frequencies()

    @staticmethod
    def _resolve_chunks_root(connection: DuckDBPyConnection, override: str | None) -> str | None:
        """Resolve chunks dataset root path from override or catalog query.

        Extended Summary
        ----------------
        Returns the override path if provided, otherwise queries the DuckDB
        catalog for the most recently created chunks dataset and returns its
        parquet_root path. This enables flexible dataset selection while
        defaulting to the latest dataset when no override is specified.

        Parameters
        ----------
        connection : DuckDBPyConnection
            Active DuckDB connection to the catalog database. Must have read
            access to the datasets table.
        override : str | None
            Optional override path to chunks dataset root. If provided, returned
            unchanged. If None, queries the catalog.

        Returns
        -------
        str | None
            Path to chunks dataset root directory, or None if no override
            provided and no chunks dataset exists in the catalog.

        Raises
        ------
        TypeError
            If the parquet_root value in the database is not a string.

        Notes
        -----
        Time O(1) for override path; O(1) for catalog query assuming indexed
        datasets table. Performs a single SQL query when override is None.
        No side effects.

        Examples
        --------
        >>> # Requires active DuckDB connection
        >>> # root = SpladeIndex._resolve_chunks_root(connection, "/custom/path")
        >>> # assert root == "/custom/path"
        >>> # root = SpladeIndex._resolve_chunks_root(connection, None)
        >>> # assert root is None or isinstance(root, str)
        """
        if override:
            return override
        dataset: tuple[object, ...] | None = connection.execute(
            "SELECT parquet_root FROM datasets WHERE kind='chunks' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if dataset is None:
            return None
        root_obj = dataset[0]
        if not isinstance(root_obj, str):
            msg = f"Invalid parquet_root type: {type(root_obj)}"
            raise TypeError(msg)
        return root_obj

    @staticmethod
    def _read_chunk_rows(
        connection: DuckDBPyConnection, root: str
    ) -> list[tuple[object, object, object, object]]:
        """Read chunk rows from parquet files under the root directory.

        Extended Summary
        ----------------
        Executes a DuckDB query to read all parquet files matching the chunks
        pattern and returns raw row tuples. Filters rows to ensure they have
        at least PARQUET_ROW_WIDTH columns (chunk_id, doc_id, section, text).
        This method performs the I/O work of loading chunk data before
        normalization and document creation.

        Parameters
        ----------
        connection : DuckDBPyConnection
            Active DuckDB connection for executing parquet read queries.
        root : str
            Root directory containing parquet files in subdirectories.
            Pattern matches "*/*.parquet" under this root.

        Returns
        -------
        list[tuple[object, object, object, object]]
            List of row tuples with (chunk_id, doc_id, section, text) values.
            Values are raw database objects (may be str, None, or other types).

        Notes
        -----
        Time O(n) where n is the total number of chunks across all parquet
        files. Memory O(n) for storing all rows in memory. Performs I/O via
        DuckDB's read_parquet function. The union_by_name parameter allows
        reading parquet files with varying schemas. Rows with fewer than
        PARQUET_ROW_WIDTH columns are skipped.

        Examples
        --------
        >>> # Requires active DuckDB connection and valid root path
        >>> # rows = SpladeIndex._read_chunk_rows(connection, "/data/chunks")
        >>> # assert all(len(row) == 4 for row in rows)
        """
        root_path = Path(root)
        parquet_pattern = str(root_path / "*" / "*.parquet")
        sql = """
            SELECT c.chunk_id, c.doc_id, coalesce(c.section,''), c.text
            FROM read_parquet(?, union_by_name=true) AS c
        """
        raw_rows: Sequence[tuple[object, ...]] = connection.execute(
            sql, [parquet_pattern]
        ).fetchall()
        typed_rows: list[tuple[object, object, object, object]] = []
        for row in raw_rows:
            if len(row) < PARQUET_ROW_WIDTH:
                continue
            chunk_id_val, doc_id_val, section_val, text_val = row[:PARQUET_ROW_WIDTH]
            typed_rows.append((chunk_id_val, doc_id_val, section_val, text_val))
        return typed_rows

    def _populate_docs(self, rows: list[tuple[object, object, object, object]]) -> None:
        """Populate documents list from raw chunk row tuples.

        Extended Summary
        ----------------
        Converts raw database row tuples into SpladeDoc instances and appends
        them to the documents list. Normalizes values to strings and provides
        defaults for missing doc_id values ("urn:doc:fixture"). This method
        transforms raw I/O data into structured document objects for indexing.

        Parameters
        ----------
        rows : list[tuple[object, object, object, object]]
            List of row tuples with (chunk_id, doc_id, section, text) values.
            Values are converted to strings with defaults for None/empty doc_id.

        Notes
        -----
        Time O(n) where n is the number of rows. Memory O(n) for document
        storage. Mutates self.docs by appending new documents. No I/O or
        external side effects.

        Examples
        --------
        >>> index = SpladeIndex(db_path="/tmp/catalog.duckdb")
        >>> rows = [("chunk1", "doc1", "section1", "text1")]
        >>> index._populate_docs(rows)
        >>> len(index.docs) == 1
        True
        """
        for chunk_id_val, doc_id_val, section_val, text_val in rows:
            doc = SpladeDoc(
                chunk_id=str(chunk_id_val),
                doc_id=str(doc_id_val) or "urn:doc:fixture",
                section=str(section_val),
                text=str(text_val) or "",
            )
            self.docs.append(doc)

    def _recompute_document_frequencies(self) -> None:
        """Recompute document frequency (DF) counts for all terms.

        Extended Summary
        ----------------
        Clears the existing DF dictionary and rebuilds it by tokenizing each
        document's text and counting how many documents contain each unique term.
        Also updates self.N to the current document count. This method builds
        the core lexical index structure used for TF-IDF scoring during search.

        Notes
        -----
        Time O(n * m) where n is the number of documents and m is the average
        tokens per document. Memory O(v) where v is vocabulary size. Mutates
        self.N and self.df. No I/O or external side effects.

        Examples
        --------
        >>> index = SpladeIndex(db_path="/tmp/catalog.duckdb")
        >>> index.docs = [SpladeDoc("c1", "d1", "", "hello world")]
        >>> index._recompute_document_frequencies()
        >>> index.N == 1
        True
        >>> "hello" in index.df
        True
        """
        self.N = len(self.docs)
        self.df.clear()
        for doc in self.docs:
            for term in set(tok(doc.text)):
                self.df[term] = self.df.get(term, 0) + 1

    def search(self, query: str, k: int = 10) -> list[tuple[int, float]]:
        """Search documents using TF-IDF scoring.

        Tokenizes the query and scores each document using TF-IDF (term
        frequency-inverse document frequency). Returns top-k results sorted
        by relevance score.

        Parameters
        ----------
        query : str
            Search query text.
        k : int, optional
            Number of top results to return. Defaults to 10.

        Returns
        -------
        list[tuple[int, float]]
            List of (document_index, score) tuples sorted by score descending.
            Only documents with score > 0 are included.
        """
        if self.N == 0:
            return []
        terms = tok(query)
        if not terms:
            return []
        scores = [0.0] * self.N
        for index, doc in enumerate(self.docs):
            term_freq: dict[str, int] = {}
            for term in tok(doc.text):
                term_freq[term] = term_freq.get(term, 0) + 1
            score = 0.0
            for term in terms:
                if term in self.df:
                    idf = (self.N + 1) / (self.df[term] + 0.5)
                    score += term_freq.get(term, 0) * idf
            scores[index] = score

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
        return [(idx, value) for idx, value in ranked[:k] if value > 0.0]

    def doc(self, index: int) -> SpladeDoc:
        """Get document by index.

        Retrieves the document at the specified index from the loaded
        documents list.

        Parameters
        ----------
        index : int
            Document index (0-based).

        Returns
        -------
        SpladeDoc
            Document fixture at the specified index.
        """
        return self.docs[index]
