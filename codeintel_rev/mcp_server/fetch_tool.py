"""Lightweight fetch helper used by the in-process MCP harness."""

from __future__ import annotations

from collections.abc import Sequence

from codeintel_rev.mcp_server.types import FetchedObject, FetchInput, FetchOutput


class CatalogProtocol:
    """Protocol describing the catalog lookups required for fetch."""

    def query_by_ids(self, ids: Sequence[int]) -> list[dict[str, object]]:
        """Return hydrated chunk rows for the provided identifiers."""
        raise NotImplementedError


def handle_fetch(catalog: CatalogProtocol, args: dict[str, object]) -> FetchOutput:
    """Hydrate chunk IDs using the provided catalog.

    Returns
    -------
    FetchOutput
        Structured response containing hydrated chunks.
    """
    payload = FetchInput(**args)
    object_ids = [int(obj) for obj in payload.objectIds if str(obj).strip()]
    if not object_ids:
        return FetchOutput(objects=[])
    rows = catalog.query_by_ids(object_ids)
    by_id = {int(row["id"]): row for row in rows if isinstance(row.get("id"), int)}
    objects: list[FetchedObject] = []
    for chunk_id in object_ids:
        row = by_id.get(int(chunk_id))
        if row is None:
            continue
        objects.append(
            FetchedObject(
                id=str(chunk_id),
                title=str(row.get("uri") or f"chunk:{chunk_id}"),
                url=_build_url(row),
                content=str(row.get("content") or ""),
                metadata={
                    "lang": row.get("lang"),
                    "start_line": row.get("start_line"),
                    "end_line": row.get("end_line"),
                    "uri": row.get("uri"),
                },
            )
        )
    return FetchOutput(objects=objects)


def _build_url(row: dict[str, object]) -> str:
    start = int(row.get("start_line") or 0) + 1
    end = int(row.get("end_line") or start) + 1
    uri = str(row.get("uri") or "")
    return f"repo://{uri}#L{start}-L{end}"
