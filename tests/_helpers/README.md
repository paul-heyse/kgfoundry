# Test Helper Conventions

We removed Ruff’s blanket suppressions for tests, which means every suite must
comply with the same docstring, annotation, and safety rules as production
code. The helper modules under `tests/_helpers/` keep that work ergonomic:

| Helper | Purpose |
| --- | --- |
| `assertions` | Drop-in replacements for bare `assert` statements. Prefer `expect_equal`, `expect_true`, etc., so tests fail with descriptive messages while satisfying Ruff’s `S101` rule. |
| `constants` | Centralizes shared “magic numbers” (vector dimensions, batch sizes, timeout budgets). Import the relevant dataclass instead of hard-coding literals flagged by `PLR2004`. |
| `cli.invoke` | Provides a single `Typer` runner; tests no longer need to instantiate `CliRunner` or worry about `mix_stderr`. |
| `process.run_process` | Thin wrapper around `kgfoundry_common.subprocess_utils.run_subprocess` that enforces consistent env/timeout behavior in tests. |

## How to apply the helpers

1. **Replace bare asserts**  
   ```python
   from tests._helpers import assertions

   assertions.expect_in("--dry-run", result.stdout)
   assertions.expect_false(out_path.exists(), reason="Dry run should not write artifacts.")
   ```

2. **Document each test function**  
   Single-sentence NumPy-style summaries keep Ruff’s D10x rules satisfied:
   ```python
   def test_relation_exists_detects_tables() -> None:
       """Tables reported by DuckDB information_schema are relations."""
   ```

3. **Name shared literals**  
   ```python
   from tests._helpers import constants

   assertions.expect_equal(result.rows, constants.BATCH_SIZES.small)
   ```

4. **Prefer pytest fixtures over helper classes**  
   If a test class only exists to share helpers, move the helpers into a fixture
   instead; this resolves `PLR6301` warnings.

## Configuration & CLI fixtures

Most suites now rely on typed fixtures instead of modifying environment variables.
Reach for these helpers before writing new `monkeypatch` logic:

| Fixture / Helper | Location | Purpose |
| --- | --- | --- |
| `build_settings_for_repo` | `tests/_helpers/settings.py` | Returns a `Settings` copy whose paths point at a temporary repo. Accepts overrides for `paths`, `bm25`, and `splade` to emulate different configurations. |
| `RepoHandle` fixtures | `tests/codeintel_rev/test_integration_full.py`, `tests/codeintel_rev/test_app_lifespan.py`, etc. | Wrap the repo + `ApplicationContext.create` patch so tests can call `handle.configure(faiss_preload=True)` instead of tweaking env vars. |
| `repo_scan_invoker` | `tests/conftest.py` | Executes `tools.repo_scan` with explicit argv and returns the parsed payload + DOT paths—no need to mutate `sys.argv`. |
| CLI context builders | `tests/conftest.py` | Builders for orchestration, download, BM25, SPLADE, XTR CLIs. Pass them into Typer `obj` to inject stub managers/providers during tests. |

### Typing gate helpers

When a test needs to bypass heavy imports (FAISS, CuPy, etc.), use the typed
context managers instead of patching modules directly:

- `kgfoundry_common.typing.override_gate_import({"faiss": fake_module})`
  returns deterministic shims for `gate_import`.
- `codeintel_rev.io.faiss_runtime.override_parameter_application(lambda *_: False)`
  disables `ParameterSpace` touching real FAISS state during unit tests.

Prefer these helpers (or `LazyModule.__setattr__`) over `monkeypatch` so tests
stay aligned with the Typing Gates policy in `AGENTS.md`.

When adding a new CLI or configuration test, prefer cloning one of these fixtures
instead of introducing new env-based scaffolding.

## Rollout checklist

- [ ] Imports sorted with Ruff (`uv run ruff check path/to/test.py --fix`)
- [ ] No `assert` statements—use helper assertions or `pytest.raises`
- [ ] No naked literals for widely reused numbers—pull them from `constants`
- [ ] CLI tests rely on `tests._helpers.cli.invoke`
- [ ] Subprocess invocations go through `tests._helpers.process.run_process`
- [ ] Each module/function has a docstring summarizing the behavior under test
