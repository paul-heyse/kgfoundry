# Changelog

## Unreleased

### Added
- Enforced strict NumPy-style docstrings using `numpydoc` validation and `.numpydoc` checks.
- Added custom doq templates and enhanced `tools/auto_docstrings.py` to generate complete NumPy sections.
- Integrated `pydoclint` into the development workflow and pre-commit hooks for parameter/return parity.
- Introduced `tools/navmap/strip_navmap_sections.py` to purge legacy `NavMap:` blocks.
- Documented new requirements in `docs/how-to/contributing.md` and `docs/explanations/numpy-docstring-migration.md`.
- Added `make lint-docs` and corresponding CI coverage to enforce docstring diffs, DocFacts parity, and strict pyright + pyrefly checks.
- **Namespace consolidation**: All public APIs are now accessible via the unified `kgfoundry.*` namespace (e.g., `from kgfoundry import vectorstore_faiss`). The namespace proxy automatically resolves submodules on first access, eliminating duplicate top-level package imports.
- **GPU extras**: GPU-specific dependencies (FAISS GPU, cuVS, PyTorch, vLLM, etc.) are now isolated in the `gpu` extra. Install with `uv sync --extra gpu` or `pip install kgfoundry[gpu]`. This keeps the base installation lightweight while enabling optional GPU acceleration.
- **Tooling automation**: Added import-linter contracts, suppression guard script (`tools/check_new_suppressions.py`), and PR summary generator (`tools/generate_pr_summary.py`) for improved code quality enforcement.
- Documented the shared observability facade (`tools/_shared/observability_facade.md`) covering typed Prometheus builders, structured logging fields, tracing helpers, and the fallback semantics for environments without `prometheus_client`.
- **Typing gates enforcement** (Phase 1): Introduced typing façade modules (`kgfoundry_common.typing`, `tools.typing`, `docs.typing`) with `gate_import()` and `safe_get_type()` helpers for deferred imports. All new modules enforce `from __future__ import annotations` (PEP 563) and TYPE_CHECKING guards for type-only imports. New CI gate: `python -m tools.lint.check_typing_gates` (see `docs/typing_migration_guide.md` for developer guidance and AGENTS.md for best practices).
- Added `tools/lint/apply_postponed_annotations.py` to automatically inject postponed annotation directives while respecting module headers, shebangs, and docstrings.
- Added `tools/lint/check_typing_gates.py` for AST-based enforcement of TYPE_CHECKING guards, detecting unguarded imports of heavy dependencies (numpy, FastAPI, FAISS, etc.).
- **Semantic Pro search**: Introduced the `search:semantic_pro` MCP tool with CodeRank FAISS retrieval, optional WARP/XTR fusion, CodeRankLLM reranker, new IO helpers, and a `coderank.py build-index` CLI for generating the dedicated FAISS index.

### Changed
- `tools/update_navmaps.py` now validates docstrings instead of injecting `NavMap:` sections.
- `docs/conf.py` loads the `numpydoc`/`numpydoc_validation` extensions and treats validation warnings as errors (`nitpicky = True`).
- `tools/update_docs.sh` ensures `pydoclint` is available and checks for lingering `NavMap:` sections during the pipeline.
- Docstrings across `src/` were regenerated to include `Parameters`, `Returns`, `Raises`, `Examples`, `See Also`, and `Notes` sections.
- **Packaging**: GPU dependencies moved to optional extras to reduce base installation footprint.

### Breaking
- Module docstrings no longer include the legacy `NavMap:` section; navigation metadata resides exclusively in `__navmap__` dictionaries and the generated JSON index.
