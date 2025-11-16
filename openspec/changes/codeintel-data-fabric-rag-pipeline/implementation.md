# Phase 5: Implementation Code Examples

**Purpose**: Production-ready code for 6 core modules that implement the data fabric and answer pipeline.

**Status**: Reference implementation (adapt to your context)

---

## 1. Answer Orchestrator (`codeintel_rev/pipelines/answerflow.py`)

**Purpose**: Pure orchestrator for retrieve → hydrate → rerank → synthesize with explicit budgets and fallbacks.

```python
"""Answer pipeline orchestrator with robust fallback semantics."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator

import structlog

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext
    from codeintel_rev.mcp_server.schemas import ScopeIn, Finding, AnswerEnvelope

logger = structlog.get_logger()


@dataclass
class AnswerPlan:
    """Execution plan for answer generation."""
    retrieval: str  # "hybrid-rrf" | "faiss-only" | "text-only"
    k_faiss: int
    k_text: int
    nprobe: int
    rerank_k: int
    synth_tokens: int


@dataclass
class AnswerLimits:
    """Degradations and fallbacks encountered."""
    items: list[str]


class AnswerOrchestrator:
    """Orchestrate end-to-end answer generation with budgets and fallbacks."""

    def __init__(self, context: ApplicationContext):
        self.context = context
        self.faiss_manager = context.faiss_manager
        self.duckdb_catalog = context.duckdb_catalog
        self.vllm_client = context.vllm_client
        self.bm25_enabled = context.settings.bm25.enabled if hasattr(context.settings, "bm25") else False

    async def answer(
        self,
        query: str,
        scope: ScopeIn,
        top_k: int = 10,
        rerank_top_n: int = 50,
        time_budget_ms: int = 2000,
    ) -> AnswerEnvelope:
        """
        Generate answer with citations from codebase.
        
        Parameters
        ----------
        query : str
            User question
        scope : ScopeIn
            Scope filters (paths, languages)
        top_k : int
            Final number of findings
        rerank_top_n : int
            Candidates to rerank before trimming to top_k
        time_budget_ms : int
            Total time budget (retrieval + synthesis)
        
        Returns
        -------
        AnswerEnvelope
            Answer with snippets, plan, limits, confidence
        """
        log = logger.bind(query=query, scope=scope)
        limits = AnswerLimits(items=[])
        
        # 1. Embed query
        try:
            embeddings = await asyncio.to_thread(
                self.vllm_client.embed_batch, [query]
            )
            query_vec = embeddings[0]
        except Exception as e:
            log.warning("embedding_failed", error=str(e))
            limits.items.append("embedding_failed: using text-only retrieval")
            query_vec = None

        # 2. Parallel retrieval (FAISS + BM25 if enabled)
        retrieval_start = asyncio.get_event_loop().time()
        retrieval_budget_ms = time_budget_ms * 0.4  # 40% of budget
        
        tasks = []
        if query_vec is not None:
            tasks.append(self._faiss_retrieve(query_vec, rerank_top_n, scope))
        if self.bm25_enabled:
            tasks.append(self._bm25_retrieve(query, rerank_top_n, scope))
        
        if not tasks:
            # Fallback: pure text search via DuckDB LIKE
            log.warning("no_retrieval_available")
            limits.items.append("no_retrieval: falling back to text scan")
            findings = await self._text_scan_fallback(query, scope, top_k)
            return self._build_envelope(
                answer=None,
                findings=findings,
                plan=AnswerPlan("text-only", 0, 0, 0, 0, 0),
                limits=limits,
                confidence=0.3,
            )
        
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=retrieval_budget_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            log.warning("retrieval_timeout")
            limits.items.append("retrieval_timeout: partial results")
            results = [[] for _ in tasks]  # Empty results
        
        retrieval_elapsed = (asyncio.get_event_loop().time() - retrieval_start) * 1000
        
        # 3. Fuse results (RRF)
        faiss_hits = results[0] if len(results) > 0 and not isinstance(results[0], Exception) else []
        bm25_hits = results[1] if len(results) > 1 and not isinstance(results[1], Exception) else []
        
        fused_ids = self._rrf_fusion(faiss_hits, bm25_hits, k=rerank_top_n)
        
        # 4. Hydrate from DuckDB
        findings = await self._hydrate(fused_ids, scope)
        
        # 5. Rerank (optional, budget permitting)
        synth_budget_ms = time_budget_ms - retrieval_elapsed
        if synth_budget_ms > 500 and len(findings) > top_k:
            try:
                findings = await self._rerank(query, findings, top_k, budget_ms=300)
            except Exception as e:
                log.warning("rerank_failed", error=str(e))
                limits.items.append("rerank_failed: using fusion order")
                findings = findings[:top_k]
        else:
            findings = findings[:top_k]
        
        # 6. Synthesize answer
        if synth_budget_ms > 200:
            try:
                answer = await self._synthesize(query, findings, max_tokens=300)
            except Exception as e:
                log.warning("synthesis_failed", error=str(e))
                limits.items.append("synthesis_failed: returning retrieval-only")
                answer = None
        else:
            limits.items.append("synthesis_skipped: time budget exhausted")
            answer = None
        
        # 7. Build response
        plan = AnswerPlan(
            retrieval="hybrid-rrf" if self.bm25_enabled else "faiss-only",
            k_faiss=rerank_top_n if query_vec else 0,
            k_text=rerank_top_n if self.bm25_enabled else 0,
            nprobe=64,
            rerank_k=top_k,
            synth_tokens=300,
        )
        
        confidence = 0.8 if answer else (0.5 if findings else 0.0)
        
        return self._build_envelope(answer, findings, plan, limits, confidence)

    async def _faiss_retrieve(self, query_vec, k: int, scope: ScopeIn) -> list[int]:
        """Retrieve from FAISS (handles CPU runtime tuning internally)."""
        # FAISSManager.search already handles loading and tuning
        results = await asyncio.to_thread(
            self.faiss_manager.search, query_vec, k=k, nprobe=64
        )
        return [hit.id for hit in results]

    async def _bm25_retrieve(self, query: str, k: int, scope: ScopeIn) -> list[int]:
        """Retrieve from BM25 (pyserini/Lucene)."""
        # TODO: Implement BM25Searcher wrapper
        # from codeintel_rev.retrieval.bm25 import BM25Searcher
        # searcher = BM25Searcher(self.context.settings.bm25.index_dir)
        # return searcher.search(query, k)
        return []  # Placeholder

    def _rrf_fusion(self, faiss_ids: list[int], bm25_ids: list[int], k: int) -> list[int]:
        """Reciprocal Rank Fusion: merge ranked lists."""
        scores = {}
        for rank, doc_id in enumerate(faiss_ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (60 + rank)
        for rank, doc_id in enumerate(bm25_ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (60 + rank)
        
        return sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:k]

    async def _hydrate(self, doc_ids: list[int], scope: ScopeIn) -> list[Finding]:
        """Hydrate chunk metadata from DuckDB with scope filters."""
        if not doc_ids:
            return []
        
        rows = await asyncio.to_thread(
            self.duckdb_catalog.query_by_ids,
            doc_ids,
            include_globs=scope.get("include_globs"),
            exclude_globs=scope.get("exclude_globs"),
            languages=scope.get("languages"),
        )
        
        findings = []
        for row in rows:
            findings.append({
                "uri": row["uri"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "language": row.get("language", "unknown"),
                "code": row.get("text", ""),
                "score": 1.0,  # TODO: Preserve RRF score
            })
        return findings

    async def _rerank(self, query: str, findings: list[Finding], k: int, budget_ms: int) -> list[Finding]:
        """Rerank findings using vLLM Score API (optional)."""
        # TODO: Implement VLLMScoreClient
        # from codeintel_rev.io.vllm_chat import VLLMScoreClient
        # score_client = VLLMScoreClient(self.context.settings.vllm.base_url)
        # candidates = [f["code"] for f in findings]
        # scores = await score_client.rerank(query, candidates)
        # for finding, score in zip(findings, scores):
        #     finding["score"] = score
        # return sorted(findings, key=lambda x: x["score"], reverse=True)[:k]
        return findings[:k]  # Placeholder: no rerank

    async def _synthesize(self, query: str, findings: list[Finding], max_tokens: int) -> str:
        """Synthesize answer from findings using vLLM chat."""
        # Build prompt with citations
        context_lines = []
        for i, finding in enumerate(findings, start=1):
            context_lines.append(
                f"[{i}] {finding['uri']}:{finding['start_line']}-{finding['end_line']}\n{finding['code']}\n"
            )
        context = "\n".join(context_lines)
        
        prompt = f"""Answer the following question using only the provided code snippets. Cite sources using [N] notation.

Question: {query}

Code snippets:
{context}

Answer:"""
        
        # TODO: Implement VLLMChatClient
        # from codeintel_rev.io.vllm_chat import VLLMChatClient
        # chat_client = VLLMChatClient(self.context.settings.vllm.base_url)
        # return await chat_client.complete(prompt, max_tokens=max_tokens, temperature=0.2)
        return None  # Placeholder

    async def _text_scan_fallback(self, query: str, scope: ScopeIn, k: int) -> list[Finding]:
        """Fallback: DuckDB LIKE scan."""
        # TODO: Implement text scan in DuckDBCatalog
        return []

    def _build_envelope(
        self,
        answer: str | None,
        findings: list[Finding],
        plan: AnswerPlan,
        limits: AnswerLimits,
        confidence: float,
    ) -> AnswerEnvelope:
        """Build final answer envelope."""
        return {
            "answer": answer,
            "snippets": findings,
            "plan": {
                "retrieval": plan.retrieval,
                "k_faiss": plan.k_faiss,
                "k_text": plan.k_text,
                "nprobe": plan.nprobe,
                "rerank_k": plan.rerank_k,
                "synth_tokens": plan.synth_tokens,
            },
            "limits": limits.items,
            "confidence": confidence,
        }
```

---

## 2. vLLM Chat/Score Clients (`codeintel_rev/io/vllm_chat.py`)

**Purpose**: OpenAI-compatible clients for chat completions and reranking (Score API).

```python
"""vLLM chat and score clients."""
from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator

import httpx
import msgspec
import structlog

if TYPE_CHECKING:
    from codeintel_rev.config.settings import VLLMConfig

logger = structlog.get_logger()


class ChatMessage(msgspec.Struct):
    """OpenAI chat message format."""
    role: str
    content: str


class ChatCompletionRequest(msgspec.Struct):
    """OpenAI chat completion request."""
    model: str
    messages: list[ChatMessage]
    max_tokens: int = 300
    temperature: float = 0.2
    stream: bool = False


class VLLMChatClient:
    """Client for vLLM /v1/chat/completions endpoint."""

    def __init__(self, base_url: str, model: str, timeout_seconds: int = 30):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.AsyncClient(timeout=timeout_seconds)

    async def complete(self, prompt: str, max_tokens: int = 300, temperature: float = 0.2) -> str:
        """
        Generate completion from prompt.
        
        Parameters
        ----------
        prompt : str
            User prompt
        max_tokens : int
            Max tokens to generate
        temperature : float
            Sampling temperature
        
        Returns
        -------
        str
            Generated text
        """
        messages = [ChatMessage(role="user", content=prompt)]
        request = ChatCompletionRequest(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )
        
        response = await self.client.post(
            f"{self.base_url}/v1/chat/completions",
            json=msgspec.json.decode(msgspec.json.encode(request)),
        )
        response.raise_for_status()
        
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def stream_completion(
        self,
        prompt: str,
        max_tokens: int = 300,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        """
        Stream completion tokens.
        
        Parameters
        ----------
        prompt : str
            User prompt
        max_tokens : int
            Max tokens to generate
        temperature : float
            Sampling temperature
        
        Yields
        ------
        str
            Token chunks
        """
        messages = [ChatMessage(role="user", content=prompt)]
        request = ChatCompletionRequest(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        
        async with self.client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            json=msgspec.json.decode(msgspec.json.encode(request)),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        data = msgspec.json.decode(chunk)
                        delta = data["choices"][0]["delta"]
                        if "content" in delta:
                            yield delta["content"]
                    except Exception as e:
                        logger.warning("sse_parse_error", line=line, error=str(e))

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()


class VLLMScoreClient:
    """Client for vLLM /v1/scores endpoint (cross-encoder reranking)."""

    def __init__(self, base_url: str, model: str, timeout_seconds: int = 10):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.AsyncClient(timeout=timeout_seconds)

    async def rerank(self, query: str, candidates: list[str]) -> list[float]:
        """
        Rerank candidates using cross-encoder.
        
        Parameters
        ----------
        query : str
            Query text
        candidates : list[str]
            Candidate documents
        
        Returns
        -------
        list[float]
            Relevance scores (same order as input)
        """
        if not candidates:
            return []
        
        response = await self.client.post(
            f"{self.base_url}/v1/scores",
            json={
                "model": self.model,
                "query": query,
                "documents": candidates,
            },
        )
        response.raise_for_status()
        
        data = response.json()
        return data["scores"]

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
```

---

## 3. MCP Adapter (`codeintel_rev/mcp_server/adapters/answers.py`)

**Purpose**: MCP tool adapter that invokes the orchestrator.

```python
"""MCP adapter for answer_query tool."""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext
    from codeintel_rev.mcp_server.schemas import ScopeIn, AnswerEnvelope

logger = structlog.get_logger()


async def answer_query(
    context: ApplicationContext,
    question: str,
    limit: int = 10,
    nprobe: int = 64,
    scope: ScopeIn | None = None,
) -> AnswerEnvelope:
    """
    Generate answer with citations from codebase.
    
    Parameters
    ----------
    context : ApplicationContext
        Application context with clients
    question : str
        User question
    limit : int
        Number of findings to return
    nprobe : int
        FAISS nprobe parameter
    scope : ScopeIn | None
        Optional scope filters
    
    Returns
    -------
    AnswerEnvelope
        Answer with snippets, plan, limits, confidence
    """
    from codeintel_rev.pipelines.answerflow import AnswerOrchestrator
    
    log = logger.bind(question=question, limit=limit)
    
    # Default scope
    if scope is None:
        scope = {
            "repos": [],
            "branches": [],
            "include_globs": [],
            "exclude_globs": [],
            "languages": [],
        }
    
    # Instantiate orchestrator
    orchestrator = AnswerOrchestrator(context)
    
    # Run answer pipeline
    try:
        envelope = await orchestrator.answer(
            query=question,
            scope=scope,
            top_k=limit,
            rerank_top_n=limit * 5,
            time_budget_ms=2000,
        )
        log.info("answer_generated", confidence=envelope["confidence"])
        return envelope
    except Exception as e:
        log.error("answer_failed", error=str(e))
        # Return degraded envelope
        return {
            "answer": None,
            "snippets": [],
            "plan": {"retrieval": "failed", "k_faiss": 0, "k_text": 0, "nprobe": 0, "rerank_k": 0, "synth_tokens": 0},
            "limits": [f"answer_failed: {str(e)}"],
            "confidence": 0.0,
        }
```

---

## 4. Redis Scope Store (`codeintel_rev/app/scope_store.py`)

**Purpose**: L1/L2 caching for session scope with single-flight coalescing.

```python
"""Redis-backed scope store with L1/L2 caching."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import msgspec
import redis.asyncio as redis
import structlog

if TYPE_CHECKING:
    from codeintel_rev.mcp_server.schemas import ScopeIn

logger = structlog.get_logger()


class LRUCache:
    """Simple in-memory LRU cache."""

    def __init__(self, maxsize: int = 256, ttl_seconds: int = 300):
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[ScopeIn, float]] = {}

    def get(self, key: str) -> ScopeIn | None:
        """Get from cache if not expired."""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self.ttl_seconds:
                return value
            else:
                del self._cache[key]
        return None

    def set(self, key: str, value: ScopeIn):
        """Set in cache with timestamp."""
        if len(self._cache) >= self.maxsize:
            # Evict oldest
            oldest = min(self._cache.items(), key=lambda x: x[1][1])
            del self._cache[oldest[0]]
        self._cache[key] = (value, time.time())


class SingleFlight:
    """Deduplicate concurrent calls to same key."""

    def __init__(self):
        self._inflight: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def do(self, key: str, fn: callable) -> any:
        """Execute fn once for concurrent calls with same key."""
        async with self._lock:
            if key in self._inflight:
                return await self._inflight[key]
            
            future = asyncio.create_task(fn())
            self._inflight[key] = future
        
        try:
            result = await future
            return result
        finally:
            async with self._lock:
                if key in self._inflight:
                    del self._inflight[key]


class ScopeStore:
    """Thread-safe scope store with L1 (LRU) and L2 (Redis) caching."""

    def __init__(self, redis_url: str, ttl_seconds: int = 3600):
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self._l1 = LRUCache(maxsize=256, ttl_seconds=300)
        self._redis: redis.Redis | None = None
        self._flight = SingleFlight()

    async def connect(self):
        """Connect to Redis."""
        self._redis = await redis.from_url(self.redis_url, decode_responses=True)

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()

    async def get(self, session_id: str) -> ScopeIn | None:
        """
        Get scope by session ID.
        
        L1 (in-memory) → L2 (Redis) with single-flight coalescing.
        
        Parameters
        ----------
        session_id : str
            Session identifier
        
        Returns
        -------
        ScopeIn | None
            Scope if found, else None
        """
        # L1 check
        if scope := self._l1.get(session_id):
            logger.debug("scope_l1_hit", session_id=session_id)
            return scope
        
        # L2 check (with single-flight)
        async def fetch_from_redis():
            if self._redis is None:
                return None
            
            try:
                data = await self._redis.get(f"scope:{session_id}")
                if data:
                    scope = msgspec.json.decode(data)
                    self._l1.set(session_id, scope)
                    logger.debug("scope_l2_hit", session_id=session_id)
                    return scope
            except Exception as e:
                logger.warning("redis_get_failed", session_id=session_id, error=str(e))
            return None
        
        return await self._flight.do(session_id, fetch_from_redis)

    async def set(self, session_id: str, scope: ScopeIn):
        """
        Set scope for session ID.
        
        Writes to L1 (in-memory) and L2 (Redis).
        
        Parameters
        ----------
        session_id : str
            Session identifier
        scope : ScopeIn
            Scope to store
        """
        # L1 write
        self._l1.set(session_id, scope)
        
        # L2 write
        if self._redis:
            try:
                data = msgspec.json.encode(scope)
                await self._redis.setex(
                    f"scope:{session_id}",
                    self.ttl_seconds,
                    data,
                )
                logger.debug("scope_l2_write", session_id=session_id)
            except Exception as e:
                logger.warning("redis_set_failed", session_id=session_id, error=str(e))

    async def delete(self, session_id: str):
        """Delete scope for session ID."""
        # L1 delete
        if session_id in self._l1._cache:
            del self._l1._cache[session_id]
        
        # L2 delete
        if self._redis:
            try:
                await self._redis.delete(f"scope:{session_id}")
            except Exception as e:
                logger.warning("redis_delete_failed", session_id=session_id, error=str(e))
```

---

## 5. Thread-Safe DuckDB Manager (`codeintel_rev/io/duckdb_manager.py`)

**Purpose**: Per-request DuckDB connections with object cache and parameterized SQL.

```python
"""Thread-safe DuckDB manager with per-request connections."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import duckdb
import structlog

if TYPE_CHECKING:
    from codeintel_rev.config.settings import DuckDBConfig

logger = structlog.get_logger()


class DuckDBManager:
    """
    Thread-safe DuckDB manager.
    
    Provides per-request connections to avoid thread-safety issues.
    Enables object cache and sets thread budget on each connection.
    """

    def __init__(self, db_path: Path, config: DuckDBConfig):
        self.db_path = db_path
        self.config = config
        self._ensure_schema()

    def _ensure_schema(self):
        """Ensure chunks view/table exists (idempotent)."""
        with self.connection() as conn:
            # Create view over Parquet files
            conn.execute("""
                CREATE OR REPLACE VIEW chunks AS
                SELECT * FROM read_parquet('vectors/*.parquet')
            """)
            
            # Optionally materialize for faster queries
            if self.config.materialize:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS chunks_materialized AS
                    SELECT * FROM chunks
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chunks_uri
                    ON chunks_materialized(uri)
                """)

    @contextmanager
    def connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """
        Get per-request connection with optimizations.
        
        Yields
        ------
        duckdb.DuckDBPyConnection
            Connection with object cache enabled
        """
        conn = duckdb.connect(str(self.db_path))
        try:
            # Enable object cache for repeated scans
            conn.execute("PRAGMA enable_object_cache")
            
            # Set thread budget
            conn.execute(f"SET threads = {self.config.threads}")
            
            yield conn
        finally:
            conn.close()

    def query_by_ids(
        self,
        ids: list[int],
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        languages: list[str] | None = None,
    ) -> list[dict]:
        """
        Query chunks by IDs with optional scope filters.
        
        Parameters
        ----------
        ids : list[int]
            Chunk IDs
        include_globs : list[str] | None
            Include path patterns (e.g., ["src/**"])
        exclude_globs : list[str] | None
            Exclude path patterns (e.g., ["**/*.test.py"])
        languages : list[str] | None
            Language filters (e.g., ["python", "typescript"])
        
        Returns
        -------
        list[dict]
            Chunk records
        """
        if not ids:
            return []
        
        with self.connection() as conn:
            # Build WHERE clause with parameterized SQL
            where_clauses = ["id = ANY($ids)"]
            params = {"ids": ids}
            
            # Add glob filters (simple LIKE conversion for common patterns)
            if include_globs:
                include_conds = []
                for i, glob in enumerate(include_globs):
                    like_pattern = glob.replace("**", "%").replace("*", "%")
                    include_conds.append(f"uri LIKE ${f'inc{i}'}")
                    params[f"inc{i}"] = like_pattern
                where_clauses.append(f"({' OR '.join(include_conds)})")
            
            if exclude_globs:
                exclude_conds = []
                for i, glob in enumerate(exclude_globs):
                    like_pattern = glob.replace("**", "%").replace("*", "%")
                    exclude_conds.append(f"uri NOT LIKE ${f'exc{i}'}")
                    params[f"exc{i}"] = like_pattern
                where_clauses.append(f"({' AND '.join(exclude_conds)})")
            
            # Add language filter
            if languages:
                where_clauses.append("language = ANY($languages)")
                params["languages"] = languages
            
            query = f"""
                SELECT id, uri, start_line, end_line, language, text, embedding
                FROM chunks
                WHERE {' AND '.join(where_clauses)}
            """
            
            result = conn.execute(query, params).fetchall()
            
            # Convert to dicts
            columns = ["id", "uri", "start_line", "end_line", "language", "text", "embedding"]
            return [dict(zip(columns, row)) for row in result]
```

---

## 6. FAISS Dual-Index (`codeintel_rev/io/faiss_dual_index.py`)

This module was removed during the CPU-only migration; see the design document for
historical context. No runtime code remains for this component.

---
---

## Integration Notes

### Wiring in `app/main.py`

```python
# During lifespan startup:
context = await ApplicationContext.create()

# Initialize scope store
context.scope_store = ScopeStore(context.settings.redis.url)
await context.scope_store.connect()

# Initialize FAISS dual-index
context.faiss_dual_index = FAISSDualIndex(
    index_dir=context.settings.index.index_dir,
    config=context.settings.faiss,
)
context.faiss_dual_index.ensure_ready()

# Initialize DuckDB manager
context.duckdb_manager = DuckDBManager(
    db_path=context.paths.duckdb_path,
    config=context.settings.duckdb,
)

# Initialize vLLM clients
context.vllm_chat_client = VLLMChatClient(
    base_url=context.settings.vllm.base_url,
    model=context.settings.vllm.chat_model,
)
context.vllm_score_client = VLLMScoreClient(
    base_url=context.settings.vllm.base_url,
    model=context.settings.vllm.score_model,
)
```

### MCP Tool Registration in `mcp_server/server.py`

```python
@mcp.tool()
async def answer_query(
    request: Request,
    question: str,
    limit: int = 10,
    nprobe: int = 64,
    scope: dict | None = None,
) -> dict:
    """Generate answer with citations from codebase."""
    context = _get_context(request)
    from codeintel_rev.mcp_server.adapters.answers import answer_query as answer_adapter
    return await answer_adapter(context, question, limit, nprobe, scope)
```

---

## Testing Strategy

### Unit Tests (Per Module)

```bash
pytest tests/unit/test_answerflow.py -v
pytest tests/unit/test_vllm_chat.py -v
pytest tests/unit/test_scope_store.py -v
pytest tests/unit/test_duckdb_manager.py -v
pytest tests/unit/test_faiss_dual_index.py -v
```

### Integration Test (End-to-End)

```python
@pytest.mark.integration
async def test_answer_query_e2e(context: ApplicationContext):
    """Test full answer pipeline."""
    from codeintel_rev.mcp_server.adapters.answers import answer_query
    
    envelope = await answer_query(
        context,
        question="where is auth middleware",
        limit=5,
        scope={"include_globs": ["src/**"], "languages": ["python"]},
    )
    
    assert envelope["confidence"] > 0.5
    assert len(envelope["snippets"]) > 0
    assert envelope["answer"] is not None or len(envelope["limits"]) > 0
```

---

## Performance Targets

| Module | Metric | Target | Notes |
|--------|--------|--------|-------|
| `answerflow.py` | p95 latency | <2s | Full pipeline |
| `vllm_chat.py` | TTFT | <800ms | Time to first token |
| `scope_store.py` | L1 hit rate | >90% | In-memory cache |
| `duckdb_manager.py` | Query latency | <150ms p95 | 100 chunk hydration |
| `faiss_dual_index.py` | CPU search | <50ms p95 | 10K index, k=50 |

---

**Version**: 1.0.0 (2025-11-08)  
**Status**: 🟢 Ready for Adaptation

Adapt these implementations to your specific `ApplicationContext`, error handling patterns, and logging framework.
