"""BM25 indexing workflow helpers."""

from __future__ import annotations

import importlib
import json
import logging
import shutil
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

import msgspec

from codeintel_rev.io.path_utils import resolve_within_repo
from kgfoundry_common.subprocess_utils import run_subprocess

if TYPE_CHECKING:
    from codeintel_rev.config.settings import Settings

GENERATOR_NAME = "codeintel_rev.io.bm25_manager"
CORPUS_METADATA_FILENAME = "metadata.json"
INDEX_METADATA_FILENAME = "metadata.json"

logger = logging.getLogger(__name__)


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


class BM25IndexManager:
    """Manage BM25 corpus preparation and Lucene index builds."""

    def __init__(
        self, settings: Settings, *, logger_: logging.Logger | None = None
    ) -> None:
        self._settings = settings
        self._logger = logger_ or logging.getLogger(__name__)
        self._repo_root = Path(settings.paths.repo_root).expanduser().resolve()
        self._config = settings.bm25

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
            source_path = resolve_within_repo(
                self._repo_root, source, allow_nonexistent=False
            )
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

                with (json_dir / f"{doc_id_str}.json").open(
                    "w", encoding="utf-8"
                ) as out_handle:
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
            _read_corpus_metadata(corpus_metadata_path)
            if corpus_metadata_path.exists()
            else None
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
        _run_pyserini_index(cmd)

        built_at = datetime.now(UTC).isoformat()
        pyserini_version = _detect_pyserini_version()
        index_size_bytes = _directory_size(resolved_index_dir)

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


__all__ = [
    "BM25BuildOptions",
    "BM25CorpusMetadata",
    "BM25CorpusSummary",
    "BM25IndexManager",
    "BM25IndexMetadata",
]
