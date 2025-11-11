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

    Simple in-memory search index that loads document chunks from a DuckDB
    catalog and builds document frequency (DF) indexes for sparse retrieval.
    Used primarily for testing and tutorials as an example SPLADE index.

    Parameters
    ----------
    db_path : str
        Path to DuckDB catalog database file.
    chunks_dataset_root : str | None, optional
        Optional override path to chunks dataset root. If None, uses the
        latest chunks dataset from the catalog. Defaults to None.
    sparse_root : str | None, optional
        Optional sparse embeddings root (retained for interface compatibility).
        Currently unused. Defaults to None.
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
        for chunk_id_val, doc_id_val, section_val, text_val in rows:
            doc = SpladeDoc(
                chunk_id=str(chunk_id_val),
                doc_id=str(doc_id_val) or "urn:doc:fixture",
                section=str(section_val),
                text=str(text_val) or "",
            )
            self.docs.append(doc)

    def _recompute_document_frequencies(self) -> None:
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
