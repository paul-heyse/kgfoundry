# Test Patching and Mocking Review

**Date**: 2025-11-20  
**Previous Review**: 2025-01-27  
**Scope**: Complete review of `tests/` directory for violations of Testing Charter (AGENTS.md Section 2)

## Executive Summary

This review identifies **0 files** using `unittest.mock.patch` (runtime patching) ✅, **1 file** using `monkeypatch` fixture ⚠️, **4 files** using `MagicMock`/`AsyncMock` ❌, and **35 files** with Stub/Fake/Mock classes ⚠️. The Testing Charter explicitly prohibits runtime patching and requires dependency injection, configuration, or explicit selectable implementations instead.

**Major Progress**: All `unittest.mock.patch` calls have been removed (down from 18 files). MagicMock usage reduced from ~15 files to 4 files.

---

## 1. Runtime Patching Violations (`unittest.mock.patch`)

### Files Using `patch()` Decorator/Context Manager

**Total: 0 files** ✅

**Status**: **COMPLIANT** - All `unittest.mock.patch` calls have been successfully removed from the test suite.

**Previous Status**: 18 files were using runtime patching. All have been migrated to dependency injection or removed.

---

## 2. Monkeypatch Fixture Usage

### Files Using `monkeypatch` Fixture

**Total: 1 file** ⚠️

| File | Pattern | Purpose | Violation Type |
|------|---------|---------|----------------|
| `tests/dist/test_extras_minimal_import.py` | `monkeypatch.setattr()` | Simulating missing optional dependencies | Import simulation |

**Assessment**: This test validates that the package can be imported when heavy optional dependencies are absent. The `monkeypatch` fixture is used to temporarily replace `importlib.import_module` to simulate missing modules.

**Recommended Fix**: Consider using a test environment without optional dependencies installed, or use a more explicit dependency injection pattern. However, this may be acceptable as a boundary test for import-time behavior.

---

## 3. Mock/Stub/Fake Classes

### Files with Test Doubles

**Total: 35 files** (down from 67)

#### Category A: Protocol/Interface Implementations (Acceptable Pattern)

These implement real interfaces but with simplified behavior:

- `tests/_helpers/integration.py`: `FakeFAISSManager`, `FakeAsyncGitClient` - Protocol implementations
- `tests/_helpers/cli.py`: `_StubArtifactFS` - Filesystem protocol stub
- `tests/io/test_sparse_engines.py`: `_StubSpladeBackend`, `_StubBM25Backend` - Backend protocol implementations
- `tests/retrieval/pipeline/test_stage0.py`: `_StubHybridEngine` - Hybrid engine stub
- `tests/retrieval/pipeline/test_late_interaction.py`: `_StubXTRIndex` - XTR index stub
- `tests/search_api/test_client_idempotency.py`: `StubHttpClient` - HTTP client stub
- `tests/_helpers/ml.py`: Various ML component stubs

**Assessment**: These follow the Testing Charter if they:
- Implement the same interface as production
- Are injected via configuration/DI (not patched)
- Preserve key invariants

#### Category B: MagicMock Usage (Violation)

These use `MagicMock()` which bypasses production code entirely:

**Total: 4 files** (down from ~15)

| File | Usage | Purpose |
|------|-------|---------|
| `tests/codeintel_rev/test_vllm_client.py` | `MagicMock()` for `embed_batch` return values | VLLM client testing |
| `tests/codeintel_rev/test_app_lifespan.py` | `MagicMock(spec=VLLMClient)` | Lifespan initialization testing |
| `tests/codeintel_rev/test_integration_full.py` | `MagicMock(spec=VLLMClient)` | Integration testing |
| `tests/codeintel_rev/test_scope_integration.py` | `MagicMock()`, `AsyncMock()` for multiple clients | Scope integration testing |

**Assessment**: **Violation** - MagicMock skips all production logic, making tests validate mocks rather than real behavior.

**Recommended Fix**: Replace with:
- Real `VLLMClient` instances with test HTTP transport contexts
- Real `FAISSManager` instances with in-memory indexes
- Real `GitClient` instances with temporary repositories
- Real `AsyncGitClient` instances with test adapters

#### Category C: Stub Classes with Minimal Implementation

These provide deterministic test behavior but may skip production logic:

**Total: 35 files** (representative sample)

- `tests/cli/test_indexctl_embeddings.py`: `_StubProvider` - Embedding provider stub
- `tests/cli/test_indexctl_health.py`: `_ManagerStub`, `_ConnectionStub`, `_CatalogStub` - Database stubs
- `tests/codeintel_rev/test_offline_eval.py`: `_StubFAISSManager`, `_StubVLLMClient` - Evaluation stubs
- `tests/codeintel_rev/test_scip_coverage.py`: `_StubFaissManager`, `_StubVLLMClient` - Coverage stubs
- `tests/mcp/test_search_fetch_golden.py`: `_StubEmbedder`, `_StubFaissRuntime`, `_StubCatalog` - Golden test stubs
- `tests/io/test_splade_onnx_encoder.py`: `_StubSession` - ONNX session stub
- `tests/plugins/test_registry.py`: `_ToyChannel` - Channel registry stub

**Assessment**: **Needs Review** - Depends on whether they:
- Skip critical production logic (serialization, validation, error handling)
- Are injected via DI vs runtime patching
- Could be replaced with isolated real instances

---

## 4. Specific Violation Examples

### Example 1: MagicMock for VLLMClient (`test_app_lifespan.py`)

```python
from unittest.mock import MagicMock

overrides = ApplicationContextOverrides(vllm_client=MagicMock(spec=VLLMClient))
context = ApplicationContext.create(app_config=app_config, overrides=overrides)
```

**Issue**: Uses `MagicMock` instead of real `VLLMClient` instance, skipping all production logic.

**Recommended Fix**: Use real `VLLMClient` with test transport context:
```python
from tests._helpers.http import build_test_vllm_client

vllm_client = build_test_vllm_client(tmp_path)  # Real client with test HTTP transport
overrides = ApplicationContextOverrides(vllm_client=vllm_client)
```

### Example 2: MagicMock for Multiple Clients (`test_scope_integration.py`)

```python
from unittest.mock import AsyncMock, MagicMock

vllm_client = MagicMock(spec=VLLMClient)
faiss_manager = MagicMock(spec=FAISSManager)
git_client = MagicMock(spec=GitClient)
async_git_client = AsyncMock(spec=AsyncGitClient)
```

**Issue**: All dependencies are mocks, so tests validate mock behavior, not production integration.

**Recommended Fix**: Use real instances with test data:
```python
from tests._helpers.integration import build_integration_harness

harness = build_integration_harness(tmp_path)  # Real instances with test data
vllm_client = harness.context.vllm_client
faiss_manager = harness.context.faiss_manager
git_client = harness.context.git_client
```

### Example 3: MagicMock for embed_batch (`test_vllm_client.py`)

```python
from unittest.mock import MagicMock

class _StubInprocessEngine:
    def __init__(self):
        self.embed_batch = MagicMock(return_value=np.ones((1, embedding_dim), dtype=np.float32))
```

**Issue**: Uses `MagicMock` for method return values, skipping real embedding logic.

**Recommended Fix**: Use real engine with deterministic test data or explicit stub that implements the interface:
```python
class _StubInprocessEngine:
    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Return deterministic embeddings for testing."""
        return np.ones((len(texts), embedding_dim), dtype=np.float32)
```

---

## 5. Acceptable Patterns Found

### Pattern 1: Dependency Injection via Configuration

**Example**: `tests/_helpers/settings.py` - `build_app_config_for_repo()` creates real `AppConfig` with test paths.

**Status**: ✅ Compliant - Uses configuration, not patching.

### Pattern 2: Explicit Test Doubles via DI

**Example**: `tests/_helpers/integration.py` - `FakeFAISSManager`, `FakeAsyncGitClient` implement protocols and are injected via factories.

**Status**: ✅ Compliant - Uses factory injection, not runtime patching.

### Pattern 3: Real Instances with Isolated Data

**Example**: `tests/_helpers/catalog.py` - `_scope()` creates real `DuckDBCatalog` with test data.

**Status**: ✅ Compliant - Uses same technology (DuckDB) with isolated instances.

### Pattern 4: Test Helper Factories

**Example**: `tests/_helpers/integration.py` - `build_integration_harness()` creates real `ApplicationContext` with test adapters.

**Status**: ✅ Compliant - Provides real instances with test-friendly configurations.

---

## 6. Files Requiring Immediate Attention

### High Priority (MagicMock Usage)

1. `tests/codeintel_rev/test_app_lifespan.py` - Uses `MagicMock(spec=VLLMClient)` for lifespan testing
2. `tests/codeintel_rev/test_integration_full.py` - Uses `MagicMock(spec=VLLMClient)` for integration testing
3. `tests/codeintel_rev/test_scope_integration.py` - Uses `MagicMock()` and `AsyncMock()` for multiple clients
4. `tests/codeintel_rev/test_vllm_client.py` - Uses `MagicMock()` for `embed_batch` return values

### Medium Priority (Monkeypatch Fixture)

1. `tests/dist/test_extras_minimal_import.py` - Uses `monkeypatch.setattr()` to simulate missing dependencies

### Low Priority (Stub Classes - Review Needed)

1. `tests/cli/test_indexctl_health.py` - Database stubs (may be acceptable if they preserve SQL semantics)
2. `tests/codeintel_rev/test_offline_eval.py` - Evaluation stubs (may skip critical logic)
3. `tests/mcp/test_search_fetch_golden.py` - Golden test stubs (may be acceptable for deterministic outputs)
4. `tests/io/test_splade_onnx_encoder.py` - ONNX session stub (may skip serialization logic)

---

## 7. Compliance Status

| Category | Previous | Current | Status |
|----------|----------|---------|--------|
| `monkeypatch` fixture usage | 0 | 1 | ⚠️ Needs Review |
| `unittest.mock.patch` usage | 18 files | **0 files** | ✅ **Compliant** |
| `MagicMock()` usage | ~15 files | **4 files** | ❌ Violation (Improved) |
| Stub/Fake classes | 67 files | **35 files** | ⚠️ Needs Review (Improved) |
| Dependency injection patterns | ~10 files | ~20+ files | ✅ Compliant (Improved) |

**Progress Summary**:
- ✅ **100% removal** of `unittest.mock.patch` calls (18 → 0)
- ✅ **73% reduction** in `MagicMock` usage (~15 → 4 files)
- ✅ **48% reduction** in stub/fake classes (67 → 35 files)
- ✅ **100% increase** in dependency injection patterns (~10 → 20+ files)

---

## 8. Recommendations

### Priority 1: Replace Remaining MagicMock Usage

1. **Create test factories** for common dependencies:
   ```python
   # tests/_helpers/vllm.py
   def build_test_vllm_client(tmp_path: Path) -> VLLMClient:
       """Build real VLLMClient with test HTTP transport."""
       config = VLLMSettings(base_url="http://localhost:8000")
       transport = build_test_transport_context(tmp_path)
       return VLLMClient(config, transport_context=transport)
   ```

2. **Replace MagicMock instances** with real implementations:
   - `MagicMock(spec=VLLMClient)` → `build_test_vllm_client(tmp_path)`
   - `MagicMock(spec=FAISSManager)` → `build_test_faiss_manager(tmp_path)`
   - `AsyncMock(spec=AsyncGitClient)` → `build_test_async_git_client(tmp_path)`

### Priority 2: Review Monkeypatch Usage

1. **Evaluate** `tests/dist/test_extras_minimal_import.py`:
   - Consider if this test can be run in an environment without optional dependencies
   - If monkeypatch is necessary, document why it's an exception to the Testing Charter

### Priority 3: Audit Remaining Stub Classes

1. **Review each stub** to ensure it:
   - Implements the full interface (not just happy path)
   - Preserves serialization/validation logic
   - Could plausibly be used in dev/staging

2. **Replace stubs that skip critical logic** with:
   - Real implementations with test data
   - In-memory/test-friendly variants (e.g., `_FakeRedis`, `FakeFAISSManager`)

### Priority 4: Document Approved Patterns

1. **Update** `tests/_helpers/README.md` with:
   - Approved stub/fake patterns
   - Test factory examples
   - Dependency injection guidelines

2. **Create examples** for common test scenarios:
   - Testing with VLLM clients
   - Testing with FAISS managers
   - Testing with Git clients
   - Testing with async adapters

---

## 9. Next Steps

1. ✅ **Completed**: Remove all `unittest.mock.patch` calls
2. **In Progress**: Replace `MagicMock` usage with real instances
3. **Pending**: Review and document stub class patterns
4. **Pending**: Evaluate `monkeypatch` fixture usage exception
5. **Pending**: Create test factories for common dependencies
6. **Pending**: Update Testing Charter with specific examples

---

## Appendix: Complete File List

### Runtime Patching Files

**Total: 0 files** ✅

All `unittest.mock.patch` calls have been removed.

### Monkeypatch Fixture Files

**Total: 1 file**

- `tests/dist/test_extras_minimal_import.py`

### MagicMock Usage Files

**Total: 4 files**

- `tests/codeintel_rev/test_vllm_client.py`
- `tests/codeintel_rev/test_app_lifespan.py`
- `tests/codeintel_rev/test_integration_full.py`
- `tests/codeintel_rev/test_scope_integration.py`

### Stub/Fake/Mock Class Files (35 files)

- `tests/_helpers/integration.py`
- `tests/_helpers/cli.py`
- `tests/_helpers/ml.py`
- `tests/app/test_lifespan_runtime_cleanup.py`
- `tests/cli/test_indexctl_embeddings.py`
- `tests/cli/test_indexctl_health.py`
- `tests/codeintel_rev/eval/test_hybrid_evaluator.py`
- `tests/codeintel_rev/io/test_coderank_embedder.py`
- `tests/codeintel_rev/io/test_rerank_coderankllm.py`
- `tests/codeintel_rev/io/test_vllm_engine.py`
- `tests/codeintel_rev/mcp_server/test_semantic_pro_adapter.py`
- `tests/codeintel_rev/test_bm25_cli.py`
- `tests/codeintel_rev/test_offline_eval.py`
- `tests/codeintel_rev/test_readiness.py`
- `tests/codeintel_rev/test_scip_coverage.py`
- `tests/codeintel_rev/test_scope_store.py`
- `tests/codeintel_rev/test_semantic_adapter.py`
- `tests/codeintel_rev/test_splade_cli.py`
- `tests/codeintel_rev/test_splade_manager.py`
- `tests/codeintel_rev/test_vllm_client.py`
- `tests/conftest.py`
- `tests/embeddings/test_provider_shape.py`
- `tests/io/test_faiss_runtime_dual_merge.py`
- `tests/io/test_faiss_runtime.py`
- `tests/io/test_sparse_engines.py`
- `tests/io/test_splade_onnx_encoder.py`
- `tests/mcp/test_registry_contracts.py`
- `tests/mcp/test_search_fetch_golden.py`
- `tests/mcp/test_tools_contract.py`
- `tests/plugins/test_registry.py`
- `tests/retrieval/pipeline/test_late_interaction.py`
- `tests/retrieval/pipeline/test_stage0.py`
- `tests/retrieval/test_refine_rerank.py`
- `tests/search_api/test_client_idempotency.py`
- `tests/search_api/test_faiss_adapter.py`

---

**Review Completed**: 2025-11-20  
**Previous Review**: 2025-01-27  
**Next Review**: After replacement of remaining MagicMock usage
