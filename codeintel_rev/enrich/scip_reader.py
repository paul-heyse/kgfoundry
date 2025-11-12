# SPDX-License-Identifier: MIT
"""Lightweight helpers for loading and querying SCIP JSON indices."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional dependency
    import orjson as _orjson  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    _orjson = None  # type: ignore[assignment]


def _loads(payload: bytes) -> object:
    """Deserialize JSON bytes using orjson when available.

    Parameters
    ----------
    payload : bytes
        JSON-encoded bytes to deserialize. Must be valid UTF-8 when orjson
        is unavailable (falls back to stdlib json).

    Returns
    -------
    object
        Parsed JSON payload (typically a dict or list).
    """
    if _orjson is not None:
        return _orjson.loads(payload)
    return json.loads(payload.decode("utf-8"))


@dataclass(slots=True, frozen=True)
class Occurrence:
    """Symbol occurrence entry extracted from the SCIP schema."""

    symbol: str
    range: list[int] | None = None
    roles: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SymbolInfo:
    """Symbol metadata bundled with a document."""

    symbol: str
    documentation: list[str] = field(default_factory=list)
    kind: str | None = None
    relationships: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class Document:
    """SCIP document entry (per source file)."""

    path: str
    occurrences: list[Occurrence] = field(default_factory=list)
    symbols: list[SymbolInfo] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SCIPIndex:
    """In-memory representation of a SCIP dataset."""

    documents: list[Document] = field(default_factory=list)
    external_symbols: dict[str, SymbolInfo] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> SCIPIndex:
        """Load the index from ``path`` (JSON file).

        Parameters
        ----------
        path : str | Path
            File system path to the SCIP JSON index file. May be absolute
            or relative to the current working directory.

        Returns
        -------
        SCIPIndex
            Parsed index containing documents and external symbols. Returns
            an empty index if the file is missing or malformed.
        """
        raw_blob = _loads(Path(path).read_bytes())
        if not isinstance(raw_blob, dict):
            return cls()
        documents = [_parse_document(doc_record) for doc_record in raw_blob.get("documents", [])]
        external = {
            entry.get("symbol", ""): SymbolInfo(
                symbol=entry.get("symbol", ""),
                documentation=list(entry.get("documentation", [])),
                kind=entry.get("kind"),
                relationships=list(entry.get("relationships", [])),
            )
            for entry in raw_blob.get("externalSymbols", [])
        }
        return cls(documents=documents, external_symbols=external)

    def by_file(self) -> dict[str, Document]:
        """Return a mapping of relative path → SCIP document.

        Returns
        -------
        dict[str, Document]
            Mapping of file paths to SCIP documents.
        """
        return {doc.path: doc for doc in self.documents}

    def symbol_to_files(self) -> dict[str, list[str]]:
        """Return occurrences grouped by symbol.

        Returns
        -------
        dict[str, list[str]]
            Mapping of symbol identifiers to file paths.
        """
        mapping: dict[str, list[str]] = {}
        for doc in self.documents:
            for occurrence in doc.occurrences:
                mapping.setdefault(occurrence.symbol, []).append(doc.path)
        return mapping

    def file_symbol_kinds(self) -> dict[str, dict[str, str]]:
        """Return symbol-kind maps per file.

        Returns
        -------
        dict[str, dict[str, str]]
            Mapping of file paths to symbol-kind dictionaries.
        """
        result: dict[str, dict[str, str]] = {}
        for doc in self.documents:
            kinds = {symbol.symbol: symbol.kind for symbol in doc.symbols if symbol.kind}
            if kinds:
                result[doc.path] = kinds
        return result


def _parse_document(record: dict[str, Any]) -> Document:
    """Convert a raw SCIP document record into a :class:`Document`.

    Parameters
    ----------
    record : dict[str, Any]
        Raw SCIP document dictionary containing keys like "relativePath",
        "occurrences", "symbols", etc. The dictionary may use snake_case
        or camelCase keys (both formats are supported).

    Returns
    -------
    Document
        Parsed document extracted from the raw SCIP payload.
    """
    relative_path = (
        record.get("relativePath") or record.get("relative_path") or record.get("path", "")
    )
    occurrences = [
        Occurrence(
            symbol=occurrence.get("symbol", ""),
            range=occurrence.get("range"),
            roles=[
                role
                for role in (occurrence.get("symbolRoles") or occurrence.get("roles") or [])
                if isinstance(role, str)
            ],
        )
        for occurrence in record.get("occurrences", [])
    ]
    symbols = [
        SymbolInfo(
            symbol=symbol.get("symbol", ""),
            documentation=list(symbol.get("documentation", [])),
            kind=symbol.get("kind"),
            relationships=list(symbol.get("relationships", [])),
        )
        for symbol in record.get("symbols", [])
    ]
    return Document(path=relative_path, occurrences=occurrences, symbols=symbols)
