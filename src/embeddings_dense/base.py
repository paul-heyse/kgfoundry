"""Overview of base.

This module bundles base logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:
    from collections.abc import Sequence

    import numpy as np
    from numpy.typing import NDArray


__all__ = [
    "DenseEmbeddingModel",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor DenseEmbeddingModel]
class DenseEmbeddingModel(Protocol):
    """Protocol for dense embedding model implementations.

    Defines the interface for models that generate dense vector embeddings from text sequences.
    Implementations must provide an encode method that accepts a sequence of text strings and
    returns a NumPy array of float32 vectors.
    """

    def encode(self, texts: Sequence[str]) -> NDArray[np.float32]:
        """Encode text sequences into dense embedding vectors.

        Converts a sequence of text strings into a NumPy array of dense
        float32 vectors where each row corresponds to one input text.

        Parameters
        ----------
        texts : Sequence[str]
            Sequence of text strings to encode.

        Returns
        -------
        NDArray[np.float32]
            NumPy array of shape (len(texts), embedding_dim) containing
            the dense embedding vectors.
        """
        ...
