"""Lightweight fetch helper used by the in-process MCP harness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from codeintel_rev.mcp_server.types import FetchedObject, FetchInput, FetchOutput


class CatalogProtocol:
    """Protocol describing the catalog lookups required for fetch."""

    def query_by_ids(self, ids: Sequence[int]) -> list[dict[str, object]]:
        """Return hydrated chunk rows for the provided identifiers."""
        raise NotImplementedError


def handle_fetch(catalog: CatalogProtocol, args: dict[str, object]) -> FetchOutput:
    """Hydrate chunk IDs using the provided catalog.

    This function processes fetch tool requests by querying the catalog for chunk
    metadata corresponding to the provided object IDs. It is called by MCP tool
    handlers to retrieve full chunk information (URI, line ranges, content, language)
    for search result IDs.

    Parameters
    ----------
    catalog : CatalogProtocol
        Catalog implementation providing query_by_ids method for chunk retrieval.
    args : dict[str, object]
        Dictionary containing FetchInput fields, typically with "objectIds" key
        containing a list of chunk identifier strings.

    Returns
    -------
    FetchOutput
        Structured response containing hydrated chunks with metadata, or empty
        objects list if no valid IDs are provided.
    """
    payload = _normalize_fetch_input(args)
    object_ids: list[int] = []
    for obj in payload.objectIds:
        try:
            object_ids.append(int(obj))
        except ValueError:
            continue
    if not object_ids:
        return FetchOutput(objects=[])
    rows = catalog.query_by_ids(object_ids)
    by_id: dict[int, dict[str, object]] = {}
    for row in rows:
        row_id = row.get("id")
        if isinstance(row_id, int):
            by_id[row_id] = row
    objects: list[FetchedObject] = []
    for chunk_id in object_ids:
        row = by_id.get(chunk_id)
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


def _build_url(row: Mapping[str, object]) -> str:
    """Build a repo:// URL from chunk metadata row.

    Parameters
    ----------
    row : Mapping[str, object]
        Chunk metadata dictionary containing uri, start_line, and end_line.

    Returns
    -------
    str
        URL in format "repo://{uri}#L{start}-L{end}" with 1-based line numbers.
    """
    start = _coerce_int(row.get("start_line"), default=0) + 1
    end = _coerce_int(row.get("end_line"), default=start) + 1
    uri = str(row.get("uri") or "")
    return f"repo://{uri}#L{start}-L{end}"


def _normalize_fetch_input(args: Mapping[str, object]) -> FetchInput:
    """Normalize and validate fetch tool input arguments.

    Parameters
    ----------
    args : Mapping[str, object]
        Raw arguments dictionary containing objectIds, max_tokens, and resolve.

    Returns
    -------
    FetchInput
        Normalized and validated FetchInput object.

    Raises
    ------
    ValueError
        If objectIds is missing or empty, or if resolve value is invalid.
    TypeError
        If objectIds is not a sequence (raised by ``_coerce_object_ids``).
    """
    raw_ids = args.get("objectIds")
    if raw_ids is None:
        msg = "objectIds is required"
        raise ValueError(msg)
    try:
        object_ids = _coerce_object_ids(raw_ids)
    except TypeError as exc:
        msg = "objectIds must be a sequence of identifiers"
        raise TypeError(msg) from exc
    max_tokens = _coerce_optional_int(args.get("max_tokens"))
    resolve = _coerce_resolve(args.get("resolve"))
    return FetchInput(objectIds=object_ids, max_tokens=max_tokens, resolve=resolve)


def _coerce_optional_int(value: object | None) -> int | None:
    """Coerce an optional value to int or None.

    Parameters
    ----------
    value : object | None
        Value to coerce, or None.

    Returns
    -------
    int | None
        Coerced integer value, or None if input is None.
    """
    if value is None:
        return None
    return _coerce_int(value)


def _coerce_object_ids(value: object) -> list[str]:
    """Coerce object IDs to a list of non-empty strings.

    Parameters
    ----------
    value : object
        Value to coerce to a list of object ID strings.

    Returns
    -------
    list[str]
        List of non-empty object ID strings.

    Raises
    ------
    TypeError
        If value is not a sequence (excluding strings and bytes).
    ValueError
        If the resulting list is empty.
    """
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        msg = "objectIds must be a sequence of identifiers"
        raise TypeError(msg)
    items: list[str] = []
    for obj in value:
        text = str(obj).strip()
        if text:
            items.append(text)
    if not items:
        msg = "objectIds must contain at least one identifier"
        raise ValueError(msg)
    return items


def _coerce_resolve(value: object | None) -> Literal["full", "summary", "metadata_only"]:
    """Coerce resolve option to a valid literal value.

    Parameters
    ----------
    value : object | None
        Resolve option value to coerce, or None for default.

    Returns
    -------
    Literal["full", "summary", "metadata_only"]
        Valid resolve option, defaulting to "full" if None.

    Raises
    ------
    ValueError
        If value does not match any allowed option.
    """
    allowed: tuple[Literal["full", "summary", "metadata_only"], ...] = (
        "full",
        "summary",
        "metadata_only",
    )
    if value is None:
        return "full"
    text = str(value).strip().lower()
    for option in allowed:
        if text == option:
            return option
    msg = f"resolve must be one of {allowed}"
    raise ValueError(msg)


def _coerce_int(value: object, *, default: int = 0) -> int:
    """Coerce a value to an integer with fallback to default.

    This function attempts to convert various types (bool, int, float, str) to
    an integer, falling back to the default value if conversion fails or the
    value is None. Used by input normalization functions to safely coerce
    user-provided values.

    Parameters
    ----------
    value : object
        Value to coerce to integer.
    default : int
        Default value to return if coercion fails. Defaults to 0.

    Returns
    -------
    int
        Coerced integer value, or default if conversion fails.
    """
    if value is None:
        return default
    candidate = default
    if isinstance(value, bool):
        candidate = int(value)
    elif isinstance(value, int):
        candidate = value
    elif isinstance(value, float):
        candidate = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                candidate = int(stripped, 10)
            except ValueError:
                candidate = default
    return candidate
