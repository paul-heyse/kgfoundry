# SPDX-License-Identifier: MIT
"""Global object identifier helpers used across enrichment features."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

import xxhash as _xxhash

_XXHASH_MODULE = cast("Any", _xxhash)
XXH64 = cast("Callable[[bytes], Any]", _XXHASH_MODULE.xxh64)
XXH128 = cast("Callable[[], Any]", _XXHASH_MODULE.xxh128)

GoidKind = Literal["module", "class", "function", "method", "variable", "chunk", "block"]


@dataclass(slots=True, frozen=True)
class RepoSnapshot:
    """Repository identity used for GOID derivation."""

    repo: str
    commit: str


@dataclass(slots=True, frozen=True)
class EntityDescriptor:
    """Code entity metadata used when computing GOIDs."""

    language: str
    kind: GoidKind
    rel_path: str | Path
    qualname: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    scip_symbol: str | None = None


@dataclass(slots=True, frozen=True)
class _NormalizedComponents:
    repo: str
    commit: str
    language: str
    kind: GoidKind
    rel_path: str
    qualname: str | None
    start_line: int | None
    end_line: int | None
    scip_symbol: str | None


def _normalize_language(language: str) -> str:
    normalized = (language or "").strip().lower()
    if not normalized:
        return "unknown"
    return normalized


def _normalize_qualname(qualname: str | None) -> str | None:
    if qualname is None:
        return None
    trimmed = qualname.strip()
    return trimmed or None


def _normalize_line(value: int | None) -> int | None:
    if value is None:
        return None
    if value <= 0:
        return None
    return int(value)


def _normalize_path(rel_path: str | Path) -> str:
    normalized = rel_path.as_posix() if isinstance(rel_path, Path) else rel_path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _repo_fingerprint(repo: str) -> str:
    digest = XXH64(repo.encode("utf-8", "ignore"))
    return digest.hexdigest()[:12]


def _scip_fingerprint(scip_symbol: str | None) -> str | None:
    if not scip_symbol:
        return None
    digest = XXH64(scip_symbol.encode("utf-8", "ignore"))
    return digest.hexdigest()


def _tuple_for_hash(components: _NormalizedComponents) -> tuple[str, ...]:
    return (
        components.repo.strip(),
        components.commit.strip(),
        components.language,
        components.kind,
        components.rel_path,
        components.qualname or "",
        str(components.start_line or ""),
        str(components.end_line or ""),
        components.scip_symbol or "",
    )


def _hash_tuple(data: tuple[str, ...]) -> int:
    digest = XXH128()
    for part in data:
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")
    value = digest.intdigest()
    signed_threshold = 1 << 127
    if value >= signed_threshold:
        return value - (1 << 128)
    return value


def _build_urn(components: _NormalizedComponents) -> str:
    repo_fp = _repo_fingerprint(components.repo)
    qual_segment = components.qualname or "_"
    urn = f"goid:1/{repo_fp}@{components.commit}:/"
    urn += components.rel_path
    urn += f"#{components.language}:{components.kind}:{qual_segment}"
    params: list[str] = []
    if components.start_line is not None:
        params.append(f"s={components.start_line}")
    if components.end_line is not None:
        params.append(f"e={components.end_line}")
    scip_fp = _scip_fingerprint(components.scip_symbol)
    if scip_fp:
        params.append(f"scip={scip_fp}")
    if params:
        urn += f"?{'&'.join(params)}"
    return urn


@dataclass(slots=True, frozen=True)
class GOID:
    """Stable identifier for a single code entity."""

    urn: str
    h128: int
    repo: str
    commit: str
    rel_path: str
    language: str
    kind: GoidKind
    qualname: str | None
    start_line: int | None
    end_line: int | None


class CrosswalkRow(TypedDict, total=False):
    """DuckDB crosswalk row describing alternate anchors for a GOID."""

    goid_h128: int
    scip_symbol: str | None
    chunk_id: str | None
    chunk_row_id: int | None
    cst_node_id: str | None
    ast_node_type: str | None
    git_blob_sha: str | None
    git_commit_sha: str | None
    evidence_json: dict[str, object] | None


def compute_goid(snapshot: RepoSnapshot, descriptor: EntityDescriptor) -> GOID:
    """Return a stable GOID derived from repository snapshot and descriptor.

    Parameters
    ----------
    snapshot : RepoSnapshot
        Repository identifier and commit hash.
    descriptor : EntityDescriptor
        Code entity metadata describing path, kind, and positional anchors.

    Returns
    -------
    GOID
        Stable identifier referencing the entity described by ``descriptor``.
    """
    normalized = _normalize_components(snapshot, descriptor)
    normalized_tuple = _tuple_for_hash(normalized)
    h128 = _hash_tuple(normalized_tuple)
    urn = _build_urn(normalized)
    return GOID(
        urn=urn,
        h128=h128,
        repo=normalized.repo,
        commit=normalized.commit,
        rel_path=normalized.rel_path,
        language=normalized.language,
        kind=normalized.kind,
        qualname=normalized.qualname,
        start_line=normalized.start_line,
        end_line=normalized.end_line,
    )


def _normalize_components(
    snapshot: RepoSnapshot,
    descriptor: EntityDescriptor,
) -> _NormalizedComponents:
    rel_path = _normalize_path(descriptor.rel_path)
    lang = _normalize_language(descriptor.language)
    qual = _normalize_qualname(descriptor.qualname)
    start = _normalize_line(descriptor.start_line)
    end = _normalize_line(descriptor.end_line)
    return _NormalizedComponents(
        repo=snapshot.repo,
        commit=snapshot.commit,
        language=lang,
        kind=descriptor.kind,
        rel_path=rel_path,
        qualname=qual,
        start_line=start,
        end_line=end,
        scip_symbol=descriptor.scip_symbol,
    )
