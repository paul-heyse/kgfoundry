# CodeIntel Data Fabric & RAG Pipeline - Capability Specification

**Capability ID**: `codeintel-data-fabric`  
**Version**: 1.0.0  
**Status**: Proposed  
**Owner**: CodeIntel Team

---

## Overview

This specification defines the **Data Fabric & RAG Pipeline** capability for CodeIntel MCP, a production-grade system for answering code intelligence queries through hybrid retrieval and LLM synthesis.

### Scope

This capability encompasses:
- **Storage Layer**: Thread-safe DuckDB, dual-index FAISS, BM25 Lucene
- **Retrieval Layer**: Hybrid search (semantic + lexical), RRF fusion, reranking
- **Orchestration Layer**: RAG pipeline controller with fallback strategies
- **State Management**: Redis-backed cross-worker scope coherence
- **Observability**: Comprehensive metrics, traces, and structured logging

### Out of Scope

- Multi-LLM support (vLLM only in v1.0)
- Streaming answers to browsers (SSE infrastructure ready, UI not included)
- Query intent classification (future enhancement)
- Feedback loop for answer quality (future enhancement)

---

## Functional Requirements

### FR-1: Answer Query Capability

**Priority**: Critical  
**Status**: Proposed

The system SHALL provide an `answer_query` MCP tool that accepts a user query and returns a synthesized answer with citations.

**Inputs**:
```typescript
interface AnswerQueryIn {
    query: string;           // User query (max 500 chars)
    scope?: ScopeIn;         // Optional scope filters
    top_k?: number;          // Results in answer (default: 10)
    rerank_top_n?: number;   // Candidates for reranking (default: 50)
}
```

**Outputs**:
```typescript
interface AnswerEnvelope {
    answer: string;                    // Synthesized answer
    snippets: Finding[];               // Cited code snippets
    plan: {                           // Execution plan
        retrieval: "hybrid-rrf";
        k_faiss: number;
        k_bm25: number;
        nprobe: number;
        rerank_k: number;
        synth_tokens: number;
    };
    limits: string[];                  // Degradations/timeouts
    confidence: number;                // [0, 1]
}
```

**Behavior**:
1. Embed query using vLLM embeddings endpoint
2. Parallel retrieval: FAISS (semantic) + BM25 (lexical)
3. RRF fusion and deduplication
4. DuckDB hydration with scope filtering
5. Optional vLLM reranking (if enabled)
6. vLLM chat synthesis with streaming
7. Return answer + citations + trace

**Acceptance Criteria**:
- [ ] Query processed in <2s (p95 latency)
- [ ] Answer includes file:line citations
- [ ] Graceful degradation on timeout (no crash)
- [ ] Trace emitted for every request

---

### FR-2: Hybrid Retrieval

**Priority**: Critical  
**Status**: Proposed

The system SHALL perform hybrid retrieval combining semantic and lexical search.

**Components**:
- **FAISS**: Semantic search via vector similarity (IP metric)
- **BM25**: Lexical search via term matching (pyserini/Lucene)
- **SPLADE** (optional): Learned sparse retrieval

**Fusion Strategy**:
- Reciprocal Rank Fusion (RRF) with k=60
- Formula: `score(doc) = sum_{retriever} 1/(k + rank(doc, retriever))`
- Deduplication by chunk ID (keep max score)

**Acceptance Criteria**:
- [ ] FAISS and BM25 run in parallel (concurrent)
- [ ] RRF correctly merges results
- [ ] Recall@10 improves ≥20% over FAISS-only
- [ ] Independent timeouts (400ms each by default)

---

### FR-3: Cross-Worker Scope Coherence

**Priority**: Critical  
**Status**: Proposed

The system SHALL maintain session-scoped state across multiple Hypercorn workers.

**Architecture**:
- **L1 Cache**: In-process LRU (256 entries, 5min TTL)
- **L2 Cache**: Redis (shared, 1hour TTL)
- **Single-Flight**: Coalesce concurrent L1 misses into single Redis fetch

**Behavior**:
1. `set_scope(session_id, scope)` writes to L1 and L2
2. `get_scope(session_id)` checks L1 → L2
3. L1 miss → fetch from Redis → populate L1
4. Expiry handled by TTL (no background cleanup)

**Acceptance Criteria**:
- [ ] Scope set on worker A, retrieved on worker B (same session_id)
- [ ] L1 hit rate ≥90% (measured via metrics)
- [ ] L2 hit rate ≥8% (cross-worker requests)
- [ ] Single-flight prevents thundering herd

---

### FR-4: Thread-Safe DuckDB Access

**Priority**: Critical  
**Status**: Proposed

The system SHALL ensure DuckDB queries are thread-safe via per-request connections.

**Implementation**:
- `DuckDBManager` provides `connection()` context manager
- Each request creates new connection (cheap for local DuckDB)
- Connection configured with: `PRAGMA enable_object_cache`, `SET threads = N`

**Acceptance Criteria**:
- [ ] 100 concurrent queries return identical results (no race conditions)
- [ ] Object cache enabled (verify via pragma query)
- [ ] Connections properly closed (no leaks)
- [ ] Query performance within 10% of baseline (overhead acceptable)

---

### FR-5: FAISS Incremental Updates

**Priority**: High  
**Status**: Proposed

The system SHALL support incremental FAISS index updates via dual-index architecture.

**Architecture**:
- **Primary Index**: Trained IVF-PQ index for bulk corpus (GPU-cloned)
- **Secondary Index**: Flat index for incremental additions (RAM/GPU)
- **Compaction**: Merge secondary into primary when threshold (5%) exceeded

**Operations**:
- `add_incremental(vectors, chunk_ids)`: Append to secondary
- `search(query_vec, k, nprobe)`: Search both, merge results
- `compact()`: Rebuild primary with secondary, clear secondary

**Acceptance Criteria**:
- [ ] Incremental add completes in <60s for 1K vectors
- [ ] Search finds vectors in both primary and secondary
- [ ] Compaction reduces total time by ≥90% vs full rebuild
- [ ] No downtime during compaction (blue-green swap)

---

### FR-6: GPU/CPU FAISS Fallback

**Priority**: High  
**Status**: Proposed

The system SHALL attempt GPU acceleration and gracefully degrade to CPU on failure.

**Behavior**:
1. On startup, attempt GPU clone with cuVS acceleration
2. If GPU clone fails:
   - Set `gpu_disabled_reason` (log details)
   - Mark readiness as "degraded" (still usable)
   - Continue with CPU index
3. Search automatically uses GPU if available, else CPU

**Acceptance Criteria**:
- [ ] Service starts even if GPU unavailable
- [ ] Readiness endpoint indicates `mode: "degraded"` with reason
- [ ] CPU search slower but correct (same results as GPU)
- [ ] GPU clone success logged with cuVS version

---

### FR-7: Embedding Contract Enforcement

**Priority**: Critical  
**Status**: Proposed

The system SHALL enforce embedding dimension consistency across all components.

**Contract**:
- **Single Source**: `settings.embedding.vec_dim`
- **Components**: vLLM embeddings, FAISS index, Parquet schema
- **Validation**: Readiness probe checks all components match

**Checks**:
1. **vLLM**: Embed probe vector, verify dimension
2. **FAISS**: Load index, verify `index.d == vec_dim`
3. **Parquet**: Check `FixedSizeList` length

**Acceptance Criteria**:
- [ ] Dimension mismatch prevents startup (fail-fast)
- [ ] Readiness returns `ready: false` with clear error message
- [ ] Changing dimension in config updates all components
- [ ] No hardcoded dimensions (all reference config)

---

### FR-8: Answer Trace Emission

**Priority**: High  
**Status**: Proposed

The system SHALL emit comprehensive traces for every answer request.

**Trace Schema** (25+ fields):
- Identity: `trace_id`, `session_id`, `timestamp`
- Retrieval: `faiss_latency_ms`, `bm25_latency_ms`, `top_k_doc_ids`
- Reranking: `rerank_latency_ms`, `reranked_doc_ids`
- Synthesis: `tokens_in`, `tokens_out`, `ttft_ms`, `tps`
- Quality: `confidence`, `limits`

**Emission Channels**:
1. **Real-Time SSE**: Stream trace event to client
2. **Batch Parquet**: Append to `traces/YYYY-MM-DD.parquet` (batch size: 100)

**Acceptance Criteria**:
- [ ] 100% of requests have traces (no gaps)
- [ ] Traces queryable via DuckDB
- [ ] SSE trace arrives before response completes
- [ ] Parquet batching reduces write I/O by ≥90%

---

### FR-9: Prometheus Metrics

**Priority**: High  
**Status**: Proposed

The system SHALL expose 20+ metrics via `/metrics` endpoint.

**Categories**:
- **Counters**: `answers_total{status,mode}`, `retrieval_timeouts_total{retriever}`
- **Histograms**: `answer_latency_seconds{phase}`, `tokens_generated{model}`
- **Gauges**: `faiss_index_size{type}`, `scope_registry_size`

**Acceptance Criteria**:
- [ ] `/metrics` returns Prometheus-formatted output
- [ ] Metrics updated in real-time (no delay)
- [ ] Histograms have p50, p95, p99 quantiles
- [ ] Grafana dashboard provided (JSON export)

---

### FR-10: vLLM Chat & Score Integration

**Priority**: Critical  
**Status**: Proposed

The system SHALL integrate vLLM for synthesis and reranking.

**Endpoints**:
- **Embeddings**: `/v1/embeddings` (already used)
- **Chat Completions**: `/v1/chat/completions` with streaming
- **Score API**: `/v1/scores` for cross-encoder reranking (optional)

**Clients**:
- `VLLMChatClient`: Streaming synthesis via SSE
- `VLLMScoreClient`: Batch reranking

**Acceptance Criteria**:
- [ ] Streaming tokens arrive in real-time (not buffered)
- [ ] Reranking improves MRR by ≥20%
- [ ] Persistent HTTP connections (no per-request overhead)
- [ ] Graceful fallback if score endpoint unavailable

---

### FR-11: Prompt Construction

**Priority**: Medium  
**Status**: Proposed

The system SHALL construct context-aware prompts with code snippets.

**Format**:
```
System: You are a code expert assistant.

User: {query}

Context:
[1] {file.py} (lines {start}-{end}):
```{language}
{code}
```

[2] {file2.py} (lines {start}-{end}):
```{language}
{code}
```

Answer (reference snippets by number):
```

**Token Budget**:
- Maximum input tokens: 4096 (configurable)
- Truncate snippets if exceeds budget
- Prioritize higher-scoring snippets

**Acceptance Criteria**:
- [ ] Prompt fits within token budget
- [ ] Snippets formatted with syntax highlighting markers
- [ ] Answer references snippets by number
- [ ] System message configurable

---

### FR-12: Progressive Citations

**Priority**: Medium  
**Status**: Proposed

The system SHALL emit citations during or after synthesis.

**Citation Format**:
```typescript
interface Citation {
    uri: string;          // Relative to repo root
    start_line: number;
    end_line: number;
    language: string;
}
```

**Emission**:
- Citations emitted as separate events after synthesis
- Order matches snippet order in prompt ([1], [2], ...)

**Acceptance Criteria**:
- [ ] All cited snippets have citations
- [ ] Citation file paths valid (within repo)
- [ ] Line ranges accurate (match DuckDB data)

---

### FR-13: Confidence Scoring

**Priority**: Medium  
**Status**: Proposed

The system SHALL compute confidence score for each answer.

**Factors**:
- **Base**: 0.8 if synthesis succeeded
- **Penalties**: -0.1 per timeout/degradation
- **Bonus**: +0.1 if top hit score >0.7

**Range**: [0, 1]

**Acceptance Criteria**:
- [ ] Confidence correlates with actual quality (manual evaluation)
- [ ] Low confidence (<0.3) answers flagged for review
- [ ] Confidence exposed in `AnswerEnvelope`

---

### FR-14: BM25 Indexing

**Priority**: High  
**Status**: Proposed

The system SHALL build and maintain BM25 Lucene index for lexical search.

**Implementation**:
- **Tool**: pyserini/Lucene
- **Input**: Chunks as JSON (from Parquet)
- **Output**: Lucene index at `indexes/lucene/`

**Indexing Command**:
```bash
python -m pyserini.index.lucene \
    --collection JsonCollection \
    --input data/chunks_jsonl/ \
    --index indexes/lucene/ \
    --threads 4
```

**Acceptance Criteria**:
- [ ] Index build completes in <10min for 100K chunks
- [ ] Search latency <100ms (p95)
- [ ] Index size <5GB for 100K chunks
- [ ] Documented in README

---

### FR-15: Adaptive FAISS Indexing

**Priority**: Medium  
**Status**: Proposed

The system SHALL choose FAISS index type based on corpus size.

**Strategy**:
- **n <10K**: Flat index (exact search)
- **10K ≤ n <100K**: IVF-Flat (nlist = min(4096, n//100))
- **n ≥100K**: IVF-PQ (nlist = min(8192, n//200), pq_m=32)

**Training**:
- Train on full corpus if <1M vectors
- Train on random sample if ≥1M vectors

**Acceptance Criteria**:
- [ ] Index type logged at build time
- [ ] Manifest records index_type, nlist, pq_m
- [ ] Performance appropriate for corpus size

---

## Non-Functional Requirements

### NFR-1: Performance (Latency)

**Requirement**: p95 latency <2s for answer queries under normal load.

**Breakdown**:
- Retrieval (parallel): <400ms (p95)
- Hydration: <200ms (p95)
- Reranking: <300ms (p95)
- Synthesis: <1000ms (p95)
- Total: <1900ms (budget), <2000ms (SLO)

**Measurement**: Prometheus histogram `answer_latency_seconds{phase}`

**Acceptance**: Load test (vegeta) at 100 QPS for 5min confirms p95 <2s

---

### NFR-2: Performance (Throughput)

**Requirement**: Sustain 1000 QPS with <2% error rate.

**Constraints**:
- Single Hypercorn instance (8 workers)
- GPU acceleration enabled (NVIDIA A100)
- Redis co-located (localhost)
- vLLM on separate instance (H100 GPU)

**Measurement**: Load test with vegeta at 1000 QPS for 5min

**Acceptance**:
- [ ] p95 latency <3s (degraded SLO at high load)
- [ ] Error rate <2%
- [ ] No memory leaks (stable RSS)

---

### NFR-3: Availability

**Requirement**: 99.5% uptime for answer query capability.

**Uptime Calculation**: Excludes planned maintenance, counts only unplanned outages.

**Fail-Open Strategy**:
- FAISS GPU fails → Continue on CPU (degraded)
- Redis fails → Continue with L1 cache only (scoped to worker)
- Reranking times out → Skip reranking, use fusion scores
- Synthesis times out → Return retrieval-only response

**Acceptance**: No single-point-of-failure causes total outage

---

### NFR-4: Observability

**Requirement**: Full visibility into pipeline stages, errors, and quality.

**Components**:
- **Metrics**: 20+ Prometheus metrics (counters, histograms, gauges)
- **Traces**: AnswerTrace Parquet dataset (100% of requests)
- **Logs**: Structured logging at INFO level (stage start/end, errors)
- **Dashboard**: Grafana dashboard with key metrics

**Acceptance**:
- [ ] Detect 5% latency regression within 5 minutes
- [ ] Identify failing queries via trace analysis
- [ ] All errors logged with context (trace_id, session_id, query)

---

### NFR-5: Correctness

**Requirement**: Results deterministic and reproducible.

**Guarantees**:
- Same query + scope → same results (within RRF tie-breaking)
- Cross-worker requests → identical behavior
- DuckDB queries → thread-safe, no race conditions
- FAISS search → deterministic given fixed seed

**Acceptance**: Fuzz test (1000 queries, 2 workers) shows <1% variance

---

### NFR-6: Security

**Requirement**: Prevent unauthorized access and data leakage.

**Controls**:
- **Path Traversal**: Scope filtering enforces repo boundaries
- **SQL Injection**: All DuckDB queries parameterized
- **Redis Security**: AUTH enabled, no key wildcards
- **vLLM API**: No untrusted input to `/v1/chat` (sanitized)

**Acceptance**: Penetration test finds no critical vulnerabilities

---

### NFR-7: Scalability

**Requirement**: Support 1M+ chunk corpus with linear degradation.

**Scaling Factors**:
- **FAISS**: IVF-PQ index scales to 10M+ vectors
- **DuckDB**: Parquet scans scale to 100GB+ (object cache)
- **BM25**: Lucene scales to 10M+ documents

**Acceptance**: Indexing and query time grow <O(n log n)

---

### NFR-8: Maintainability

**Requirement**: Code adheres to best practices, fully typed, tested.

**Standards**:
- **Type Coverage**: 100% (pyright strict, no Any)
- **Test Coverage**: ≥90% (excluding integration/GPU tests)
- **Documentation**: All public APIs have NumPy docstrings
- **Linting**: Zero Ruff errors, zero pyrefly issues

**Acceptance**: `make quality-gates` passes

---

## Data Contracts

### Contract 1: ScopeIn

**Purpose**: Filter chunks by repository, branch, path, language.

**Schema**:
```typescript
interface ScopeIn {
    repos?: string[];          // Repository IDs
    branches?: string[];       // Branch names
    include_globs?: string[];  // Path patterns (*, **)
    exclude_globs?: string[];  // Exclusion patterns
    languages?: string[];      // Language IDs (py, ts, rs)
}
```

**Validation**:
- All fields optional (empty = no filter)
- Globs follow shell pattern syntax
- Languages from predefined set

---

### Contract 2: Finding

**Purpose**: Code snippet with metadata.

**Schema**:
```typescript
interface Finding {
    id: number;          // Chunk ID
    uri: string;         // Relative path
    start_line: number;
    end_line: number;
    language: string;
    code: string;
    score: number;       // Relevance [0, 1]
}
```

---

### Contract 3: AnswerTrace

**Purpose**: Complete observability trace.

**Schema**: See FR-8 (25+ fields)

**Persistence**: Parquet with schema:
```python
pa.schema([
    ("trace_id", pa.string()),
    ("session_id", pa.string()),
    ("timestamp", pa.timestamp("us")),
    ("query", pa.string()),
    ("scope", pa.string()),  # JSON
    ("faiss_latency_ms", pa.float32()),
    # ... 20 more fields ...
])
```

---

## Testing Strategy

### Unit Tests (Target: 150+ tests)

**Coverage**:
- LRUCache: eviction, TTL expiration
- AsyncSingleFlight: coalescing, exceptions
- DuckDBManager: connection lifecycle, pragmas
- FAISSDualIndexManager: search merge, compaction
- RRF fusion: correctness, tie-breaking
- Confidence scoring: edge cases

**Tools**: pytest, pytest-asyncio, pytest-mock

---

### Integration Tests (Target: 50+ tests)

**Scenarios**:
- End-to-end answer (query → synthesis → trace)
- Cross-worker scope coherence
- DuckDB concurrent queries
- FAISS incremental → search
- BM25 + FAISS hybrid
- vLLM streaming
- Timeout fallbacks

**Environment**: Docker Compose (vLLM, Redis, DuckDB)

---

### Load Tests

**Tools**: vegeta, Prometheus

**Profiles**:
- **Sustained**: 1000 QPS for 5min
- **Spike**: 5000 QPS for 30s
- **Soak**: 100 QPS for 1hour

**Metrics**: p50/p95/p99 latency, error rate, memory growth

---

### Performance Benchmarks

**Datasets**: CodeSearchNet (1000 queries with ground truth)

**Metrics**:
- Recall@k (k=1,5,10,20)
- MRR (Mean Reciprocal Rank)
- Latency (p50, p95, p99)

**Baselines**:
- FAISS-only
- BM25-only
- Hybrid (no rerank)
- Hybrid + rerank

---

## Deployment

### Dependencies

**Required**:
- Python 3.13+
- Redis 7.0+ (for scope store)
- DuckDB 0.9+ (embedded)
- FAISS 1.7+ with cuVS (for GPU)
- vLLM 0.3+ (separate instance)

**Optional**:
- NVIDIA GPU (A100 recommended) for FAISS GPU
- Prometheus for metrics
- Grafana for dashboards

---

### Configuration

**Environment Variables**:
```bash
# Redis
REDIS_URL=redis://localhost:6379
REDIS_SCOPE_L1_SIZE=256
REDIS_SCOPE_L1_TTL_SECONDS=300
REDIS_SCOPE_L2_TTL_SECONDS=3600

# DuckDB
DUCKDB_THREADS=4
DUCKDB_MATERIALIZE=false
DUCKDB_OBJECT_CACHE=true

# FAISS
FAISS_USE_CUVS=true
FAISS_COMPACTION_THRESHOLD=0.05
FAISS_ADAPTIVE_NPROBE=true

# vLLM
VLLM_BASE_URL=http://vllm-server:8000
VLLM_EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5
VLLM_CHAT_MODEL=meta-llama/Llama-3.1-8B-Instruct
VLLM_SCORE_MODEL=BAAI/bge-reranker-large  # optional

# Answer Pipeline
ANSWER_FAISS_TIMEOUT_MS=400
ANSWER_BM25_TIMEOUT_MS=400
ANSWER_SYNTHESIS_TIMEOUT_MS=1000
ANSWER_MAX_INPUT_TOKENS=4096
ANSWER_MAX_OUTPUT_TOKENS=500
ANSWER_RERANK_ENABLED=true

# Embedding Contract
EMBEDDING_MODEL_ID=nomic-ai/nomic-embed-text-v1.5
EMBEDDING_VEC_DIM=2560
EMBEDDING_NORMALIZE=true
EMBEDDING_DTYPE=float32
```

---

## Success Criteria

### Milestone 1: Phase 5a Complete (Week 2)

- [ ] Redis scope store operational (L1/L2)
- [ ] DuckDB thread-safe (100 concurrent queries pass)
- [ ] FAISS dual-index (incremental updates <60s)
- [ ] BM25 index built and searchable
- [ ] Embedding contract enforced (readiness validates)

---

### Milestone 2: Phase 5b Complete (Week 4)

- [ ] Answer orchestrator operational
- [ ] vLLM chat/score clients functional
- [ ] End-to-end RAG pipeline working
- [ ] Hybrid retrieval improves recall ≥20%
- [ ] MCP `answer_query` tool registered

---

### Milestone 3: Phase 5c Complete (Week 6)

- [ ] AnswerTrace Parquet dataset populated
- [ ] Prometheus metrics exposed
- [ ] Grafana dashboard deployed
- [ ] Load test passes (1000 QPS sustained)
- [ ] Integration tests green (50+ tests)

---

### Final Acceptance

- [ ] All 15 functional requirements met
- [ ] All 8 non-functional requirements met
- [ ] All 3 milestones completed
- [ ] Documentation complete (architecture, API, ops)
- [ ] Production deployment verified

---

**End of Specification**

