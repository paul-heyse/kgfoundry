# AGENTS.md — Agent Operating Protocol (AOP)

> **Purpose**: This file is the agent-first playbook for building and maintaining this codebase at **best‑in‑class** quality. It specifies *exact commands*, *acceptance gates*, and *fallbacks* so both humans and AI agents can ship production‑grade Python safely and quickly.

---

## Table of contents
1. [Agent Operating Protocol (TL;DR)](#agent-operating-protocol-tldr)
2. [Environment Setup (Agent‑grade, deterministic)](#environment-setup-agentgrade-deterministic)
3. [Source‑of‑Truth Index](#source-of-truth-index)
4. [Code Formatting & Style (Ruff is canonical)](#code-formatting--style-ruff-is-canonical)
5. [Type Checking (pyright strict, pyrefly sharp)](#type-checking-pyright-strict-pyrefly-sharp)
6. [Docstrings (NumPy style; enforced; runnable)](#docstrings-numpy-style-enforced-runnable)
7. [Testing Standards (markers, coverage, GPU hygiene)](#testing-standards-markers-coverage-gpu-hygiene)
8. [Data Contracts (JSON Schema 2020‑12 / OpenAPI 3.2)](#data-contracts-json-schema-2020-12--openapi-32)
9. [Link Policy for Remote Editors](#link-policy-for-remote-editors)
10. [Agent Catalog & STDIO API (session‑scoped, no daemon)](#agent-catalog--stdio-api-sessionscoped-no-daemon)
11. [Task Playbooks (feature / refactor / bugfix)](#task-playbooks-feature--refactor--bugfix)
12. [PR Template & Checklist](#pr-template--checklist)
13. [Quick Commands (copy/paste)](#quick-commands-copypaste)
14. [Troubleshooting (for Agents)](#troubleshooting-for-agents)
15. [Security & Compliance Hygiene](#security--compliance-hygiene)
16. [Repo Layout & Do‑not‑edit Zones](#repo-layout--do-not-edit-zones)
17. [CI / Pre‑commit parity](#ci--precommit-parity)
18. [Glossary](#glossary)

---

## Agent Operating Protocol (TL;DR)

**You are an autonomous Python engineer. Follow this sequence for *every* change:**

1) **Load context fast**
   - Read this file end‑to‑end.
   - Open the relevant spec/proposal under `openspec/` (when applicable).
   - Bootstrap environment and run local checks:
    ```bash
    scripts/bootstrap.sh
    ```

2) **Implement**
   - Code to the typed API sketch.
   - Keep functions small; separate I/O from pure logic; prefer composition over inheritance.

3) **Validate quality gates locally**
  ```bash
  uv run ruff format && uv run ruff check --fix
  uv run fixit fix -a .
  uv run pyright --warnings --pythonversion=3.13
  uv run pyrefly check
  uv run vulture src tools stubs --min-confidence 90
  SKIP_GPU_WARMUP=1 uv run pytest -q    # unset on CUDA-capable hosts
  # If OpenAPI changed: lint spec (e.g., spectral lint openapi.yaml)

  ```

### Quality checks (zero-error mandate)

For all code blocks that you make edits to, please check for pyright, pyrefly, and Ruff errors or warnings and ensure that by the time you have concluded your edits in a code block there are zero errors in any of those categories. Your error checking and resolution should not solely focus on your scope, all errors in the files that you have made edits in are part of the scope of your review when implementing a change and should be fully resolved before you conclude your work. Under no circumstances should you ever suppress errors, even stylistic Ruff errors. Instead of suppressing errors, derive a structural solution that causally addresses the source of the error, even if it is intensive to implement. All of your code designs and implementation work should be structural, holistic, and best-in-class, guided by the following principles:

#### Principles for your code design and implementation

##### 1) Clarity & API design

* Public API is explicit and named per PEP 8; internal helpers remain private.
* Every public module/class/function has a PEP 257 docstring whose first line is a one-sentence summary.
* Fully annotated signatures; prefer modern generics/type params (PEP 484 + PEP 695). **No untyped public APIs.**
* Exceptions are part of the contract. Define a small **exception taxonomy**, and for HTTP use **RFC 9457 Problem Details**; always `raise ... from e` to preserve cause chains.
* **Verify:** `ruff format && ruff check --fix` is clean; docstrings present; types on all public symbols; include a sample Problem Details JSON for at least one error path.

##### 2) Data contracts & schemas

* Cross-boundary data MUST have a schema: **JSON Schema 2020-12** for payloads; **OpenAPI 3.2** for HTTP.
* Code models may **emit** or **round-trip** the schema, but the schema file is the **source of truth**.
* Include examples and versioning notes (backward-/forward-compat, deprecations).
* **Verify:** schema validates against 2020-12 meta-schema; OpenAPI passes a linter; round-trip tests confirm model↔schema parity.

##### 3) Testing strategy

* Pytest; **table-driven** tests with `@pytest.mark.parametrize` covering happy path, edges, and failure modes.
* Integrate **doctest/xdoctest** so examples in docs truly run.
* Map tests to scenarios in the spec (when applicable).
* **Verify:** `pytest -q` green; param/edge/error cases present; doctests pass.

##### 4) Type safety

* Project is **type-clean** under **pyright** (strict mode), **pyrefly** (sharp checks).
* Prefer `Protocol`/`TypedDict`/PEP 695 generics over `Any`; minimize `cast` and justify any `# type: ignore[...]`.
* **Verify:** both checkers pass; no unexplained ignores.

##### 5) Logging & errors

* Use stdlib `logging`; libraries define a `NullHandler`; apps configure handlers.
* Prefer **structured logs** (extra fields); never log secrets/PII.
* For HTTP, return **Problem Details** consistently and log with correlation IDs (see Observability below).
* **Verify:** module loggers exist; no `print` in libraries; errors produce logs + exceptions/Problem Details.

##### 6) Configuration & 12-factor basics

* Config via **environment variables** (use `pydantic_settings` or equivalent for typed settings); no hard-coded secrets.
* Backing services are replaceable; logs to stdout/stderr.
* **Verify:** swapping URLs/credentials is config-only; startup fails fast if required env is missing.

##### 7) Modularity & structure

* Favor **single-responsibility** modules; separate pure logic from I/O; explicit dependency injection; **no global state**.
* Layering: **domain** (pure) → **adapters/ports** → **I/O/CLI/HTTP**; consider import-linter rules to prevent cross-layer leaks.
* **Verify:** imports are acyclic; small functions; side-effect boundaries explicit.

##### 8) Concurrency & context correctness

* For async, use **`contextvars`** for request/task context; document timeouts and cancellation.
* Avoid blocking calls in async code; use thread pools for legacy I/O.
* **Verify:** async APIs document await/timeout rules; context propagated via `ContextVar`.

##### 9) Observability (logs • metrics • traces)

* Emit **structured logs**, **Prometheus metrics**, and **OpenTelemetry traces** at boundaries.
* Minimum: request/operation name, duration, status, error type, correlation/trace ID.
* **Verify:** a failing path produces (1) an error log with context, (2) a counter increment, and (3) a trace span with error status.

##### 10) Security & supply-chain

* **Never** use `eval/exec` or untrusted `pickle`/`yaml.load` (use `safe_load`).
* Validate/sanitize all untrusted inputs; prevent path traversal with `pathlib` and whitelists.
* Run a vuln scan (e.g., `pip-audit`) on dependency changes; pin ranges sensibly.
* **Verify:** `pip-audit` clean; inputs validated in tests.

##### 11) Packaging & distribution

* `pyproject.toml` with **PEP 621** metadata; **PEP 440** versioning; build wheels.
* Keep dependencies minimal; use **extras** for optional features; add environment markers for platform-specific bits.
* **Verify:** `pip wheel .` succeeds; `pip install .` works in a clean venv; metadata is correct.

##### 12) Performance & scalability

* Set simple budgets where relevant (e.g., p95 latency, memory ceiling) and write micro-bench tests for hot paths.
* Avoid quadratic behavior; stream large I/O; prefer `pathlib`, `itertools`, vectorized ops where apt.
* **Verify:** a representative input meets the budget locally; add notes if a budget is intentionally exceeded.

##### 13) Documentation & discoverability

* Examples are **copy-ready** and runnable; public API shows minimal, idiomatic usage.
* Cross-link code to spec and schema files; keep the **Agent Portal** links working (editor/GitHub).


##### 14) Versioning & deprecation policy

* Use **SemVer language** for public API; mark deprecations with warnings and removal version; update CHANGELOG.
* **Verify:** deprecated calls warn once with a clear migration path.

##### 15) Idempotency & error-retries

* Any externally triggered operation (HTTP/CLI/queue) should be **idempotent** where possible; document retry semantics.
* **Verify:** repeated calls with same input either no-op or converge; tests prove it.

##### 16) File, time, and number hygiene

* **`pathlib`** for paths; **timezone-aware** datetimes; use **`time.monotonic()`** for durations; **`decimal.Decimal`** for money.
* **Verify:** no `os.path` in new code; no naive datetimes in boundaries.


> If any step fails, **stop and fix** before continuing.

---

## Environment Setup (Agent‑grade, deterministic)

- **Canonical manager:** `uv`
- **Python:** pinned to **3.13.9**
- **Virtual env:** project‑local `.venv/` only (never system Python)
- **One-shot bootstrap (REQUIRED):** use `scripts/bootstrap.sh`
  ```bash
  scripts/bootstrap.sh
  ```
  The script lives at `scripts/bootstrap.sh` and provisions uv, pins Python 3.13.9, syncs dependencies, activates the project `.venv/`, and sets project paths correctly. It is REQUIRED, the code will not function correctly if you do not run this script. Pass `--help` for options.

  If you are having difficulties with reaching the directory even after running `scripts/bootstrap.sh` please attempt to run the bash command "/bin/bash -lc 'pwd && ls -la'"

- **Remote container / devcontainer:** follow [Link Policy for Remote Editors](#link-policy-for-remote-editors) so deep links open correctly from generated artifacts.
- **Do not** duplicate tool configs across files. `pyrightconfig.jsonc` and `pyrefly.toml` are canonical; `pyproject.toml` is canonical for Ruff and packaging.

---

## Source‑of‑Truth Index

Read these first when editing configs or debugging local vs CI drift:

- **Formatting & lint:** `pyproject.toml` → `[tool.ruff]`, `[tool.ruff.lint]`
- **Dead code scanning:** `pyproject.toml` → `[tool.vulture]`, `.github/workflows/ci-vulture.yml`, `vulture_whitelist.py`
- **Types:** `pyrefly.toml` (single source), `pyrightconfig.jsonc` (strict pyright)
- **Tests:** `pytest.ini` (markers, doctest/xdoctest config)
- **CI:** `.github/workflows/ci.yaml` (job order: precommit → lint → types → tests → docs; OS matrix; caches; artifacts)
- **Pre‑commit:** `.pre-commit-config.yaml` (runs the same gates locally)

---

## Code Formatting & Style (Ruff is canonical)

- **Run order:** `uv run ruff format` → `uv run ruff check --fix` (imports auto‑sorted).
- **Imports:** stdlib → third‑party → first‑party; absolute imports only.
- **Style guardrails:** 100‑col width, 4‑space indent, double quotes, trailing commas on multiline.
- **Complexity:** cyclomatic ≤ 10, returns ≤ 6, branches ≤ 12; refactor if exceeded.
- **Rule families emphasized (non‑exhaustive):**
  - Baseline: `F,E4,E7,E9,I,N,UP,SIM,B,RUF,ANN,D,RET,RSE,TRY,EM,G,LOG,ISC,TID,TD,ERA,PGH,C90,PLR`
  - Extra quality & safety: `W,A,ARG,BLE,DTZ,PTH,PIE,S,PT,T20`
    (builtins shadowing, unused args, bare except, timezone‑aware datetimes, pathlib, security, pytest style, ban prints)

> We standardize on **Ruff** for formatter + linter. Do **not** run Black in parallel (conflicts / duplicate work).

---

## Type Checking (pyright strict, pyrefly sharp)

- **Static analysis (strict mode):**
  ```bash
  uv run pyright --warnings --pythonversion=3.13
  ```
- **First-line check (semantics):**
  ```bash
  uv run pyrefly check
  ```
- **Rules of engagement:**
  - Pyright runs in strict mode (`pyrightconfig.jsonc`); update execution environments when adding new roots.
  - No untyped **public** APIs.
  - Prefer **PEP 695** generics and `Protocol`/`TypedDict` over `Any`.
  - Every `# type: ignore[...]` requires a comment **why** + a ticket reference.
  - Narrow exceptions; HTTP surfaces return **RFC 9457 Problem Details**.

**“Type-clean” means pyright and pyrefly both pass.**

---

## Typing Gates (Postponed Annotations & TYPE_CHECKING Hygiene)

**Purpose**: Prevent runtime imports of heavy optional dependencies (numpy, fastapi, FAISS) when they're only used in type hints. This ensures tooling stays lightweight and import-clean.

### 1. Postponed Annotations (PEP 563)

Every Python module MUST include:
```python
from __future__ import annotations
```

This directive must be **the first import statement** (after shebang and encoding declaration). Use the automated fixer:
```bash
python -m tools.lint.apply_postponed_annotations src/ tools/ docs/_scripts/
```

**Why**: Postponed annotations eliminate eager type hint evaluation, preventing `NameError` when optional dependencies are missing.

### 2. Typing Façade Modules

Use canonical typing imports instead of direct imports from heavy libraries:

**Canonical façades** (re-export safe type-only helpers):
- `kgfoundry_common.typing` — Core type aliases and runtime helpers
- `tools.typing` — Tooling scripts (re-export from kgfoundry_common.typing)
- `docs.typing` — Documentation scripts (re-export from kgfoundry_common.typing)

**Type-only imports MUST be guarded**:
```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from fastapi import FastAPI

def process(vectors: np.ndarray, app: FastAPI | None = None) -> None:
    """Annotations use types safely; runtime code doesn't import them."""
    pass
```

**Runtime access to heavy types** (when genuinely required):
```python
from kgfoundry_common.typing import gate_import

# Inside a function that actually needs numpy at runtime:
np = gate_import("numpy", "array reshaping in process()")
result = np.reshape(data, (10, 10))
```

### 3. Ruff Rules (Automatic Enforcement)

**Enabled rules** (errors by default):
- `TC001–TC006` — Type-checking import violations (move to TYPE_CHECKING blocks)
- `PLC2701` — Type-only import used at runtime (special: allowed in façade modules only)
- `INP001` — Implicit namespace packages (require `__init__.py` for packages)
- `EXE002` — Missing shebang for executable files

Per-file ignores are defined in `pyproject.toml` for:
- Façade modules (`src/kgfoundry_common/typing`, `tools/typing`, `docs/typing`)
- Special internal packages (`docs/_types`, `docs/_scripts`)

### 5. Development Workflow

**When adding a new module that uses type hints**:
1. Add `from __future__ import annotations` at the top
2. Move heavy type imports into `if TYPE_CHECKING:` blocks
3. For runtime needs, use `gate_import()` from the façade
4. Run checks before committing:
   ```bash
   uv run pyrefly check
   uv run ruff check --fix  # Enforces TC/INP/EXE rules
   ```

**Deprecation path**: Old code using `docs._types` or private imports will emit `PLC2701` warnings and will be removed after Phase 1 migration (see openspec/changes/typing-gates-holistic-phase1/).

---

## Docstrings (NumPy style; enforced; runnable)

- **Style:** NumPy docstrings; PEP 257 structure (module/class/function docstrings for all public symbols)
- **Enforcement:** `pydoclint` parity checks + `docstr-coverage` (≥90%)
- **Runnability:** Examples in `Examples` must execute (doctest/xdoctest); keep snippets short and copy‑ready
- **Required sections (public APIs):**
  - Summary (one line, imperative)
  - Parameters (name, type, meaning)
  - Returns / None
  - Raises (type + condition)
  - Examples
  - Notes (performance, side‑effects)


---

## Testing Standards (markers, coverage, GPU hygiene)

- **Markers:**
  - `@pytest.mark.integration` — network/services/resources
  - `@pytest.mark.gpu` — requires GPU libraries
  - `@pytest.mark.benchmark` — performance, non‑gating
- **Conventions:**
  - Parametrize edge cases with `@pytest.mark.parametrize`
  - No reliance on test order or realtime; use fixed seeds
  - GPU tests are **skipped by default** in CI unless explicitly enabled
- **Coverage (local whenever core paths change):**
  ```bash
  SKIP_GPU_WARMUP=1 uv run pytest -q --cov=src --cov-report=xml:coverage.xml --cov-report=html:htmlcov
  ```

---

## Data Contracts (JSON Schema 2020‑12 / OpenAPI 3.2)

- **Boundary rule:** whenever data crosses a boundary (API, file, queue), define a **JSON Schema 2020‑12**. For HTTP, use **OpenAPI 3.2** (embeds 2020‑12).
- **Source of truth:** the schema is canonical; models may be generated from it (or emit it) but do not replace it.
- **Validation:** validate inputs/outputs in tests; version schemas with SemVer and document breaking changes.

---

## Link Policy for Remote Editors

- **Editor mode (preferred for local dev):**
  - `DOCS_LINK_MODE=editor`
  - `EDITOR_URI_TEMPLATE="vscode-remote://dev-container+{container_id}{path}:{line}"`
  - Optional `PATH_MAP` file, lines: `/container/prefix => /editor/workspace/prefix`
- **GitHub mode (fallback):**
  - `DOCS_LINK_MODE=github`
  - `DOCS_GITHUB_ORG`, `DOCS_GITHUB_REPO`, `DOCS_GITHUB_SHA`
  - Links like: `https://github.com/{org}/{repo}/blob/{sha}/{path}#L{line}`
- **Agent rule:** use **editor** mode in remote containers for deep linking; use **github** when editor URIs are unavailable.

Example `PATH_MAP`:
```
/workspace => /workspaces/kgfoundry
/app       => /workspaces/kgfoundry
```

---

## Agent Catalog & STDIO API (session‑scoped, no daemon)

- **Artifacts:**
  - Ground truth: navigation artifacts under `docs/_build/`
  - Portal: `site/_build/agent/index.html`
- **Session API (JSON over stdio):**
  ```json
  {"id":"1","method":"capabilities","params":{}}
  {"id":"2","method":"search","params":{"q":"vector store","k":10}}
  {"id":"3","method":"open_anchor","params":{"symbol_id":"py:kg.index.faiss.build_index","mode":"editor"}}
  {"id":"4","method":"find_callers","params":{"symbol_id":"py:kg.doc.parse.Parser.parse"}}
  {"id":"5","method":"find_callees","params":{"symbol_id":"py:kg.index.faiss.build_index"}}
  ```
- **Lifecycle:**
  - Editor spawns: `python -m tools.docs.stdio_api`
  - First call is `capabilities`; one request at a time (MVP)
  - Process exits when stdin closes

---

## Task Playbooks (feature / refactor / bugfix)

### A) New Feature
1. Read the spec/proposal; write the **4‑item design note**.
2. Define/update **JSON Schema** for any boundary payloads.
3. Implement **typed** public API; write pure logic first, I/O later.
4. Add **parametrized tests** (happy paths, edges, negative cases).
5. Run quality gates (format → lint → pyright → pyrefly → pytest).


**Done when:** all gates green; PR includes design note, schemas, and runnable examples.

### B) Safe Refactor (no behavior change)
1. Prove parity with tests/fixtures **before** changes.
2. Extract pure functions; reduce complexity; improve names & docs.
3. Maintain public signatures; add deprecations if needed (warn + doc).
4. Run full gates; add a “refactor proof” note in the PR (tests proving equivalence).

### C) Bugfix
1. Reproduce with a failing **parametrized** test.
2. Fix with smallest diff; explain root cause in PR.
3. Add a **regression test**.
4. Run full gates; link issue/ticket in commit.

---

## PR Template & Checklist

**Use this PR template:**

- **Title:** `<area>: <short imperative>`
- **Summary:** one paragraph describing the change and why.
- **Public API:** list symbols & **typed** signatures that changed/added.
- **Data Contracts:** link to JSON Schema/OpenAPI diff (if any).
- **Test Plan:** commands + what they prove.
- **Impact:** migration notes / deprecations.

**Checklist (paste outputs):**
```
[ ] uv run ruff format && uv run ruff check --fix
[ ] uv run pyright --warnings --pythonversion=3.13
[ ] uv run pyrefly check
[ ] SKIP_GPU_WARMUP=1 uv run pytest -q
[ ] python tools/check_new_suppressions.py src
[ ] python tools/check_imports.py
[ ] uv run pip-audit
[ ] OpenAPI spec lints clean (if applicable)
```

**Problem Details Example:**
- Canonical example: `schema/examples/problem_details/search-missing-index.json`
- All HTTP error responses must conform to RFC 9457 Problem Details format
- See `src/kgfoundry_common/errors/` for exception taxonomy and Problem Details helpers

---

## Quick Commands (copy/paste)

```bash
# Format & lint
uv run ruff format && uv run ruff check --fix

# Types (pyright strict + pyrefly sharp)
uv run pyright --warnings --pythonversion=3.13
uv run pyrefly check

# Tests (incl. doctests/xdoctest via pytest.ini)
SKIP_GPU_WARMUP=1 uv run pytest -q


# Architectural boundaries & suppression guard
python tools/check_new_suppressions.py src
python tools/check_imports.py

# Dead code
uv run vulture src tools stubs --min-confidence 90

# All pre-commit hooks
uvx pre-commit run --all-files
```

> **Note:** Drop `SKIP_GPU_WARMUP=1` on CUDA-capable hosts or CI jobs that require GPU warm-up coverage.

**Problem Details Reference:**
- Example: `schema/examples/problem_details/search-missing-index.json`
- Schema: RFC 9457 Problem Details format
- Implementation: `src/kgfoundry_common/errors/`

---

## Troubleshooting (for Agents)

- **Ruff vs Black conflicts**: We use **Ruff only**; remove Black changes, re-run Ruff.
- **Third‑party typing gaps**: prefer small typed facades (`Protocol`, `TypedDict`) or `stubs/` alongside the stub configuration in `pyrightconfig.jsonc`, not `Any`.
- **Docs drift keeps appearing**: run `make artifacts` from a **clean** tree; ensure `docs/_build/**` isn’t ignored; commit regenerated files.
- **Editor links open wrong path**: verify `PATH_MAP` and `EDITOR_URI_TEMPLATE`; rebuild artifacts.
- **Slow CI**: check cache restore logs for `uv`, `ruff`, `pyright`. If keys miss, verify `uv.lock` & Python version detection step.

---

## Security & Compliance Hygiene

- **Secrets**: never commit `.env` or tokens; redact secrets in logs.
- **Validation**: sanitize all untrusted inputs at boundaries; validate against schemas.
- **Licenses**: prefer MIT/Apache‑2.0; consult SBOM when adding third‑party libs.

---

## Repo Layout & Do‑not‑edit Zones

- **Source**: `src/**`
- **Tests**: `tests/**` (mirrors `src`)
- **Docs & site**: `docs/**`, `site/**`
- **Generated artifacts**: `docs/_build/**`, `site/_build/**` → **do not hand‑edit**
- **Stubs**: `stubs/**` for local type shims (referenced by `stubPath`)

---

## CI / Pre‑commit parity

- **Job order**: precommit → lint → types → tests → docs
- **OS matrix**: lint/types on linux + macOS; tests on linux (expand later if needed)
- **Caches**: `~/.cache/uv`, `~/.cache/ruff` keyed on OS + Python + lock/config
- **Artifacts**: docs site, Agent Portal, coverage, JUnit are uploaded for each run
- **Branch protection (recommended)**: require `precommit`, `lint`, `types`, `tests` to merge

---

## Glossary

- **Agent Catalog** — machine‑readable index of packages/modules/symbols with stable anchors and links
- **Agent Portal** — static HTML UI over the catalog with search and deep links
- **Anchor** — a deep link to source (editor/GitHub), optionally including a line number
- **PATH_MAP** — rules for translating container paths to editor workspace paths
- **DocFacts/NavMap** — generated indices that power docs and linking
- **RFC 9457 Problem Details** — standard JSON error envelope for HTTP APIs

---

**This document is the authoritative operating protocol for agents.** If a task conflicts with these rules, prefer the rules — or open a proposal under `openspec/changes/**` to evolve them.
