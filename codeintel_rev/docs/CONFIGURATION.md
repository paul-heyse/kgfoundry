# Configuration Management

## Overview

CodeIntel MCP uses a **centralized configuration lifecycle** where all settings are loaded exactly once during FastAPI application startup. This eliminates redundant environment variable parsing and ensures consistent configuration across all components.

The configuration system follows these principles:

- **Load Once**: Settings parsed from environment exactly once at startup
- **Explicit Injection**: Context passed as parameter (no global state)
- **Fail-Fast**: Invalid configuration prevents application startup
- **Immutable**: Settings frozen after creation (thread-safe)
- **RFC 9457**: All errors use Problem Details format

## Configuration Loading Sequence

The configuration lifecycle follows this sequence during application startup:

```
1. FastAPI Startup
   ├─ lifespan() entered
   │
2. Load Configuration
   ├─ load_settings() reads environment variables ONCE
   ├─ resolve_application_paths() validates all paths
   │  ├─ Raises ConfigurationError if repo_root missing
   │  ├─ Converts relative paths to absolute
   │  └─ Returns ResolvedPaths dataclass
   │
3. Initialize Clients
   ├─ VLLMClient(settings.vllm) created
   ├─ FAISSManager(...) created (CPU index not loaded yet)
   ├─ ApplicationContext assembled
   │
4. Health Checks
   ├─ ReadinessProbe.initialize()
   │  ├─ Check repo_root exists
   │  ├─ Check data directories (create if missing)
   │  ├─ Check FAISS index file exists
   │  ├─ Check DuckDB catalog exists
   │  ├─ Check vLLM service reachable
   │  └─ Return CheckResult per resource
   │
5. Optional FAISS Pre-loading
   ├─ If FAISS_PRELOAD=1:
   │  ├─ faiss_manager.load_cpu_index()
   │  ├─ faiss_manager.clone_to_gpu()
   │  └─ Log success or degraded mode
   │
6. Store Context
   ├─ app.state.context = context
   ├─ app.state.readiness = readiness
   │
7. Application Ready
   └─ Serve requests
```

## Key Environment Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `REPO_ROOT` | Absolute path to repository root directory (must exist) | `/home/user/kgfoundry` |
| `FAISS_INDEX` | Path to FAISS index file (must exist for startup) | `data/faiss/code.ivfpq.faiss` |
| `DUCKDB_PATH` | Path to DuckDB catalog (must exist for startup) | `data/catalog.duckdb` |

### Optional Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `FAISS_PRELOAD` | Pre-load FAISS index during startup (`0` = lazy, `1` = eager) | `0` | `1` |
| `VLLM_URL` | vLLM service endpoint | `http://127.0.0.1:8001/v1` | `http://localhost:8001/v1` |
| `VLLM_MODEL` | Embedding model identifier | `nomic-ai/nomic-embed-code` | `nomic-ai/nomic-embed-code` |
| `VLLM_BATCH_SIZE` | Batch size for embedding requests | `64` | `128` |
| `VLLM_TIMEOUT_S` | HTTP request timeout in seconds | `120.0` | `180.0` |
| `DUCKDB_LOG_QUERIES` | Emit debug logs for every DuckDB SQL statement (`0` = disabled, `1` = enabled) | `0` | `1` |
| `DUCKDB_POOL_SIZE` | Size of optional DuckDB connection pool (`0` disables pooling) | `0` | `16` |
| `DATA_DIR` | Base directory for data storage | `data` | `data` |
| `VECTORS_DIR` | Directory containing Parquet files | `data/vectors` | `data/vectors` |
| `SCIP_INDEX` | Path to SCIP index file | `index.scip` | `index.scip.json` |
| `VEC_DIM` | Embedding vector dimension | `3584` | `3584` |
| `CHUNK_BUDGET` | Target chunk size in characters | `2200` | `2200` |
| `FAISS_NLIST` | Number of IVF centroids | `8192` | `16384` |
| `FAISS_NPROBE` | Number of IVF cells to probe per live search (higher = better recall, slower queries) | `128` | `256` |
| `USE_CUVS` | Enable cuVS GPU acceleration | `1` | `0` |
| `DUCKDB_MATERIALIZE` | Materialize chunks into DuckDB table with secondary index | `0` | `1` |
| `MAX_RESULTS` | Maximum results per query | `1000` | `500` |
| `QUERY_TIMEOUT_S` | Query timeout in seconds | `30.0` | `60.0` |
| `SEMANTIC_OVERFETCH_MULTIPLIER` | FAISS fan-out multiplier when scope filters active | `2` | `3` |
| `HYBRID_ENABLE_BM25` | Enable BM25 channel in hybrid retrieval (`1` = enabled, `0` = disabled) | `1` | `0` |
| `HYBRID_ENABLE_SPLADE` | Enable SPLADE channel in hybrid retrieval (`1` = enabled, `0` = disabled) | `1` | `0` |
| `HYBRID_TOP_K_PER_CHANNEL` | Per-channel candidate fan-out gathered before RRF fusion | `50` | `75` |
| `LUCENE_DIR` | Base directory for sparse Lucene indexes | `data/lucene` | `/var/lib/codeintel/lucene` |
| `SPLADE_DIR` | Legacy SPLADE directory (superseded by dedicated settings) | `data/splade` | `/var/lib/codeintel/splade` |
| `BM25_JSONL_DIR` | Directory containing JsonCollection documents for BM25 indexing | `data/jsonl` | `/mnt/data/bm25/json` |
| `BM25_INDEX_DIR` | Directory where the BM25 Lucene index is stored | `indexes/bm25` | `/mnt/data/bm25/index` |
| `BM25_THREADS` | Worker threads used while building BM25 indexes | `8` | `16` |
| `SPLADE_MODEL_ID` | Hugging Face model identifier for SPLADE | `naver/splade-v3` | `models/splade-finetuned` |
| `SPLADE_MODEL_DIR` | Directory for SPLADE model artifacts | `models/splade-v3` | `/srv/models/splade-v3` |
| `SPLADE_ONNX_DIR` | Directory for exported SPLADE ONNX files | `models/splade-v3/onnx` | `/srv/models/splade-v3/onnx` |
| `SPLADE_ONNX_FILE` | Default SPLADE ONNX file name used for inference | `model_qint8.onnx` | `model_qint8_avx2.onnx` |
| `SPLADE_VECTORS_DIR` | Directory with SPLADE JsonVectorCollection shards | `data/splade_vectors` | `/mnt/data/splade/vectors` |
| `SPLADE_INDEX_DIR` | Directory for SPLADE impact indexes | `indexes/splade_v3_impact` | `/mnt/data/splade/index` |
| `SPLADE_PROVIDER` | Default ONNX Runtime execution provider | `CPUExecutionProvider` | `CUDAExecutionProvider` |
| `SPLADE_QUANTIZATION` | Integer quantization factor applied during encoding | `100` | `50` |
| `SPLADE_MAX_TERMS` | Maximum number of terms retained for expanded queries | `3000` | `2000` |
| `SPLADE_MAX_CLAUSE` | Lucene Boolean clause limit applied while indexing | `4096` | `8192` |
| `SPLADE_BATCH_SIZE` | Default batch size for SPLADE encoding commands | `32` | `16` |
| `SPLADE_THREADS` | Default worker threads for SPLADE impact index builds | `8` | `12` |

> **GPU warm-up tip:** On CPU-only workstations, export `SKIP_GPU_WARMUP=1` before running pytest to bypass the FAISS GPU smoke test. Drop the variable on CUDA-capable hosts so the warm-up coverage runs.

### Sparse retrieval prerequisites

- **Java 21 runtime**: Pyserini relies on the Lucene Java toolchain. Ensure `java` (JDK 21) is
  available on the `PATH` before invoking BM25 or SPLADE index builders.

### CLI helpers

BM25 maintenance commands are exposed via the `codeintel` console script:

```console
# prepare a JsonCollection from data/corpus.jsonl (uses BM25_JSONL_DIR by default)
codeintel bm25 prepare-corpus data/corpus.jsonl

# build the Lucene index with an explicit thread override
codeintel bm25 build-index --threads 8
```

Both commands write CLI envelopes beneath `docs/_data/cli/bm25/` and produce
metadata files in the configured directories. The default values shown in the
table above are used when the CLI options are omitted.
- **SPLADE maintenance** adds complementary commands:

```console
# export (optimized + quantized) ONNX artifacts
codeintel splade export-onnx --quantization-config avx512

# encode a JSONL corpus into JsonVectorCollection shards
codeintel splade encode data/corpus.jsonl --batch-size 16

# build the Lucene impact index from vectors
codeintel splade build-index --vectors-dir data/splade_vectors
```

SPLADE commands emit envelopes under `docs/_data/cli/splade/` and attach the
generated metadata files so automation can track build history alongside BM25.
- **Hugging Face authentication**: The `naver/splade-v3` checkpoint is gated. Run
  `huggingface-cli login` (or set `HF_TOKEN`) on any machine that will export or encode SPLADE
  artifacts.

### DuckDB Thread Safety & Pooling

DuckDB connections are managed by `DuckDBManager`, which enforces **per-request connections** so no worker shares stateful `duckdb.DuckDBPyConnection` instances. When `DUCKDB_POOL_SIZE > 0`, the manager reuses connections via a bounded LIFO pool, reducing connection churn while keeping concurrency capped. Leave pooling disabled (`DUCKDB_POOL_SIZE=0`) for most workloads; enable a small pool (8–32) only when sustained parallel queries cause measurable connection overhead.

## Configuration Best Practices

### Development Configuration

For local development, use lazy loading for faster startup:

```bash
export REPO_ROOT=/path/to/repo
export FAISS_PRELOAD=0  # Lazy loading for faster startup
export VLLM_URL=http://127.0.0.1:8001/v1
```

**Benefits**:
- Fast startup (< 1 second)
- No waiting for FAISS index loading
- First request loads index (2-10 seconds added to first query)

### Production Configuration

For production deployments, use eager loading for consistent response times:

```bash
export REPO_ROOT=/var/lib/codeintel/repo
export FAISS_PRELOAD=1  # Eager loading for consistent latency
export FAISS_INDEX=/var/lib/codeintel/faiss/code.ivfpq.faiss
export DUCKDB_PATH=/var/lib/codeintel/catalog.duckdb
export DUCKDB_MATERIALIZE=1  # Persist chunks_materialized table with uri index
export VLLM_URL=http://vllm-service:8001/v1
export MAX_RESULTS=1000
export QUERY_TIMEOUT_S=30.0
```

**Benefits**:
- Consistent response times (no first-request delay)
- Startup validates FAISS index exists and is loadable
- Readiness probe can verify FAISS is actually ready

**Trade-offs**:
- Slower startup (2-10 seconds for FAISS loading)
- Higher memory usage at startup
- Materialized DuckDB catalog requires periodic re-indexing to keep table/index fresh

### Kubernetes Configuration

For Kubernetes deployments, configure environment variables and readiness probes:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: codeintel-mcp
spec:
  template:
    spec:
      containers:
      - name: codeintel-mcp
        image: codeintel-mcp:latest
        env:
        - name: REPO_ROOT
          value: /data/repo
        - name: FAISS_PRELOAD
          value: "1"
        - name: FAISS_INDEX
          value: /data/faiss/code.ivfpq.faiss
        - name: DUCKDB_PATH
          value: /data/catalog.duckdb
        - name: VLLM_URL
          value: http://vllm-service:8001/v1
        volumeMounts:
        - name: data
          mountPath: /data
        readinessProbe:
          httpGet:
            path: /readyz
            port: 8000
          initialDelaySeconds: 10  # Allow time for FAISS pre-loading
          periodSeconds: 5
          timeoutSeconds: 2
          failureThreshold: 3
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: codeintel-data
```

**Key Points**:
- Set `initialDelaySeconds` to account for FAISS pre-loading time
- Use `/readyz` endpoint for readiness probe (validates all resources)
- Use `/healthz` endpoint for liveness probe (basic connectivity check)
- Mount persistent volumes for indexes and data

### Observability Configuration

Observability behavior (metrics, logging, Problem Details) is documented in
[`docs/architecture/observability.md`](architecture/observability.md). Enable
`DUCKDB_LOG_QUERIES=1` in environments where fine-grained query diagnostics are
required; disable it in production to avoid verbose logs.

## Configuration Lifecycle

### Startup Phase

During application startup (`lifespan()` function):

1. **Load Settings**: `load_settings()` reads all environment variables
2. **Validate Paths**: `resolve_application_paths()` converts relative paths to absolute and validates `REPO_ROOT` exists
3. **Initialize Clients**: Create `VLLMClient` and `FAISSManager` instances
4. **Health Checks**: Run readiness probe to verify all resources exist
5. **Optional Pre-loading**: If `FAISS_PRELOAD=1`, load FAISS index immediately
6. **Store Context**: Store `ApplicationContext` in `app.state.context`

**Fail-Fast Behavior**: If any critical resource is missing or invalid, the application fails to start with a clear error message.

### Runtime Phase

During request handling:

- Configuration is **immutable** (frozen dataclasses)
- No re-loading or hot-reloading
- All adapters receive `ApplicationContext` via explicit dependency injection
- Changes require application restart

### Shutdown Phase

During application shutdown:

- Resources explicitly closed
- No dangling connections or locks
- Readiness probe state cleared

## Troubleshooting

### "FAISS index not found"

**Symptom**: Application fails to start with `ConfigurationError: FAISS index not found at {path}`

**Causes**:
- `FAISS_INDEX` environment variable points to non-existent file
- Index file was deleted or moved
- Path resolution failed (relative path not resolved correctly)

**Solutions**:
1. Verify `FAISS_INDEX` points to valid file: `ls -la $(resolve_path $FAISS_INDEX)`
2. Run indexing pipeline: `python bin/index_all.py`
3. Check path resolution: Ensure `REPO_ROOT` is set correctly
4. If using relative paths, ensure they're relative to `REPO_ROOT`

### "Repository root does not exist"

**Symptom**: Application fails to start with `ConfigurationError: Repository root does not exist: {path}`

**Causes**:
- `REPO_ROOT` environment variable is missing or incorrect
- Directory doesn't exist or isn't accessible
- Path is a file, not a directory

**Solutions**:
1. Verify `REPO_ROOT` is set: `echo $REPO_ROOT`
2. Check directory exists: `test -d "$REPO_ROOT" && echo "OK" || echo "Missing"`
3. Verify permissions: `ls -ld "$REPO_ROOT"`
4. Use absolute path: `export REPO_ROOT=$(realpath /path/to/repo)`

### "vLLM service unreachable"

**Symptom**: Readiness probe shows `vllm_service` check as unhealthy

**Causes**:
- vLLM service is not running
- Network connectivity issues
- Incorrect `VLLM_URL` configuration
- Firewall blocking connection

**Solutions**:
1. Verify vLLM is running: `curl http://localhost:8001/v1/health`
2. Check network connectivity: `telnet vllm-host 8001`
3. Verify `VLLM_URL` is correct: `echo $VLLM_URL`
4. Check firewall rules: `sudo ufw status`
5. Test with curl: `curl "$VLLM_URL/embeddings" -H "Content-Type: application/json" -d '{"model":"nomic-ai/nomic-embed-code","input":"test"}'`

### Slow First Query (with FAISS_PRELOAD=0)

**Symptom**: First semantic search request takes 2-10 seconds longer than subsequent requests

**Cause**: FAISS index is loaded lazily on first request

**Solutions**:
1. Enable pre-loading: `export FAISS_PRELOAD=1`
2. Accept the delay: First request loads index, subsequent requests are fast
3. Send a warm-up request after startup: `curl http://localhost:8000/mcp/tools/semantic_search -d '{"query":"test"}'`

### Configuration Changes Not Applied

**Symptom**: Changes to environment variables don't take effect

**Cause**: Configuration is loaded once at startup and cached

**Solution**: Restart the application after changing environment variables

## Path Resolution

All paths are resolved relative to `REPO_ROOT`:

- **Absolute paths**: Used as-is (e.g., `/var/lib/codeintel/faiss/index.faiss`)
- **Relative paths**: Resolved against `REPO_ROOT` (e.g., `data/faiss/index.faiss` → `$REPO_ROOT/data/faiss/index.faiss`)

**Examples**:

```bash
# Absolute path
export FAISS_INDEX=/var/lib/codeintel/faiss/code.ivfpq.faiss

# Relative path (resolved against REPO_ROOT)
export REPO_ROOT=/home/user/kgfoundry
export FAISS_INDEX=data/faiss/code.ivfpq.faiss
# Resolves to: /home/user/kgfoundry/data/faiss/code.ivfpq.faiss
```

## Environment Variable Reference

See `codeintel_rev/config/settings.py` for complete documentation of all configuration options.

## See Also

- `codeintel_rev/app/config_context.py` - Configuration context implementation
- `codeintel_rev/app/readiness.py` - Readiness probe system
- `codeintel_rev/config/settings.py` - Settings dataclasses and defaults
- `AGENTS.md` - Development standards and design principles
- `docs/architecture/bm25.md` - BM25 index management architecture
- `docs/architecture/splade.md` - SPLADE pipeline architecture
- `docs/operations/hybrid_search.md` - Hybrid retrieval operations runbook

