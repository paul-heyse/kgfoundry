# CodeIntel MCP - Best-in-Class Code Intelligence Platform

Production-grade MCP server for AI-assisted code review with SCIP indexing, semantic search, and HTTP/3 streaming.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Client (ChatGPT, Claude, etc via MCP)                      │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTPS (H2/H3)
┌──────────────────────▼──────────────────────────────────────┐
│  NGINX-QUIC (Edge)                                          │
│  - HTTP/3 + H2                                              │
│  - OAuth 2.1 (optional)                                     │
│  - Streaming (proxy_buffering off)                          │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  Hypercorn (ASGI)                                           │
│  - HTTP/2, HTTP/3                                           │
│  - Backpressure-aware streaming                             │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  FastAPI + FastMCP                                          │
│  - /healthz, /readyz, /sse                                  │
│  - /mcp/* (Streamable HTTP)                                 │
│  - Tool catalog (search, symbols, history, etc)             │
└─────────────────────────────────────────────────────────────┘
           │                    │                    │
    ┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐
    │   FAISS     │     │   DuckDB    │     │    vLLM     │
    │   (GPU)     │     │  (Parquet)  │     │ (Embeddings)│
    └─────────────┘     └─────────────┘     └─────────────┘
```

### Observability

- [Observability Architecture Guide](docs/architecture/observability.md) —
  explains the shared metrics helper, naming conventions, resource cleanup, and
  RFC 9457 error handling expectations.

### Capability Snapshot

- `GET /capz` returns a cheap, side-effect-free view of what runtimes and indexes are
  currently available. This is the canonical source for gated MCP tool registration.
- Append `?refresh=true` to recompute the snapshot without restarting the server.

Example response:

```json
{
  "faiss_index_present": true,
  "duckdb_catalog_present": true,
  "scip_index_present": true,
  "vllm_client_ready": true,
  "coderank_index_present": false,
  "warp_index_present": true,
  "xtr_index_present": true,
  "faiss_importable": true,
  "duckdb_importable": true,
  "httpx_importable": true,
  "torch_importable": true,
  "faiss_gpu_available": false,
  "faiss_gpu_disabled_reason": "no-gpu-visible",
  "has_semantic": true,
  "has_symbols": true
}
```

### Sparse Retrieval

- [BM25 Architecture Guide](docs/architecture/bm25.md)
- [SPLADE Architecture Guide](docs/architecture/splade.md)
- [Hybrid Retrieval Runbook](docs/operations/hybrid_search.md)

## Features

- **SCIP-based Indexing**: Uses Sourcegraph SCIP for precise symbol information
- **cAST Chunking**: Structure-aware code chunking (2200 char budget)
- **Semantic Search**: GPU FAISS with cuVS acceleration
- **Hybrid Retrieval**: RRF fusion combining FAISS, BM25, and SPLADE signals
- **HTTP/3 Streaming**: QUIC + proper backpressure for token streams
- **FastMCP Tools**: Full QueryScope catalog (search, symbols, history, docs)
- **Production Edge**: NGINX with OAuth 2.1, streaming optimizations

## Prerequisites

### System Requirements

- Python 3.13.9
- CUDA-capable GPU (for FAISS + vLLM)
- Node.js 16+ (for SCIP Python indexer)
- NGINX with QUIC support (or nginx-quic build)
- 16GB+ RAM recommended
- 10GB+ disk for indexes

### Dependencies

```bash
# Core dependencies (already in environment via bootstrap.sh)
uv add msgspec httpx numpy pyarrow duckdb fastapi starlette fastmcp gitpython

# GPU stack (optional dependencies)
uv add --group gpu faiss vllm torch libcuvs-cu13

# SCIP indexer
npm install -g @sourcegraph/scip-python
```

**Note**: GitPython (>=3.1.43) is required for Git operations. The `git` binary must be available on your system (checked by `scripts/bootstrap.sh`).

## Quick Start

### 1. Bootstrap Environment

```bash
cd /home/paul/kgfoundry
scripts/bootstrap.sh
```

This sets up Python 3.13.9, syncs dependencies, and activates the `.venv`.

### 2. Generate SCIP Index

```bash
cd codeintel-rev
scip-python index ../src --project-name kgfoundry
# Export to JSON for parsing
# (Optional: install scip CLI from github.com/sourcegraph/scip)
# scip print --json index.scip > index.scip.json
```

### 3. Start vLLM Embedding Service

```bash
# Start vLLM with Nomic code embeddings
vllm serve nomic-ai/nomic-embed-code \
  --task embed \
  --dtype bfloat16 \
  --trust-remote-code \
  --port 8001
```

### 4. Run Indexing Pipeline

```bash
cd codeintel-rev

# Set environment
export REPO_ROOT=/home/paul/kgfoundry
export SCIP_INDEX=index.scip.json
export VLLM_URL=http://127.0.0.1:8001/v1

# Run indexer
python bin/index_all.py
```

This will:
1. Parse SCIP index
2. Chunk files using cAST (symbol boundaries)
3. Embed chunks with vLLM
4. Write Parquet with vectors
5. Build FAISS GPU index
6. Initialize DuckDB catalog

### 4a. Maintain Sparse Retrieval Artifacts

```bash
# BM25 corpus normalization and index build
codeintel bm25 prepare-corpus data/corpus.jsonl --output-dir data/jsonl
codeintel bm25 build-index --threads 12

# SPLADE artifact export, encoding, and impact index build
codeintel splade export-onnx --quantization-config avx2
codeintel splade encode data/corpus.jsonl --batch-size 16 --shard-size 50000
codeintel splade build-index --threads 12
```

The CLI commands emit structured envelopes (JSON) with metadata, SHA256 digests,
and can be scheduled in CI for nightly rebuilds. See `codeintel bm25 --help`
and `codeintel splade --help` for full command listings.

### 5. Start MCP Server

```bash
cd codeintel-rev

# Set required environment variables
export REPO_ROOT=/home/paul/kgfoundry
export FAISS_PRELOAD=0  # Lazy loading for development

# Option A: Direct with Hypercorn
hypercorn --config app/hypercorn.toml codeintel_rev.app.main:app

# Option B: Development mode
uvicorn codeintel_rev.app.main:app --reload --port 8000
```

**Note**: The application will fail to start if `REPO_ROOT` is invalid or required resources are missing. This is intentional fail-fast behavior to catch configuration errors early.

### 6. Configure NGINX (Production)

```bash
# Copy NGINX config
sudo cp config/nginx/codeintel-mcp.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/codeintel-mcp.conf /etc/nginx/sites-enabled/

# Update server_name and paths in config
sudo vim /etc/nginx/sites-available/codeintel-mcp.conf

# Test and reload
sudo nginx -t
sudo systemctl reload nginx
```

### 7. Test MCP Server

```bash
# Health check
curl https://localhost:8000/healthz

# Readiness check
curl https://localhost:8000/readyz

# Test SSE streaming
curl https://localhost:8000/sse

# Test MCP tools (requires MCP client)
# Use FastMCP dev server:
mcp dev codeintel_rev/mcp_server/server.py
```

## Configuration

All configuration is via environment variables. Configuration is loaded **once at startup** and shared across all requests via explicit dependency injection.

**See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for comprehensive configuration documentation.**

### Quick Configuration

**Required**:
```bash
export REPO_ROOT=/path/to/repo  # Must exist
```

**Optional** (with defaults):
```bash
export FAISS_PRELOAD=0          # 0 = lazy loading (dev), 1 = eager loading (prod)
export VLLM_URL=http://127.0.0.1:8001/v1
export FAISS_INDEX=data/faiss/code.ivfpq.faiss
export DUCKDB_PATH=data/catalog.duckdb
```

### Configuration Lifecycle

- **Startup**: Configuration loaded once, paths validated, clients initialized
- **Fail-Fast**: Invalid configuration prevents application startup
- **Runtime**: Configuration is immutable (changes require restart)
- **Readiness**: `/readyz` endpoint validates all resources are available

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for:
- Complete environment variable reference
- Development vs production best practices
- Kubernetes deployment guide
- Troubleshooting common configuration errors

## MCP Tools

The server exposes the following tools via FastMCP:

### Scope & Navigation
- `set_scope(scope)` - Set query scope for current session (persists across requests)
- `list_paths(path, globs, max)` - List files (applies session scope filters)
- `open_file(path, start_line, end_line)` - Read file content

### Search
- `search_text(query, regex, paths)` - Fast text search (applies session scope path filters)
- `semantic_search(query, limit)` - Semantic code search (applies session scope language/path filters)

### Symbols
- `symbol_search(query, kind, language)` - Find symbols
- `definition_at(path, line, char)` - Go to definition
- `references_at(path, line, char)` - Find references

### Git History
- `blame_range(path, start_line, end_line)` - Git blame
- `file_history(path, limit)` - Commit history

### Resources
- `file://{path}` - File content as MCP resource

### Prompts
- `prompt_code_review(area)` - Code review template

## Scope Management

Scope management allows you to set query constraints (path patterns, languages, repositories) that persist across multiple requests within a session. Instead of passing scope parameters with every query, you call `set_scope` once and subsequent queries automatically apply those constraints.

### What is Scope?

Scope is a set of query constraints that filter search results. It includes:
- **Path patterns** (`include_globs`, `exclude_globs`): Filter files by path (e.g., `["**/*.py"]`, `["src/**"]`)
- **Languages** (`languages`): Filter files by programming language (e.g., `["python", "typescript"]`)
- **Repositories** (`repos`): Filter by repository (reserved for Phase 3 multi-repo support)
- **Branches** (`branches`): Filter by Git branch (reserved for Phase 4)
- **Commit** (`commit`): Filter by specific commit SHA (reserved for Phase 4)

### Supported Scope Fields

```python
{
    "include_globs": ["**/*.py", "src/**"],      # Files to include
    "exclude_globs": ["**/test_*.py"],          # Files to exclude
    "languages": ["python", "typescript"],      # Programming languages
    "repos": [],                                 # Reserved (Phase 3)
    "branches": [],                              # Reserved (Phase 4)
    "commit": ""                                 # Reserved (Phase 4)
}
```

### Usage Examples

**Set scope to search only Python files:**

```python
# Set scope for current session
result = mcp.call_tool("set_scope", {
    "languages": ["python"]
})
session_id = result["session_id"]  # Save for subsequent requests

# Subsequent searches respect scope
results = mcp.call_tool("semantic_search", {"query": "data processing"})
# Only Python files in results

results = mcp.call_tool("search_text", {"query": "def main"})
# Only searches Python files
```

**Set scope with path patterns:**

```python
# Limit to src/ directory
mcp.call_tool("set_scope", {
    "include_globs": ["src/**"],
    "exclude_globs": ["**/test_*.py"]
})

# All searches now limited to src/ (excluding test files)
results = mcp.call_tool("list_paths", {})
# Only files in src/ directory (no test files)
```

**Override scope with explicit parameters:**

```python
# Set scope to Python files
mcp.call_tool("set_scope", {"languages": ["python"]})

# Override scope for one query (explicit parameters win)
results = mcp.call_tool("list_paths", {
    "include_globs": ["**/*.ts"]
})
# Returns TypeScript files only (scope ignored)

# Next query still uses Python scope
results = mcp.call_tool("semantic_search", {"query": "function"})
# Only Python files (scope still active)
```

**Combine multiple filters:**

```python
# Python files in src/ directory, excluding tests
mcp.call_tool("set_scope", {
    "languages": ["python"],
    "include_globs": ["src/**"],
    "exclude_globs": ["**/test_*.py", "**/__pycache__/**"]
})
```

## Session Management

Scope is stored per-session, allowing multiple clients to use different scopes concurrently without interference.

### Session IDs

Each session is identified by a unique session ID (UUID format). Sessions can be managed in two ways:

**1. Auto-generated (default):**
- If you don't provide a session ID, the server generates one automatically
- The session ID is returned in the `set_scope` response
- Use this session ID in subsequent requests via the `X-Session-ID` header

**2. Client-provided:**
- Send `X-Session-ID` header with your requests
- Use a consistent session ID across multiple requests
- Useful for maintaining scope across client restarts

### Using Session IDs

**With HTTP client:**

```python
import httpx

# First request: set scope (auto-generated session ID)
response = httpx.post(
    "http://localhost:8000/mcp/tools/set_scope",
    headers={"Content-Type": "application/json"},
    json={"languages": ["python"]}
)
session_id = response.json()["session_id"]

# Subsequent requests: include session ID header
response = httpx.post(
    "http://localhost:8000/mcp/tools/semantic_search",
    headers={
        "Content-Type": "application/json",
        "X-Session-ID": session_id  # Include session ID
    },
    json={"query": "data processing"}
)
```

**With MCP client:**

```python
# MCP clients typically handle session management automatically
# Check your MCP client documentation for session ID handling
```

### Session Expiration

Sessions expire after **1 hour of inactivity** (configurable via `SESSION_MAX_AGE_SECONDS` environment variable). When a session expires:
- Scope is cleared automatically
- Subsequent requests without a session ID get a new session
- Expired sessions are pruned by a background task (runs every 10 minutes)

**To prevent expiration:**
- Make requests within the session regularly
- Use explicit parameters instead of scope if you need long-lived constraints
- Re-set scope periodically if needed

## Multi-Repository Support (Future)

**Current Status**: Single-repository mode only.

The `repos` field in `ScopeIn` is **reserved for Phase 3** multi-repository support. Currently:
- Only one repository is indexed per server instance
- The `repos` field is ignored (all queries search the single repository)
- Other scope fields (globs, languages) work as documented

**Future (Phase 3):**
- Multiple repositories can be indexed in a single server instance
- `repos` field will select which repositories to query
- Cross-repository queries will be supported
- Each repository will have its own FAISS index and DuckDB catalog

**Migration Path:**
- Current code is forward-compatible with multi-repo architecture
- No changes needed when Phase 3 is released
- Simply start using the `repos` field when available

## Development

### Project Structure

```
codeintel-rev/
├── app/                  # FastAPI application
├── bin/                  # CLI scripts (index_all.py)
├── config/               # Configuration files
│   └── nginx/            # NGINX configs
├── indexing/             # SCIP reader, cAST chunker
├── io/                   # Storage (Parquet, DuckDB, FAISS, vLLM)
├── mcp_server/           # FastMCP server + tools
├── retrieval/            # Hybrid search (RRF)
└── tests/                # Tests
```

### Running Tests

```bash
# Unit tests (CPU-only workstations)
SKIP_GPU_WARMUP=1 uv run pytest tests/ -v

# Drop the env var on CUDA-capable hosts to exercise the GPU warm-up.

# With coverage
SKIP_GPU_WARMUP=1 uv run pytest tests/ --cov=codeintel_rev --cov-report=html
```

### Quality Gates

```bash
# Format and lint
uv run ruff format codeintel-rev/
uv run ruff check --fix codeintel-rev/

# Type check
uv run pyright codeintel-rev/
uv run pyrefly check

# Security scan
uv run pip-audit
```

## OAuth 2.1 Setup (Optional)

### Using oauth2-proxy

```bash
# Install oauth2-proxy
wget https://github.com/oauth2-proxy/oauth2-proxy/releases/download/v7.4.0/oauth2-proxy-v7.4.0.linux-amd64.tar.gz
tar -xzf oauth2-proxy-v7.4.0.linux-amd64.tar.gz

# Configure
cat > oauth2-proxy.cfg <<EOF
http_address = "127.0.0.1:4180"
upstreams = ["http://127.0.0.1:8000"]
provider = "oidc"
client_id = "YOUR_CLIENT_ID"
client_secret = "YOUR_CLIENT_SECRET"
oidc_issuer_url = "https://YOUR_IDP/.well-known/openid-configuration"
cookie_secret = "$(openssl rand -base64 32)"
email_domains = ["yourdomain.com"]
EOF

# Run
./oauth2-proxy --config oauth2-proxy.cfg
```

### NGINX OAuth Integration

Uncomment the `auth_request` directives in `config/nginx/codeintel-mcp.conf`.

## Performance Tuning

### Adaptive FAISS Indexing

The FAISS index type is **automatically selected** based on corpus size for optimal performance:

- **Small corpus (<5K vectors)**: Flat index (`IndexFlatIP`)
  - Fast training (no training required)
  - Exact search
  - Best for small codebases or development

- **Medium corpus (5K-50K vectors)**: IVFFlat (`IndexIVFFlat`)
  - Balanced training time and recall
  - Dynamic `nlist` calculation: `min(√N, N//39)` with minimum 100
  - Good for medium-sized codebases

- **Large corpus (>50K vectors)**: IVF-PQ (`IndexIVFPQ`)
  - Memory-efficient with Product Quantization
  - Dynamic `nlist` calculation: `max(√N, 1024)`
  - Best for large codebases (100K+ chunks)

**Memory Estimation**:
```python
from codeintel_rev.io.faiss_manager import FAISSManager

manager = FAISSManager(index_path=Path("index.faiss"), vec_dim=3584)
estimates = manager.estimate_memory_usage(n_vectors=100_000)
print(f"CPU: {estimates['cpu_index_bytes']/1e9:.2f} GB")
print(f"GPU: {estimates['gpu_index_bytes']/1e9:.2f} GB")
print(f"Total: {estimates['total_bytes']/1e9:.2f} GB")
```

**Manual Override** (if needed):
```bash
# Force specific nlist (used as fallback for large corpora)
export FAISS_NLIST=16384  # More centroids = better recall, slower training
export FAISS_NPROBE=256   # More probes = better recall, slower live searches

# Enable cuVS acceleration (requires custom FAISS wheel)
export USE_CUVS=1
```

### Incremental Index Updates

For large codebases, use **incremental indexing** to add new chunks without rebuilding the entire index:

```bash
# Initial indexing (full rebuild)
python bin/index_all.py

# Later: add new chunks incrementally (fast - seconds instead of hours)
python bin/index_all.py --incremental
```

**How it works**:
- New chunks are added to a **secondary flat index** (no training required)
- Search automatically queries both primary and secondary indexes
- Results are merged by similarity score
- Periodically merge secondary into primary for optimal performance

**Merge secondary index** (periodic maintenance):
```python
from codeintel_rev.io.faiss_manager import FAISSManager

manager = FAISSManager(index_path=Path("index.faiss"), vec_dim=3584)
manager.load_cpu_index()
manager.load_secondary_index()  # If exists
manager.merge_indexes()  # Rebuilds primary with all vectors
manager.save_cpu_index()
```

**When to merge**:
- After accumulating significant new chunks (e.g., 10K+ in secondary)
- Before major deployments (ensures optimal search performance)
- During low-traffic periods (merge is expensive but faster than full rebuild)

### HTTP Connection Pooling

The vLLM client uses **persistent HTTP connections** to reduce overhead:

- Connections are reused across multiple embedding requests
- Automatic connection pooling (configurable limits)
- Connections are closed during application shutdown (via `lifespan`)

**Connection Limits**:
```bash
# Adjust connection pool size (default: auto-detected)
export VLLM_MAX_CONNECTIONS=10
export VLLM_MAX_KEEPALIVE_CONNECTIONS=5
```

**Note**: The `VLLMClient.close()` method is called automatically during application shutdown. Manual cleanup is only needed if creating clients outside the application lifecycle.

### Async Operations

All I/O operations are **asynchronous** to enable high concurrency:

- **Git operations**: Blame and history use `AsyncGitClient` (threadpool offload)
- **File operations**: Directory traversal uses `asyncio.to_thread`
- **Search operations**: FAISS search is CPU-bound but non-blocking

**Concurrency Benefits**:
- Multiple requests can be processed concurrently
- No thread exhaustion (operations offloaded to threadpool)
- Better resource utilization under load

**Concurrency Limits**:
- Default threadpool size: `min(32, (os.cpu_count() or 1) + 4)`
- Adjust via `asyncio.set_event_loop_policy()` if needed
- Monitor thread usage via application metrics

### vLLM Embedding Service

```bash
# Increase batch size for throughput
export VLLM_BATCH_SIZE=128

# Enable tensor parallelism for large models
vllm serve ... --tensor-parallel-size 2
```

### DuckDB Catalog

```bash
# Increase memory limit
export DUCKDB_MEMORY_LIMIT=8GB

# Enable parallel query execution
export DUCKDB_THREADS=8

# Enable bounded connection pool (reuse connections under high concurrency)
export DUCKDB_POOL_SIZE=16
```

DuckDB access is handled by `DuckDBManager`, which ensures:
- **Thread safety**: every request obtains its own connection; no shared global connection objects.
- **Connection hygiene**: pragmas (`PRAGMA enable_object_cache`, `SET threads`) are applied on every new connection.
- **Optional pooling**: when `DUCKDB_POOL_SIZE` is set, connections are stored in a LIFO pool to reduce open/close churn while keeping concurrency bounded.
- **Structured logging**: enable `DUCKDB_LOG_QUERIES=1` during debugging to trace SQL statements.

For workloads with bursty concurrency, start with a small pool (e.g., 8–16 connections) and monitor CPU utilization. Leaving pooling disabled (`DUCKDB_POOL_SIZE=0`) falls back to per-request connections, which is sufficient for most deployments.

## Troubleshooting

### Scope not applied

**Symptoms**: Queries return results outside the set scope.

**Causes and Solutions**:

1. **Session ID mismatch**: Ensure you're using the same session ID across requests.
   ```python
   # ❌ Wrong: Different session IDs
   session1 = mcp.call_tool("set_scope", {...})["session_id"]
   # ... later, new request without session ID header
   results = mcp.call_tool("semantic_search", {...})  # New session, no scope
   
   # ✅ Correct: Use same session ID
   session_id = mcp.call_tool("set_scope", {...})["session_id"]
   # Include X-Session-ID header in subsequent requests
   ```

2. **Session expired**: Sessions expire after 1 hour of inactivity.
   ```python
   # Re-set scope if session expired
   mcp.call_tool("set_scope", {...})
   ```

3. **Explicit parameters override scope**: Explicit parameters always take precedence.
   ```python
   # Scope: Python files only
   mcp.call_tool("set_scope", {"languages": ["python"]})
   
   # This query ignores scope (explicit override)
   results = mcp.call_tool("list_paths", {"include_globs": ["**/*.ts"]})
   # Returns TypeScript files, not Python
   ```

### Unexpected results

**Symptoms**: Results don't match expected scope constraints.

**Causes and Solutions**:

1. **Verify scope was set**: Check `set_scope` response includes your scope.
   ```python
   result = mcp.call_tool("set_scope", {"languages": ["python"]})
   assert result["effective_scope"]["languages"] == ["python"]
   ```

2. **Check explicit parameter precedence**: Explicit parameters override scope.
   ```python
   # If you pass include_globs explicitly, it overrides scope's include_globs
   # Remove explicit parameters to use scope defaults
   ```

3. **Verify glob patterns**: Ensure glob patterns match your file structure.
   ```python
   # Test glob patterns with list_paths first
   results = mcp.call_tool("list_paths", {"include_globs": ["**/*.py"]})
   # Verify expected files are returned before setting scope
   ```

### High Memory Usage

**Symptoms**: Application uses excessive memory, especially during indexing.

**Solutions**:
1. **Use incremental indexing** instead of full rebuilds:
   ```bash
   python bin/index_all.py --incremental  # Fast, low memory
   ```

2. **Adjust FAISS parameters** for smaller indexes:
   ```bash
   export FAISS_NLIST=4096  # Fewer centroids = less memory
   ```

3. **Check memory estimates** before indexing:
   ```python
   from codeintel_rev.io.faiss_manager import FAISSManager
   estimates = FAISSManager(...).estimate_memory_usage(n_vectors)
   ```

4. **Periodically merge secondary index** to consolidate memory usage

### Slow Indexing

**Symptoms**: Full index rebuild takes hours.

**Solutions**:
1. **Use incremental mode** for adding new chunks:
   ```bash
   python bin/index_all.py --incremental  # Seconds instead of hours
   ```

2. **Verify adaptive indexing** is working (check logs for index type selection)

3. **Reduce training limit** for very large corpora (if acceptable):
   ```python
   # In index_all.py, reduce TRAINING_LIMIT
   TRAINING_LIMIT = 5_000  # Smaller = faster training, potentially lower recall
   ```

### Thread Exhaustion

**Symptoms**: Requests hang or timeout under load.

**Solutions**:
- **Async operations are already enabled** - all I/O uses `asyncio.to_thread`
- Check threadpool size: `asyncio.get_event_loop()._default_executor._max_workers`
- Monitor concurrent request count via application metrics
- Consider horizontal scaling if single instance is saturated

### FAISS GPU fails

```bash
# Check CUDA availability
python -c "import torch; print(torch.cuda.is_available())"

# Run GPU diagnostics
python -m codeintel_rev.mcp_server.tools.gpu_doctor --require-gpu

# Fallback to CPU-only FAISS
export USE_CUVS=0
# Or install CPU-only FAISS
uv add faiss-cpu
```

### vLLM connection issues

```bash
# Test vLLM directly
curl http://localhost:8001/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"nomic-ai/nomic-embed-code","input":"test"}'
```

### HTTP/3 not working

```bash
# Verify QUIC/UDP port open
sudo ufw allow 443/udp

# Check NGINX QUIC module
nginx -V 2>&1 | grep quic

# Test with curl
curl --http3 -I https://localhost/healthz
```

## License

See main project LICENSE.

## References

- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [SCIP Protocol](https://github.com/sourcegraph/scip)
- [Nomic Embed Code](https://huggingface.co/nomic-ai/nomic-embed-code)
- [vLLM Documentation](https://docs.vllm.ai/)
- [FAISS Wiki](https://github.com/facebookresearch/faiss/wiki)
- [AGENTS.md](../AGENTS.md) - Development standards
