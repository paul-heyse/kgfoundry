"""Heavy dependency registry shared across typing gates and gate_import."""

from __future__ import annotations

__all__ = ["EXTRAS_HINT", "HEAVY_DEPS"]

# Minimum supported versions (None implies "any version is fine")
HEAVY_DEPS: dict[str, str | None] = {
    "numpy": "1.26",
    "faiss": None,
    "duckdb": None,
    "torch": None,
    "onnxruntime": None,
    "lucene": None,
    "pyserini": None,
    "httpx": None,
}

# Mapping from module roots to pip extras exposed by this project
EXTRAS_HINT: dict[str, str] = {
    "faiss": "faiss-cpu or faiss-gpu",
    "duckdb": "duckdb",
    "torch": "xtr",
    "onnxruntime": "splade",
    "lucene": "splade",
    "pyserini": "splade",
}
