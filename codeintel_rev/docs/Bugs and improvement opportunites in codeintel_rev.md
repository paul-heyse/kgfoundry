# Bugs and improvement opportunites in codeintel_rev #

## Holistic overview

CodeIntel MCP provides a FastAPI app that mounts a FastMCP tool server to expose code-intelligence capabilities over HTTP/2/3 with structured error handling and explicit configuration injection. The architecture centers on:
- FastAPI app (`app/`) with lifecycle, readiness, CORS, and streaming
- FastMCP tool handlers (`mcp_server/`) delegating to adapters for files, search, git history
- IO layer (`io/`) for FAISS, DuckDB, Parquet, Git, vLLM
- Indexing utilities (`indexing/`), and hybrid retrieval (`retrieval/`)
- Centralized, immutable settings via `msgspec` (`config/settings.py`)

The design aligns with AGENTS.md: explicit deps, no global state, typed config, structured errors, and observability hooks. Key areas to tighten are readiness semantics, a few doc path inconsistencies, and consolidating limits/defaults across tools to use `Settings.limits`.

## Bugs ##

- File: README.md
  - Inconsistent project path uses `codeintel-rev` (hyphen) while the actual module path is `codeintel_rev` (underscore). Commands like `cd codeintel-rev`, `ruff format codeintel-rev/`, etc., will fail on this repo layout.

- File: app/main.py
  - Readiness endpoint always returns HTTP 200 even when checks fail, which breaks Kubernetes readiness gating (K8s relies on status codes). It should return 503 when not ready.
    - Impact: Pods may be marked Ready prematurely; traffic can be routed before FAISS/vLLM/catalog are ready.

- File: docs/CONFIGURATION.md
  - States FAISS/DuckDB “must exist for startup,” but current app lifecycle does not fail-fast on readiness checks; it initializes and serves while `/readyz` flags unhealthy. This is inconsistent with the description (“Fail-Fast”) and could confuse operators.

- File: mcp_server/server.py
  - `file_resource()` returns a plain error string when file read fails rather than a Problem Details envelope (inconsistent with tool error handling). Resource contract is string, but message format inconsistency makes client handling brittle.

- File: mcp_server/adapters/text_search.py
  - Fallback to `grep` ignores scope path/language filters. When `rg` is unavailable, results may include files outside the intended scope, diverging from ripgrep semantics.

- File: io/faiss_manager.py
  - Module-level `faiss` import via `gate_import` at import time prevents graceful CPU-only/text-only operation when FAISS isn’t installed. Importing this module (and anything that depends on it) will fail instead of degrading.

## Improvement opportunites ##

- File: README.md
  - Standardize all paths and commands to `codeintel_rev` (underscore). Update all `cd`, `ruff`, `pyright`, and Hypercorn examples.
  - Ensure Quick Start sections reference repo-root consistent with `REPO_ROOT` examples and actual tree.
  - Consider adding a short “Readiness semantics” note explaining `/readyz` status codes (after fixing).

- File: QUICKSTART.md
  - The “FastMCP upstream bug” note should be version-pinned and time-bounded. Prefer documenting an explicit compatible version constraint (e.g., `fastmcp<0.5.0`) in `pyproject.toml` and removing once upstream is fixed.

- File: docs/CONFIGURATION.md
  - Clarify startup vs readiness behavior: either (a) fail-fast on missing critical resources or (b) document that startup succeeds and `/readyz` governs gating (recommended with proper 503 status).
  - Add explicit examples for `/readyz` returning 503 when not ready, 200 when ready.

- File: app/main.py
  - Return 503 when not ready: set HTTP status based on `overall_ready`.
  - Consider adding a query flag (e.g., `?soft=1`) if a 200-always variant is needed for non-K8s consumers.
  - Log readiness transitions (unhealthy→healthy) at INFO with structured fields.

- File: mcp_server/server.py
  - Align default `max_results` and other limits with `Settings.limits` to centralize tuning.
  - Normalize resource error behavior: either encode Problem Details text consistently or provide a dedicated error resource type.
  - Implement `symbol_search/definition_at/references_at` or mark as experimental with explicit capability flags.

- File: config/settings.py
  - Optionally validate `repo_root` existence during context creation (or here with a guard) and document the fail strategy.
  - Consider exposing a single helper for parsing booleans to ensure consistent env parsing across modules.

- File: app/config_context.py
  - The lifespan docstring mentions starting a background pruning task for expired sessions, but ScopeStore relies on TTL semantics. Either implement a lightweight periodic L1 prune or update docs to reflect TTL-only design.

- File: app/scope_registry.py
  - Appears unused given the Redis-backed `ScopeStore`. Consider removing to reduce duplication, or clearly mark as deprecated in favor of `ScopeStore`.

- File: mcp_server/adapters/text_search.py
  - Extend grep fallback to honor include/exclude globs and (optionally) languages. If feature parity is too heavy, clearly document the degraded behavior and warn via `limits` metadata.

- File: io/faiss_manager.py
  - Defer `faiss` import to method boundaries (e.g., inside `build_index`, `load_cpu_index`, `search`) and handle ImportError with a clear Problem Details pathway so text/BM25-only deployments can run.
  - Consider factoring GPU detection and cuVS loading into an injectable strategy for easier testing and CPU-only environments.

- File: io/faiss_dual_index.py
  - Overlaps with `FAISSManager` functionality. Consider consolidating into a single manager to avoid maintenance duplication; if kept, clearly document its intended usage and ensure it’s integrated or moved under an experimental namespace.

- File: io/TEMP_BM25+SPLADE_GUIDE/playbook.py
  - Fine as a CLI utility, but consider relocating under `tools/` or `examples/` and adding a short README. Ensure optional dependencies are clearly noted and not imported by the server runtime.

- Cross-cutting
  - Add Problem Details examples for adapter failure paths in docs, mirroring AGENTS.md.
  - Ensure observability (metrics/logging) is consistently emitted at boundaries (e.g., readiness, adapter calls).



## Improvement opportunites ##