# Test Patching and Mocking Review

**Date**: 2025-01-27  
**Scope**: Complete review of `tests/` directory for violations of Testing Charter (AGENTS.md Section 2)

## Executive Summary

This review identifies **18 files** using `unittest.mock.patch` (runtime patching), **67 files** with Stub/Fake/Mock classes, and **0 files** using `monkeypatch` fixture. The Testing Charter explicitly prohibits runtime patching and requires dependency injection, configuration, or explicit selectable implementations instead.

---

## 1. Runtime Patching Violations (`unittest.mock.patch`)

### Files Using `patch()` Decorator/Context Manager

**Total: 18 files**

| File | Pattern | Purpose | Violation Type |
|------|---------|---------|----------------|
| `tests/codeintel_rev/test_vllm_client.py` | `patch.object()` | Patching `client.embed_batch` method | Runtime method patching |
| `tests/codeintel_rev/test_text_search_adapter.py` | `patch()` module-level | Patching `get_session_id`, `get_effective_scope` | Module-level patching |
| `tests/codeintel_rev/test_git_client.py` | `patch()` module-level | Patching `git.Repo` factory | External library patching |
| `tests/codeintel_rev/test_readiness.py` | `patch()` | Patching readiness probe dependencies | Dependency patching |
| `tests/codeintel_rev/test_history_adapter.py` | `patch()` | Patching Git client methods | Adapter dependency patching |
| `tests/codeintel_rev/test_files_adapter.py` | `patch()` | Patching file system operations | I/O patching |
| `tests/codeintel_rev/test_scope_integration.py` | `patch()` | Patching scope store | State patching |
| `tests/codeintel_rev/load/test_concurrent_adapters.py` | `patch()` | Patching async Git client | Async dependency patching |
| `tests/codeintel_rev/benchmarks/test_async_adapters.py` | `patch()` | Patching async adapters | Performance test patching |
| `tests/codeintel_rev/test_app_lifespan.py` | `patch()` | Patching lifespan hooks | Lifecycle patching |
| `tests/app/test_admin_index.py` | `patch()` | Patching admin endpoints | Route patching |
| `tests/codeintel_rev/test_integration_full.py` | `patch()` | Patching integration components | Integration patching |
| `tests/codeintel_rev/test_integration_smoke.py` | `patch()` | Patching smoke test dependencies | Smoke test patching |
| `tests/orchestration/test_cli_refactor.py` | `patch()` | Patching CLI commands | CLI patching |
| `tests/kgfoundry_common/test_optional_deps.py` | `mock.patch()` | Patching optional dependency checks | Dependency gate patching |
| `tests/codeintel_rev/conftest.py` | `patch()` (indirect) | Used in fixtures | Fixture-level patching |
| `tests/app/_context_factory.py` | `MagicMock()` | Creating mock dependencies | Mock factory usage |
| `tests/tools/test_cli_context_registry.py` | `patch()` | Patching CLI context registry | Registry patching |

### Common Patterns

1. **Module-level patching**: `patch("module.path.function")` - replaces functions at import time
2. **Object patching**: `patch.object(obj, "method")` - replaces methods on instances
3. **Factory patching**: `patch("module.Class")` - replaces class constructors
4. **Context manager usage**: `with patch(...):` - temporary runtime replacement

---

## 2. Mock/Stub/Fake Classes

### Files with Test Doubles

**Total: 67 files** (partial list of most significant)

#### Category A: Protocol/Interface Implementations (Acceptable Pattern)

These implement real interfaces but with simplified behavior:

- `tests/codeintel_rev/conftest.py`: `_FakeRedis` - In-memory Redis implementation
- `tests/io/test_sparse_engines.py`: `_StubSpladeBackend`, `_StubBM25Backend` - Backend protocol implementations
- `tests/retrieval/pipeline/test_stage0.py`: `_StubHybridEngine` - Hybrid engine stub
- `tests/retrieval/pipeline/test_late_interaction.py`: `_StubXTRIndex` - XTR index stub

**Assessment**: These follow the Testing Charter if they:
- Implement the same interface as production
- Are injected via configuration/DI (not patched)
- Preserve key invariants

#### Category B: MagicMock Usage (Violation)

These use `MagicMock()` which bypasses production code entirely:

- `tests/app/_context_factory.py`: `MagicMock()` for `vllm_client`, `faiss_manager`, `scope_store`, `git_client`
- `tests/codeintel_rev/test_vllm_client.py`: `MagicMock()` for `embed_batch` return values
- `tests/codeintel_rev/conftest.py`: `MagicMock()`, `AsyncMock()` for various dependencies
- `tests/codeintel_rev/test_app_lifespan.py`: `MagicMock()` for lifespan components
- `tests/app/test_admin_index.py`: `MagicMock()` for scope store

**Assessment**: **Violation** - MagicMock skips all production logic, making tests validate mocks rather than real behavior.

#### Category C: Stub Classes with Minimal Implementation

These provide deterministic test behavior but may skip production logic:

- `tests/cli/test_indexctl_embeddings.py`: `_StubProvider` - Embedding provider stub
- `tests/cli/test_indexctl_health.py`: `_ManagerStub`, `_ConnectionStub`, `_CatalogStub` - Database stubs
- `tests/codeintel_rev/test_offline_eval.py`: `_StubFAISSManager`, `_StubVLLMClient` - Evaluation stubs
- `tests/codeintel_rev/test_scip_coverage.py`: `_StubFaissManager`, `_StubVLLMClient` - Coverage stubs
- `tests/mcp/test_search_fetch_golden.py`: `_StubEmbedder`, `_StubFaissRuntime`, `_StubCatalog` - Golden test stubs

**Assessment**: **Needs Review** - Depends on whether they:
- Skip critical production logic (serialization, validation, error handling)
- Are injected via DI vs runtime patching
- Could be replaced with isolated real instances

---

## 3. Specific Violation Examples

### Example 1: Module-Level Patching (`test_text_search_adapter.py`)

```python
with patch("codeintel_rev.mcp_server.adapters.text_search.get_session_id", return_value="session-123"):
    # Test code
```

**Issue**: Replaces production function at runtime, bypassing real session ID logic.

**Recommended Fix**: Inject session ID provider via dependency injection or use real `ScopeStore` with test data.

### Example 2: Object Method Patching (`test_vllm_client.py`)

```python
mock_embed_batch = MagicMock()
with patch.object(client, "embed_batch", mock_embed_batch):
    result = client.embed_chunks([], batch_size=4)
```

**Issue**: Patches method on instance, skipping real `embed_batch` implementation.

**Recommended Fix**: Use transport context injection (already partially implemented) to provide test HTTP clients.

### Example 3: Factory Patching (`test_git_client.py`)

```python
with patch("codeintel_rev.io.git_client.git.Repo", return_value=mock_repo):
    repo = git_client.repo
```

**Issue**: Replaces GitPython `Repo` constructor, skipping real Git repository initialization.

**Recommended Fix**: Use real Git repositories in temporary directories or inject `Repo` instance via `with_cached_repo()` (already supported).

### Example 4: MagicMock Dependencies (`_context_factory.py`)

```python
return ApplicationContext(
    vllm_client=MagicMock(),
    faiss_manager=MagicMock(),
    scope_store=MagicMock(),
    git_client=MagicMock(),
    # ...
)
```

**Issue**: All dependencies are mocks, so tests validate mock behavior, not production integration.

**Recommended Fix**: Use real instances with isolated test data (temporary directories, in-memory stores).

---

## 4. Acceptable Patterns Found

### Pattern 1: Dependency Injection via Configuration

**Example**: `tests/_helpers/settings.py` - `build_settings_for_repo()` creates real `Settings` with test paths.

**Status**: ✅ Compliant - Uses configuration, not patching.

### Pattern 2: Explicit Test Doubles via DI

**Example**: `tests/codeintel_rev/test_vllm_client.py` - `_build_transport_context()` injects test HTTP clients.

**Status**: ✅ Compliant - Uses factory injection, not runtime patching.

### Pattern 3: Real Instances with Isolated Data

**Example**: `tests/_helpers/catalog.py` - `build_graph_catalog_fixture()` creates real `DuckDBCatalog` with test data.

**Status**: ✅ Compliant - Uses same technology (DuckDB) with isolated instances.

---

## 5. Recommendations

### Priority 1: Remove Runtime Patching

1. **Replace `patch()` calls** with dependency injection:
   - Module functions → inject via parameters or context
   - Class methods → inject via constructor/factory
   - External libraries → use real instances with test data

2. **Refactor test fixtures** to accept dependencies:
   ```python
   # Before
   with patch("module.function", return_value=value):
       test_code()
   
   # After
   def test_function(dependency: Dependency = test_dependency):
       test_code()
   ```

### Priority 2: Replace MagicMock with Real Instances

1. **Use real implementations** with test data:
   - `MagicMock()` → Real class instances with temporary directories/files
   - `AsyncMock()` → Real async implementations with test data
   - `Mock(spec=...)` → Real instances conforming to spec

2. **Create test factories** that return real instances:
   ```python
   # Before
   context = ApplicationContext(..., scope_store=MagicMock())
   
   # After
   def build_test_context(tmp_path: Path) -> ApplicationContext:
       scope_store = ScopeStore(redis=_FakeRedis())  # Real class, test data
       return ApplicationContext(..., scope_store=scope_store)
   ```

### Priority 3: Audit Stub Classes

1. **Review each stub** to ensure it:
   - Implements the full interface (not just happy path)
   - Preserves serialization/validation logic
   - Could plausibly be used in dev/staging

2. **Replace stubs that skip critical logic** with:
   - Real implementations with test data
   - In-memory/test-friendly variants (e.g., `_FakeRedis`)

### Priority 4: Establish Test Patterns

1. **Create helper factories** for common test dependencies:
   - `build_test_git_client(repo_path: Path) -> GitClient`
   - `build_test_scope_store() -> ScopeStore`
   - `build_test_catalog(tmp_path: Path) -> DuckDBCatalog`

2. **Document approved patterns** in `tests/_helpers/README.md` (already started)

---

## 6. Files Requiring Immediate Attention

### High Priority (Runtime Patching)

1. `tests/codeintel_rev/test_text_search_adapter.py` - 6 `patch()` calls
2. `tests/codeintel_rev/test_git_client.py` - 4 `patch()` calls
3. `tests/codeintel_rev/test_vllm_client.py` - 1 `patch.object()` call
4. `tests/codeintel_rev/test_readiness.py` - Multiple `patch()` calls
5. `tests/codeintel_rev/test_history_adapter.py` - Multiple `patch()` calls
6. `tests/codeintel_rev/test_files_adapter.py` - Multiple `patch()` calls

### Medium Priority (MagicMock Dependencies)

1. `tests/app/_context_factory.py` - 5 `MagicMock()` instances
2. `tests/codeintel_rev/conftest.py` - Multiple `MagicMock()`/`AsyncMock()` instances
3. `tests/codeintel_rev/test_app_lifespan.py` - `MagicMock()` dependencies

### Low Priority (Stub Classes - Review Needed)

1. `tests/cli/test_indexctl_health.py` - Database stubs (may be acceptable if they preserve SQL semantics)
2. `tests/codeintel_rev/test_offline_eval.py` - Evaluation stubs (may skip critical logic)
3. `tests/mcp/test_search_fetch_golden.py` - Golden test stubs (may be acceptable for deterministic outputs)

---

## 7. Compliance Status

| Category | Count | Status |
|----------|-------|--------|
| `monkeypatch` fixture usage | 0 | ✅ Compliant |
| `unittest.mock.patch` usage | 18 files | ❌ Violation |
| `MagicMock()` usage | ~15 files | ❌ Violation |
| Stub/Fake classes | 67 files | ⚠️ Needs Review |
| Dependency injection patterns | ~10 files | ✅ Compliant |

---

## 8. Next Steps

1. **Create migration plan** for each high-priority file
2. **Establish test factories** for common dependencies
3. **Update Testing Charter** with specific examples of approved patterns
4. **Add pre-commit hook** to detect `patch()` usage (optional)
5. **Refactor incrementally** starting with highest-impact tests

---

## Appendix: Complete File List

### Runtime Patching Files (18)
- `tests/codeintel_rev/benchmarks/test_async_adapters.py`
- `tests/codeintel_rev/test_vllm_client.py`
- `tests/codeintel_rev/test_scope_integration.py`
- `tests/codeintel_rev/load/test_concurrent_adapters.py`
- `tests/codeintel_rev/test_app_lifespan.py`
- `tests/app/test_admin_index.py`
- `tests/codeintel_rev/test_integration_full.py`
- `tests/codeintel_rev/test_text_search_adapter.py`
- `tests/codeintel_rev/conftest.py`
- `tests/app/_context_factory.py`
- `tests/codeintel_rev/test_readiness.py`
- `tests/codeintel_rev/test_history_adapter.py`
- `tests/codeintel_rev/test_files_adapter.py`
- `tests/codeintel_rev/test_integration_smoke.py`
- `tests/orchestration/test_cli_refactor.py`
- `tests/kgfoundry_common/test_optional_deps.py`
- `tests/codeintel_rev/test_git_client.py`
- `tests/tools/test_cli_context_registry.py`

### Stub/Fake/Mock Class Files (67 - Representative Sample)
- `tests/cli/test_indexctl_embeddings.py`
- `tests/codeintel_rev/_faiss_stub.py`
- `tests/io/test_splade_onnx_encoder.py`
- `tests/codeintel_rev/mcp_server/test_semantic_pro_adapter.py`
- `tests/codeintel_rev/benchmarks/test_async_adapters.py`
- `tests/conftest.py`
- `tests/cli/test_indexctl_health.py`
- `tests/codeintel_rev/io/test_rerank_coderankllm.py`
- `tests/codeintel_rev/eval/test_hybrid_evaluator.py`
- `tests/mcp/test_search_fetch_golden.py`
- `tests/codeintel_rev/test_vllm_client.py`
- `tests/codeintel_rev/test_scope_integration.py`
- `tests/io/test_faiss_runtime.py`
- `tests/io/test_sparse_engines.py`
- `tests/orchestration/test_cli_envelopes.py`
- `tests/retrieval/pipeline/test_stage0.py`
- `tests/retrieval/test_refine_rerank.py`
- `tests/retrieval/pipeline/test_late_interaction.py`
- `tests/plugins/test_registry.py`
- `tests/mcp/test_tools_contract.py`
- `tests/mcp/test_registry_contracts.py`
- `tests/io/test_faiss_runtime_dual_merge.py`
- `tests/codeintel_rev/load/test_concurrent_adapters.py`
- `tests/codeintel_rev/test_scip_coverage.py`
- `tests/app/test_admin_index.py`
- `tests/codeintel_rev/test_offline_eval.py`
- `tests/codeintel_rev/test_semantic_adapter.py`
- `tests/codeintel_rev/test_bm25_cli.py`
- `tests/codeintel_rev/test_splade_cli.py`
- `tests/codeintel_rev/test_splade_manager.py`
- `tests/codeintel_rev/io/test_coderank_embedder.py`
- `tests/codeintel_rev/io/test_vllm_engine.py`
- `tests/codeintel_rev/test_text_search_adapter.py`
- `tests/codeintel_rev/test_text_search.py`
- `tests/app/test_runtime_gates.py`
- `tests/app/test_lifespan_runtime_cleanup.py`
- `tests/codeintel_rev/test_bm25_manager.py`
- `tests/codeintel_rev/conftest.py`
- `tests/codeintel_rev/test_scope_store.py`
- `tests/app/_context_factory.py`
- `tests/codeintel_rev/test_readiness.py`
- `tests/codeintel_rev/test_service_context_paths.py`
- `tests/codeintel_rev/test_history_adapter.py`
- `tests/codeintel_rev/test_files_adapter.py`
- `tests/embeddings/test_provider_shape.py`
- `tests/_helpers/imports.py`
- `tests/retrieval/pipeline/test_gating.py`
- `tests/search_api/test_client_idempotency.py`
- `tests/test_typing_facade.py`
- `tests/app/test_capz.py`
- `tests/test_cli_runtime.py`
- `tests/codeintel_rev/test_integration_smoke.py`
- `tests/codeintel_rev/test_mcp_server.py`
- `tests/codeintel_rev/test_enrich_overlays.py`
- `tests/bootstrap.py`
- `tests/search_api/test_faiss_adapter.py`
- `tests/codeintel_rev/test_git_client.py`
- `tests/tools/test_check_stub_parity.py`
- ... (additional files)

---

**Review Completed**: 2025-01-27  
**Next Review**: After migration of high-priority files

