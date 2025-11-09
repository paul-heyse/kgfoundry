"""Navmap document models aligned with ``schema/tools/navmap_document.json``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, TypedDict

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from tools.navmap.models import ModuleMeta, NavIndex, SymbolMeta

NAVMAP_SCHEMA: Final[str] = "navmap_document.json"
NAVMAP_SCHEMA_ID: Final[str] = "https://kgfoundry.dev/schema/tools/navmap-document.json"
NAVMAP_SCHEMA_VERSION: Final[str] = "1.0.0"


class NavSectionDocument(BaseModel):
    """Serialized representation of a navigation section."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    symbols: list[str]


class SymbolMetaDocument(BaseModel):
    """Symbol metadata emitted in navmap documents."""

    model_config = ConfigDict(populate_by_name=True)

    owner: str | None = None
    stability: str | None = None
    since: str | None = None
    deprecated_in: str | None = Field(None, alias="deprecatedIn")


class ModuleMetaDocument(BaseModel):
    """Module-level metadata defaults."""

    model_config = ConfigDict(populate_by_name=True)

    owner: str | None = None
    stability: str | None = None
    since: str | None = None
    deprecated_in: str | None = Field(None, alias="deprecatedIn")


class ModuleEntryDocument(BaseModel):
    """Serialized module entry within the navmap document."""

    model_config = ConfigDict(populate_by_name=True)

    path: str
    exports: list[str]
    sections: list[NavSectionDocument]
    section_lines: dict[str, int] = Field(alias="sectionLines")
    anchors: dict[str, int]
    links: dict[str, str]
    meta: dict[str, SymbolMetaDocument]
    module_meta: ModuleMetaDocument = Field(alias="moduleMeta")
    tags: list[str]
    synopsis: str
    see_also: list[str] = Field(alias="seeAlso")
    deps: list[str]


ModuleEntryDocumentType: type[ModuleEntryDocument] = ModuleEntryDocument


class ModuleEntryPayload(TypedDict):
    """Serialized representation of module entry fields using schema aliases."""

    path: str
    exports: list[str]
    sections: list[NavSectionDocument]
    sectionLines: dict[str, int]
    anchors: dict[str, int]
    links: dict[str, str]
    meta: dict[str, SymbolMetaDocument]
    moduleMeta: ModuleMetaDocument
    tags: list[str]
    synopsis: str
    seeAlso: list[str]
    deps: list[str]


def _utc_iso_now() -> str:
    """Return the current UTC timestamp as an ISO-8601 string.

    Returns
    -------
    str
        ISO-8601 formatted UTC timestamp string.
    """
    return datetime.now(tz=UTC).isoformat()


class _NavmapDocumentInit(TypedDict, total=False):
    schemaVersion: str
    schemaId: str
    generatedAt: str
    commit: str
    policyVersion: str
    linkMode: str
    modules: dict[str, ModuleEntryDocument]


class NavmapDocument(BaseModel):
    """Top-level navmap document captured on disk."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: str = Field(NAVMAP_SCHEMA_VERSION, alias="schemaVersion")
    schema_id: str = Field(NAVMAP_SCHEMA_ID, alias="schemaId")
    generated_at: str = Field(default_factory=_utc_iso_now, alias="generatedAt")
    commit: str = "HEAD"
    policy_version: str = Field("1", alias="policyVersion")
    link_mode: str = Field("editor", alias="linkMode")
    modules: dict[str, ModuleEntryDocument] = Field(default_factory=dict)


def _symbol_meta_to_document(meta: SymbolMeta) -> SymbolMetaDocument:
    return SymbolMetaDocument(
        owner=meta.owner,
        stability=meta.stability,
        since=meta.since,
        deprecatedIn=meta.deprecated_in,
    )


def _module_meta_to_document(module_meta: ModuleMeta) -> ModuleMetaDocument:
    return ModuleMetaDocument(
        owner=module_meta.owner,
        stability=module_meta.stability,
        since=module_meta.since,
        deprecatedIn=module_meta.deprecated_in,
    )


def _new_navmap_document(
    *,
    commit: str,
    policy_version: str,
    link_mode: str,
    modules: dict[str, ModuleEntryDocument],
) -> NavmapDocument:
    payload: _NavmapDocumentInit = {
        "schemaVersion": NAVMAP_SCHEMA_VERSION,
        "schemaId": NAVMAP_SCHEMA_ID,
        "commit": commit,
        "policyVersion": policy_version,
        "linkMode": link_mode,
        "modules": modules,
    }
    return NavmapDocument(**payload)


def navmap_document_from_index(
    index: NavIndex,
    *,
    commit: str,
    policy_version: str,
    link_mode: str,
) -> NavmapDocument:
    """Build a :class:`NavmapDocument` from a :class:`NavIndex` instance.

    Parameters
    ----------
    index : NavIndex
        Nav index to convert.
    commit : str
        Git commit hash.
    policy_version : str
        Policy version string.
    link_mode : str
        Link mode configuration.

    Returns
    -------
    NavmapDocument
        Navmap document instance.
    """
    modules: dict[str, ModuleEntryDocument] = {}
    for name, entry in index.modules.items():
        section_models = entry.sections
        sections: list[NavSectionDocument] = [
            NavSectionDocument(id=section.id, symbols=section.symbols.copy())
            for section in section_models
        ]
        symbol_meta: dict[str, SymbolMetaDocument] = {
            symbol: _symbol_meta_to_document(meta)
            for symbol, meta in entry.meta.items()
        }
        module_meta_doc = _module_meta_to_document(entry.module_meta)
        exports: list[str] = entry.exports.copy()
        section_lines: dict[str, int] = entry.section_lines.copy()
        anchors: dict[str, int] = entry.anchors.copy()
        links: dict[str, str] = entry.links.copy()
        tags: list[str] = entry.tags.copy()
        synopsis: str = entry.synopsis
        see_also: list[str] = entry.see_also.copy()
        deps: list[str] = entry.deps.copy()
        module_payload: ModuleEntryPayload = {
            "path": entry.path,
            "exports": exports,
            "sections": sections,
            "sectionLines": section_lines,
            "anchors": anchors,
            "links": links,
            "meta": symbol_meta,
            "moduleMeta": module_meta_doc,
            "tags": tags,
            "synopsis": synopsis,
            "seeAlso": see_also,
            "deps": deps,
        }
        modules[name] = ModuleEntryDocumentType.model_validate(module_payload)

    return _new_navmap_document(
        commit=commit,
        policy_version=policy_version,
        link_mode=link_mode,
        modules=modules,
    )
