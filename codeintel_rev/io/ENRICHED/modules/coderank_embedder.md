# io/coderank_embedder.py

## Docstring

```
Pooled wrapper around the CodeRank embedding SentenceTransformer.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import threading
- from **collections.abc** import Iterable
- from **typing** import TYPE_CHECKING, Any, ClassVar, Protocol, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.typing** import NDArrayF32, gate_import
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import numpy
- from **sentence_transformers** import SentenceTransformer

## Definitions

- class: `SupportsCodeRankSettings` (line 21)
- function: `model_id` (line 25)
- function: `device` (line 30)
- function: `trust_remote_code` (line 35)
- function: `query_prefix` (line 40)
- function: `normalize` (line 45)
- function: `batch_size` (line 50)
- class: `CodeRankEmbedder` (line 58)
- function: `__init__` (line 69)
- function: `encode_queries` (line 77)
- function: `encode_codes` (line 108)
- function: `_ensure_model` (line 139)

## Tags

overlay-needed
