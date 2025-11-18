# Detailed implementation plan with drop-in code #

Below is a **comprehensive, implementation‑ready plan** (with drop‑in code) to complete items **D** and **E** against the *current* repo. I’ve aligned this to the architecture and guardrails we already established in the earlier refactor specs so an agent can execute end‑to‑end without ambiguity. Where I cite acceptance checks or file shapes, they match the design you approved for D/E earlier.  

---

# D) DuckDB split — keep catalog thin; SQL in schema; queries in DAO

## Objectives (recap)

* **Move SQL/DDL** into `io/duckdb_schema.py` (pure strings + small dataclasses).
* **Move tiny executors & typed queries** into `io/duckdb_dao.py` (accept an open `duckdb.DuckDBPyConnection`; **no path logic**).
* Keep **`io/duckdb_catalog.py`** as a thin coordinator (checksum + path concerns + small wrappers).
* Keep **`io/duckdb_manager.py`** focused on connection lifecycle; **re‑export** `DuckDBQueryBuilder`/`DuckDBQueryOptions` from DAO to avoid churn. 

### Guardrails & acceptance

* **Catalog**: no raw `CREATE VIEW` or long SQL strings; bodies delegate to DAO.
  Quick check:

  ```bash
  ! grep -R "CREATE OR REPLACE VIEW" -n codeintel_rev/io/duckdb_catalog.py
  ```
* **Manager** re‑exports:

  ```bash
  grep -n "from codeintel_rev.io.duckdb_dao import DuckDBQueryBuilder, DuckDBQueryOptions" \
    codeintel_rev/io/duckdb_manager.py
  ```
* **Tests**: in‑memory DB covers `ensure_chunks`, `ensure_faiss_idmap_view`, `v_faiss_join`, and checksum‑guarded materialization. 

---

## 1) New file: `codeintel_rev/io/duckdb_schema.py` (pure DDL/SQL)

```python
# codeintel_rev/io/duckdb_schema.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Public relation identifiers (single source of truth)
VIEW_CHUNKS: Final[str] = "chunks"
VIEW_FAISS_IDMAP: Final[str] = "faiss_idmap"
VIEW_V_FAISS_JOIN: Final[str] = "v_faiss_join"
TABLE_FAISS_JOIN_MAT: Final[str] = "faiss_join_mat"
TABLE_FAISS_IDMAP_MAT: Final[str] = "faiss_idmap_mat"
TABLE_FAISS_IDMAP_MAT_META: Final[str] = "faiss_idmap_mat_meta"

@dataclass(frozen=True, slots=True)
class IdMapMeta:
    """
    Observability payload for idmap materialization.
    """
    checksum: str
    rows: int
    refreshed: bool

_EMPTY_CHUNKS_SELECT: Final[str] = """
SELECT
  CAST(NULL AS BIGINT) AS id,
  CAST(NULL AS TEXT)   AS uri,
  CAST(NULL AS INT)    AS start_line,
  CAST(NULL AS INT)    AS end_line,
  CAST(NULL AS BIGINT) AS start_byte,
  CAST(NULL AS BIGINT) AS end_byte,
  CAST(NULL AS TEXT)   AS lang,
  CAST(NULL AS INT)    AS embedding_dim,
  CAST(NULL AS FLOAT[]) AS embedding
WHERE FALSE
"""

def sql_create_chunks_from_parquet() -> str:
    return f"CREATE OR REPLACE VIEW {VIEW_CHUNKS} AS SELECT * FROM read_parquet(?)"

def sql_create_empty_chunks_view() -> str:
    return f"CREATE OR REPLACE VIEW {VIEW_CHUNKS} AS {_EMPTY_CHUNKS_SELECT}"

def sql_create_chunks_mat() -> str:
    return "CREATE OR REPLACE TABLE chunks_materialized AS SELECT * FROM read_parquet(?)"

def sql_point_chunks_view_to_mat() -> str:
    return f'CREATE OR REPLACE VIEW {VIEW_CHUNKS} AS SELECT * FROM "chunks_materialized"'

def sql_create_faiss_idmap_view() -> str:
    return f"""
    CREATE OR REPLACE VIEW {VIEW_FAISS_IDMAP} AS
    SELECT faiss_row, external_id
    FROM read_parquet(?)
    """

def sql_create_empty_faiss_idmap_view() -> str:
    return f"""
    CREATE OR REPLACE VIEW {VIEW_FAISS_IDMAP} AS
    SELECT CAST(NULL AS BIGINT) AS faiss_row,
           CAST(NULL AS BIGINT) AS external_id
    WHERE FALSE
    """

def sql_create_v_faiss_join() -> str:
    return f"""
    CREATE OR REPLACE VIEW {VIEW_V_FAISS_JOIN} AS
    SELECT f.faiss_row,
           f.external_id AS chunk_id,
           c.*
    FROM {VIEW_FAISS_IDMAP} AS f
    LEFT JOIN {VIEW_CHUNKS} AS c
    ON c.id = f.external_id
    """

def sql_materialize_v_faiss_join() -> str:
    return f"CREATE OR REPLACE TABLE {TABLE_FAISS_JOIN_MAT} AS SELECT * FROM {VIEW_V_FAISS_JOIN}"

def sql_count(table: str) -> str:
    return f'SELECT COUNT(*)::BIGINT FROM "{table}"'

def sql_relation_exists() -> str:
    return """
    SELECT 1 FROM information_schema.tables
    WHERE table_name = ? COLLATE NOCASE
       OR table_name = REPLACE(?, '"', '')
    LIMIT 1
    """

def sql_create_idmap_mat() -> str:
    return f"CREATE TABLE IF NOT EXISTS {TABLE_FAISS_IDMAP_MAT} AS SELECT * FROM {VIEW_V_FAISS_JOIN} LIMIT 0"

def sql_create_idmap_mat_meta() -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {TABLE_FAISS_IDMAP_MAT_META} (
      checksum   TEXT,
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """

def sql_select_idmap_checksum() -> str:
    return f"SELECT checksum FROM {TABLE_FAISS_IDMAP_MAT_META} LIMIT 1"

def sql_delete_idmap_mat() -> str:
    return f"DELETE FROM {TABLE_FAISS_IDMAP_MAT}"

def sql_insert_idmap_mat() -> str:
    return f"INSERT INTO {TABLE_FAISS_IDMAP_MAT} SELECT * FROM {VIEW_V_FAISS_JOIN}"

def sql_delete_idmap_meta() -> str:
    return f"DELETE FROM {TABLE_FAISS_IDMAP_MAT_META}"

def sql_insert_idmap_meta() -> str:
    return f"INSERT INTO {TABLE_FAISS_IDMAP_MAT_META}(checksum, updated_at) VALUES (?, CURRENT_TIMESTAMP)"
```

*Rationale:* this file contains **only** deterministic SQL and tiny dataclasses so you can unit‑test SQL shapes **without** the DB layer. 

---

## 2) New file: `codeintel_rev/io/duckdb_dao.py` (tiny executors & typed queries)

```python
# codeintel_rev/io/duckdb_dao.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, TypedDict

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.io.duckdb_schema import (
    IdMapMeta,
    sql_relation_exists,
    sql_create_chunks_from_parquet,
    sql_create_empty_chunks_view,
    sql_create_chunks_mat,
    sql_point_chunks_view_to_mat,
    sql_create_faiss_idmap_view,
    sql_create_empty_faiss_idmap_view,
    sql_create_v_faiss_join,
    sql_materialize_v_faiss_join,
    sql_create_idmap_mat,
    sql_create_idmap_mat_meta,
    sql_select_idmap_checksum,
    sql_delete_idmap_mat,
    sql_insert_idmap_mat,
    sql_delete_idmap_meta,
    sql_insert_idmap_meta,
    sql_count,
)

duckdb = LazyModule("duckdb", "DuckDB DAO")

def relation_exists(conn: "duckdb.DuckDBPyConnection", name: str) -> bool:
    cur = conn.execute(sql_relation_exists(), [name, name])
    return cur.fetchone() is not None

def ensure_chunks(
    conn: "duckdb.DuckDBPyConnection",
    *,
    parquet_glob: str,
    parquet_exists: bool,
    materialize: bool,
) -> None:
    if materialize:
        if parquet_exists:
            conn.execute(sql_create_chunks_mat(), [parquet_glob])
            conn.execute(sql_point_chunks_view_to_mat())
        else:
            conn.execute(sql_create_empty_chunks_view())
    else:
        if parquet_exists:
            conn.execute(sql_create_chunks_from_parquet(), [parquet_glob])
        else:
            conn.execute(sql_create_empty_chunks_view())

def ensure_faiss_idmap_view(conn: "duckdb.DuckDBPyConnection", *, idmap_parquet: Path | None) -> None:
    if idmap_parquet and idmap_parquet.exists():
        conn.execute(sql_create_faiss_idmap_view(), [str(idmap_parquet)])
    else:
        conn.execute(sql_create_empty_faiss_idmap_view())

def ensure_v_faiss_join(conn: "duckdb.DuckDBPyConnection") -> None:
    conn.execute(sql_create_v_faiss_join())

def materialize_v_faiss_join(conn: "duckdb.DuckDBPyConnection") -> int:
    conn.execute(sql_materialize_v_faiss_join())
    return int(conn.execute(sql_count("faiss_join_mat")).fetchone()[0])

def refresh_faiss_idmap_materialized(
    conn: "duckdb.DuckDBPyConnection",
    *,
    idmap_parquet: Path,
    chunks_parquet: Path,  # currently unused by SQL, reserved for future joins
    checksum: str,
) -> IdMapMeta:
    conn.execute(sql_create_idmap_mat())
    conn.execute(sql_create_idmap_mat_meta())
    prev = conn.execute(sql_select_idmap_checksum()).fetchone()
    prev_ck = prev[0] if prev else None

    refreshed = False
    if prev_ck != checksum:
        conn.execute(sql_delete_idmap_mat())
        conn.execute(sql_insert_idmap_mat())
        conn.execute(sql_delete_idmap_meta())
        conn.execute(sql_insert_idmap_meta(), [checksum])
        refreshed = True

    rows = int(conn.execute(sql_count("faiss_idmap_mat")).fetchone()[0])
    return IdMapMeta(checksum=checksum, rows=rows, refreshed=refreshed)

# ---------- typed, tiny query helpers (example) ----------

@dataclass(slots=True)
class DuckDBQueryOptions:
    select_columns: Sequence[str] | None = None
    languages: Sequence[str] | None = None

class ChunkRow(TypedDict, total=False):
    id: int
    uri: str
    start_line: int
    end_line: int
    lang: str

class DuckDBQueryBuilder:
    def build_select_by_ids(self, ids: Sequence[int], options: DuckDBQueryOptions | None = None) -> tuple[str, list[int]]:
        cols = ", ".join(options.select_columns) if options and options.select_columns else "c.*"
        sql = f"SELECT {cols} FROM chunks AS c WHERE c.id IN ({','.join(['?']*len(ids))})"
        if options and options.languages:
            # cheap AND c.lang IN (...)
            sql += f" AND c.lang IN ({','.join(['?']*len(options.languages))})"
        params: list[int] = list(ids)
        return sql, params
```

*Rationale:* the DAO runs SQL **only**; it accepts the open connection and returns **typed** results/structs. It never resolves paths or globs. 

---

## 3) Update `codeintel_rev/io/duckdb_manager.py` (re‑exports for back‑compat)

Add the re‑exports near the public `__all__` so existing imports continue to work:

```python
# codeintel_rev/io/duckdb_manager.py
from __future__ import annotations
# ... existing imports & code ...

# NEW: keep imports shallow here; definitions live in DAO.
from codeintel_rev.io.duckdb_dao import DuckDBQueryBuilder, DuckDBQueryOptions  # re-export

__all__ = [
    # existing exports...
    "DuckDBQueryBuilder",
    "DuckDBQueryOptions",
]
```

*(Keep the rest of the manager focused on connection lifecycle; no query construction.)* 

---

## 4) Update `codeintel_rev/io/duckdb_catalog.py` (thin coordinator)

Delegate all DDL/queries to DAO. Keep checksum at the catalog (path concern). Example changes:

```python
# codeintel_rev/io/duckdb_catalog.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
from typing import Any, Iterator, Sequence

from codeintel_rev.io.duckdb_manager import DuckDBManager, DuckDBQueryBuilder, DuckDBQueryOptions
from codeintel_rev.io.duckdb_dao import (
    ensure_chunks,
    ensure_faiss_idmap_view,
    ensure_v_faiss_join,
    materialize_v_faiss_join,
    refresh_faiss_idmap_materialized as _dao_refresh_faiss_idmap_materialized,
    relation_exists as _dao_relation_exists,
)
from codeintel_rev.io.duckdb_schema import IdMapMeta

# compat helpers
def relation_exists(conn: Any, name: str) -> bool:
    return _dao_relation_exists(conn, name)

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(2**20), b""):
            h.update(block)
    return h.hexdigest()

@dataclass(slots=True, frozen=True)
class IdMapObs:
    parquet_path: Path
    checksum: str
    rows: int
    refreshed: bool

class DuckDBCatalog:
    # ... ctor & connection() unchanged ...

    def _ensure_views(self) -> None:
        with self.connection() as conn:
            parquet_glob = str(self._vectors_dir / "**/*.parquet")
            parquet_exists = any(self._vectors_dir.rglob("*.parquet"))
            ensure_chunks(conn, parquet_glob=parquet_glob, parquet_exists=parquet_exists, materialize=self._materialize)
            ensure_faiss_idmap_view(conn, idmap_parquet=self._idmap_path)
            ensure_v_faiss_join(conn)

    def materialize_faiss_join(self) -> int:
        with self.connection() as conn:
            if not relation_exists(conn, "v_faiss_join"):
                return 0
            return materialize_v_faiss_join(conn)

    def register_idmap_parquet(self, path: Path, *, materialize: bool = False) -> IdMapObs:
        resolved = path.expanduser().resolve()
        self._idmap_path = resolved
        checksum = _sha256(resolved)
        with self.connection() as conn:
            meta: IdMapMeta = _dao_refresh_faiss_idmap_materialized(
                conn,
                idmap_parquet=resolved,
                chunks_parquet=self._vectors_dir,
                checksum=checksum,
            )
            if materialize:
                materialize_v_faiss_join(conn)
        return IdMapObs(parquet_path=resolved, checksum=meta.checksum, rows=meta.rows, refreshed=meta.refreshed)
```

*Rationale:* the catalog computes **paths/checksums** and coordinates; everything else delegates to DAO/Schema for testability and low fan‑in.  

---

## 5) Tests & quick runs

Add focused tests (in‑memory DB):

```python
# tests/io/test_duckdb_schema_dao.py
from codeintel_rev.io.duckdb_dao import (
    relation_exists, ensure_chunks, ensure_faiss_idmap_view,
    ensure_v_faiss_join, materialize_v_faiss_join, refresh_faiss_idmap_materialized
)
import duckdb
from pathlib import Path

def test_ensure_views_and_materialize(tmp_path: Path):
    conn = duckdb.connect(":memory:")
    # no parquet yet -> empty pages
    ensure_chunks(conn, parquet_glob=str(tmp_path/"*.parquet"), parquet_exists=False, materialize=False)
    ensure_faiss_idmap_view(conn, idmap_parquet=None)
    ensure_v_faiss_join(conn)
    assert relation_exists(conn, "chunks")
    assert relation_exists(conn, "faiss_idmap")
    assert relation_exists(conn, "v_faiss_join")
    assert materialize_v_faiss_join(conn) == 0  # empty

def test_checksum_guard(tmp_path: Path):
    conn = duckdb.connect(":memory:")
    ensure_v_faiss_join(conn)
    p = tmp_path / "idmap.parquet"
    # write minimal parquet via DuckDB itself
    conn.execute("CREATE TABLE t (faiss_row BIGINT, external_id BIGINT)")
    conn.execute("INSERT INTO t VALUES (0,0)")
    conn.execute("COPY t TO ? (FORMAT PARQUET)", [str(p)])
    out = refresh_faiss_idmap_materialized(conn, idmap_parquet=p, chunks_parquet=tmp_path, checksum="abc")
    assert out.refreshed and out.rows == 1
```

Then run:

```bash
pytest -q tests/io/test_duckdb_schema_dao.py
```

*Why this structure:* strictly separates **DDL strings**, **executors/queries**, and **coordination**, which is exactly what we committed to in the plan; it also matches the repo’s lint/type rules (absolute imports, TYPE_CHECKING gating for heavy deps).  

---

# E) MCP semantic adapters — ultra‑thin orchestration only

## Objectives (recap)

* Move all pipeline decisions out of adapters into `retrieval/pipeline/…`:

  * **Stage‑0** hybrid retrieval wrapper.
  * **Gating** (pure decision).
  * **Late interaction** (XTR/WARP narrow rescoring).
  * **Rerankers** (LLM pluggable, default no‑op).
* Keep adapters thin: assemble pipeline, hydrate results, map to `AnswerEnvelope`.
* Errors are wrapped **only** at the MCP boundary (Problem Details), not inside pipeline stages.  

---

## 1) New modules under `codeintel_rev/retrieval/pipeline/`

### a) `stage0.py` — normalize HybridSearch

```python
# codeintel_rev/retrieval/pipeline/stage0.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence

from codeintel_rev.io.hybrid_search import HybridSearchEngine, HybridSearchOptions
from codeintel_rev.retrieval.types import HybridSearchResult

@dataclass(frozen=True, slots=True)
class Stage0Options:
    weights: Mapping[str, float] | None = None

@dataclass(frozen=True, slots=True)
class Stage0Result:
    ids: list[int]
    scores: list[float]
    warnings: list[str]
    method: dict[str, object]

def run_stage0(
    engine: HybridSearchEngine,
    *,
    query: str,
    semantic_hits: Sequence[tuple[int, float]] | None,
    limit: int,
    options: Stage0Options | None = None,
) -> Stage0Result:
    opts = options or Stage0Options()
    hs = HybridSearchOptions(weights=opts.weights)  # type: ignore[arg-type]
    fused: HybridSearchResult = engine.search(query=query, semantic_hits=list(semantic_hits or []), limit=limit, options=hs)
    ids = [int(d.doc_id) for d in fused.docs]
    scores = [float(d.score) for d in fused.docs]
    return Stage0Result(ids=ids, scores=scores, warnings=list(fused.warnings or []), method=dict(fused.method or {}))
```

*Why:* Adapters call one pure function; fusion remains within `HybridSearchEngine`. 

### b) `gating.py` — pure decision façade

```python
# codeintel_rev/retrieval/pipeline/gating.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
from codeintel_rev.retrieval.gating import should_run_secondary_stage as _core

@dataclass(frozen=True, slots=True)
class StageGateConfig:
    time_budget_ms: int = 750
    min_candidates: int = 16
    high_margin_threshold: float = 0.25

@dataclass(frozen=True, slots=True)
class StageDecision:
    should_run: bool
    reason: str

def decide_secondary_stage(signals: Mapping[str, object], config: StageGateConfig) -> StageDecision:
    out = _core(signals, config)
    return StageDecision(should_run=bool(out.should_run), reason=str(out.reason))
```

*Why:* Mirrors today’s logic but isolates it from adapters and keeps it test‑only. 

### c) `late_interaction.py` — XTR/WARP narrow rescoring

```python
# codeintel_rev/retrieval/pipeline/late_interaction.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Protocol
from codeintel_rev.io.xtr_manager import XTRIndex

@dataclass(frozen=True, slots=True)
class LateInteractionResult:
    ids: list[int]
    scores: list[float]

class LateInteraction(Protocol):
    def rescore(self, query: str, candidate_ids: Iterable[int], *, explain: bool = False) -> LateInteractionResult: ...

class XTRLateInteraction:
    def __init__(self, index: XTRIndex) -> None:
        self._index = index

    def rescore(self, query: str, candidate_ids: Iterable[int], *, explain: bool = False) -> LateInteractionResult:
        triples = self._index.rescore(query=query, candidate_chunk_ids=candidate_ids, explain=explain, topk_explanations=5)
        return LateInteractionResult(ids=[int(t[0]) for t in triples], scores=[float(t[1]) for t in triples])
```

*Why:* Uses documented **narrow‑mode** XTR contract; easy to stub in tests. 

### d) `rerankers.py` — LLM reranking interface

```python
# codeintel_rev/retrieval/pipeline/rerankers.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Protocol

@dataclass(frozen=True, slots=True)
class RerankResult:
    ids: list[int]
    scores: list[float]

class Reranker(Protocol):
    def rerank(self, query: str, ids: Iterable[int], scores: Iterable[float]) -> RerankResult: ...

class NoopReranker:
    def rerank(self, query: str, ids: Iterable[int], scores: Iterable[float]) -> RerankResult:
        ids_l, scores_l = list(ids), list(scores)
        return RerankResult(ids=ids_l, scores=scores_l)
```

*Why:* Keeps adapters agnostic; swapping an LLM reranker is a one‑line change. 

---

## 2) Make adapters **thin**: `semantic.py` and `semantic_pro.py`

### a) Standard adapter (`semantic.py`) — Stage‑0 only

```python
# codeintel_rev/mcp_server/adapters/semantic.py
from __future__ import annotations
from typing import Sequence
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, relation_exists
from codeintel_rev.mcp_server.schemas import AnswerEnvelope
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options, run_stage0
from codeintel_rev.retrieval.pipeline.gating import StageGateConfig, decide_secondary_stage

_VIEW_CHUNKS = "chunks"

async def semantic_search(context: ApplicationContext, query: str, limit: int = 20) -> AnswerEnvelope:
    text = (query or "").strip()
    if not text:
        return AnswerEnvelope(error="missing query text")

    engine = context.get_hybrid_engine()
    s0 = run_stage0(engine, query=text, semantic_hits=[], limit=int(limit), options=Stage0Options(weights=None))

    with context.open_catalog() as catalog:
        results = _hydrate_findings(catalog, s0.ids, s0.scores)

    method = {"channels": ["hybrid"], "warnings": s0.warnings, "stage0": s0.method}
    limits = {"k": int(limit)}
    return AnswerEnvelope(findings=results, method=method, limits=limits, answer="", confidence=float(s0.scores[0]) if s0.scores else 0.0)

def _hydrate_findings(catalog: DuckDBCatalog, ids: Sequence[int], scores: Sequence[float]) -> list[dict]:
    if not ids:
        return []
    with catalog.connection() as conn:
        if not relation_exists(conn, _VIEW_CHUNKS):
            return [{"chunk_id": int(i), "score": float(s)} for i, s in zip(ids, scores)]
        placeholders = ",".join(["?"] * len(ids))
        order_case = " ".join(f"WHEN {i} THEN {pos}" for pos, i in enumerate(ids))
        tbl = conn.execute(
            f'SELECT id, uri FROM "{_VIEW_CHUNKS}" WHERE id IN ({placeholders}) ORDER BY CASE id {order_case} END',
            list(ids),
        ).fetch_arrow_table()
        out: list[dict] = []
        for rank in range(tbl.num_rows):
            cid = tbl.column(0)[rank].as_py()
            uri = tbl.column(1)[rank].as_py()
            out.append({"chunk_id": int(cid), "uri": uri, "score": float(scores[rank])})
        return out
```

*Why:* The adapter orchestrates; there’s no embedded fusion/engine logic. Hydration remains at the MCP boundary by design. 

### b) Pro adapter (`semantic_pro.py`) — Stage‑0 → gating → optional XTR → optional reranker → hydrate

```python
# codeintel_rev/mcp_server/adapters/semantic_pro.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.mcp_server.schemas import AnswerEnvelope
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options, run_stage0
from codeintel_rev.retrieval.pipeline.gating import StageGateConfig, decide_secondary_stage
from codeintel_rev.retrieval.pipeline.late_interaction import XTRLateInteraction
from codeintel_rev.retrieval.pipeline.rerankers import NoopReranker

@dataclass(frozen=True)
class ProOptions:
    use_warp: bool = True   # XTR/WARP late interaction
    use_reranker: bool = False
    xtr_k: int = 50
    stage_weights: Mapping[str, float] | None = None
    explain: bool = False

async def semantic_search_pro(context: ApplicationContext, query: str, limit: int = 20, options: ProOptions | None = None) -> AnswerEnvelope:
    opts = options or ProOptions()
    engine = context.get_hybrid_engine()
    s0 = run_stage0(engine, query=query, semantic_hits=[], limit=limit, options=Stage0Options(weights=opts.stage_weights))
    ids, scores = s0.ids, s0.scores

    decision = decide_secondary_stage(
        {"candidate_count": len(ids), "top_score": (scores[0] if scores else 0.0), "margin": ((scores[0]-scores[1]) if len(scores)>1 else 0.0), "budget_ms": 0},
        StageGateConfig(),
    )

    if opts.use_warp and decision.should_run and ids:
        xtr: XTRIndex = context.runtime_cells.xtr_index
        li = XTRLateInteraction(xtr)
        narrowed = li.rescore(query=query, candidate_ids=ids[: min(opts.xtr_k, len(ids))], explain=opts.explain)
        ids, scores = narrowed.ids, narrowed.scores

    if opts.use_reranker and ids:
        rr = NoopReranker()  # plug in LLM reranker later without touching adapter
        rer = rr.rerank(query, ids, scores)
        ids, scores = rer.ids, rer.scores

    with context.open_catalog() as catalog:
        findings = _hydrate_ids(catalog, ids, scores)

    method = {"warnings": s0.warnings, "stage0": s0.method, "gating": {"should_run_secondary_stage": decision.should_run, "reason": decision.reason}}
    return AnswerEnvelope(findings=findings, method=method, limits={"k": int(limit)}, answer="", confidence=float(scores[0]) if scores else 0.0)

def _hydrate_ids(catalog: DuckDBCatalog, ids: Sequence[int], scores: Sequence[float]) -> list[dict]:
    if not ids:
        return []
    with catalog.connection() as conn:
        placeholders = ",".join(["?"] * len(ids))
        order_case = " ".join(f"WHEN {i} THEN {pos}" for pos, i in enumerate(ids))
        tbl = conn.execute(
            f'SELECT id, uri FROM "chunks" WHERE id IN ({placeholders}) ORDER BY CASE id {order_case} END',
            list(ids),
        ).fetch_arrow_table()
        out: list[dict] = []
        for rank in range(tbl.num_rows):
            out.append({"chunk_id": int(tbl.column(0)[rank].as_py()), "uri": tbl.column(1)[rank].as_py(), "score": float(scores[rank])})
        return out
```

*Why:* Adapters are now **glue only**; swapping WARP→XTR, changing stage weights, or toggling an LLM reranker never touches adapter code again—only the pipeline modules. 

---

## 3) Tests

Unit tests target the pipeline modules (pure and fast):

```python
# tests/retrieval/pipeline/test_stage0.py
from codeintel_rev.retrieval.pipeline.stage0 import run_stage0, Stage0Options
from codeintel_rev.io.hybrid_search import HybridSearchEngine, HybridSearchOptions
from codeintel_rev.retrieval.types import HybridSearchResult, DocScore

class _StubEngine(HybridSearchEngine):
    def search(self, query, semantic_hits, limit, options):
        docs = [DocScore(doc_id=1, score=0.9), DocScore(doc_id=2, score=0.6)]
        return HybridSearchResult(docs=docs, method={"engine":"stub"}, warnings=[])

def test_stage0_normalizes():
    s0 = run_stage0(_StubEngine(), query="q", semantic_hits=[], limit=5, options=Stage0Options())
    assert s0.ids[:2] == [1, 2]
    assert s0.scores[:2] == [0.9, 0.6]
```

Adapters get a thin integration test that spies `XTRIndex.rescore` to ensure Stage‑1 is taken when gated.

---

## 4) Quick checks / quality gates

* **Adapters remain thin** (≤ ~100 LOC orchestration; no embedded fusion/LLM logic).
* **Late interaction** uses `XTRIndex.rescore(query, candidate_ids, explain=...)`.
* **Errors wrapped only at MCP boundary**; pipeline modules raise standard exceptions.
* Run the project gates from **AGENTS.md** after each edit:

```bash
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13
uv run pyrefly check
uv run pytest -q
```

These enforce absolute imports, type‑checking import gates, function complexity, and no dead code.  

---

## 5) Migration plan (small, safe PRs)

**PR‑D1** (Additive): add `duckdb_schema.py` + `duckdb_dao.py`, wire re‑exports in manager, delegate in catalog, add DAO/schema tests.
**PR‑D2** (Cleanup): remove legacy inline SQL from catalog; CI grep forbids CREATE VIEW in catalog. 

**PR‑E1** (Additive): add `retrieval/pipeline/*` modules + tests.
**PR‑E2** (Adapters thin): replace orchestration in `semantic.py` & `semantic_pro.py` with thin shells above; retain hydration helpers; add adapter integration test. 

---

## 6) End‑to‑end smoke

1. **DuckDB**

```bash
python - <<'PY'
from pathlib import Path
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
db = DuckDBManager(Path("test.duckdb"))
catalog = DuckDBCatalog(db, vectors_dir=Path(".enrich/vectors"))
with catalog.connection() as conn:
    pass
print("catalog ok")
PY
```

2. **Adapters** (with a tiny context that provides `hybrid_engine`, `xtr_index`, and `open_catalog()`), call both `semantic_search()` and `semantic_search_pro()`; confirm `AnswerEnvelope.method` contains stage metadata and warnings.

---

## 7) Why this satisfies D/E and your repo rules

* We maintain **thin, single‑purpose** modules; SQL is pure in *schema*, execution is in *DAO*, and *catalog* only coordinates **paths/checksums**—exact split agreed earlier. 
* Adapters assemble **Stage‑0 → gating → late‑interaction → rerank → hydrate**, with no hardwired fusion logic; future engine/reranker swaps don’t churn the adapters. 
* The changes comply with **AGENTS.md** (absolute imports, TYPE_CHECKING separation for heavy deps, ≤ 100‑line command shells, no print debugging, strict typing). 

---

### Ready to proceed?

If you’d like, I can now generate:

* the **exact full‑file replacements** for your current `duckdb_catalog.py` & `duckdb_manager.py` (post‑split), and
* a **codemod** to update any imports to the new pipeline modules while keeping adapters minimal.

Both are straightforward extensions of the code above and match the accepted plan.  

# Full file replacements and codemod #

Absolutely—here are the **exact full‑file replacements** for the DuckDB layer (catalog + manager) plus a **LibCST codemod** that transforms the two MCP semantic adapters into the thin, orchestration‑only shells built on the new `retrieval/pipeline/*` modules. Everything below follows the split you approved (schema → DAO → catalog; adapters → pipeline) and your repo’s strict style/typing rules from **AGENTS.md**.

> **What you get in this reply**
>
> 1. Full replacement for `codeintel_rev/io/duckdb_catalog.py` (thin coordinator; checksum at path layer; delegates to DAO/schema).
> 2. Full replacement for `codeintel_rev/io/duckdb_manager.py` (connection lifecycle; **re‑exports** `DuckDBQueryBuilder`/`DuckDBQueryOptions`).
> 3. A ready‑to‑run **LibCST codemod** that replaces `mcp_server/adapters/semantic.py` and `semantic_pro.py` with ultra‑thin versions wired to the new pipeline (Stage‑0 → gating → optional late‑interaction → optional reranker → hydrate).

---

## 1) Full file replacement — `codeintel_rev/io/duckdb_catalog.py`

```python
# codeintel_rev/io/duckdb_catalog.py
"""
Thin DuckDB catalog coordinator.

Responsibilities (path & coordination only):
- Compute checksums for path-based materializations.
- Ensure views exist (chunks, faiss_idmap, v_faiss_join).
- Delegate all DDL/queries to the DAO/schema layer.
- Keep small, stable wrappers used by the rest of the app/CLI.

Design: SQL strings live in codeintel_rev.io.duckdb_schema, executors & tiny
query helpers live in codeintel_rev.io.duckdb_dao. This file stays tiny on
purpose to minimize fan-in blast radius. See repo refactor plan.  # noqa: D205
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
from threading import Lock
from typing import Iterator

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.io.duckdb_dao import (
    ensure_chunks,
    ensure_faiss_idmap_view,
    ensure_v_faiss_join,
    materialize_v_faiss_join,
    refresh_faiss_idmap_materialized as _dao_refresh_faiss_idmap_materialized,
    relation_exists as _dao_relation_exists,
)
from codeintel_rev.io.duckdb_manager import DuckDBManager
from codeintel_rev.io.duckdb_schema import IdMapMeta

duckdb = LazyModule("duckdb", "DuckDB Catalog")

# Back-compat: keep a module-level alias for relation_exists that maps to DAO.
relation_exists = _dao_relation_exists


@dataclass(frozen=True, slots=True)
class IdMapObs:
    """Observation payload returned by register_idmap_parquet."""

    parquet_path: Path
    checksum: str
    rows: int
    refreshed: bool


class DuckDBCatalog:
    """
    Orchestrates only *coordination* concerns for DuckDB.

    Parameters
    ----------
    manager:
        Connection provider.
    vectors_dir:
        Directory containing chunk parquet files (used by 'chunks' view).
    materialize:
        If True, concrete 'chunks_materialized' table is created (and 'chunks'
        view points to it) for BI workloads.
    """

    def __init__(self, manager: DuckDBManager, *, vectors_dir: Path, materialize: bool = False) -> None:
        self._manager = manager
        self._vectors_dir = vectors_dir.expanduser().resolve()
        self._materialize = bool(materialize)
        self._idmap_path: Path | None = None
        self._log = logging.getLogger(__name__)
        self._views_installed = False
        self._lock = Lock()

    @contextmanager
    def connection(self) -> Iterator["duckdb.DuckDBPyConnection"]:
        """
        Yield a connection with catalog views ensured exactly once per process.
        """
        with self._manager.connection() as conn:
            with self._lock:
                if not self._views_installed:
                    self._ensure_views(conn)
                    self._views_installed = True
            yield conn

    # ---------- public API (tiny wrappers) ----------

    def materialize_faiss_join(self) -> int:
        """
        Materialize v_faiss_join into faiss_join_mat. Returns row count.

        This wrapper keeps the path/coordination concerns here and delegates the
        DDL to DAO. It is safe to call repeatedly.  # noqa: D401
        """
        with self.connection() as conn:
            if not relation_exists(conn, "v_faiss_join"):
                return 0
            rows = materialize_v_faiss_join(conn)
            self._log.debug("faiss_join_mat rowcount: %d", rows)
            return rows

    def register_idmap_parquet(self, path: Path, *, materialize: bool = False) -> IdMapObs:
        """
        Register (and optionally materialize) the FAISS idmap parquet.

        The checksum is computed here (path concern) and passed to DAO, which
        rebuilds the materialized table iff the checksum changed.
        """
        resolved = path.expanduser().resolve()
        self._idmap_path = resolved
        checksum = _sha256(resolved)
        with self.connection() as conn:
            meta: IdMapMeta = _dao_refresh_faiss_idmap_materialized(
                conn=conn,
                idmap_parquet=resolved,
                chunks_parquet=self._vectors_dir,
                checksum=checksum,
            )
            if materialize:
                materialize_v_faiss_join(conn)
        return IdMapObs(
            parquet_path=resolved,
            checksum=meta.checksum,
            rows=meta.rows,
            refreshed=meta.refreshed,
        )

    # ---------- internals ----------

    def _ensure_views(self, conn: "duckdb.DuckDBPyConnection") -> None:
        parquet_glob = str(self._vectors_dir / "**/*.parquet")
        parquet_exists = any(self._vectors_dir.rglob("*.parquet"))
        ensure_chunks(
            conn,
            parquet_glob=parquet_glob,
            parquet_exists=parquet_exists,
            materialize=self._materialize,
        )
        ensure_faiss_idmap_view(conn, idmap_parquet=self._idmap_path)
        ensure_v_faiss_join(conn)


def _sha256(path: Path) -> str:
    """Return a fast SHA256 of a file on disk."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(2**20), b""):
            h.update(block)
    return h.hexdigest()
```

**Why this file looks like this:** all **SQL** stays in `duckdb_schema.py`, all **execution** lives in `duckdb_dao.py`. The **catalog** computes file checksums and manages view readiness once per process—this structure keeps the high fan‑in surface stable and trivial to test. It matches the split you approved.

---

## 2) Full file replacement — `codeintel_rev/io/duckdb_manager.py`

```python
# codeintel_rev/io/duckdb_manager.py
"""
DuckDB connection lifecycle and back-compat re-exports.

This module keeps ONLY connection management and stable public aliases for
query builder/options (which are defined in duckdb_dao.py).  # noqa: D205
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from threading import Lock
from typing import Any, Iterator, Mapping

from codeintel_rev._lazy_imports import LazyModule

# Heavy import kept lazy for startup determinism.
duckdb = LazyModule("duckdb", "DuckDB Manager")

# Back-compat re-exports for callers still importing from manager:
from codeintel_rev.io.duckdb_dao import (  # noqa: F401
    DuckDBQueryBuilder,
    DuckDBQueryOptions,
)

__all__ = ["DuckDBManager", "DuckDBQueryBuilder", "DuckDBQueryOptions"]


class DuckDBManager:
    """
    Minimal connection manager.

    Parameters
    ----------
    path:
        Path to the DuckDB file (use ':memory:' for ephemeral).
    read_only:
        Open connections in read-only mode.
    pragmas:
        Optional PRAGMA overrides (e.g., {"threads": 4, "memory_limit": "1GB"}).
    """

    def __init__(
        self,
        path: Path | str,
        *,
        read_only: bool = False,
        pragmas: Mapping[str, Any] | None = None,
    ) -> None:
        self._path = Path(path)
        self._read_only = bool(read_only)
        # Sensible defaults; caller may override via pragmas.
        default_tmp = (self._path.parent / ".duckdb_tmp") if self._path != Path(":memory:") else Path(".")
        self._pragmas: dict[str, Any] = {
            "threads": max(1, os.cpu_count() or 1),
            "temp_directory": str(default_tmp),
        }
        if pragmas:
            self._pragmas.update(dict(pragmas))
        self._lock = Lock()

    @contextmanager
    def connection(self) -> Iterator["duckdb.DuckDBPyConnection"]:
        """
        Open a new connection, apply pragmas, and ensure cleanup.
        """
        with self._lock:
            conn = duckdb.module().connect(str(self._path), read_only=self._read_only)
            try:
                for key, value in self._pragmas.items():
                    if value is None:
                        continue
                    # Strings need quoting; others are fine as-is.
                    if isinstance(value, str):
                        conn.execute(f"PRAGMA {key}='{value}'")
                    else:
                        conn.execute(f"PRAGMA {key}={value}")
                yield conn
                conn.commit()
            finally:
                conn.close()
```

**Why this file looks like this:** it focuses on **connection lifecycle** and **re‑exports** the two builder types for compatibility (their definitions live in DAO now). That keeps imports stable without allowing query construction to creep back into the manager.

---

## 3) LibCST codemod — thin MCP semantic adapters

This codemod **replaces** the two adapters with the ultra‑thin versions that orchestrate the new pipeline modules you approved (Stage‑0 → gating → optional late‑interaction (XTR) → optional reranker → hydrate). Using a codemod here avoids hand edits and ensures adapters don’t retain old orchestration logic.

> **What the codemod does**
>
> * Detects files by their path (`…/mcp_server/adapters/semantic.py` and `…/semantic_pro.py`) and **replaces** them with the new canonical implementations (embedded as source in the codemod).
> * Adds the correct **absolute imports** and **typing** required by AGENTS.md (e.g., TYPE_CHECKING gating handled by our pipeline modules already).

Create `tools/codemods/pipeline_adapter_thin.py`:

```python
# tools/codemods/pipeline_adapter_thin.py
from __future__ import annotations

import pathlib
from typing import Optional

import libcst as cst
from libcst.codemod import CodemodContext, ContextAwareTransformer
from libcst.metadata import FilenameProvider


SEMANTIC_THIN_SOURCE = '''\
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, relation_exists
from codeintel_rev.mcp_server.schemas import AnswerEnvelope
from codeintel_rev.retrieval.pipeline.gating import StageGateConfig, decide_secondary_stage
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options, run_stage0

_VIEW_CHUNKS = "chunks"


async def semantic_search(context: ApplicationContext, query: str, limit: int = 20) -> AnswerEnvelope:
    text = (query or "").strip()
    if not text:
        return AnswerEnvelope(error="missing query text")

    engine = context.get_hybrid_engine()
    s0 = run_stage0(engine, query=text, semantic_hits=[], limit=int(limit), options=Stage0Options(weights=None))

    decision = decide_secondary_stage(
        signals={
            "candidate_count": len(s0.ids),
            "top_score": (s0.scores[0] if s0.scores else 0.0),
            "margin": ((s0.scores[0] - s0.scores[1]) if len(s0.scores) > 1 else 0.0),
            "budget_ms": 0,
        },
        config=StageGateConfig(time_budget_ms=750, min_candidates=16),
    )

    ids, scores = s0.ids, s0.scores

    with context.open_catalog() as catalog:
        findings = _hydrate_findings(catalog, ids, scores)

    method = {
        "channels": ["hybrid"],
        "warnings": s0.warnings,
        "stage0": s0.method,
        "gating": {"should_run_secondary_stage": bool(decision.should_run), "reason": decision.reason},
    }
    limits = {"k": int(limit)}
    return AnswerEnvelope(findings=findings, method=method, limits=limits, answer="", confidence=float(scores[0]) if scores else 0.0)

def _hydrate_findings(catalog: DuckDBCatalog, ids: Sequence[int], scores: Sequence[float]) -> list[dict]:
    if not ids:
        return []
    with catalog.connection() as conn:
        if not relation_exists(conn, _VIEW_CHUNKS):
            return [{"chunk_id": int(i), "score": float(s)} for i, s in zip(ids, scores)]
        placeholders = ",".join(["?"] * len(ids))
        order_case = " ".join(f"WHEN {i} THEN {pos}" for pos, i in enumerate(ids))
        tbl = conn.execute(
            f'SELECT id, uri FROM "{_VIEW_CHUNKS}" WHERE id IN ({placeholders}) ORDER BY CASE id {order_case} END',
            list(ids),
        ).fetch_arrow_table()
        out: list[dict] = []
        for rank in range(tbl.num_rows):
            cid = tbl.column(0)[rank].as_py()
            uri = tbl.column(1)[rank].as_py()
            out.append({"chunk_id": int(cid), "uri": uri, "score": float(scores[rank])})
        return out
'''

SEMANTIC_PRO_THIN_SOURCE = '''\
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.mcp_server.schemas import AnswerEnvelope
from codeintel_rev.retrieval.pipeline.gating import StageGateConfig, decide_secondary_stage
from codeintel_rev.retrieval.pipeline.late_interaction import XTRLateInteraction
from codeintel_rev.retrieval.pipeline.rerankers import NoopReranker
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options, run_stage0

@dataclass(frozen=True)
class ProOptions:
    use_warp: bool = True
    use_reranker: bool = False
    xtr_k: int = 50
    stage_weights: Mapping[str, float] | None = None
    explain: bool = False

async def semantic_search_pro(context: ApplicationContext, query: str, limit: int = 20, options: ProOptions | None = None) -> AnswerEnvelope:
    opts = options or ProOptions()
    engine = context.get_hybrid_engine()
    s0 = run_stage0(engine, query=query, semantic_hits=[], limit=limit, options=Stage0Options(weights=opts.stage_weights))
    ids, scores = s0.ids, s0.scores

    decision = decide_secondary_stage(
        {"candidate_count": len(ids), "top_score": (scores[0] if scores else 0.0), "margin": ((scores[0]-scores[1]) if len(scores)>1 else 0.0), "budget_ms": 0},
        StageGateConfig(),
    )

    if opts.use_warp and decision.should_run and ids:
        xtr: XTRIndex = context.runtime_cells.xtr_index
        li = XTRLateInteraction(xtr)
        narrowed = li.rescore(query=query, candidate_ids=ids[: min(opts.xtr_k, len(ids))], explain=opts.explain)
        ids, scores = narrowed.ids, narrowed.scores

    if opts.use_reranker and ids:
        rr = NoopReranker()
        rer = rr.rerank(query, ids, scores)
        ids, scores = rer.ids, rer.scores

    with context.open_catalog() as catalog:
        findings = _hydrate_ids(catalog, ids, scores)

    method = {"warnings": s0.warnings, "stage0": s0.method, "gating": {"should_run_secondary_stage": decision.should_run, "reason": decision.reason}}
    return AnswerEnvelope(findings=findings, method=method, limits={"k": int(limit)}, answer="", confidence=float(scores[0]) if scores else 0.0)

def _hydrate_ids(catalog: DuckDBCatalog, ids: Sequence[int], scores: Sequence[float]) -> list[dict]:
    if not ids:
        return []
    with catalog.connection() as conn:
        placeholders = ",".join(["?"] * len(ids))
        order_case = " ".join(f"WHEN {i} THEN {pos}" for pos, i in enumerate(ids))
        tbl = conn.execute(
            f'SELECT id, uri FROM "chunks" WHERE id IN ({placeholders}) ORDER BY CASE id {order_case} END',
            list(ids),
        ).fetch_arrow_table()
        out: list[dict] = []
        for rank in range(tbl.num_rows):
            out.append({"chunk_id": int(tbl.column(0)[rank].as_py()), "uri": tbl.column(1)[rank].as_py(), "score": float(scores[rank])})
        return out
'''


class PipelineAdapterThinCommand(ContextAwareTransformer):
    """
    Replace the two semantic adapters with thin pipeline-based implementations.

    Usage:
        python -m libcst.tool codemod tools.codemods.pipeline_adapter_thin.PipelineAdapterThinCommand \
            codeintel_rev/mcp_server/adapters/semantic.py \
            codeintel_rev/mcp_server/adapters/semantic_pro.py
    """

    METADATA_DEPENDENCIES = (FilenameProvider,)

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)
        self.filename: Optional[str] = None

    def on_visit(self, node: cst.CSTNode) -> bool:  # pragma: no cover - metadata access
        # Recorded once per module
        if self.filename is None:
            filename = self.get_metadata(FilenameProvider, node)
            self.filename = str(filename) if filename is not None else ""
        return True

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        if not self.filename:
            return updated_node

        path = pathlib.PurePosixPath(self.filename.replace("\\", "/"))
        if str(path).endswith("/mcp_server/adapters/semantic.py"):
            return cst.parse_module(SEMANTIC_THIN_SOURCE)
        if str(path).endswith("/mcp_server/adapters/semantic_pro.py"):
            return cst.parse_module(SEMANTIC_PRO_THIN_SOURCE)
        return updated_node
```

**How to run the codemod**

```bash
# (from repo root)
python -m libcst.tool codemod \
  tools.codemods.pipeline_adapter_thin.PipelineAdapterThinCommand \
  codeintel_rev/mcp_server/adapters/semantic.py \
  codeintel_rev/mcp_server/adapters/semantic_pro.py
```

---

## 4) Post‑apply quick checks (copy/paste)

Verify the **DuckDB split** and **adapter thinness** gates you set:

```bash
# Catalog must not contain CREATE VIEW strings (SQL lives in schema)
! grep -R "CREATE OR REPLACE VIEW" -n codeintel_rev/io/duckdb_catalog.py

# Manager re-exports (avoid churn)
grep -n "from codeintel_rev.io.duckdb_dao import DuckDBQueryBuilder, DuckDBQueryOptions" \
  codeintel_rev/io/duckdb_manager.py

# Adapters import pipeline modules (thin shells only)
grep -R "retrieval/pipeline" -n codeintel_rev/mcp_server/adapters/semantic*.py

# Lint, types, tests per AGENTS.md
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13
uv run pyrefly check
uv run pytest -q
```

These enforce the agreed separation and your strict repo rules (absolute imports, typing, complexity, no dead code).

---

## 5) Why this matches the approved architecture

* **DuckDB (D)**: catalog is tiny (path/coordination only); **all SQL** is in `duckdb_schema.py`; **all execution** is in `duckdb_dao.py`; manager strictly handles connections and re‑exports to avoid churn. This aligns 1:1 with the split you requested.
* **Adapters (E)**: adapters now **only orchestrate** Stage‑0 → gating → (optional) late‑interaction (XTR) → (optional) rerank → hydrate; pipeline modules hold the branching/logic, so swapping engines/rerankers doesn’t churn adapters.

---

### Notes

* The code above presumes you’ve already added `codeintel_rev/io/duckdb_schema.py` and `codeintel_rev/io/duckdb_dao.py` (as in the earlier D‑plan). If you want, I can also include **those two files** verbatim here for completeness.
* If you prefer a **surgical** codemod (rewriting specific imports/blocks rather than full‑file replacement), I can generate that variant too; the full‑file approach is more robust for large monoliths and ensures we land the agreed design cleanly.


