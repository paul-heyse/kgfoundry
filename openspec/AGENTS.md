# OpenSpec / AGENTS.md — Spec‑Driven Agent Operating Protocol

> **Purpose**: This guide teaches humans and AI agents how to use **OpenSpec** to plan, review, implement, and archive changes with **production‑grade predictability**. It specifies exact command sequences, acceptance gates, file formats, and templates so specs remain the source of truth while code stays in lock‑step.

---

## Table of contents
1. [What OpenSpec is (and isn’t)](#what-openspec-is-and-isnt)
2. [When to create a proposal (decision tree)](#when-to-create-a-proposal-decision-tree)
3. [Lifecycle & gates: Propose → Implement → Archive](#lifecycle--gates-propose--implement--archive)
4. [Repository layout & do‑not‑edit zones](#repository-layout--do-not-edit-zones)
5. [Authoring rules: requirements & scenarios](#authoring-rules-requirements--scenarios)
6. [Delta operations: ADDED / MODIFIED / REMOVED / RENAMED](#delta-operations-added--modified--removed--renamed)
7. [Templates (copy/paste)](#templates-copypaste)
8. [CLI usage: the 20% you’ll run 80% of the time](#cli-usage-the-20-youll-run-80-of-the-time)
9. [Branching, PRs, and CI integration](#branching-prs-and-ci-integration)
10. [Data contracts & schema policy](#data-contracts--schema-policy)
11. [Agent handoff protocol (planning before code)](#agent-handoff-protocol-planning-before-code)
12. [Troubleshooting & common errors](#troubleshooting--common-errors)
13. [Governance: reviews, SLAs, and merges](#governance-reviews-slas-and-merges)
14. [Glossary](#glossary)

---

## What OpenSpec is (and isn’t)

**OpenSpec is a change management system** for this repo:
- It captures **why**, **what**, and **acceptance** *before* code is written.
- It lets agents generate **deterministic tasks** and **tests** from agreed specs.
- It keeps long‑lived **capability specs** separate from short‑lived **change proposals**.

**OpenSpec isn’t** a replacement for code review or standards. It complements them by making the intent explicit, testable, and archived.

---

## When to create a proposal (decision tree)

```
New request?
├─ Bug fix that restores intended behavior → implement directly (no proposal)
├─ Typos / comments / formatting only → direct change
├─ Non‑breaking config / dependency update → direct change
├─ New capability or behavior → proposal REQUIRED
├─ Breaking change (API, schema, user‑visible) → proposal REQUIRED
├─ Cross‑cutting or architecture shift → proposal REQUIRED
└─ Unclear scope → proposal RECOMMENDED
```

**Rule of thumb**: if a reviewer would ask “what exactly changes and how do we accept it?”, you need a proposal.

---

## Lifecycle & gates: Propose → Implement → Archive

### Stage 1 — **Propose**
**Goal**: agree on intent and acceptance *before* code.

**Deliverables**
- `openspec/changes/<change-id>/proposal.md` — why + what + impact
- `openspec/changes/<change-id>/tasks.md` — implementation checklist (ordered)
- `openspec/changes/<change-id>/specs/<capability>/spec.md` — **deltas** (ADDED/MODIFIED/REMOVED/RENAMED)
- `openspec/changes/<change-id>/design.md` — *optional*, include only if cross‑cutting or ambiguous

**Gates (must pass)**
```bash
openspec validate <change-id> --strict
# All delta files have valid operations; every requirement has ≥1 Scenario; no format violations.
```

> **Do not start coding** until the proposal validates and reviewers approve.

---

### Stage 2 — **Implement**
**Goal**: code to spec; keep docs and artifacts in sync.

**Agent steps**
1. Read `proposal.md`, (optional) `design.md`, and `tasks.md`.
2. Execute tasks in order (check off as you go).
3. Keep data contracts in sync (see [Data contracts](#data-contracts--schema-policy)).
4. Run local quality gates (Ruff → pyrefly → pyright → pytest → artifacts).

**Gates**
```bash
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13 && uv run pyrefly check
SKIP_GPU_WARMUP=1 uv run pytest -q    # unset on CUDA-capable hosts
make artifacts && git diff --exit-code
openspec validate <change-id> --strict
```

> **Heads-up:** drop `SKIP_GPU_WARMUP=1` when running on GPU-capable hosts so the warm-up smoke tests execute.

---

### Stage 3 — **Archive**
**Goal**: record what landed and close the loop.

**Actions**
- Move `openspec/changes/<change-id>/` → `openspec/changes/archive/YYYY-MM-DD-<change-id>/`
- If a capability changed, ensure the canonical spec under `openspec/specs/**` reflects the final truth
- Run validation on archived change
```bash
openspec archive <change-id> --yes
openspec validate --strict
```

---

## Repository layout & do‑not‑edit zones

```
openspec/
├── project.md              # Conventions & global rules
├── specs/                  # Canonical truth (WHAT IS)
│   └── <capability>/
│       ├── spec.md         # Requirements & Scenarios (normative)
│       └── design.md       # Patterns and rationale (optional)
├── changes/                # Proposals (WHAT SHOULD CHANGE)
│   ├── <change-id>/
│   │   ├── proposal.md
│   │   ├── tasks.md
│   │   ├── design.md       # optional
│   │   └── specs/
│   │       └── <capability>/spec.md   # delta file(s)
│   └── archive/            # Completed changes (read‑only)
```

**Do not hand‑edit** archives except via the `openspec archive` flow.

---

## Authoring rules: requirements & scenarios

- **Normative language**: use **SHALL/MUST** for requirements (avoid “should/may” unless non‑normative).
- **Requirement header**: `### Requirement: <concise name>` — one capability per requirement.
- **Scenario header**: `#### Scenario: <name>` — **exactly four hashes** and the word “Scenario”.
- **Scenario body**: bullet list using **WHEN / THEN** (and **GIVEN** if needed). Keep steps minimal and testable.
- **Acceptance**: every requirement MUST have ≥1 scenario.
- **IDs**: if you reference IDs, prefer kebab‑case (e.g., `import-catalog-anchors`).

**Good example**
```markdown
### Requirement: Import Catalog Anchors
The system SHALL import anchors for all modules emitted by the Docs pipeline.

#### Scenario: Import success
- **WHEN** the importer runs
- **THEN** anchors are persisted with package, module, file, and line number
```

**Anti‑example**
```markdown
- Scenario: Import works  # ❌ wrong header format (missing ####)
- When importer does stuff # ❌ lowercase and vague
```

---

## Delta operations: ADDED / MODIFIED / REMOVED / RENAMED

Pick the **smallest correct** operation; use one file per capability under the change.

- `## ADDED Requirements` — introduce a new requirement
- `## MODIFIED Requirements` — change an existing requirement (paste the **entire** updated block)
- `## REMOVED Requirements` — explicitly remove a requirement (include reason + migration)
- `## RENAMED Requirements` — rename a requirement (pair with MODIFIED if content changes)

**Common pitfall**: Using MODIFIED to append details without pasting the previous full text. Always paste the entire requirement; partial deltas drop prior details at archive time.

**RENAMED example**
```markdown
## RENAMED Requirements
- FROM: `### Requirement: Login`
- TO:   `### Requirement: User Authentication`
```

---

## Templates (copy/paste)

### `changes/<change-id>/proposal.md`
```markdown
## Why
[Problem/opportunity in 1–3 sentences]

## What Changes
- [Bullet list of changes]
- [Mark breaking changes with **BREAKING**]

## Impact
- Affected specs: [list capabilities]
- Affected code: [modules, services, schemas]
- Rollout: [flags, migrations, compatibility]
```

### `changes/<change-id>/tasks.md`
```markdown
## 1. Implementation
- [ ] 1.1 ...
- [ ] 1.2 ...

## 2. Testing
- [ ] 2.1 Unit
- [ ] 2.2 Integration
- [ ] 2.3 Doctests / examples

## 3. Docs & Artifacts
- [ ] 3.1 Update examples
- [ ] 3.2 make artifacts
- [ ] 3.3 Validate OpenSpec

## 4. Rollout
- [ ] 4.1 Flags / config
- [ ] 4.2 Metrics / dashboards
```

### `changes/<change-id>/design.md` (optional)
```markdown
## Context
[Background, constraints]

## Goals / Non‑Goals
- Goals: [...]
- Non‑Goals: [...]

## Decisions
- Decision: [What & why]
- Alternatives: [Considered, rejected]

## Risks / Trade‑offs
- [Risk] → Mitigation

## Migration
- Steps & rollback
```

### Delta file `changes/<change-id>/specs/<capability>/spec.md`
```markdown
## ADDED Requirements
### Requirement: <New capability>
The system SHALL ...

#### Scenario: <Happy path>
- **WHEN** ...
- **THEN** ...

## MODIFIED Requirements
### Requirement: <Existing capability>
[Full, updated text of the requirement including scenarios]

## REMOVED Requirements
### Requirement: <Capability>
**Reason**: [...]
**Migration**: [...]
```

---

## CLI usage: the 20% you’ll run 80% of the time

```bash
# List specs & changes
openspec spec list --long
openspec list

# Show details (human/json)
openspec show <spec-or-change>
openspec show <change> --json --deltas-only | jq '.'

# Validate (always strict)
openspec validate <change-id> --strict

# Archive when done
openspec archive <change-id> --yes
openspec validate --strict
```

**Full‑text search tips**
```bash
# Find requirements & scenarios quickly
rg -n "^(### Requirement:|#### Scenario:)" openspec

# Show headings only
rg -n "^#|^## |^### Requirement:|^#### Scenario:" openspec
```

---

## Branching, PRs, and CI integration

- **Branch name**: `openspec/<change-id>` (e.g., `openspec/add-agent-catalog-stdio-api`)
- **PR description** must include:
  - Link to `openspec/changes/<change-id>/proposal.md`
  - Snapshot of `tasks.md` progress (checked boxes)
  - Summary of delta operations per capability
  - CI artifact links (docs, portal, coverage, pyright report)
- **CI gates** (required to merge):
  - precommit → lint (Ruff) → types (pyright + pyrefly) → tests → docs
  - `openspec validate <change-id> --strict` runs in CI and must pass
- **Artifacts**:
  - Docs site & Agent Portal uploaded for preview
  - Coverage and JUnit uploaded for quick triage
  - (Optional) pyright HTML report uploaded for type issues

---

## Data contracts & schema policy

- **Golden rule**: if data crosses a boundary, declare a **JSON Schema 2020‑12** (OpenAPI 3.1 for HTTP).
- **Change process**: breaking contract updates require a proposal; non‑breaking may be direct with tests.
- **Validation**: tests must validate payloads against schemas; PR must link schema diffs for reviewers.

---

## Agent handoff protocol (planning before code)

Every implementation task must begin with a **four‑item design note** in the PR:
1) **Summary** — one paragraph
2) **Public API sketch** — typed signatures
3) **Data/Schema contracts** — what changes and where the schema lives
4) **Test plan** — how we prove it works (unit, integration, doctest examples)

Agents must paste **command outputs** for: `ruff`, `pyrefly`, `pyright`, `pytest`, and `openspec validate`.

---

## Troubleshooting & common errors

- **“Change must have at least one delta”**
  Create `changes/<id>/specs/<capability>/spec.md` with `## ADDED|MODIFIED|REMOVED|RENAMED Requirements`.

- **“Requirement must have at least one scenario”**
  Ensure **`#### Scenario:`** headers are used (four `#`), not bullets/bold/`###`.

- **Silent scenario parse failure**
  Header must be *exactly* `#### Scenario: <name>` on its own line. Debug with:
  ```bash
  openspec show <change-id> --json --deltas-only | jq '.deltas'
  ```

- **Ambiguous MODIFIED**
  Paste the entire requirement block from the canonical spec, then edit. Partial edits drop prior details.

- **Docs/catalog drift**
  Run `make artifacts` on a clean tree; commit generated outputs.

---

## Governance: reviews, SLAs, and merges

- **Reviewers**: at least one domain owner + one implementation owner.
- **SLA**: acknowledge within 1 business day; review within 3. Use “request changes” with concrete edits.
- **Merges**: require green CI, strict validation, and checked tasks list. Breaking changes require migration notes.

---

## Safe Tooling Practices

Documentation and tooling scripts in `docs/_scripts/` and `tools/` follow these conventions:

### Typed Facades for I/O Operations

Use the typed helpers in `docs._scripts.shared` for JSON operations:

```python
from docs._scripts import shared  # Internal tooling module

# Safe JSON deserialization with error handling
data = shared.safe_json_deserialize(
    path,
    logger=shared.build_warning_logger("my_operation")
)
if data is None:
    raise ValueError(f"Failed to load {path}")

# Safe JSON serialization with atomic writes
success = shared.safe_json_serialize(
    payload,
    path,
    logger=shared.build_warning_logger("my_operation")
)
if not success:
    raise ValueError(f"Failed to write {path}")
```

These helpers ensure:
- **Atomic writes** via temp-file-then-rename pattern (prevent partial writes)
- **Type safety** with explicit dict/list validation
- **Structured logging** with extra context fields
- **Path safety** using `pathlib` exclusively

### CLI Entry Points

All tools and docs scripts expose a typed `main()` entry point:

```python
from collections.abc import Sequence

def main(argv: Sequence[str] | None = None) -> int:
    """Describe the tool's purpose and output artifacts.
    
    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Command-line arguments (reserved for future use).
    
    Returns
    -------
    int
        Exit code (0 = success, non-zero = failure).
    """
    # Implementation here
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

### Error Handling

Follow RFC 9457 Problem Details for all errors:

```python
from tools import build_problem_details, render_problem

try:
    # operation
except SomeError as exc:
    problem = build_problem_details(
        type="https://kgfoundry.dev/problems/my-tool",
        title="Operation failed",
        status=500,
        detail=str(exc),
        instance=f"urn:tool:my-tool:{operation}",
    )
    print(render_problem(problem))
    return 1
```

### Defensive Exception Handling

When catching broad exceptions for observability, use `BaseException` with a `noqa` comment explaining the defensive purpose:

```python
except BaseException as exc:  # noqa: BLE001 - defensive catch ensures Problem Details emission
    observation.failure("exception", returncode=1)
    problem = build_problem_details(...)
    # ... emit structured error
    return 1
```

---

## Glossary

- **Capability** — a cohesive feature area described in `openspec/specs/<capability>`
- **Change** — a proposal under `openspec/changes/<id>` that modifies capabilities
- **Requirement** — normative statement under a capability (“SHALL/MUST”)
- **Scenario** — testable acceptance for a requirement (GIVEN/WHEN/THEN)
- **Delta** — operation in a change: ADDED/MODIFIED/REMOVED/RENAMED
- **Archive** — finalized change snapshot for audit

---

## Quick start (daily loop)

```bash
# Context
openspec spec list --long
openspec list

# Validate proposal
openspec validate <change-id> --strict

# Quality gates
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13 && uv run pyrefly check
SKIP_GPU_WARMUP=1 uv run pytest -q
make artifacts && git diff --exit-code

# Archive when done
openspec archive <change-id> --yes && openspec validate --strict
```
