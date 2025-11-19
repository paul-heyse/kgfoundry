"""BM25 indexing workflow helpers."""

from __future__ import annotations

import importlib
import json
import logging
import shutil
import sys
from collections.abc import Callable, Sequence
from collections.abc import Sequence as TypingSequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast

import msgspec

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.config.api import AppConfig
from codeintel_rev.io.bm25_engine import BM25Engine
from codeintel_rev.io.path_utils import resolve_within_repo
from kgfoundry_common.subprocess_utils import run_subprocess

GENERATOR_NAME = "codeintel_rev.io.bm25_manager"
CORPUS_METADATA_FILENAME = "metadata.json"
INDEX_METADATA_FILENAME = "metadata.json"

logger = logging.getLogger(__name__)

_lucene_search = LazyModule("pyserini.search.lucene", "bm25 search runtime")


class _LuceneHit(Protocol):
    """Protocol describing a Lucene search result hit.

    Attributes
    ----------
    docid : str | int
        Document identifier from the search result.
    score : float
        Relevance score assigned by the search engine.
    """

    docid: str | int
    score: float


class _LuceneSearcher(Protocol):
    """Protocol describing the Pyserini Lucene searcher interface.

    This protocol abstracts the Pyserini LuceneSearcher API to enable
    type-safe interaction with search functionality while maintaining
    compatibility across different Pyserini versions.
    """

    def search(self, query: str, k: int) -> TypingSequence[_LuceneHit]:
        """Search the index for documents matching the query.

        Parameters
        ----------
        query : str
            Query string to search for.
        k : int
            Maximum number of results to return.

        Returns
        -------
        TypingSequence[_LuceneHit]
            Sequence of search hits ordered by relevance score descending.
        """
        ...

    def set_bm25(self, k1: float, b: float) -> None:
        """Configure BM25 ranking parameters.

        Parameters
        ----------
        k1 : float
            Term frequency saturation parameter.
        b : float
            Length normalization parameter.
        """
        ...

    def set_rm3(self, fb_docs: int, fb_terms: int, original_query_weight: float) -> None:
        """Configure RM3 query expansion parameters.

        Parameters
        ----------
        fb_docs : int
            Number of feedback documents to use for expansion.
        fb_terms : int
            Number of expansion terms to add to the query.
        original_query_weight : float
            Weight given to the original query terms versus expansion terms.
        """
        ...

    def set_analyzer(self, analyzer: str) -> None:
        """Set the text analyzer for query processing.

        Parameters
        ----------
        analyzer : str
            Name of the analyzer to use (e.g., "english", "standard").
        """
        ...


class _LuceneMultiFieldSearcher(Protocol):
    """Protocol describing a multi-field Lucene searcher interface.

    This protocol extends the basic Lucene searcher with support for
    searching across multiple fields with per-field boost weights.
    """

    def search_fields(
        self,
        query: str,
        fields: Sequence[str],
        boosts: Sequence[float],
        k: int,
    ) -> TypingSequence[_LuceneHit]:
        """Search multiple fields with per-field boost weights.

        Parameters
        ----------
        query : str
            Query string to search for.
        fields : Sequence[str]
            Field names to search across.
        boosts : Sequence[float]
            Boost weights for each field, must match the length of fields.
        k : int
            Maximum number of results to return.

        Returns
        -------
        TypingSequence[_LuceneHit]
            Sequence of search hits ordered by relevance score descending.
        """
        ...

    def set_analyzer(self, analyzer: str) -> None:
        """Set the text analyzer for query processing.

        Parameters
        ----------
        analyzer : str
            Name of the analyzer to use (e.g., "english", "standard").
        """
        ...


class BM25CorpusMetadata(msgspec.Struct, frozen=True):
    """Metadata describing a prepared BM25 corpus."""

    doc_count: int
    source_path: str
    digest: str
    prepared_at: str
    generator: str


class BM25CorpusSummary(msgspec.Struct, frozen=True):
    """Summary information returned after preparing a corpus."""

    doc_count: int
    output_dir: str
    digest: str
    corpus_metadata_path: str


class BM25IndexMetadata(msgspec.Struct, frozen=True):
    """Metadata describing a built BM25 index."""

    doc_count: int
    built_at: str
    corpus_digest: str
    corpus_source: str
    pyserini_version: str
    threads: int
    index_dir: str
    index_size_bytes: int
    generator: str


class BM25BuildOptions(msgspec.Struct, frozen=True):
    """Options controlling BM25 index builds."""

    json_dir: str | Path | None = None
    index_dir: str | Path | None = None
    threads: int | None = None
    overwrite: bool = True
    store_positions: bool = True
    store_docvectors: bool = True
    store_raw: bool = True


@dataclass(frozen=True)
class BM25BuildContext:
    """Dependency injection hooks for BM25 index builds.

    Attributes
    ----------
    pyserini_runner : Callable[[list[str]], None]
        Function that executes Pyserini index commands. Used for dependency
        injection in tests.
    version_provider : Callable[[], str]
        Function that returns the Pyserini version string. Used for dependency
        injection in tests.
    directory_size : Callable[[Path], int]
        Function that computes total size of all files in a directory. Used
        for dependency injection in tests.
    clock : Callable[[], datetime]
        Clock function returning current UTC datetime. Used for timestamping
        index builds. Used for dependency injection in tests.
    """

    pyserini_runner: Callable[[list[str]], None]
    version_provider: Callable[[], str]
    directory_size: Callable[[Path], int]
    clock: Callable[[], datetime]

    @classmethod
    def production(cls) -> BM25BuildContext:
        """Return the default build context used in production.

        Returns
        -------
        BM25BuildContext
            Context configured with runtime subprocess, filesystem, and clock helpers.
        """
        return cls(
            pyserini_runner=_run_pyserini_index,
            version_provider=_detect_pyserini_version,
            directory_size=_directory_size,
            clock=lambda: datetime.now(UTC),
        )


class BM25IndexManager:
    """Manage BM25 corpus preparation and Lucene index builds."""

    def __init__(
        self,
        app_config: AppConfig,
        *,
        logger_: logging.Logger | None = None,
        build_context: BM25BuildContext | None = None,
    ) -> None:
        """Initialize BM25 index manager.

        Parameters
        ----------
        app_config : AppConfig
            Immutable application configuration containing BM25 settings.
        logger_ : logging.Logger | None, optional
            Custom logger instance. If None, uses module logger.
        build_context : BM25BuildContext | None, optional
            Build context for index construction. If None, uses production context.
        """
        self._logger = logger_ or logging.getLogger(__name__)
        self._repo_root = Path(app_config.paths.repo_root).expanduser().resolve()
        self._config = app_config.bm25
        self._build_context = build_context or BM25BuildContext.production()

    @property
    def corpus_dir(self) -> Path:
        """Return the resolved corpus JsonCollection directory."""
        return resolve_within_repo(self._repo_root, self._config.corpus_json_dir)

    @property
    def index_dir(self) -> Path:
        """Return the resolved Lucene index directory."""
        return resolve_within_repo(self._repo_root, self._config.index_dir)

    def prepare_corpus(
        self,
        source: str | Path,
        *,
        output_dir: str | Path | None = None,
        overwrite: bool = True,
    ) -> BM25CorpusSummary:
        """Materialize a Pyserini JsonCollection directory from a JSONL source.

        Parameters
        ----------
        source : str | Path
            Path to the JSONL corpus containing ``{"id": "...", "contents": ...}`` rows.
        output_dir : str | Path | None, optional
            Override the configured JsonCollection directory. If None, uses the
            default corpus directory from configuration. The directory will be
            created if it doesn't exist. Defaults to None.
        overwrite : bool, optional
            When ``True`` (default) existing documents in the output directory are removed.

        Returns
        -------
        BM25CorpusSummary
            Summary describing the prepared corpus and metadata location.

        Raises
        ------
        FileNotFoundError
            If ``source`` does not exist.
        ValueError
            If a document is missing required fields or duplicated.
        FileExistsError
            If ``overwrite`` is ``False`` and the output directory already contains documents.
        """
        try:
            source_path = resolve_within_repo(self._repo_root, source, allow_nonexistent=False)
        except FileNotFoundError as exc:  # pragma: no cover - exercised in tests
            msg = f"Corpus source {source} does not exist"
            raise FileNotFoundError(msg) from exc
        json_dir = (
            resolve_within_repo(self._repo_root, output_dir)
            if output_dir is not None
            else self.corpus_dir
        )
        json_dir.mkdir(parents=True, exist_ok=True)

        if overwrite:
            for existing in json_dir.glob("*.json"):
                existing.unlink()
        else:
            existing_docs = list(json_dir.glob("*.json"))
            if existing_docs:
                msg = f"Corpus directory {json_dir} is not empty"
                raise FileExistsError(msg)

        doc_count = 0
        digest = sha256()
        seen_ids: set[str] = set()

        with source_path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                try:
                    parsed = _parse_corpus_line(
                        raw_line,
                        line_number=line_number,
                        seen_ids=seen_ids,
                        source_path=source_path,
                    )
                except ValueError as exc:
                    raise ValueError(str(exc)) from exc
                if parsed is None:
                    continue
                doc_id_str, contents = parsed

                digest.update(doc_id_str.encode("utf-8"))
                digest.update(b"\x1f")
                digest.update(contents.encode("utf-8"))
                digest.update(b"\x1e")

                with (json_dir / f"{doc_id_str}.json").open("w", encoding="utf-8") as out_handle:
                    json.dump(
                        {"id": doc_id_str, "contents": contents},
                        out_handle,
                        ensure_ascii=False,
                    )
                doc_count += 1

        prepared_at = datetime.now(UTC).isoformat()
        corpus_metadata = BM25CorpusMetadata(
            doc_count=doc_count,
            source_path=str(source_path),
            digest=digest.hexdigest(),
            prepared_at=prepared_at,
            generator=GENERATOR_NAME,
        )
        metadata_path = json_dir / CORPUS_METADATA_FILENAME
        _write_struct(metadata_path, corpus_metadata)

        self._logger.info(
            "Prepared BM25 corpus at %s (docs=%s, digest=%s)",
            json_dir,
            doc_count,
            corpus_metadata.digest,
        )

        return BM25CorpusSummary(
            doc_count=doc_count,
            output_dir=str(json_dir),
            digest=corpus_metadata.digest,
            corpus_metadata_path=str(metadata_path),
        )

    def build_index(self, options: BM25BuildOptions | None = None) -> BM25IndexMetadata:
        """Invoke Pyserini to build a Lucene BM25 index.

        Parameters
        ----------
        options : BM25BuildOptions | None, optional
            Build options. When omitted, defaults from configuration are used.

        Returns
        -------
        BM25IndexMetadata
            Structured metadata describing the resulting Lucene index.

        Raises
        ------
        FileNotFoundError
            If the JsonCollection directory does not exist.
        FileExistsError
            If ``overwrite`` is ``False`` and the index directory already contains data.
        """
        opts = options or BM25BuildOptions()
        resolved_json_dir = (
            resolve_within_repo(self._repo_root, opts.json_dir)
            if opts.json_dir is not None
            else self.corpus_dir
        )
        resolved_index_dir = (
            resolve_within_repo(self._repo_root, opts.index_dir)
            if opts.index_dir is not None
            else self.index_dir
        )
        resolved_json_dir.mkdir(parents=True, exist_ok=True)
        if not resolved_json_dir.exists():
            msg = f"JsonCollection directory {resolved_json_dir} does not exist"
            raise FileNotFoundError(msg)

        if resolved_index_dir.exists():
            has_contents = any(resolved_index_dir.iterdir())
            if has_contents and not opts.overwrite:
                msg = f"Index directory {resolved_index_dir} already contains data"
                raise FileExistsError(msg)
            if has_contents and opts.overwrite:
                shutil.rmtree(resolved_index_dir)
        resolved_index_dir.mkdir(parents=True, exist_ok=True)

        corpus_metadata_path = resolved_json_dir / CORPUS_METADATA_FILENAME
        corpus_metadata = (
            _read_corpus_metadata(corpus_metadata_path) if corpus_metadata_path.exists() else None
        )

        cmd = [
            sys.executable,
            "-m",
            "pyserini.index.lucene",
            "--collection",
            "JsonCollection",
            "--input",
            str(resolved_json_dir),
            "--index",
            str(resolved_index_dir),
            "--generator",
            "DefaultLuceneDocumentGenerator",
            "--threads",
            str(opts.threads if opts.threads is not None else self._config.threads),
        ]
        if opts.store_positions:
            cmd.append("--storePositions")
        if opts.store_docvectors:
            cmd.append("--storeDocvectors")
        if opts.store_raw:
            cmd.append("--storeRaw")

        self._logger.info("Building BM25 index via Pyserini: %s", " ".join(cmd))
        self._build_context.pyserini_runner(cmd)

        built_at = self._build_context.clock().isoformat()
        pyserini_version = self._build_context.version_provider()
        index_size_bytes = self._build_context.directory_size(resolved_index_dir)

        metadata = BM25IndexMetadata(
            doc_count=(corpus_metadata.doc_count if corpus_metadata else 0),
            built_at=built_at,
            corpus_digest=(corpus_metadata.digest if corpus_metadata else ""),
            corpus_source=(corpus_metadata.source_path if corpus_metadata else ""),
            pyserini_version=pyserini_version,
            threads=int(cmd[cmd.index("--threads") + 1]),
            index_dir=str(resolved_index_dir),
            index_size_bytes=index_size_bytes,
            generator=GENERATOR_NAME,
        )
        _write_struct(resolved_index_dir / INDEX_METADATA_FILENAME, metadata)

        self._logger.info(
            "Built BM25 index at %s (docs=%s, size=%s bytes)",
            resolved_index_dir,
            metadata.doc_count,
            metadata.index_size_bytes,
        )
        return metadata


def _write_struct(path: Path, data: msgspec.Struct) -> None:
    """Write a msgspec struct to JSON with UTF-8 encoding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = msgspec.json.encode(data)
    path.write_text(serialized.decode("utf-8"), encoding="utf-8")


def _read_corpus_metadata(path: Path) -> BM25CorpusMetadata:
    """Read corpus metadata from JSON file.

    This helper function deserializes BM25 corpus metadata from a JSON file
    created during corpus preparation. The metadata contains information about
    document count, source path, content digest, preparation timestamp, and
    generator identifier.

    Parameters
    ----------
    path : Path
        File path to the JSON metadata file. The file must exist and contain
        valid BM25CorpusMetadata JSON serialized data.

    Returns
    -------
    BM25CorpusMetadata
        Decoded metadata structure containing corpus statistics and provenance
        information. Includes document count, source path, SHA-256 digest of
        corpus content, ISO 8601 timestamp, and generator name.

    Notes
    -----
    Exception Propagation:
        This function may propagate exceptions from underlying operations:
        - FileNotFoundError: If the metadata file does not exist (from path.read_bytes())
        - msgspec.DecodeError: If the file contains invalid JSON or data that doesn't
          match the BM25CorpusMetadata schema (from msgspec.json.decode())
    """
    return msgspec.json.decode(path.read_bytes(), type=BM25CorpusMetadata)


def _parse_corpus_line(
    raw_line: str,
    *,
    line_number: int,
    seen_ids: set[str],
    source_path: Path,
) -> tuple[str, str] | None:
    """Parse and validate a JSONL line from the corpus source.

    This function parses a single line from a JSONL corpus file, validates that
    it contains required fields (id and contents/text), checks for duplicate
    document IDs, and returns the parsed document identifier and content. Empty
    lines are skipped by returning None.

    The function maintains a set of seen document IDs to detect duplicates within
    the corpus, which is important for ensuring corpus integrity and preventing
    indexing errors.

    Parameters
    ----------
    raw_line : str
        Raw line from the JSONL file, including any trailing whitespace or
        newline characters. Will be stripped before parsing.
    line_number : int
        One-based line number in the source file. Used for error messages to
        help identify problematic lines during corpus preparation.
    seen_ids : set[str]
        Set of document IDs that have been encountered in previous lines. This
        set is mutated by adding the current document ID if parsing succeeds.
        Used to detect duplicate document IDs within the corpus.
    source_path : Path
        Path to the source JSONL file. Used in error messages to provide context
        about which file contains the problematic line.

    Returns
    -------
    tuple[str, str] | None
        Tuple of (doc_id, contents) if the line was successfully parsed and
        validated. Returns None if the line is empty (after stripping) or should
        be skipped for any reason.

    Raises
    ------
    ValueError
        Raised in the following cases:
        - Line contains invalid JSON (JSONDecodeError)
        - Document object is missing the 'id' field
        - Document ID has already been seen (duplicate)
        - Document is missing both 'contents' and 'text' fields, or the content
          field is empty or not a string
    """
    stripped_line = raw_line.strip()
    if not stripped_line:
        return None
    try:
        obj = json.loads(stripped_line)
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON on line {line_number} of {source_path}"
        raise ValueError(msg) from exc

    doc_id_raw = obj.get("id")
    if doc_id_raw is None:
        msg = f"Document on line {line_number} is missing 'id'"
        raise ValueError(msg)
    doc_id_str = str(doc_id_raw)
    if doc_id_str in seen_ids:
        msg = f"Duplicate document id '{doc_id_str}' on line {line_number}"
        raise ValueError(msg)
    seen_ids.add(doc_id_str)

    contents = obj.get("contents", obj.get("text"))
    if not isinstance(contents, str) or not contents:
        msg = f"Document '{doc_id_str}' is missing textual contents"
        raise ValueError(msg)
    return doc_id_str, contents


def _run_pyserini_index(cmd: list[str]) -> None:
    """Execute the Pyserini index command and raise for failures."""
    run_subprocess(cmd)


def _detect_pyserini_version() -> str:
    """Return the installed Pyserini version or ``'unknown'`` if unavailable.

    Returns
    -------
    str
        The Pyserini version string, or ``'unknown'`` if the package is not installed.
    """
    try:
        module = importlib.import_module("pyserini")
    except ModuleNotFoundError:
        return "unknown"
    version = getattr(module, "__version__", None)
    return str(version) if version is not None else "unknown"


def _directory_size(path: Path) -> int:
    """Compute total size in bytes for all files beneath a directory.

    This utility function recursively traverses a directory tree and sums the
    sizes of all regular files found. It's used to calculate index sizes for
    metadata purposes. Symbolic links are followed, but directories themselves
    don't contribute to the size.

    Parameters
    ----------
    path : Path
        Root directory path to measure. The function recursively traverses all
        subdirectories and sums file sizes. The path must exist and be a directory.

    Returns
    -------
    int
        Total size in bytes for all regular files contained within the directory
        tree. Returns 0 if the directory is empty or contains no files. The
        size is calculated using file system stat information (st_size).
    """
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


@dataclass(frozen=True, slots=True)
class BM25QueryOptions:
    """Runtime BM25 search parameters.

    Attributes
    ----------
    top_k : int, optional
        Maximum number of results to return. Must be positive. Defaults to 50.
    k1 : float | None, optional
        BM25 k1 parameter (term frequency saturation). None means use index
        defaults. Must be positive if specified. Defaults to None.
    b : float | None, optional
        BM25 b parameter (length normalization). None means use index defaults.
        Must be between 0.0 and 1.0 if specified. Defaults to None.
    rm3 : bool | None, optional
        Whether to enable RM3 pseudo-relevance feedback. None means use
        configuration defaults. Defaults to None.
    rm3_fb_terms : int | None, optional
        Number of feedback terms for RM3. None means use RM3 params defaults.
        Must be positive if specified. Defaults to None.
    rm3_fb_docs : int | None, optional
        Number of feedback documents for RM3. None means use RM3 params defaults.
        Must be positive if specified. Defaults to None.
    rm3_original_weight : float | None, optional
        Weight for original query in RM3. None means use RM3 params defaults.
        Must be between 0.0 and 1.0 if specified. Defaults to None.
    field_weights : dict[str, float] | None, optional
        Per-field weight overrides for multi-field indexes. None means use
        index defaults. Defaults to None.
    """

    top_k: int = 50
    k1: float | None = None
    b: float | None = None
    rm3: bool | None = None
    rm3_fb_terms: int | None = None
    rm3_fb_docs: int | None = None
    rm3_original_weight: float | None = None
    field_weights: dict[str, float] | None = None


@dataclass(frozen=True, slots=True)
class BM25Hit:
    """Typed BM25 hit row.

    Attributes
    ----------
    doc_id : int
        Document/chunk identifier returned by the search.
    score : float
        BM25 relevance score for this hit. Higher scores indicate better matches.
    """

    doc_id: int
    score: float


class BM25QueryEngine:
    """Thin BM25 query surface backed by Pyserini searchers."""

    def __init__(self, index_dir: Path, *, analyzer: str | None = None) -> None:
        """Initialize BM25 query engine.

        Parameters
        ----------
        index_dir : Path
            Path to the Lucene BM25 index directory.
        analyzer : str | None, optional
            Optional analyzer name for query processing.
        """
        self._index_dir = Path(index_dir).resolve()
        self._analyzer = analyzer
        self._searcher: _LuceneSearcher | None = None
        self._mf_searcher: _LuceneMultiFieldSearcher | None = None

    def search(
        self,
        query: str,
        *,
        options: BM25QueryOptions | None = None,
    ) -> list[BM25Hit]:
        """Return BM25 hits for ``query``.

        Parameters
        ----------
        query : str
            Query text to search for.
        options : BM25QueryOptions | None, optional
            Optional BM25 search configuration (k1, b, rm3, etc.).

        Returns
        -------
        list[BM25Hit]
            List of BM25 search hits sorted by score descending.
        """
        opts = options or BM25QueryOptions()
        module = _lucene_search.module()
        searcher = self._ensure_searcher(module)

        if opts.k1 is not None or opts.b is not None:
            k1 = float(opts.k1 if opts.k1 is not None else 0.9)
            b = float(opts.b if opts.b is not None else 0.4)
            searcher.set_bm25(k1=k1, b=b)

        if opts.rm3:
            fb_terms = int(opts.rm3_fb_terms or 10)
            fb_docs = int(opts.rm3_fb_docs or 10)
            orig_w = float(opts.rm3_original_weight or 0.5)
            searcher.set_rm3(fb_terms=fb_terms, fb_docs=fb_docs, original_query_weight=orig_w)

        hits_raw = None
        if opts.field_weights:
            hits_raw = self._search_multi_field(
                module,
                query,
                opts.field_weights,
                searcher,
                int(opts.top_k),
            )

        if hits_raw is None:
            qtext = self._compose_fielded_query(query, opts.field_weights)
            hits_raw = searcher.search(qtext, k=int(opts.top_k))

        return [
            BM25Hit(doc_id=_bm25_docid_to_int(hit.docid), score=float(hit.score))
            for hit in hits_raw
        ]

    def search_batch(
        self,
        queries: Sequence[str],
        *,
        options: BM25QueryOptions | None = None,
    ) -> list[list[BM25Hit]]:
        """Execute BM25 search sequentially for ``queries``.

        Parameters
        ----------
        queries : Sequence[str]
            Sequence of query texts to search for.
        options : BM25QueryOptions | None, optional
            Optional BM25 search configuration applied to all queries.

        Returns
        -------
        list[list[BM25Hit]]
            List of search result lists, one per query.
        """
        return [self.search(query, options=options) for query in queries]

    def _ensure_searcher(self, module: object) -> _LuceneSearcher:
        """Create or return a cached Lucene searcher instance.

        Parameters
        ----------
        module : object
            The Pyserini Lucene search module containing the LuceneSearcher class.

        Returns
        -------
        _LuceneSearcher
            A Lucene searcher instance bound to the index directory. The searcher
            is cached after first creation and configured with the analyzer if
            one was specified during engine initialization.
        """
        searcher = self._searcher
        if searcher is not None:
            return searcher
        lucene_module = cast("Any", module)
        searcher = cast("_LuceneSearcher", lucene_module.LuceneSearcher(str(self._index_dir)))
        if self._analyzer:
            searcher.set_analyzer(self._analyzer)
        self._searcher = searcher
        return searcher

    def _search_multi_field(
        self,
        module: object,
        query: str,
        weights: dict[str, float],
        default_searcher: _LuceneSearcher,
        limit: int,
    ) -> TypingSequence[_LuceneHit] | None:
        """Perform multi-field search with per-field boost weights.

        Parameters
        ----------
        module : object
            The Pyserini Lucene search module, used to create a multi-field
            searcher if available.
        query : str
            Query text to search for.
        weights : dict[str, float]
            Dictionary mapping field names to boost weights.
        default_searcher : _LuceneSearcher
            Fallback searcher to use if multi-field search is not available.
        limit : int
            Maximum number of results to return.

        Returns
        -------
        TypingSequence[_LuceneHit] | None
            Sequence of search hits if multi-field search is supported, None
            if multi-field search is not available and fallback to default
            searcher failed.
        """
        if self._mf_searcher is None:
            mf_cls = getattr(module, "LuceneMultiFieldSearcher", None)
            if mf_cls is not None:
                self._mf_searcher = cast("_LuceneMultiFieldSearcher", mf_cls(str(self._index_dir)))
                if self._analyzer and hasattr(self._mf_searcher, "set_analyzer"):
                    self._mf_searcher.set_analyzer(self._analyzer)
        if self._mf_searcher is not None and hasattr(self._mf_searcher, "search_fields"):
            fields = list(weights.keys())
            boosts = [float(value) for value in weights.values()]
            return self._mf_searcher.search_fields(query, fields, boosts, k=limit)
        if hasattr(default_searcher, "search_fields"):
            fields = list(weights.keys())
            boosts = [float(value) for value in weights.values()]
            mf_default = cast("_LuceneMultiFieldSearcher", default_searcher)
            return mf_default.search_fields(query, fields, boosts, k=limit)
        return None

    @staticmethod
    def _compose_fielded_query(query: str, weights: dict[str, float] | None) -> str:
        """Compose a Lucene query string with field-specific boosts.

        Parameters
        ----------
        query : str
            Base query text to search for.
        weights : dict[str, float] | None
            Dictionary mapping field names to boost weights. If None or empty,
            returns the base query unchanged.

        Returns
        -------
        str
            A Lucene query string combining the base query with field-specific
            boosted queries. Format: "(query) (field1:(query))^weight1 ..."
        """
        if not weights:
            return query
        parts = [f"({query})"]
        for field, weight in weights.items():
            parts.append(f"({field}:({query}))^{float(weight)}")
        return " ".join(parts)


def _bm25_docid_to_int(docid: str | int) -> int:
    """Best-effort conversion from Lucene docid to integer chunk id.

    Parameters
    ----------
    docid : str | int
        Lucene document ID string or integer (may include "chunk:" prefix).

    Returns
    -------
    int
        Extracted integer chunk ID.
    """
    text = str(docid).strip()
    if text.startswith("chunk:"):
        text = text.split(":", 1)[1]
    try:
        return int(text)
    except ValueError:
        digits = ""
        for char in reversed(text):
            if char.isdigit():
                digits = char + digits
            else:
                break
        try:
            return int(digits) if digits else -1
        except ValueError:
            return -1


__all__ = [
    "BM25BuildOptions",
    "BM25CorpusMetadata",
    "BM25CorpusSummary",
    "BM25Engine",
    "BM25Hit",
    "BM25IndexManager",
    "BM25IndexMetadata",
    "BM25QueryEngine",
    "BM25QueryOptions",
]
