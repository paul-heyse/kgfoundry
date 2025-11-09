"""Tokenization components for ColBERT models.

This package provides document and query tokenizers, plus utilities
for processing training triples.
"""

from warp.modeling.tokenization.doc_tokenization import *
from warp.modeling.tokenization.query_tokenization import *
from warp.modeling.tokenization.utils import tensorize_triples as tensorize_triples
