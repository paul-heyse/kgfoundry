"""Collection encoding utilities for WARP indexing.

This module provides CollectionEncoder for encoding document passages into
dense embeddings using ColBERT checkpoints with batching support.
"""

from __future__ import annotations

import torch
from warp.infra.config.config import ColBERTConfig
from warp.infra.run import Run
from warp.modeling.checkpoint import Checkpoint
from warp.utils.utils import batch


class CollectionEncoder:
    """Encodes document passages into dense embeddings for indexing.

    Uses a ColBERT checkpoint to encode passages in batches, handling GPU/CPU
    execution and memory management through configurable batch sizes.

    Parameters
    ----------
    config : ColBERTConfig
        Configuration object with total_visible_gpus and index_bsize attributes.
    checkpoint : Checkpoint
        ColBERT checkpoint instance with docFromText method.

    Attributes
    ----------
    config : ColBERTConfig
        Configuration object.
    checkpoint : Checkpoint
        ColBERT checkpoint for encoding.
    use_gpu : bool
        Whether GPU is available for encoding.
    """

    def __init__(self, config: ColBERTConfig, checkpoint: Checkpoint) -> None:
        """Initialize CollectionEncoder with configuration and checkpoint.

        Parameters
        ----------
        config
            Configuration object with total_visible_gpus and index_bsize.
        checkpoint
            ColBERT checkpoint instance for encoding.
        """
        self.config = config
        self.checkpoint = checkpoint
        self.use_gpu = self.config.total_visible_gpus > 0

    def encode_passages(self, passages: list[str]) -> tuple[torch.Tensor | None, list[int] | None]:
        """Encode a list of passages into dense embeddings.

        Processes passages in batches to manage memory, especially on GPU.
        Returns flattened embeddings and corresponding document lengths.

        Parameters
        ----------
        passages : list[str]
            List of passage text strings to encode.

        Returns
        -------
        tuple[torch.Tensor | None, list[int] | None]
            Tuple of (embeddings_tensor, doclens_list). Returns (None, None) if
            passages list is empty.
        """
        Run().print(f"#> Encoding {len(passages)} passages..")

        if len(passages) == 0:
            return None, None

        with torch.inference_mode():
            embs, doclens = [], []

            # Batch here to avoid OOM from storing intermediate embeddings on GPU.
            # Storing on the GPU helps with speed of masking, etc.
            # But ideally this batching happens internally inside doc_from_text.
            for passages_batch in batch(passages, self.config.index_bsize * 50):
                embs_, doclens_ = self.checkpoint.doc_from_text(
                    passages_batch,
                    bsize=self.config.index_bsize,
                    keep_dims="flatten",
                    showprogress=(not self.use_gpu),
                )
                embs.append(embs_)
                doclens.extend(doclens_)

            embs = torch.cat(embs)

        return embs, doclens
