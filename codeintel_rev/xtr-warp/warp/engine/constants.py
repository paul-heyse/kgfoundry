"""Constants and policies for WARP engine execution.

This module provides dimension constants and T' (T-prime) policy classes
for controlling search behavior.
"""

TOKEN_EMBED_DIM = 128
QUERY_MAXLEN = 32
DOC_MAXLEN = 512
TOKEN_EMBED_DIM = 128

# T' policy threshold
DOCUMENT_TOP_K_THRESHOLD = 100


class TPrimePolicy:
    """Fixed T' policy returning constant value.

    Returns a fixed T' value regardless of document_top_k.

    Parameters
    ----------
    value : int
        Fixed T' value to return.
    """

    def __init__(self, value: int) -> None:
        """Initialize TPrimePolicy with fixed value.

        Parameters
        ----------
        value : int
            Fixed T' value to return.
        """
        self.value = value

    def __getitem__(self, document_top_k: int) -> int:
        """Get T' value for document_top_k.

        Parameters
        ----------
        document_top_k : int
            Number of top documents (ignored).

        Returns
        -------
        int
            Fixed T' value.
        """
        return self.value


class TPrimeMaxPolicy:
    """Maximum T' policy based on document_top_k.

    Returns different T' values based on document_top_k threshold.
    """

    def __getitem__(self, document_top_k: int) -> int:
        """Get T' value based on document_top_k.

        Returns 100,000 if document_top_k > 100, otherwise 50,000.

        Parameters
        ----------
        document_top_k : int
            Number of top documents.

        Returns
        -------
        int
            T' value (50,000 or 100,000).
        """
        if document_top_k > DOCUMENT_TOP_K_THRESHOLD:
            return 100_000
        return 50_000


T_PRIME_MAX = TPrimeMaxPolicy()
