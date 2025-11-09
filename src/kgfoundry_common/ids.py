"""Overview of ids.

This module bundles ids logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import base64
import hashlib

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "urn_chunk",
    "urn_doc_from_text",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor urn_doc_from_text]
def urn_doc_from_text(text: str) -> str:
    """Generate a deterministic URN for a document from its text content.

    Creates a SHA256-based URN identifier for a document by hashing
    its text content and encoding the hash in base32.

    Parameters
    ----------
    text : str
        Document text content to hash.

    Returns
    -------
    str
        URN string in format "urn:doc:sha256:{base32_hash}".
    """
    h = hashlib.sha256(text.encode("utf-8")).digest()[:16]
    b32 = base64.b32encode(h).decode("ascii").strip("=").lower()
    return f"urn:doc:sha256:{b32}"


# [nav:anchor urn_chunk]
def urn_chunk(doc_hash: str, start: int, end: int) -> str:
    """Generate a URN for a chunk referencing a document.

    Creates a URN identifier for a text chunk by extracting the hash
    from the document URN and appending the start and end positions.

    Parameters
    ----------
    doc_hash : str
        Document URN hash (e.g., "urn:doc:sha256:{hash}").
    start : int
        Start character position of the chunk.
    end : int
        End character position of the chunk.

    Returns
    -------
    str
        URN string in format "urn:chunk:{hash}:{start}-{end}".
    """
    return f"urn:chunk:{doc_hash.rsplit(':', maxsplit=1)[-1]}:{start}-{end}"
