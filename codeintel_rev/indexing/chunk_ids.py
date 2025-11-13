"""Deterministic chunk identifier helpers."""

from __future__ import annotations

from hashlib import blake2b

_DIGEST_SIZE = 8
_SIGNED_LIMIT = 1 << 63
_UINT64_MOD = 1 << 64


def stable_chunk_id(uri: str, start_byte: int, end_byte: int, *, salt: str = "") -> int:
    """Return a deterministic signed 64-bit chunk identifier.

    Parameters
    ----------
    uri : str
        Normalized path/URI for the chunk (see :mod:`codeintel_rev.indexing.cast_chunker`).
    start_byte : int
        Inclusive starting byte offset of the chunk.
    end_byte : int
        Exclusive ending byte offset of the chunk.
    salt : str, optional
        Extra differentiator for multi-tenant deployments. Defaults to ``""``.

    Returns
    -------
    int
        Signed 64-bit integer suitable for FAISS ``add_with_ids`` and Arrow
        ``int64`` columns.
    """
    # BLAKE2b is fast, keyed, and widely available in hashlib. Digest size of 8
    # keeps identifiers compact while maintaining negligible collision risk for
    # repository-sized corpora. We store ids in signed 64-bit columns, so values
    # that would otherwise exceed ``int64`` are wrapped into two's complement
    # space for compatibility with DuckDB/Arrow.
    hasher = blake2b(digest_size=_DIGEST_SIZE)
    hasher.update(uri.encode("utf-8"))
    hasher.update(b"|")
    hasher.update(str(int(start_byte)).encode("ascii"))
    hasher.update(b"|")
    hasher.update(str(int(end_byte)).encode("ascii"))
    if salt:
        hasher.update(b"|")
        hasher.update(salt.encode("utf-8"))
    value = int.from_bytes(hasher.digest(), byteorder="little", signed=False)
    if value >= _SIGNED_LIMIT:
        value -= _UINT64_MOD
    return value


__all__ = ["stable_chunk_id"]
