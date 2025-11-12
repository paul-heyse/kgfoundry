# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import orjson as _json  # type: ignore[import-not-found]

    def _loads(b: bytes) -> Any:
        return _json.loads(b)
except Exception:  # pragma: no cover - runtime fallback

    def _loads(b: bytes) -> Any:
        return json.loads(b.decode("utf-8"))


@dataclass
class Occurrence:
    symbol: str
    range: list[int] | None = None
    roles: list[str] = field(default_factory=list)


@dataclass
class SymbolInfo:
    symbol: str
    documentation: list[str] = field(default_factory=list)
    kind: str | None = None
    relationships: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Document:
    path: str
    occurrences: list[Occurrence] = field(default_factory=list)
    symbols: list[SymbolInfo] = field(default_factory=list)


@dataclass
class SCIPIndex:
    documents: list[Document] = field(default_factory=list)
    external_symbols: dict[str, SymbolInfo] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> SCIPIndex:
        """
        Load a SCIP index from a JSON file. Tolerates minor schema variations.
        """
        p = Path(path)
        data = _loads(p.read_bytes())
        docs = []
        for d in data.get("documents", []):
            rel = d.get("relativePath") or d.get("relative_path") or d.get("path", "")
            occs = []
            for o in d.get("occurrences", []):
                occs.append(
                    Occurrence(
                        symbol=o.get("symbol", ""),
                        range=o.get("range"),
                        roles=[
                            r
                            for r in (o.get("symbolRoles") or o.get("roles") or [])
                            if isinstance(r, str)
                        ],
                    )
                )
            syms = []
            for s in d.get("symbols", []):
                syms.append(
                    SymbolInfo(
                        symbol=s.get("symbol", ""),
                        documentation=list(s.get("documentation", [])),
                        kind=s.get("kind"),
                        relationships=list(s.get("relationships", [])),
                    )
                )
            docs.append(Document(path=rel, occurrences=occs, symbols=syms))
        ext = {}
        for s in data.get("externalSymbols", []):
            ext[s.get("symbol", "")] = SymbolInfo(
                symbol=s.get("symbol", ""),
                documentation=list(s.get("documentation", [])),
                kind=s.get("kind"),
                relationships=list(s.get("relationships", [])),
            )
        return cls(documents=docs, external_symbols=ext)

    def by_file(self) -> dict[str, Document]:
        return {d.path: d for d in self.documents}

    def symbol_to_files(self) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for d in self.documents:
            for o in d.occurrences:
                mapping.setdefault(o.symbol, []).append(d.path)
        return mapping

    def file_symbol_kinds(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for d in self.documents:
            kinds = {}
            for s in d.symbols:
                if s.symbol and s.kind:
                    kinds[s.symbol] = s.kind
            if kinds:
                out[d.path] = kinds
        return out
