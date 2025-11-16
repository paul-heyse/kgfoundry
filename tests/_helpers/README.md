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

## Rollout checklist

- [ ] Imports sorted with Ruff (`uv run ruff check path/to/test.py --fix`)
- [ ] No `assert` statements—use helper assertions or `pytest.raises`
- [ ] No naked literals for widely reused numbers—pull them from `constants`
- [ ] CLI tests rely on `tests._helpers.cli.invoke`
- [ ] Subprocess invocations go through `tests._helpers.process.run_process`
- [ ] Each module/function has a docstring summarizing the behavior under test
