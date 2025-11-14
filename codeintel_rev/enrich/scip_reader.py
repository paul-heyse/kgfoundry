# SPDX-License-Identifier: MIT
"""Lightweight helpers for loading and querying SCIP JSON indices."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import msgspec


class Occurrence(msgspec.Struct, frozen=True, omit_defaults=True):
    """Symbol occurrence entry extracted from the SCIP schema."""

    symbol: str = ""
    range: list[int] | None = None
    roles: list[str] = msgspec.field(default_factory=list)


class SymbolInfo(msgspec.Struct, frozen=True, omit_defaults=True):
    """Symbol metadata bundled with a document."""

    symbol: str = ""
    documentation: list[str] = msgspec.field(default_factory=list)
    kind: str | None = None
    relationships: list[dict[str, Any]] = msgspec.field(default_factory=list)


class Document(msgspec.Struct, frozen=True, omit_defaults=True):
    """SCIP document entry (per source file)."""

    path: str = msgspec.field(name="relativePath", default="")
    occurrences: list[Occurrence] = msgspec.field(default_factory=list)
    symbols: list[SymbolInfo] = msgspec.field(default_factory=list)


class _SCIPPayload(msgspec.Struct, frozen=True, omit_defaults=True):
    documents: list[Document] = msgspec.field(default_factory=list)
    external_symbols: list[SymbolInfo] = msgspec.field(default_factory=list, name="externalSymbols")


class SCIPIndex:
    """In-memory representation of a SCIP dataset."""

    __slots__ = ("_by_file_cache", "_documents", "_external_symbols")

    def __init__(
        self,
        documents: list[Document] | None = None,
        external_symbols: dict[str, SymbolInfo] | None = None,
    ) -> None:
        self._documents = documents or []
        self._external_symbols = external_symbols or {}
        self._by_file_cache: dict[str, Document] | None = None

    @property
    def documents(self) -> list[Document]:
        """Return the list of SCIP documents loaded from the index.

        Returns
        -------
        list[Document]
            List of SCIP document objects, each containing occurrences, symbols,
            and metadata for a single source file. The list is empty if no
            documents were loaded or if the index was empty.
        """
        return self._documents

    @property
    def external_symbols(self) -> dict[str, SymbolInfo]:
        """Return the mapping of external symbol identifiers to symbol information.

        Returns
        -------
        dict[str, SymbolInfo]
            Dictionary mapping external symbol identifiers (e.g., "pkg:module.Class")
            to their symbol information objects. External symbols are symbols defined
            outside the indexed codebase (e.g., standard library, third-party packages).
            The dictionary is empty if no external symbols were loaded.
        """
        return self._external_symbols

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
            Parsed index containing documents and external symbols.
        """
        payload = Path(path).read_bytes()
        model = msgspec.json.decode(payload, type=_SCIPPayload)
        external = {entry.symbol: entry for entry in model.external_symbols if entry.symbol}
        return cls(documents=list(model.documents), external_symbols=external)

    def by_file(self) -> dict[str, Document]:
        """Return a mapping of relative path → SCIP document.

        Returns
        -------
        dict[str, Document]
            Mapping of file paths to SCIP documents.
        """
        if self._by_file_cache is None:
            self._by_file_cache = {
                doc.path: doc for doc in self._documents if getattr(doc, "path", "")
            }
        return self._by_file_cache

    def symbol_to_files(self) -> dict[str, list[str]]:
        """Return occurrences grouped by symbol.

        Returns
        -------
        dict[str, list[str]]
            Mapping of symbol identifiers to file paths.
        """
        mapping: dict[str, list[str]] = {}
        for doc in self._documents:
            doc_path = getattr(doc, "path", "")
            if not doc_path:
                continue
            for occurrence in doc.occurrences:
                mapping.setdefault(occurrence.symbol, []).append(doc_path)
        return mapping

    def file_symbol_kinds(self) -> dict[str, dict[str, str]]:
        """Return symbol-kind maps per file.

        Returns
        -------
        dict[str, dict[str, str]]
            Mapping of file paths to symbol-kind dictionaries.
        """
        result: dict[str, dict[str, str]] = {}
        for doc in self._documents:
            doc_path = getattr(doc, "path", "")
            if not doc_path:
                continue
            kinds = {
                symbol.symbol: symbol.kind
                for symbol in doc.symbols
                if symbol.kind and symbol.symbol
            }
            if kinds:
                result[doc_path] = kinds
        return result
