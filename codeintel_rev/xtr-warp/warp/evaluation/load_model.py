"""Model loading utilities for evaluation.

This module provides functions for loading ColBERT models from checkpoints
for evaluation purposes.
"""

from __future__ import annotations


from warp.modeling.colbert import ColBERT
from warp.parameters import DEVICE
from warp.utils.utils import load_checkpoint, print_message


def load_model(args: object, *, do_print: bool = True) -> tuple[ColBERT, dict[str, object]]:
    """Load ColBERT model from checkpoint.

    Creates a ColBERT model with bert-base-uncased base, loads checkpoint,
    and sets model to evaluation mode.

    Parameters
    ----------
    args : Any
        Arguments object with query_maxlen, doc_maxlen, dim, similarity,
        mask_punctuation, and checkpoint attributes.
    do_print : bool
        Whether to print loading messages (default: True).

    Returns
    -------
    tuple[ColBERT, dict[str, Any]]
        Tuple of (loaded_model, checkpoint_dict).
    """
    colbert = ColBERT.from_pretrained(
        "bert-base-uncased",
        query_maxlen=args.query_maxlen,
        doc_maxlen=args.doc_maxlen,
        dim=args.dim,
        similarity_metric=args.similarity,
        mask_punctuation=args.mask_punctuation,
    )
    colbert = colbert.to(DEVICE)

    print_message("#> Loading model checkpoint.", condition=do_print)

    checkpoint = load_checkpoint(args.checkpoint, colbert, do_print=do_print)

    colbert.eval()

    return colbert, checkpoint
