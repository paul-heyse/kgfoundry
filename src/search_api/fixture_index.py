"""Overview of fixture index.

This module bundles fixture index logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, cast

from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.typing import gate_import
from registry.duckdb_helpers import fetch_all, fetch_one

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from duckdb import DuckDBPyConnection

__all__ = [
    "FixtureDoc",
    "FixtureIndex",
    "tokenize",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@lru_cache(maxsize=1)
def _duckdb_module() -> ModuleType:
    """Return duckdb module resolved lazily for fixture index loading.

    Returns
    -------
    ModuleType
        Imported :mod:`duckdb` module reference.
    """
    return cast("ModuleType", gate_import("duckdb", "fixture index loading"))


def _as_str(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


# [nav:anchor tokenize]
def tokenize(text: str) -> list[str]:
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
    matches: list[str] = TOKEN_RE.findall(text or "")
    return [token.lower() for token in matches]


# [nav:anchor FixtureDoc]
@dataclass(frozen=True)
class FixtureDoc:
    """Document fixture for test and tutorial use.

    Represents a document chunk loaded from the fixture index. Inline attribute docstrings note
    alias usage for clarity and mkdocstrings compatibility.
    """

    chunk_id: str
    """Unique chunk identifier.

    Alias: none; name ``chunk_id``.
    """
    doc_id: str
    """Parent document identifier.

    Alias: none; name ``doc_id``.
    """
    title: str
    """Document title.

    Alias: none; name ``title``.
    """
    section: str
    """Optional section heading.

    Alias: none; name ``section``.
    """
    text: str
    """Chunk text content.

    Alias: none; name ``text``.
    """


# [nav:anchor FixtureIndex]
class FixtureIndex:
    """In-memory fixture index for tests and tutorials.

    Simple in-memory search index that loads document chunks from a DuckDB
    catalog and builds term frequency (TF) and document frequency (DF)
    indexes for basic text search. Used primarily for testing and tutorials.

    Parameters
    ----------
    root : str, optional
        Root directory path for data files. Defaults to "/data".
    db_path : str, optional
        Path to DuckDB catalog database file. Defaults to
        "/data/catalog/catalog.duckdb".
    """

    def __init__(self, root: str = "/data", db_path: str = "/data/catalog/catalog.duckdb") -> None:
        self.root = Path(root)
        self.db_path = db_path
        self.docs: list[FixtureDoc] = []
        self.df: dict[str, int] = {}
        self.tf: list[dict[str, int]] = []
        self._load_from_duckdb()

    def _load_from_duckdb(self) -> None:
        """Load documents from DuckDB catalog.

        Connects to the DuckDB database, finds the latest chunks dataset, and loads all document
        chunks into memory. Then builds the lexical index for search.
        """
        db_file = Path(self.db_path)
        if not db_file.exists():
            return

        duckdb_module = _duckdb_module()
        with duckdb_module.connect(str(db_file)) as connection:
            root_path = self._latest_chunks_root(connection)
            if root_path is None:
                return
            for doc in self._iter_fixture_docs(connection, root_path):
                self.docs.append(doc)

        self._build_lex()

    @staticmethod
    def _latest_chunks_root(connection: DuckDBPyConnection) -> Path | None:
        dataset_row = fetch_one(
            connection,
            """
              SELECT parquet_root FROM datasets
              WHERE kind='chunks'
              ORDER BY created_at DESC
              LIMIT 1
            """,
        )
        if dataset_row is None:
            return None
        parquet_root = dataset_row[0]
        if not isinstance(parquet_root, str):
            msg = f"Invalid parquet_root type: {type(parquet_root)}"
            raise TypeError(msg)
        return Path(parquet_root)

    @staticmethod
    def _iter_fixture_docs(
        connection: DuckDBPyConnection, root_path: Path
    ) -> Iterator[FixtureDoc]:
        parquet_pattern = str(root_path / "*" / "*.parquet")
        rows: Sequence[tuple[object, ...]] = fetch_all(
            connection,
            """
                SELECT c.chunk_id, c.doc_id, coalesce(c.section,''), c.text,
                       coalesce(d.title,'') AS title
                FROM read_parquet(?, union_by_name=true) AS c
                LEFT JOIN documents d ON c.doc_id = d.doc_id
            """,
            [parquet_pattern],
        )
        for chunk_id_val, doc_id_val, section_val, text_val, title_val in rows:
            chunk_id = _as_str(chunk_id_val)
            doc_id = _as_str(doc_id_val)
            section = _as_str(section_val)
            text = _as_str(text_val)
            title = _as_str(title_val)
            yield FixtureDoc(
                chunk_id=chunk_id,
                doc_id=doc_id or "urn:doc:fixture",
                title=title or "Fixture",
                section=section or "",
                text=text or "",
            )

    def _build_lex(self) -> None:
        """Build lexical index (TF/DF structures) from loaded documents.

        Computes term frequency (TF) for each document and document frequency (DF) for each token
        across all documents. Sets self.N to the total number of documents.
        """
        self.tf.clear()
        self.df.clear()
        for doc in self.docs:
            tokens = tokenize(doc.text)
            tf_counts: dict[str, int] = {}
            for token in tokens:
                tf_counts[token] = tf_counts.get(token, 0) + 1
            self.tf.append(tf_counts)
            for token in set(tokens):
                self.df[token] = self.df.get(token, 0) + 1
        self.N = len(self.docs)

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
        if not hasattr(self, "N") or self.N == 0:
            return []
        qtoks = tokenize(query)
        if not qtoks:
            return []
        scores = [0.0] * self.N
        for i, tf in enumerate(self.tf):
            score = 0.0
            for token in qtoks:
                if token not in self.df:
                    continue
                idf = math.log((self.N + 1) / (self.df[token] + 0.5) + 1.0)
                score += idf * tf.get(token, 0)
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
        return [(index, score) for index, score in ranked[:k] if score > 0.0]

    def doc(self, index: int) -> FixtureDoc:
        """Get document by index.

        Retrieves the document at the specified index from the loaded
        documents list.

        Parameters
        ----------
        index : int
            Document index (0-based).

        Returns
        -------
        FixtureDoc
            Document fixture at the specified index.
        """
        return self.docs[index]
