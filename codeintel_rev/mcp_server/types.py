"""Typed DTOs and JSON Schema helpers for MCP search/fetch tools."""

# ruff: noqa: N815

from __future__ import annotations

from typing import Any, Literal

import msgspec


class SearchInput(msgspec.Struct, frozen=True):
    """Incoming payload for the lightweight MCP search tool."""

    query: str
    top_k: int = 12
    filters: dict[str, Any] | None = None


class SearchResultItem(msgspec.Struct, frozen=True):
    """Single search result entry returned by the lightweight MCP tools."""

    id: str
    title: str | None = None
    url: str | None = None
    snippet: str | None = None
    score: float | None = None
    source: str | None = None
    metadata: dict[str, Any] | None = None


class SearchOutput(msgspec.Struct, frozen=True):
    """Structured search response returned to the caller."""

    results: list[SearchResultItem]
    queryEcho: str
    top_k: int
    limits: list[str] | None = None


class FetchInput(msgspec.Struct, frozen=True):
    """Incoming payload for the lightweight MCP fetch tool."""

    objectIds: list[str]
    max_tokens: int | None = None
    resolve: Literal["full", "summary", "metadata_only"] = "full"


class FetchedObject(msgspec.Struct, frozen=True):
    """Hydrated chunk entry returned from fetch operations."""

    id: str
    title: str | None = None
    url: str | None = None
    content: str | None = None
    metadata: dict[str, Any] | None = None


class FetchOutput(msgspec.Struct, frozen=True):
    """Fetch response wrapping one or more hydrated chunk objects."""

    objects: list[FetchedObject]


def search_input_schema() -> dict[str, Any]:
    """Return the JSON Schema describing search tool inputs.

    Returns
    -------
    dict[str, Any]
        JSON Schema dictionary describing search inputs.
    """
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
            "filters": {"type": "object"},
        },
        "required": ["query"],
        "additionalProperties": True,
    }


def search_output_schema() -> dict[str, Any]:
    """Return the JSON Schema describing search tool outputs.

    Returns
    -------
    dict[str, Any]
        JSON Schema dictionary describing search outputs.
    """
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "snippet": {"type": "string"},
                        "score": {"type": "number"},
                        "source": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["id"],
                },
            },
            "queryEcho": {"type": "string"},
            "top_k": {"type": "integer"},
            "limits": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["results", "queryEcho", "top_k"],
        "additionalProperties": True,
    }


def fetch_input_schema() -> dict[str, Any]:
    """Return the JSON Schema describing fetch tool inputs.

    Returns
    -------
    dict[str, Any]
        JSON Schema dictionary describing fetch inputs.
    """
    return {
        "type": "object",
        "properties": {
            "objectIds": {"type": "array", "items": {"type": "string"}},
            "max_tokens": {"type": "integer", "minimum": 256, "maximum": 16000},
            "resolve": {
                "type": "string",
                "enum": ["full", "summary", "metadata_only"],
            },
        },
        "required": ["objectIds"],
        "additionalProperties": False,
    }


def fetch_output_schema() -> dict[str, Any]:
    """Return the JSON Schema describing fetch tool outputs.

    Returns
    -------
    dict[str, Any]
        JSON Schema dictionary describing fetch outputs.
    """
    return {
        "type": "object",
        "properties": {
            "objects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "content": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["id", "content"],
                },
            }
        },
        "required": ["objects"],
        "additionalProperties": True,
    }
