"""Shared OpenTelemetry semantic convention helpers for CodeIntel."""

from __future__ import annotations

import json

__all__ = ["Attrs", "as_kv", "to_label_str"]


class Attrs:
    """Trusted attribute keys used across spans, metrics, and logs."""

    # Identity / request scaffolding
    SESSION_ID: str = "session.id"
    MCP_SESSION_ID: str = "mcp.session_id"
    RUN_ID: str = "run.id"
    MCP_RUN_ID: str = "mcp.run_id"
    REQUEST_ID: str = "request.id"
    MCP_TOOL: str = "mcp.tool"
    COMPONENT: str = "component"
    OPERATION: str = "operation"
    STAGE: str = "stage"
    REQUEST_STAGE: str = "request.stage"
    WARN_DEGRADED: str = "warn.degraded"
    FALLBACK_REASON: str = "fallback.reason"
    FALLBACK_TARGET: str = "fallback.target"

    # Query metadata
    QUERY_TEXT: str = "retrieval.query_text"
    QUERY_LEN: str = "retrieval.query_len"
    RETRIEVAL_TOP_K: str = "retrieval.top_k"
    TOP_K: str = RETRIEVAL_TOP_K
    RETRIEVAL_CHANNELS: str = "retrieval.channels"
    RETRIEVAL_RRF_K: str = "retrieval.rrf_k"
    RETRIEVAL_EXPLAINABILITY: str = "retrieval.explainability"
    CHANNEL_DEPTHS: str = "retrieval.channel_depths"

    # Budget + gating metadata
    BUDGET_MS: str = "budget.ms"
    DECISION_RRF_K: str = "decision.rrf_k"
    RRF_K: str = "decision.rrf_k"
    DECISION_CHANNEL_DEPTHS: str = "decision.per_channel_depths"
    DECISION_BM25_RM3_ENABLED: str = "bm25.rm3_enabled"
    BM25_RM3_ENABLED: str = "bm25.rm3_enabled"
    GATING_RM3_ENABLED: str = "gating.rm3_enabled"
    GATING_AMBIGUITY: str = "gating.ambiguity_score"

    WARNINGS: str = "codeintel.warnings"

    # Hybrid + channel contributions
    GATHERED_DOCS: str = "retrieval.channel_hits"
    CHANNELS_USED: str = "retrieval.channels_used"
    FUSED_DOCS: str = "retrieval.fused_docs"
    RECENCY_BOOSTED: str = "retrieval.recency_boosted"

    # FAISS / ANN
    FAISS_INDEX_KIND: str = "faiss.index_kind"
    FAISS_INDEX_TYPE: str = FAISS_INDEX_KIND
    FAISS_METRIC: str = "faiss.metric"
    FAISS_DIM: str = "faiss.dim"
    FAISS_TOP_K: str = "faiss.k"
    FAISS_NPROBE: str = "faiss.nprobe"
    FAISS_GPU: str = "faiss.gpu"
    FAISS_GPU_READY: str = "faiss.gpu_ready"

    # vLLM embeddings
    VLLM_MODE: str = "vllm.mode"
    VLLM_MODEL_NAME: str = "vllm.model_name"
    VLLM_EMBED_DIM: str = "vllm.embed_dim"
    VLLM_BATCH: str = "vllm.batch_size"

    # DuckDB hydration
    DUCKDB_CATALOG: str = "duckdb.catalog"
    DUCKDB_ROWS: str = "duckdb.rows"
    DUCKDB_SQL_BYTES: str = "duckdb.sql_bytes"

    # Rerankers / XTR
    XTR_VERSION: str = "xtr.version"
    XTR_TOP_K: str = "xtr.top_k"
    XTR_CANDIDATES: str = "xtr.candidates"

    # Git utilities
    GIT_OPERATION: str = "git.op"
    GIT_COMMAND: str = GIT_OPERATION
    GIT_PATH: str = "git.path"
    FILE_PATH: str = "file.path"
    GIT_LINE_RANGE: str = "git.line_range"
    LINE_START: str = "line.start"
    LINE_END: str = "line.end"
    LINE_LIMIT: str = "limit"

    # Envelope wiring
    ENVELOPE_TRACE_ID: str = "envelope.trace_id"
    ENVELOPE_SPAN_ID: str = "envelope.span_id"
    ENVELOPE_DIAG_URI: str = "envelope.diag_report_uri"

    # Structured step events
    STEP_KIND: str = "codeintel.step.kind"
    STEP_STATUS: str = "codeintel.step.status"
    STEP_DETAIL: str = "codeintel.step.detail"
    STEP_PAYLOAD: str = "codeintel.step.payload"
    RUN_LEDGER_PATH: str = "codeintel.run.ledger_path"
    TRACE_ID: str = "codeintel.trace.id"

    # Request/session (additional)  # noqa: ERA001
    REQUEST_SCOPE: str = "request.scope"
    REQUEST_CONTROLS: str = "request.controls"


def as_kv(**attrs: object) -> dict[str, object]:
    """Return a dict filtered to values that are not ``None``.

    Parameters
    ----------
    **attrs : object
        Arbitrary keyword arguments. Values that are ``None`` are excluded
        from the returned dictionary.

    Returns
    -------
    dict[str, object]
        Dictionary containing only non-None key-value pairs from the input
        attributes.
    """
    return {key: value for key, value in attrs.items() if value is not None}


def to_label_str(value: object) -> str:
    """Return a deterministic string label for structured values.

    Parameters
    ----------
    value : object
        Value to convert to a string label. Strings are returned as-is.
        Other types are JSON-serialized (with sorted keys) or converted
        to string representation if JSON serialization fails.

    Returns
    -------
    str
        String representation of the value. For strings, returns the value
        unchanged. For other types, returns JSON-serialized form (with sorted
        keys) or string representation if JSON serialization fails.
    """
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)
