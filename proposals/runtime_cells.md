# Draft Proposal: Runtime Cells for Frozen Dataclass Integrations

**Status:** Draft

**Author:** Codex (GPT-5) for kgfoundry/codeintel_rev

---

## 1. Motivation

The codeintel_rev stack adopted an "everything is a frozen dataclass" policy to ensure predictable, thread-safe configuration objects. While this yields stronger immutability guarantees, several subsystems (vLLM embedder, XTR index, ApplicationContext) need legitimately mutable state: lazily-initialized GPU handles, memmaps, connection pools, etc. To bypass the freeze, each component now stores ad-hoc `_runtime` structs that hide mutable fields. The pattern works but has drawbacks:

- **Inconsistent lifecycle management:** every module invents its own holder (`_RuntimeHandle`, `_XTRIndexRuntime`, `_FaissRuntimeState`) with custom locking and shutdown semantics.
- **Testing friction:** tests must monkeypatch class methods or private `_runtime` fields to inject stubs (see `tests/codeintel_rev/io/test_xtr_manager.py` and earlier metrics tests).
- **Limited observability:** runtimes aren't first-class objects, so we can't easily instrument warmup, cleanup, or error handling.
- **Risk of leaks:** because runtimes are opaque, the application lifespan has no unified way to close GPU contexts or memmaps. Bugs here can leave CUDA contexts dangling or keep file handles open.

We need a structural solution that preserves frozen dataclasses while giving the mutable subsystems well-defined lifecycles.

## 2. Goals and Non-Goals

### Goals
1. Introduce a shared abstraction for mutable state owned by frozen dataclasses.
2. Provide sanctioned APIs for dependency injection / testing without monkeypatching.
3. Centralize lifecycle management (init, shutdown, health) for runtime resources.
4. Keep existing public configurations (Settings, ApplicationContext, etc.) frozen.

### Non-Goals
- Changing the freeze policy itself.
- Rewriting FAISS/vLLM business logic (only reorganizing how runtimes are stored/managed).
- Providing a general DI container—scope is limited to runtime resources bound to frozen dataclasses.

## 3. Proposed Design

### 3.1 RuntimeCell Primitive
We introduce a `RuntimeCell[T]` helper (either in `kgfoundry_common.runtime` or `codeintel_rev.runtime`) with the following properties:

- **Immutable interface:** the dataclass holds a `RuntimeCell[T]` field (still frozen), but the cell internally stores a mutable payload.
- **Thread-safe lazy init:** `get_or_initialize(factory: Callable[[], T])` initializes the payload once and returns it. Internally uses a re-entrant lock.
- **Inspection hooks:** `peek()` returns the current payload or `None` without creating one (useful for readiness checks).
- **Swap for testing:** `seed(value: T)` is allowed in tests or controlled contexts (guarded by explicit API), enabling deterministic injection without monkeypatching.
- **Lifecycle:** `close(dispose: Callable[[T], None])` runs a disposer if the payload exists and clears it, so the application lifespan can cleanly shut down resources.

Implementation sketch:
```python
@dataclass(slots=True)
class RuntimeCell(Generic[T]):
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _value: T | None = field(default=None, init=False, repr=False)

    def get_or_initialize(self, factory: Callable[[], T]) -> T:
        if self._value is not None:
            return self._value
        with self._lock:
            if self._value is None:
                self._value = factory()
            return self._value

    def peek(self) -> T | None: ...
    def seed(self, value: T) -> None: ...
    def close(self, disposer: Callable[[T], None] | None = None) -> None: ...
```

`seed` may be limited to test code via policy or context manager to avoid accidental production misuse.

### 3.2 Runtime Objects
We separate configuration dataclasses from mutable runtime executors. Examples:

- `InprocessVLLMEmbedder` becomes `VLLMEmbedderConfig` (frozen) + `VLLMRuntime` object that actually holds tokenizer/engine. The config keeps fields like model path, pooling, dims. Application code interacts with a lightweight façade that internally uses a `RuntimeCell[VLLMRuntime]`.
- `XTRIndex` retains its frozen config but defers to `XTRRuntime` for tokenizer, model, memmap. `RuntimeCell` manages lifecycle, making it easy to close memmaps or free GPU memory on shutdown.
- `ApplicationContext` maintains `RuntimeCell`s for hybrid engine, FAISS clones, XTR, etc., rather than home-grown `_RuntimeHandle` structs. This consolidates the locking and exposes uniform `close_all()` behavior.

### 3.3 Testability and Injection
With runtime cells, tests gain explicit hooks:
```python
def test_xtr_search(monkeypatch):
    runtime = DummyXTRRuntime(...)
    index = XTRIndex(config)
    index.runtime_cell.seed(runtime)
    results = index.search(...)
```
No need to monkeypatch class methods globally; injection is scoped to the instance under test.

### 3.4 Lifecycle Integration
- **Startup:** `ApplicationContext.create()` wires runtime cells but does not immediately instantiate heavy components unless eager warmup is desired.
- **Readiness/Warmup:** readiness checks call `peek()` to report status (e.g., `None` means not loaded). Warmup jobs call `get_or_initialize()` to force initialization.
- **Shutdown:** the FastAPI lifespan hook calls `context.close()` which iterates over known cells and calls `close()` with appropriate disposers (e.g., `lambda runtime: runtime.close()`). This ensures GPU contexts, HTTP pools, and memmaps are closed deterministically.

### 3.5 Incremental Rollout Plan
1. Implement `RuntimeCell` in a shared module with unit tests (thread safety, seeding, close semantics).
2. Refactor `InprocessVLLMEmbedder` to use `RuntimeCell[VLLMRuntime]`. Update existing tests to seed runtimes instead of monkeypatching.
3. Apply the same pattern to `XTRIndex` and `ApplicationContext` (replacing `_RuntimeHandle` and `_FaissRuntimeState`).
4. Ensure readiness, warmup, and shutdown logic leverage the new API. Document the pattern in `AGENTS.md` (new section under Typing Gates or Architecture guidelines).
5. After core adoption, sweep other modules for `_runtime` or `object.__setattr__` helpers and migrate them.

## 4. Risks & Mitigations
- **Risk:** Developers may misuse `seed()` in production.
  - *Mitigation:* guard behind a context manager or debug flag; lint/test to ensure seeding is only used under `pytest`.
- **Risk:** Increased indirection could add complexity.
  - *Mitigation:* keep `RuntimeCell` API tiny and document its usage with clear examples.
- **Risk:** Existing tests rely on monkeypatching classes; migration requires updated fixtures.
  - *Mitigation:* provide helper fixtures that wrap the new seeding API to keep test changes minimal.

## 5. Open Questions
1. Should RuntimeCell support metrics (init duration, failure counts) out of the box?
2. Do we want optional `AsyncRuntimeCell` for async resources, or can we keep the primitive synchronous and run async initialization via `asyncio.to_thread`?
3. How do we enforce the pattern? (e.g., lint rule to forbid custom `_runtime` dataclasses?)

---

**Call for Feedback:**
- Do we agree on RuntimeCell as the standard abstraction?
- Any concerns about test injection semantics or lifecycle integration?
- Which subsystem should we convert first after the proving ground (vLLM)?

