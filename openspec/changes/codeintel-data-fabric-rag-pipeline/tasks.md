# Phase 5: Data Fabric & RAG Pipeline - Implementation Tasks

**Version**: 1.0.0  
**Last Updated**: 2025-11-08  
**Total Duration**: 4-6 weeks (150+ hours)  
**Task Count**: 85 tasks across 3 phases

---

## Task Overview

| Phase | Focus | Tasks | Hours | Critical Path |
|-------|-------|-------|-------|---------------|
| **Phase 5a: Foundations** | Storage, indexing, scope | 30 | 50h | Redis, DuckDB, FAISS |
| **Phase 5b: RAG Pipeline** | Answer orchestration | 30 | 60h | Orchestrator, vLLM |
| **Phase 5c: Observability** | Metrics, traces, testing | 25 | 40h | AnswerTrace, Testing |
| **Total** | | **85** | **150h** | |

---

## Phase 5a: Foundations (Week 1-2, 50 hours)

### Epic 1: Redis-Backed Scope Store (Tasks 1-10, 10 hours)

#### Task 1: Implement LRUCache Generic Class
**Priority**: High  
**Duration**: 45 minutes  
**Complexity**: Medium

**Description**:  
Create thread-safe LRU cache with TTL support for L1 caching.

**Acceptance Criteria**:
- [ ] `LRUCache[T]` generic class with `maxsize` and `ttl_seconds`
- [ ] Thread-safe using `RLock`
- [ ] `get(key)` returns `None` if expired or missing
- [ ] `set(key, value)` evicts LRU when full
- [ ] TTL checked on access, not background timer

**Files to Modify**:
- `codeintel_rev/app/scope_store.py` (new)

**Testing**:
```python
# tests/app/test_scope_store.py
def test_lru_cache_eviction():
    cache = LRUCache[str](maxsize=2, ttl_seconds=60)
    cache.set("a", "1")
    cache.set("b", "2")
    cache.set("c", "3")  # Evicts "a" (LRU)
    assert cache.get("a") is None
    assert cache.get("c") == "3"

def test_lru_cache_ttl():
    cache = LRUCache[str](maxsize=10, ttl_seconds=1)
    cache.set("k", "v")
    assert cache.get("k") == "v"
    time.sleep(1.1)
    assert cache.get("k") is None  # Expired
```

---

#### Task 2: Implement AsyncSingleFlight
**Priority**: High  
**Duration**: 30 minutes  
**Complexity**: Medium

**Description**:  
Coalesces concurrent async calls for same key into single execution.

**Acceptance Criteria**:
- [ ] `do(key, fn)` method that awaits or starts new flight
- [ ] Thread-safe using `asyncio.Lock`
- [ ] Exceptions propagated to all waiters
- [ ] Cleanup after flight completes

**Files to Modify**:
- `codeintel_rev/app/scope_store.py`

**Testing**:
```python
@pytest.mark.asyncio
async def test_single_flight_coalescing():
    flight = AsyncSingleFlight()
    call_count = 0
    
    async def expensive_fn():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.1)
        return "result"
    
    # 100 concurrent calls
    results = await asyncio.gather(*[
        flight.do("key", expensive_fn) for _ in range(100)
    ])
    
    assert all(r == "result" for r in results)
    assert call_count == 1  # Only one execution
```

---

#### Task 3: Implement ScopeStore with L1/L2
**Priority**: Critical  
**Duration**: 2 hours  
**Complexity**: High

**Description**:  
Main scope store with L1 (LRU) and L2 (Redis) caching.

**Acceptance Criteria**:
- [ ] `get(session_id)` checks L1 → L2 with single-flight
- [ ] `set(session_id, scope, ttl)` writes to both L1 and L2
- [ ] `delete(session_id)` removes from both caches
- [ ] Metrics tracking (L1/L2 hits, misses, hit_rate)
- [ ] Proper serialization (msgspec JSON)

**Files to Modify**:
- `codeintel_rev/app/scope_store.py`

**Testing**:
```python
@pytest.mark.asyncio
async def test_scope_store_l1_hit():
    redis = await aioredis.from_url("redis://localhost")
    store = ScopeStore(redis, l1_maxsize=256, l1_ttl_seconds=300)
    
    scope = ScopeIn(repos=["kgfoundry"], languages=["py"])
    await store.set("session-123", scope)
    
    # L1 hit (no Redis call)
    retrieved = await store.get("session-123")
    assert retrieved == scope
    assert store.metrics["l1_hits"] == 1

@pytest.mark.asyncio
async def test_scope_store_l2_hit():
    store = ScopeStore(redis)
    scope = ScopeIn(repos=["repo"])
    
    # Set and flush L1
    await store.set("sess", scope)
    store._l1.clear()
    
    # L2 hit (Redis fetch, populates L1)
    retrieved = await store.get("sess")
    assert retrieved == scope
    assert store.metrics["l2_hits"] == 1
    
    # Next call is L1 hit
    retrieved2 = await store.get("sess")
    assert store.metrics["l1_hits"] == 1
```

---

#### Task 4: Update ApplicationContext
**Priority**: Critical  
**Duration**: 30 minutes  
**Complexity**: Low

**Description**:  
Replace `ScopeRegistry` with `ScopeStore` in `ApplicationContext`.

**Acceptance Criteria**:
- [ ] Remove `scope_registry: ScopeRegistry` field
- [ ] Add `scope_store: ScopeStore` field
- [ ] Initialize `ScopeStore` in `ApplicationContext.create()`
- [ ] Pass Redis client from settings

**Files to Modify**:
- `codeintel_rev/app/config_context.py`

**Changes**:
```python
# Before
@dataclass(frozen=True, slots=True)
class ApplicationContext:
    scope_registry: ScopeRegistry

# After
@dataclass(frozen=True, slots=True)
class ApplicationContext:
    scope_store: ScopeStore  # Redis-backed

@classmethod
async def create(cls, settings: Settings) -> ApplicationContext:
    # Initialize Redis
    redis_client = await aioredis.from_url(settings.redis.url)
    
    # Create scope store
    scope_store = ScopeStore(
        redis_client,
        l1_maxsize=settings.redis.scope_l1_size,
        l1_ttl_seconds=settings.redis.scope_l1_ttl_seconds,
        l2_ttl_seconds=settings.redis.scope_l2_ttl_seconds,
    )
    
    return cls(
        # ... other fields ...
        scope_store=scope_store,
    )
```

---

#### Task 5: Update Adapters for ScopeStore
**Priority**: High  
**Duration**: 1 hour  
**Complexity**: Low

**Description**:  
Update all adapters to use `context.scope_store` instead of `context.scope_registry`.

**Acceptance Criteria**:
- [ ] Replace `scope_registry.get()` with `await scope_store.get()`
- [ ] Replace `scope_registry.set()` with `await scope_store.set()`
- [ ] All adapter functions are `async def`

**Files to Modify**:
- `codeintel_rev/mcp_server/adapters/semantic.py`
- `codeintel_rev/mcp_server/adapters/files.py`
- `codeintel_rev/mcp_server/adapters/text_search.py`
- `codeintel_rev/mcp_server/adapters/history.py`

**Changes**:
```python
# Before (synchronous)
def semantic_search(context: ApplicationContext, query: str):
    session_id = get_session_id()
    scope = context.scope_registry.get(session_id)

# After (asynchronous)
async def semantic_search(context: ApplicationContext, query: str):
    session_id = get_session_id()
    scope = await context.scope_store.get(session_id)
```

---

#### Tasks 6-10: Redis Configuration & Testing
**Total Duration**: 5 hours

**Task 6**: Add Redis settings to `config/settings.py` (30min)  
**Task 7**: Write integration tests for scope persistence (2h)  
**Task 8**: Write load tests (1000 concurrent scope gets) (1h)  
**Task 9**: Document Redis deployment (Docker Compose) (1h)  
**Task 10**: Add Redis health check to readiness probe (30min)

---

### Epic 2: Thread-Safe DuckDB Manager (Tasks 11-20, 10 hours)

#### Task 11: Implement DuckDBManager Context Manager
**Priority**: Critical  
**Duration**: 1.5 hours  
**Complexity**: Medium

**Description**:  
Create per-request DuckDB connection manager with optimizations.

**Acceptance Criteria**:
- [ ] `@contextmanager connection()` yields configured connection
- [ ] `PRAGMA enable_object_cache` executed on each connection
- [ ] `SET threads = N` executed
- [ ] `_ensure_schema()` creates view or materialized table
- [ ] Connection closed in finally block

**Files to Modify**:
- `codeintel_rev/io/duckdb_manager.py` (new)

**Testing**:
```python
def test_duckdb_manager_connection():
    manager = DuckDBManager(db_path, settings)
    
    with manager.connection() as conn:
        result = conn.execute("SELECT 1").fetchone()
        assert result == (1,)
    
    # Connection closed after context exit

def test_duckdb_manager_pragmas():
    manager = DuckDBManager(db_path, settings)
    
    with manager.connection() as conn:
        # Check object cache enabled
        result = conn.execute("PRAGMA enable_object_cache").fetchone()
        # Check threads set
        result = conn.execute("SELECT current_setting('threads')").fetchone()
        assert int(result[0]) == settings.threads
```

---

#### Task 12: Implement DuckDBQueryBuilder
**Priority**: High  
**Duration**: 1 hour  
**Complexity**: Medium

**Description**:  
Helper for building parameterized DuckDB queries with scope filtering.

**Acceptance Criteria**:
- [ ] `build_filter_query(chunk_ids, include_globs, exclude_globs, languages)`
- [ ] Returns `(sql, params)` tuple
- [ ] All parameters use placeholders (no string concat)
- [ ] Globs converted to SQL LIKE patterns (` * → %`)

**Files to Modify**:
- `codeintel_rev/io/duckdb_manager.py`

**Testing**:
```python
def test_query_builder_basic():
    builder = DuckDBQueryBuilder()
    sql, params = builder.build_filter_query(chunk_ids=[1, 2, 3])
    
    assert "id = ANY($ids)" in sql
    assert params["ids"] == [1, 2, 3]

def test_query_builder_with_filters():
    sql, params = builder.build_filter_query(
        chunk_ids=[1],
        include_globs=["src/**"],
        languages=["py", "ts"]
    )
    
    assert "uri LIKE $include_0" in sql
    assert params["include_0"] == "src/%"
    assert "lang = ANY($languages)" in sql
```

---

#### Task 13: Refactor DuckDBCatalog to use Manager
**Priority**: Critical  
**Duration**: 2 hours  
**Complexity**: Medium

**Description**:  
Replace shared `self.conn` with `DuckDBManager` in `DuckDBCatalog`.

**Acceptance Criteria**:
- [ ] Remove `self.conn` field
- [ ] Add `self._manager: DuckDBManager` field
- [ ] All queries use `with self._manager.connection() as conn:`
- [ ] No shared connection state

**Files to Modify**:
- `codeintel_rev/io/duckdb_catalog.py`

**Changes**:
```python
# Before
class DuckDBCatalog:
    def __init__(self, db_path: Path):
        self.conn = duckdb.connect(str(db_path))  # SHARED STATE
    
    def query_by_ids(self, ids: list[int]):
        return self.conn.execute("SELECT ...").fetchall()

# After
class DuckDBCatalog:
    def __init__(self, db_path: Path, settings: DuckDBConfig):
        self._manager = DuckDBManager(db_path, settings)  # NO SHARED STATE
    
    async def query_by_ids(self, ids: list[int]):
        with self._manager.connection() as conn:
            return await asyncio.to_thread(
                conn.execute, "SELECT ...", params
            ).fetchall()
```

---

#### Tasks 14-20: DuckDB Testing & Optimization
**Total Duration**: 5.5 hours

**Task 14**: Write concurrency tests (100 parallel queries) (2h)  
**Task 15**: Benchmark object cache impact (before/after) (1h)  
**Task 16**: Test materialized vs view performance (1h)  
**Task 17**: Add SQL query logging (optional, debug) (30min)  
**Task 18**: Document thread safety guarantees (30min)  
**Task 19**: Add connection pool option (advanced, optional) (30min)  
**Task 20**: Update configuration docs for DuckDB settings (30min)

---

### Epic 3: FAISS Dual-Index with Compaction (Tasks 21-30, 20 hours)

#### Task 21: Implement IndexManifest Dataclass
**Priority**: High  
**Duration**: 30 minutes  
**Complexity**: Low

**Description**:  
Create manifest for FAISS index metadata.

**Acceptance Criteria**:
- [ ] `@dataclass IndexManifest` with all required fields
- [ ] `from_file(path)` loads from JSON
- [ ] `to_file(path)` saves to JSON
- [ ] Fields: version, vec_dim, index_type, metric, nlist, pq_m, etc.

**Files to Modify**:
- `codeintel_rev/io/faiss_dual_index.py` (new)

---

#### Task 22: Implement FAISSDualIndexManager Skeleton
**Priority**: Critical  
**Duration**: 2 hours  
**Complexity**: High

**Description**:  
Create main manager class with primary + secondary index fields.

**Acceptance Criteria**:
- [ ] `__init__(index_dir, settings, vec_dim)`
- [ ] Fields: `_primary_cpu`, `_primary_gpu`, `_secondary_cpu`, `_secondary_gpu`
- [ ] `_gpu_resources: StandardGpuResources | None`
- [ ] `_gpu_enabled: bool` and `_gpu_disabled_reason: str | None`

**Files to Modify**:
- `codeintel_rev/io/faiss_dual_index.py`

---

#### Task 23: Implement ensure_ready() with GPU Clone
**Priority**: Critical  
**Duration**: 3 hours  
**Complexity**: High

**Description**:  
Load indexes, validate dimensions, attempt GPU clone.

**Acceptance Criteria**:
- [ ] Load `primary.faiss` from disk
- [ ] Validate `primary.d == vec_dim`
- [ ] Load `secondary.faiss` (or create empty Flat)
- [ ] Load `primary.manifest.json`
- [ ] Attempt GPU clone with cuVS
- [ ] On GPU failure, set degraded mode (continue on CPU)
- [ ] Return `(ready: bool, error: str | None)`

**Files to Modify**:
- `codeintel_rev/io/faiss_dual_index.py`

**Testing**:
```python
@pytest.mark.asyncio
async def test_ensure_ready_success():
    manager = FAISSDualIndexManager(index_dir, settings, vec_dim=2560)
    ready, error = await manager.ensure_ready()
    
    assert ready is True
    assert error is None or "GPU degraded" in error  # GPU optional

@pytest.mark.asyncio
async def test_ensure_ready_dimension_mismatch():
    # Create index with wrong dimension
    manager = FAISSDualIndexManager(index_dir, settings, vec_dim=1024)
    ready, error = await manager.ensure_ready()
    
    assert ready is False
    assert "Dimension mismatch" in error
```

---

#### Task 24: Implement Dual-Index Search with Merge
**Priority**: Critical  
**Duration**: 2 hours  
**Complexity**: Medium

**Description**:  
Search both primary and secondary, merge results, deduplicate.

**Acceptance Criteria**:
- [ ] Search primary for `k*2` results
- [ ] Search secondary for `k*2` results
- [ ] Merge by chunk ID (keep max score on duplicates)
- [ ] Sort by score descending
- [ ] Return top `k`
- [ ] Prefer GPU if enabled, fallback to CPU

**Files to Modify**:
- `codeintel_rev/io/faiss_dual_index.py`

**Testing**:
```python
def test_dual_index_search():
    manager = FAISSDualIndexManager(index_dir, settings, vec_dim)
    await manager.ensure_ready()
    
    # Add vector to secondary only
    new_vec = np.random.rand(1, vec_dim).astype(np.float32)
    await manager.add_incremental(new_vec, np.array([99999]))
    
    # Search should find it (merged from secondary)
    hits = manager.search(new_vec[0], k=10)
    
    assert any(hit[0] == 99999 for hit in hits)
```

---

#### Task 25: Implement add_incremental()
**Priority**: High  
**Duration**: 1 hour  
**Complexity**: Medium

**Description**:  
Add vectors to secondary index with ID persistence.

**Acceptance Criteria**:
- [ ] Validate vector dimension
- [ ] `secondary_cpu.add_with_ids(vectors, chunk_ids)`
- [ ] Persist `secondary.faiss` to disk
- [ ] Update GPU secondary if enabled (re-clone)
- [ ] Log secondary total count

**Files to Modify**:
- `codeintel_rev/io/faiss_dual_index.py`

---

#### Task 26: Implement needs_compaction()
**Priority**: Medium  
**Duration**: 15 minutes  
**Complexity**: Low

**Description**:  
Check if secondary exceeds compaction threshold.

**Acceptance Criteria**:
- [ ] Compute `secondary_ratio = secondary.ntotal / primary.ntotal`
- [ ] Return `secondary_ratio > settings.compaction_threshold`
- [ ] Default threshold: 0.05 (5%)

---

#### Task 27: Implement compact() Blue-Green Strategy
**Priority**: High  
**Duration**: 3 hours  
**Complexity**: High

**Description**:  
Rebuild primary with secondary merged, atomic swap.

**Acceptance Criteria**:
- [ ] Extract vectors from primary + secondary
- [ ] Build new primary (`_build_adaptive_index`)
- [ ] Write to `primary_new.faiss`
- [ ] Validate new primary (dimension, count)
- [ ] Atomic rename: `primary_new.faiss` → `primary.faiss`
- [ ] Clear secondary (create empty Flat)
- [ ] Update manifest with new counts, timestamp
- [ ] Re-clone to GPU

**Files to Modify**:
- `codeintel_rev/io/faiss_dual_index.py`

**Testing**:
```python
@pytest.mark.asyncio
async def test_compaction():
    manager = FAISSDualIndexManager(index_dir, settings, vec_dim)
    await manager.ensure_ready()
    
    initial_primary = manager._primary_cpu.ntotal
    
    # Add many vectors to secondary
    for _ in range(1000):
        vec = np.random.rand(1, vec_dim).astype(np.float32)
        await manager.add_incremental(vec, np.array([_ + 10000]))
    
    assert manager.needs_compaction()
    
    # Compact
    await manager.compact()
    
    # Primary now includes secondary
    assert manager._primary_cpu.ntotal == initial_primary + 1000
    assert manager._secondary_cpu.ntotal == 0
```

---

#### Task 28: Implement _build_adaptive_index()
**Priority**: Medium  
**Duration**: 2 hours  
**Complexity**: Medium

**Description**:  
Build FAISS index with type adapted to corpus size.

**Acceptance Criteria**:
- [ ] `n < 10K`: Flat index
- [ ] `10K <= n < 100K`: IVF-Flat (nlist = min(4096, n//100))
- [ ] `n >= 100K`: IVF-PQ (nlist = min(8192, n//200), pq_m=32)
- [ ] Train on sample if corpus huge (>1M)

---

#### Tasks 29-30: FAISS Testing & Documentation
**Total Duration**: 6 hours

**Task 29**: Write incremental update integration test (2h)  
**Task 30**: Write GPU fallback test (mock CUDA unavailable) (1h)  
**Task 31**: Benchmark adaptive indexing (Flat vs IVF vs IVFPQ) (2h)  
**Task 32**: Document compaction scheduler (cron job) (1h)

---

### Epic 4: BM25 Integration & Hybrid Retrieval (Tasks 31-40, 10 hours)

#### Task 33: Implement BM25Searcher
**Priority**: High  
**Duration**: 1 hour  
**Complexity**: Low

**Description**:  
Wrapper for pyserini Lucene BM25 search.

**Acceptance Criteria**:
- [ ] `__init__(index_dir)` initializes `LuceneSearcher`
- [ ] `search(query, k)` returns `list[BM25Hit]`
- [ ] `BM25Hit` dataclass with `doc_id` and `score`

**Files to Modify**:
- `codeintel_rev/retrieval/bm25_searcher.py` (new)

**Testing**:
```python
def test_bm25_search():
    searcher = BM25Searcher(lucene_index_dir)
    hits = searcher.search("AuthMiddleware class", k=10)
    
    assert len(hits) <= 10
    assert all(isinstance(h.doc_id, int) for h in hits)
    assert all(h.score > 0 for h in hits)
```

---

#### Task 34: Build BM25 Lucene Index
**Priority**: Critical  
**Duration**: 2 hours  
**Complexity**: Medium

**Description**:  
Index code chunks with pyserini for BM25 search.

**Acceptance Criteria**:
- [ ] Convert Parquet chunks to JSON format for pyserini
- [ ] Run `python -m pyserini.index.lucene` command
- [ ] Index stored in `indexes/lucene/` directory
- [ ] Document indexing command in README

**Script**:
```bash
# scripts/build_bm25_index.sh
python -m pyserini.index.lucene \
    --collection JsonCollection \
    --input data/chunks_jsonl/ \
    --index indexes/lucene/ \
    --generator DefaultLuceneDocumentGenerator \
    --threads 4 \
    --storePositions \
    --storeDocvectors \
    --storeRaw
```

---

#### Tasks 35-40: BM25 Integration
**Total Duration**: 7 hours

**Task 35**: Add BM25 settings to config (30min)  
**Task 36**: Initialize `BM25Searcher` in `ApplicationContext` (30min)  
**Task 37**: Write BM25 retrieval method in orchestrator (1h)  
**Task 38**: Test BM25 vs FAISS recall on benchmark (2h)  
**Task 39**: Document BM25 index building process (1h)  
**Task 40**: Add BM25 health check to readiness (30min)

---

### Epic 5: Embedding Contract Enforcement (Tasks 41-45, 5 hours)

#### Task 41: Add EmbeddingConfig to Settings
**Priority**: Critical  
**Duration**: 30 minutes  
**Complexity**: Low

**Description**:  
Single source of truth for embedding contract.

**Acceptance Criteria**:
- [ ] `@dataclass EmbeddingConfig` with fields: `model_id`, `vec_dim`, `normalize`, `dtype`
- [ ] Default: `model_id="nomic-ai/nomic-embed-text-v1.5"`, `vec_dim=2560`
- [ ] Added to `Settings` dataclass

**Files to Modify**:
- `codeintel_rev/config/settings.py`

---

#### Task 42: Update Components to Use EmbeddingConfig
**Priority**: High  
**Duration**: 1 hour  
**Complexity**: Low

**Description**:  
Replace hardcoded dimensions with `settings.embedding.vec_dim`.

**Acceptance Criteria**:
- [ ] `FAISSManager` uses `settings.embedding.vec_dim`
- [ ] `ParquetStore` uses `settings.embedding.vec_dim` for schema
- [ ] `VLLMClient` validates output dimension

**Files to Modify**:
- `codeintel_rev/io/faiss_manager.py`
- `codeintel_rev/io/parquet_store.py`
- `codeintel_rev/io/vllm_client.py`

---

#### Task 43: Implement Dimension Validation in Readiness
**Priority**: Critical  
**Duration**: 2 hours  
**Complexity**: Medium

**Description**:  
Add `_check_embedding_contract()` to readiness probe.

**Acceptance Criteria**:
- [ ] Probe vLLM with single vector, check dimension
- [ ] Load FAISS index, check `index.d`
- [ ] Check Parquet schema `FixedSizeList` length
- [ ] All must match `settings.embedding.vec_dim`
- [ ] Return `(valid: bool, error: str)`
- [ ] Fail startup if invalid

**Files to Modify**:
- `codeintel_rev/app/readiness.py`

**Testing**:
```python
@pytest.mark.asyncio
async def test_readiness_dimension_mismatch():
    # Create FAISS index with wrong dimension
    wrong_index = faiss.IndexFlatIP(1024)
    faiss.write_index(wrong_index, "test_index.faiss")
    
    probe = ReadinessProbe(context)
    ready = await probe.check()
    
    assert ready["ready"] is False
    assert "dimension mismatch" in ready["detail"].lower()
```

---

#### Tasks 44-45: Documentation
**Total Duration**: 1.5 hours

**Task 44**: Document embedding contract in architecture guide (1h)  
**Task 45**: Add troubleshooting guide for dimension mismatches (30min)

---

## Phase 5b: RAG Pipeline (Week 3-4, 60 hours)

### Epic 6: Answer Orchestrator (Tasks 46-60, 30 hours)

#### Task 46: Implement SearchHit Dataclass
**Priority**: High  
**Duration**: 15 minutes  
**Complexity**: Low

**Description**:  
Unified search result structure.

**Acceptance Criteria**:
- [ ] `@dataclass SearchHit` with `doc_id`, `score`, `source`
- [ ] `source: Literal["faiss", "bm25", "splade"]`
- [ ] Fields for hydrated data: `uri`, `start_line`, `end_line`, `language`, `code`

**Files to Modify**:
- `codeintel_rev/answer/orchestrator.py` (new)

---

#### Task 47: Implement AnswerEvent Dataclass
**Priority**: High  
**Duration**: 30 minutes  
**Complexity**: Low

**Description**:  
Streaming event structure.

**Acceptance Criteria**:
- [ ] `@dataclass AnswerEvent` with `type` field
- [ ] `type: Literal["token", "citation", "trace", "error"]`
- [ ] Fields for each event type

---

#### Task 48: Implement RetrievalBudget Dataclass
**Priority**: Medium  
**Duration**: 15 minutes  
**Complexity**: Low

**Description**:  
Time budgets for pipeline stages.

**Acceptance Criteria**:
- [ ] Fields for each stage (ms): `faiss`, `bm25`, `splade`, `fusion`, `hydration`, `reranking`, `synthesis`
- [ ] `total_retrieval` property (max of parallel stages)

---

#### Task 49: Implement RRF Fusion
**Priority**: Critical  
**Duration**: 2 hours  
**Complexity**: Medium

**Description**:  
Reciprocal Rank Fusion for merging retriever results.

**Acceptance Criteria**:
- [ ] `_rrf_fusion(faiss_hits, bm25_hits, k=60)` method
- [ ] Formula: `score(doc) = sum 1/(k + rank)`
- [ ] Deduplicate by `doc_id` (keep max score)
- [ ] Sort by RRF score descending

**Files to Modify**:
- `codeintel_rev/answer/orchestrator.py`

**Testing**:
```python
def test_rrf_fusion():
    faiss_hits = [SearchHit(doc_id=1, score=0.9), SearchHit(doc_id=2, score=0.8)]
    bm25_hits = [SearchHit(doc_id=2, score=15.0), SearchHit(doc_id=3, score=12.0)]
    
    orchestrator = AnswerOrchestrator(context)
    fused = orchestrator._rrf_fusion(faiss_hits, bm25_hits, k=60)
    
    # doc_id=2 appears in both (highest RRF score)
    assert fused[0].doc_id == 2
    # Scores are RRF scores, not original
    assert 0 < fused[0].score < 1
```

---

#### Task 50: Implement Parallel Retrieval with Timeouts
**Priority**: Critical  
**Duration**: 3 hours  
**Complexity**: High

**Description**:  
Launch FAISS + BM25 in parallel, handle timeouts gracefully.

**Acceptance Criteria**:
- [ ] `_retrieve_parallel(query, scope, top_n, limits)` method
- [ ] Launch FAISS and BM25 as `asyncio.create_task`
- [ ] `asyncio.wait()` with timeout (400ms)
- [ ] Cancel pending tasks on timeout
- [ ] Append timeout info to `limits` list
- [ ] RRF fuse results
- [ ] Hydrate from DuckDB with scope filtering

**Files to Modify**:
- `codeintel_rev/answer/orchestrator.py`

**Testing**:
```python
@pytest.mark.asyncio
async def test_parallel_retrieval_timeout():
    orchestrator = AnswerOrchestrator(context)
    
    # Mock FAISS to timeout
    async def slow_faiss(*args):
        await asyncio.sleep(1.0)  # Exceeds 400ms budget
        return []
    
    with mock.patch.object(orchestrator, "_retrieve_faiss", slow_faiss):
        limits = []
        hits = await orchestrator._retrieve_parallel("query", scope, 10, limits)
        
        assert "faiss_timeout" in limits
        # BM25 results still used
        assert len(hits) > 0
```

---

#### Tasks 51-60: Orchestrator Implementation
**Total Duration**: 24.5 hours

**Task 51**: Implement `_retrieve_faiss()` with embedding (1h)  
**Task 52**: Implement `_retrieve_bm25()` wrapper (30min)  
**Task 53**: Implement `_rerank_with_timeout()` using vLLM Score (2h)  
**Task 54**: Implement `_build_prompt()` with code snippets (1h)  
**Task 55**: Implement `_synthesize_streaming()` with vLLM Chat (3h)  
**Task 56**: Implement `_estimate_prompt_tokens()` heuristic (30min)  
**Task 57**: Implement `_compute_confidence()` scoring (1h)  
**Task 58**: Implement main `answer()` async generator (3h)  
**Task 59**: Wire orchestrator into MCP `answer_query` tool (2h)  
**Task 60**: End-to-end integration test (answer query → trace) (10h)

---

### Epic 7: vLLM Chat & Score Clients (Tasks 61-70, 15 hours)

#### Task 61: Implement VLLMChatClient
**Priority**: Critical  
**Duration**: 2 hours  
**Complexity**: Medium

**Description**:  
Client for vLLM Chat Completions with streaming.

**Acceptance Criteria**:
- [ ] `__init__(base_url, model_id, timeout)`
- [ ] Persistent `httpx.AsyncClient`
- [ ] `async stream_completion(messages, max_tokens, temperature, stop)`
- [ ] Parse SSE format: `data: {"choices": [{"delta": {"content": "..."}}]}`
- [ ] Yield tokens as strings
- [ ] `close()` and `__aenter__/__aexit__` for resource management

**Files to Modify**:
- `codeintel_rev/io/vllm_chat_client.py` (new)

**Testing**:
```python
@pytest.mark.asyncio
async def test_vllm_chat_streaming(mock_vllm_server):
    client = VLLMChatClient("http://localhost:8000", "llama-3.1-8b")
    
    tokens = []
    async for token in client.stream_completion(
        messages=[{"role": "user", "content": "Hi"}],
        max_tokens=50
    ):
        tokens.append(token)
    
    assert len(tokens) > 0
    assert "".join(tokens)  # Non-empty response
```

---

#### Task 62: Implement VLLMScoreClient
**Priority**: High  
**Duration**: 1 hour  
**Complexity**: Low

**Description**:  
Client for vLLM Score API reranking.

**Acceptance Criteria**:
- [ ] `rerank(query, candidates)` returns `list[float]`
- [ ] POST to `/v1/scores` with JSON payload
- [ ] Parse response `{"scores": [...]}`
- [ ] Scores in [0, 1] range

**Files to Modify**:
- `codeintel_rev/io/vllm_chat_client.py`

---

#### Tasks 63-70: vLLM Integration
**Total Duration**: 12 hours

**Task 63**: Add vLLM chat/score settings to config (30min)  
**Task 64**: Initialize chat/score clients in ApplicationContext (1h)  
**Task 65**: Write integration test with real vLLM server (3h)  
**Task 66**: Test streaming cancellation (1h)  
**Task 67**: Test reranking accuracy on benchmark (2h)  
**Task 68**: Document vLLM deployment (Docker, models) (2h)  
**Task 69**: Add vLLM health checks to readiness (1h)  
**Task 70**: Benchmark synthesis latency (TTFT, TPS) (1.5h)

---

### Epic 8: Prompt Engineering & Citations (Tasks 71-75, 10 hours)

#### Task 71: Design Prompt Template
**Priority**: High  
**Duration**: 2 hours  
**Complexity**: Medium

**Description**:  
Create context-aware prompt with code snippets.

**Acceptance Criteria**:
- [ ] Format: System message + user query + code context
- [ ] Each snippet: `[N] file.py (lines X-Y): ```lang\ncode\n``` `
- [ ] Instruction to reference snippets by number
- [ ] Token budget awareness (truncate if needed)

**Files to Modify**:
- `codeintel_rev/answer/orchestrator.py` (already in `_build_prompt`)

**Example**:
```
System: You are a code expert assistant.

User: where is auth middleware

Context:
[1] app/middleware.py (lines 10-25):
```python
class AuthMiddleware:
    async def __call__(self, request):
        # ...
```

[2] app/main.py (lines 50-55):
```python
app.add_middleware(AuthMiddleware)
```

Answer (reference snippets by number):
```

---

#### Tasks 72-75: Citations & Prompt Optimization
**Total Duration**: 8 hours

**Task 72**: Implement progressive citations emission (2h)  
**Task 73**: Test token budget enforcement (max 4096 input) (2h)  
**Task 74**: A/B test prompt variations (with/without system) (2h)  
**Task 75**: Document prompt engineering guidelines (2h)

---

### Epic 9: Answer Schemas & MCP Tool (Tasks 76-80, 5 hours)

#### Task 76: Define AnswerQueryIn Schema
**Priority**: High  
**Duration**: 30 minutes  
**Complexity**: Low

**Description**:  
MCP tool input schema.

**Acceptance Criteria**:
- [ ] `TypedDict AnswerQueryIn` with fields: `query`, `scope`, `top_k`, `rerank_top_n`
- [ ] Documented in `mcp_server/schemas.py`

---

#### Tasks 77-80: MCP Integration
**Total Duration**: 4.5 hours

**Task 77**: Define AnswerEnvelope output schema (30min)  
**Task 78**: Register `answer_query` tool in `mcp_server/server.py` (1h)  
**Task 79**: Write adapter `mcp_server/adapters/answers.py` (2h)  
**Task 80**: Test MCP tool end-to-end (1h)

---

## Phase 5c: Observability & Testing (Week 5-6, 40 hours)

### Epic 10: Answer Trace Framework (Tasks 81-90, 15 hours)

#### Task 81: Implement AnswerTrace Dataclass
**Priority**: High  
**Duration**: 1 hour  
**Complexity**: Low

**Description**:  
Complete trace structure with all metrics.

**Acceptance Criteria**:
- [ ] `@dataclass AnswerTrace` with 25+ fields
- [ ] Identity: `trace_id`, `session_id`, `timestamp`
- [ ] Retrieval: `faiss_latency_ms`, `bm25_latency_ms`, `top_k_doc_ids`
- [ ] Reranking: `rerank_latency_ms`, `reranked_doc_ids`
- [ ] Synthesis: `tokens_in`, `tokens_out`, `ttft_ms`, `tps`
- [ ] Quality: `confidence`, `limits`

**Files to Modify**:
- `codeintel_rev/observability/answer_trace.py` (new)

---

#### Task 82: Implement AnswerTracer with Parquet Batching
**Priority**: High  
**Duration**: 2 hours  
**Complexity**: Medium

**Description**:  
Trace collector with batched Parquet writes.

**Acceptance Criteria**:
- [ ] `emit(trace)` adds to batch
- [ ] `_flush()` writes batch to daily Parquet file
- [ ] Batch size configurable (default 100)
- [ ] Append to existing file if date matches
- [ ] `close()` flushes remaining batch

**Files to Modify**:
- `codeintel_rev/observability/answer_trace.py`

---

#### Tasks 83-90: Tracing Integration
**Total Duration**: 12 hours

**Task 83**: Emit traces from orchestrator (2h)  
**Task 84**: Stream traces via SSE to client (2h)  
**Task 85**: Write DuckDB analysis queries (example notebook) (2h)  
**Task 86**: Add trace metrics to Prometheus (1h)  
**Task 87**: Test trace batching (1000 traces) (2h)  
**Task 88**: Document trace schema and analysis (2h)  
**Task 89**: Create Grafana dashboard for traces (1h)

---

### Epic 11: Prometheus Metrics (Tasks 91-95, 10 hours)

#### Task 91: Define Metrics Catalog
**Priority**: High  
**Duration**: 1 hour  
**Complexity**: Low

**Description**:  
Define 20+ metrics for answer pipeline.

**Acceptance Criteria**:
- [ ] Counters: `codeintel_answers_total`, `codeintel_retrieval_timeouts_total`
- [ ] Histograms: `codeintel_answer_latency_seconds`, `codeintel_tokens_generated`
- [ ] Gauges: `codeintel_faiss_index_size`, `codeintel_scope_registry_size`

**Files to Modify**:
- `codeintel_rev/observability/metrics.py` (new)

---

#### Tasks 92-95: Metrics Implementation
**Total Duration**: 9 hours

**Task 92**: Instrument orchestrator with metrics (3h)  
**Task 93**: Add `/metrics` endpoint to FastAPI (1h)  
**Task 94**: Write Prometheus scrape config (1h)  
**Task 95**: Create Grafana dashboard (2h)  
**Task 96**: Document metrics catalog (2h)

---

### Epic 12: Integration Testing (Tasks 96-105, 15 hours)

#### Task 96: Write End-to-End Answer Test
**Priority**: Critical  
**Duration**: 3 hours  
**Complexity**: High

**Description**:  
Full pipeline test: query → retrieval → synthesis → trace.

**Acceptance Criteria**:
- [ ] Start test vLLM server (Docker Compose)
- [ ] Index test corpus (100 chunks)
- [ ] Call `answer_query` with test query
- [ ] Assert answer contains expected content
- [ ] Assert citations reference correct files
- [ ] Assert trace has all metrics populated

**Files to Modify**:
- `tests/answer/test_orchestrator_e2e.py` (new)

---

#### Tasks 97-105: Testing Suite
**Total Duration**: 12 hours

**Task 97**: Test FAISS timeout fallback (BM25 only) (1h)  
**Task 98**: Test synthesis timeout fallback (retrieval-only) (1h)  
**Task 99**: Test cross-worker scope coherence (Redis) (2h)  
**Task 100**: Test DuckDB concurrent queries (100 parallel) (1h)  
**Task 101**: Test FAISS incremental → compact → search (2h)  
**Task 102**: Load test: 1000 QPS sustained (vegeta) (2h)  
**Task 103**: Spike test: 5000 QPS burst (1h)  
**Task 104**: Write performance benchmarks (recall, latency) (1h)  
**Task 105**: Document testing strategy and commands (1h)

---

## Summary

### Phase 5a: Foundations (50 hours)
- ✅ **Tasks 1-45**: Redis scope, DuckDB thread-safety, FAISS dual-index, BM25, embedding contract
- ✅ **Deliverables**: Cross-worker coherence, thread-safe queries, incremental updates, hybrid retrieval

### Phase 5b: RAG Pipeline (60 hours)
- ✅ **Tasks 46-80**: Answer orchestrator, vLLM clients, prompt engineering, MCP integration
- ✅ **Deliverables**: End-to-end RAG, streaming synthesis, reranking, citations

### Phase 5c: Observability & Testing (40 hours)
- ✅ **Tasks 81-105**: AnswerTrace, Prometheus metrics, integration tests, load tests
- ✅ **Deliverables**: Full observability, performance benchmarks, production readiness

---

**Total**: 85 tasks, 150 hours, 4-6 weeks

