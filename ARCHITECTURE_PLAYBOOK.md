

# Architecture Narrative Generation Playbook

*(For LLM agents embedded in a codebase-aware development environment)*

## 0. Purpose & Scope

You are an AI coding agent operating inside a software repository with access to code search, file reading, and (optionally) rich metadata such as ASTs, CSTs, symbol graphs, and dependency graphs.

Your task is to **create and maintain a single, cohesive “Architecture Narrative”** (or a small set of tightly related documents) that:

1. Explains the system’s architecture in clear, structured, layered prose.
2. Is optimized for **other LLMs and human engineers** to understand and modify the system safely.
3. Acts as a **normative reference** for future changes: it describes how the system is *intended* to be structured and extended.

You must:

* Base your narrative on the **actual code and metadata**, not speculation.
* Make architecture concepts **discoverable from natural language** (e.g. “How do I add a new index type?”).
* Make invariants, layering rules, and extension patterns explicit.

If the repository has an **AGENTS.md** or similar guidelines file, you must follow its conventions and not contradict them.

---

## 1. Assumptions & Capabilities

Assume you have:

* A way to:

  * List files/directories.
  * Search text across the repository (e.g. “full-text search”, “symbol search”).
  * Read complete files and/or segments.
* Possibly, additional metadata tools (if available):

  * AST/CST views.
  * Symbol graph (definitions and references).
  * Dependency graph (module import relationships).
  * Code metrics (LOC, fan-in, fan-out).
* Ability to:

  * Create/edit markdown docs inside the repo (e.g. `docs/architecture/ARCHITECTURE_NARRATIVE.md`).
  * Create small helper docs (e.g. symbol indices) if needed.

If any of these capabilities are missing, you must **adapt** the steps below, but never skip them silently: explicitly note limitations in the narrative.

---

## 2. Global Behavior Rules

When generating the architecture narrative:

1. **Be grounded in code**

   * Do not invent modules, flows, or components that don’t exist.
   * If you must speculate (e.g. behavior not derivable from code), mark it clearly as **“(Hypothesis)”** and keep it minimal.

2. **Prefer stable, canonical names**

   * Always use full module paths (e.g. `package/subpackage/module.py`) and fully qualified symbol names (`package.module.Class.method`).
   * Avoid ambiguous pronouns like “this module” when multiple candidates exist.

3. **Follow repository conventions**

   * If there is an **AGENTS.md** or style guide, obey its formatting and terminology rules.
   * Do not introduce new formatting conventions unless absolutely necessary, and then explain them.

4. **Use templates consistently**

   * For sections that repeat (module entries, flows, extension recipes), always follow the same template.
   * Consistency is more important than clever phrasing.

5. **Make invariants and guardrails explicit**

   * Use strong language for rules:

     * “Always…”
     * “Never…”
     * “Must…”
   * Tie rules to consequences (“violating this may corrupt indices” etc.).

6. **Optimize for retrieval & chunking**

   * Make each section reasonably self-contained.
   * Begin important sections with a short **TL;DR**.
   * Repeat critical invariants in both higher-level summaries and local sections.

7. **Document your uncertainty**

   * If parts of the code are unclear or contradictory, say so explicitly and provide pointers:

     * “This module appears to be legacy; its responsibilities overlap with X. Needs human review.”

---

## 3. High-Level Workflow Overview

You will create the architecture narrative in **phases**:

1. **Phase A – Pre-flight & Context Discovery**
2. **Phase B – Codebase Recon & Structural Mapping**
3. **Phase C – Document Skeleton (Table of Contents)**
4. **Phase D – System Purpose & Context Sections**
5. **Phase E – Domain Model & Glossary**
6. **Phase F – Static Structure: Layers, Modules, Dependencies**
7. **Phase G – Runtime Behavior & Key Flows**
8. **Phase H – Data & Metadata Structures**
9. **Phase I – Cross-cutting Concerns**
10. **Phase J – Change Patterns & Extension Recipes**
11. **Phase K – Testing & Operational Views**
12. **Phase L – Indices & Cross-References**
13. **Phase M – Validation & Coverage Check**

You should proceed roughly in this order, but you may iterate: discover more during later phases and then update earlier sections.

---

## 4. Phase A – Pre-flight & Context Discovery

**Goal:** Understand any existing documentation, conventions, and non-code context so you don’t reinvent or contradict it.

### Steps

1. **Search for existing architecture docs**

   * Look for files/directories like:

     * `docs/architecture/`
     * `ARCHITECTURE.md`, `SYSTEM_DESIGN.md`
     * `README.md` in root or key packages.
   * Read them fully and summarize:

     * What they claim about system purpose, components, and constraints.
     * Any clearly stated invariants or layering rules.

2. **Locate agent guidelines**

   * Search for:

     * `AGENTS.md`, `CONTRIBUTING.md`, `DEVELOPING.md`, `TESTING.md`.
   * Extract:

     * Style/formatting rules that apply to docs.
     * Testing philosophy and quality gates (use later).
     * Any instructions on how agents should behave.

3. **Identify configuration & entrypoints**

   * Search for:

     * `main.py`, `__main__.py`, `cli.py`, `app.py`, `wsgi.py`, `asgi.py`.
     * CLI definitions (Typer, click, argparse).
     * Framework entrypoints (FastAPI, Django, etc.).
   * Note:

     * How the system is typically started.
     * What high-level responsibilities are attached to each entrypoint.

4. **Create a short internal summary (not final doc)**

   * For yourself, note:

     * System’s apparent purpose.
     * Existing architecture documentation coverage.
     * Gaps or contradictions you notice.

You will refine these in the actual narrative later.

---

## 5. Phase B – Codebase Recon & Structural Mapping

**Goal:** Build a mental (and textual) map of how the code is organized: packages, key modules, and dependencies.

### Steps

1. **List top-level packages and modules**

   * Enumerate directories at the top of the repo that contain Python packages (or analogous for other languages).
   * Ignore pure config or tooling directories at first (e.g. `.github`, `.ci`, `.vscode`, etc.) unless clearly part of runtime.

2. **For each top-level package:**

   * List subpackages and key modules (names and paths).
   * Tag each with a **provisional role**, such as:

     * `cli`: entrypoints, commands.
     * `services`: business logic.
     * `io/adapters`: DB, file system, external APIs.
     * `models`: domain models, schemas.
     * `config/settings`: configuration.
     * `tests`: tests.

3. **Use dependency analysis (if available)**

   * Use import graphs or symbol graphs to identify:

     * High fan-in modules (used by many others).
     * High fan-out modules (depend on many others).
   * Mark these as **architecturally significant**; they will get more detailed coverage later.

4. **Identify “layers” heuristically**

   * Look for patterns in imports:

     * Low-level modules rarely import higher-level code.
     * CLI or API modules import services, which import IO or models.
   * Draft a **provisional layering** like:

     * Layer 1: CLI / API entrypoints
     * Layer 2: Application services
     * Layer 3: Domain models / business logic
     * Layer 4: IO / infrastructure adapters
     * Layer 5: Shared utilities

5. **Capture a rough structural summary**

   * Create a small internal note (for yourself, not yet final doc) describing:

     * Each layer
     * Which packages/modules belong to it
     * Any circular or suspicious dependencies

You’ll turn this into a polished “Static Structure” section later.

---

## 6. Phase C – Document Skeleton (Table of Contents)

**Goal:** Create the architecture narrative file(s) and wire in a consistent, LLM-friendly structure.

### Steps

1. **Create or update the main doc**

   * Prefer: `docs/architecture/ARCHITECTURE_NARRATIVE.md`
   * If docs folder doesn’t exist, create `docs/` and then `architecture/`.

2. **Write the initial skeleton with headings**

Use this base structure (you may adapt naming, but keep the hierarchy):

```markdown
# Architecture Narrative

## 0. How to Use This Document (For Humans & AI Agents)
## 1. System Purpose & High-Level Overview
## 2. Domain Model & Glossary
## 3. Architectural Principles & Constraints
## 4. System Context & External Integrations
## 5. Runtime Behavior & Key Flows
## 6. Static Structure: Layers, Modules, and Dependencies
## 7. Data & Metadata Structures
## 8. Cross-Cutting Concerns
## 9. Change Patterns & Extension Recipes
## 10. Testing & Quality Gates
## 11. Operational & Deployment View
## 12. Architectural Decisions & History
## 13. Indices & Cross-References
```

3. **Add stubs under each heading**

   * For each section, add a placeholder text like:

     * `> TODO: Agent to fill this section following the Architecture Narrative Generation Playbook.`
   * This reminds future agents (and humans) that the section is intentional, not an omission.

From now on, you will iteratively fill in each section.

---

## 7. Phase D – Section 0 & 1: “How to Use” + System Purpose

### 7.1 Section 0 – How to Use This Document (For Humans & AI Agents)

**Goal:** Instruct future consumers (including LLMs) on how to read and rely on this narrative.

**Template:**

```markdown
## 0. How to Use This Document (For Humans & AI Agents)

**Audience**

- Primary: AI coding agents and senior engineers working on this repository.
- Secondary: Stakeholders seeking a high-level understanding of the system.

**Scope**

- This document describes the intended architecture of the system.
- It is **normative**: if code disagrees with this narrative, treat the narrative as the desired target and propose refactors.

**Reading Order**

- Start with Section 1 (System Purpose) and Section 3 (Architectural Principles).
- For code changes in a specific area:
  - Read Section 6 (Static Structure) for the relevant module/package.
  - Read Section 9 (Change Patterns) for instructions on how to modify or extend that area.
  - Read Section 10 (Testing & Quality Gates) for required tests.

**Conventions**

- File paths are written as: `package/subpackage/module.py`.
- Symbols are written as: `package.module.Class.method`.
- Important invariants and “never do this” rules are explicitly labeled.
- Hypotheses or unclear areas are labeled with **(Hypothesis)** or **(Needs Review)**.

**Norms for AI Agents**

- Always ground your changes in this document and the actual code.
- If you detect discrepancies between this narrative and the code:
  - Explain the discrepancy.
  - Recommend a resolution (update narrative vs refactor code).
- Never silently violate stated invariants or principles.
```

Populate and adjust these bullet points to reflect the repo’s real paths, special tools, and rules.

### 7.2 Section 1 – System Purpose & High-Level Overview

**Goal:** State *what* the system is for and *why it exists* in concrete terms.

**Steps:**

1. **Extract purpose from existing docs & entrypoints**

   * Look at root `README`, any intro docs, and main entrypoints.
   * Identify:

     * Primary users/consumers (developers, analysts, services, etc.).
     * Main problem the system solves.
     * High-level value proposition.

2. **Write the section with this template:**

```markdown
## 1. System Purpose & High-Level Overview

### 1.1 Mission

[Tightly written 3–5 sentences describing what the system does, for whom, and what problems it solves.]

### 1.2 Non-Goals

- [Bulleted list of things the system explicitly does not try to do.]

### 1.3 Primary Use Cases

- **Use Case A** – [Short name]
  - What: [1–2 sentences]
  - Who: [user or system]
  - Where in code: [key modules or entrypoints]

- **Use Case B** – ...

### 1.4 External Systems and Stakeholders

- **Upstream inputs**
  - [System A]: what data it provides, where it enters the system.
- **Downstream consumers**
  - [System B / User type]: what they consume from this system.

### 1.5 Key Constraints

- Performance: [e.g., must handle N documents per hour].
- Reliability: [e.g., must avoid data corruption for indices].
- Security/Compliance: [any special rules if applicable].
```

3. **Base statements on evidence**

   * If you infer a use case from code patterns, confirm:

     * E.g. “CLI command `foo` suggests use case X.”
   * If uncertain, label it as **(Hypothesis)**.

---

## 8. Phase E – Domain Model & Glossary (Section 2)

**Goal:** Define the core concepts and their relationships, and map them to code.

### Steps

1. **Identify domain entities**

   * Search for:

     * `models.py`, `schemas.py`, domain-specific class names.
     * Pydantic/Dataclass models.
     * ORM models (if using an ORM).
   * Cluster them into domain concepts: e.g. `Corpus`, `Document`, `Chunk`, `Index`, `Query`.

2. **Create a glossary table**

Template:

```markdown
## 2. Domain Model & Glossary

### 2.1 Glossary

| Term      | Definition (Plain Language)                                       | Primary Code Representations                                  |
|----------|--------------------------------------------------------------------|----------------------------------------------------------------|
| Corpus   | [Concise description]                                              | `package.models.CorpusModel`, `db.table_corpora`              |
| Document | [Concise description]                                              | `package.models.DocumentModel`, `db.table_documents`          |
| Chunk    | [Concise description]                                              | `package.models.ChunkModel`                                  |
| ...      | ...                                                                | ...                                                            |

### 2.2 Entity Relationships (Textual Overview)

- A **Corpus** contains many **Document**s.
- Each **Document** is split into multiple **Chunk**s.
- A **Chunk** may be associated with one or more **IndexEntry** records.
```

3. **Map concepts to code**

   * For each row, fill the “Primary Code Representations” column with:

     * Classes, modules, or tables that embody the concept.
   * Use fully qualified names.

4. **Keep terminology consistent**

   * Choose one term per concept and use it consistently across all sections.

---

## 9. Phase F – Static Structure: Layers, Modules, Dependencies (Section 6)

You’ll come back to Section 3–5 shortly; the static structure leverages your Phase B recon.

**Goal:** Describe how the code is organized and what each major module does.

### 9.1 Define layers

In Section 6, create a subsection:

```markdown
## 6. Static Structure: Layers, Modules, and Dependencies

### 6.1 Layer Overview

We structure the system into the following logical layers:

1. [Layer 1] – [Short description]
2. [Layer 2] – ...
```

For each layer, document:

* **Responsibilities**
* **Allowed dependencies** (what it may import/call).
* **Forbidden dependencies** (what it must not depend on).

### 9.2 Create a module catalog

For each **architecturally significant module/package**, add an entry using this consistent template:

```markdown
#### Module: `package/subpackage/module.py`

**Role**

[1–3 sentences describing what this module is responsible for.]

**Public Surface**

- `package.module.ClassA`
- `package.module.function_x(...)`

**Dependencies**

- Calls into:
  - `package.other.module1`
  - `package.io.storage`
- Used by:
  - `package.cli.commands`
  - `package.services.service_x`

**Invariants**

- [Rule 1, e.g. “All index operations must be atomic from the caller’s perspective.”]
- [Rule 2, e.g. “Never perform network IO from this module.”]

**Extension Points**

- To add a new [thing]:
  - Implement `AbstractSomething` in this module.
  - Register it in `package.registry.something_registry`.
  - Add tests in `tests/package/test_something.py`.

**Anti-Patterns**

- Do **not**:
  - Bypass `SomethingRegistry` and construct implementations manually.
  - Call into higher-level layers from this module.
```

Populate this catalog for:

* High fan-in modules.
* Entrypoints.
* Core services.
* IO/infrastructure wrappers.
* Configuration and settings.

Use code search and symbol graphs to find where each module is used and what it depends on.

---

## 10. Phase G – Runtime Behavior & Key Flows (Section 5)

**Goal:** Describe the typical execution paths through the system (e.g. indexing, query handling).

### Steps

1. **Identify top workflows**

   * Search for:

     * CLI commands associated with end-to-end actions.
     * API endpoints.
     * Scheduled jobs or pipelines.
   * Choose the 5–10 most important flows.

2. **For each flow, write an entry using this template:**

```markdown
### 5.X Flow: [Flow Name] – [Short Tagline]

**Trigger**

- [CLI command / HTTP endpoint / scheduled job]
- Code entrypoints: `package.cli:command_x`, `package.api:route_y`.

**High-Level Steps**

1. [Step 1: e.g., “Validate input corpus configuration.”]
2. [Step 2: “Load documents using `package.io.loader`.”]
3. [Step 3: “Chunk documents via `package.services.chunker`.”]
4. ...

**Components Involved**

- `package.cli.commands.index_corpus`
- `package.services.chunker.DocumentChunker`
- `package.io.index_writer.IndexWriter`

**Key Invariants**

- [Invariant 1, e.g., “Chunks must be idempotent for a given (corpus_id, document_id, chunk_index).”]
- [Invariant 2, e.g., “Failures in writing to index must not corrupt existing index state.”]

**Error Handling & Retries**

- Errors in [component] are propagated/logged as [exception type].
- Retries are handled by [mechanism], with [backoff strategy] if applicable.
```

3. **Base the steps on actual code**

   * Follow the call graph from entrypoint through services and IO.
   * Confirm each step with real functions/methods.

---

## 11. Phase H – System Context & External Integrations (Section 4)

**Goal:** Show how the system interacts with external systems.

### Steps

1. **Scan for external connections**

   * Look for:

     * Configuration keys (e.g. URLs, API keys).
     * Client modules (e.g. `requests`, DB clients, message queues).

2. **Document in Section 4:**

```markdown
## 4. System Context & External Integrations

### 4.1 Inbound Interfaces

- **CLI**
  - Entry module: `package.cli.main`.
  - Commands: [list briefly].

- **HTTP API**
  - Framework: [FastAPI/Django/Flask/None].
  - Entry module: `package.api.app`.

### 4.2 Outbound Dependencies

- **Database: [Name]**
  - Client: `package.io.db_client`.
  - Used for: [what data].
  - Connection pattern: [e.g., pooled per process].

- **Vector Store: [If any]**
  - Client: `package.io.vector_store_client`.
  - Stored entities: [e.g., chunk embeddings].
```

3. **Include trust boundaries and security notes**

   * For each external integration, mention:

     * Input validation.
     * Authentication/authorization.
     * Error handling.

---

## 12. Phase I – Cross-Cutting Concerns (Section 8)

**Goal:** Document patterns that apply across many modules: logging, config, errors, concurrency, performance.

### Steps

Create subsections:

```markdown
## 8. Cross-Cutting Concerns

### 8.1 Configuration Management
### 8.2 Logging & Observability
### 8.3 Error Handling
### 8.4 Concurrency & Parallelism
### 8.5 Performance & Scaling
```

For each:

1. **Discover the pattern**

   * Search for:

     * `logging` usages, custom loggers.
     * Config loading modules (`settings.py`, env var readers).
     * Custom exception classes.
     * Threading, asyncio, multiprocessing usage.
   * Identify common patterns and any specific rules.

2. **Document rules and anti-patterns**

   * Example for configuration:

```markdown
### 8.1 Configuration Management

**Pattern**

- Configuration is centralized in `package.config.settings`.
- Config is loaded at process startup and treated as read-only thereafter.

**Rules**

- Always access config via `settings` objects, never directly via `os.environ`.
- New configuration keys must be added to `settings.py` with defaults and typed definitions.

**Anti-Patterns**

- Do **not**:
  - Read env vars directly in business logic.
  - Modify `settings` at runtime.
```

Replicate this approach for logging, errors, concurrency, etc.

---

## 13. Phase J – Change Patterns & Extension Recipes (Section 9)

**Goal:** Provide pre-defined playbooks for common modifications, so future agents follow safe, repeatable patterns.

### Steps

1. **Identify high-frequency change types**

   * E.g.:

     * Add a new feature flag.
     * Add a new index type.
     * Add a new CLI command.
     * Integrate a new external service.
     * Add a new metadata dataset.

2. **For each, write a recipe:**

```markdown
## 9. Change Patterns & Extension Recipes

### 9.1 How to Add a New [Thing]

**When to Use This**

- [Brief description of scenario.]

**Preconditions**

- Read:
  - Section 6 entry for `package/module`.
  - Relevant flow description in Section 5.
  - Any related ADRs in Section 12.

**Steps**

1. Define [new model or type] in `package.models.[...]`.
2. Add configuration entries to `package.config.settings`.
3. Implement [new service or adapter] in `package.services.[...]`.
4. Wire new behavior into [CLI/API] entrypoints.
5. Add tests:
   - Unit tests: `tests/package/test_[...]_unit.py`.
   - Integration tests: `tests/package/test_[...]_integration.py`.

**Required Tests & Checks**

- [List of tests that must be added or updated.]
- [Mention type-checking, linting, etc.]

**Success Criteria**

- [Functional success condition, e.g., “New index is discoverable via [command] and passes golden tests.”]
- [No violation of invariants listed in Section 6 and 8.]
```

3. **Ground recipes in real code structure**

   * Use actual file paths and modules.
   * If multiple valid patterns exist, choose one canonical pattern and document only that unless alternatives are necessary.

---

## 14. Phase K – Testing & Operational Views (Sections 10 & 11)

### 14.1 Section 10 – Testing & Quality Gates

**Goal:** Summarize how testing is organized and what gates must be respected.

**Steps**

1. **Discover testing strategy**

   * Inspect `tests/` directory structure.
   * Read any testing docs in AGENTS/testing guides.
   * Identify:

     * Types of tests (unit/integration/e2e).
     * Test naming conventions.
     * Fixtures and test data patterns.

2. **Document with template:**

```markdown
## 10. Testing & Quality Gates

### 10.1 Test Types

- **Unit tests**
  - Location: `tests/unit/` or `tests/package/test_*.py`.
  - Purpose: [short description].

- **Integration tests**
  - Location: `tests/integration/`.
  - Purpose: [short description].

- **End-to-end / golden tests**
  - Location: [paths].
  - Purpose: [short description].

### 10.2 Rules for Writing Tests

- Prefer [real collaborators / specific patterns] over monkeypatching (if applicable).
- Use [fixture patterns] from `tests/conftest.py`.
- For new features:
  - At least one unit test for each new behavior.
  - At least one integration/golden test when behavior crosses boundaries.

### 10.3 CI & Quality Gates

- Linting tools: [Ruff, etc.].
- Type checking: [Pyright, Mypy, Pyrefly].
- Additional analyzers: [Fixit, etc.].

All changes must pass these checks.
```

### 14.2 Section 11 – Operational & Deployment View

**Goal:** Show how the system runs in production or typical deployments.

**Steps**

1. **Identify deployment artifacts**

   * Look for Dockerfiles, Helm charts, deployment scripts, `systemd` units, etc.
   * Understand:

     * How services are started.
     * How they are configured at runtime.
     * Any horizontal/vertical scaling mechanisms.

2. **Document operational view:**

```markdown
## 11. Operational & Deployment View

### 11.1 Deployment Model

- [Single machine / Kubernetes / serverless / etc.]
- Typical instance layout and roles.

### 11.2 Runtime Configuration

- How configuration is provided (env vars, config files, flags).
- How secrets are handled.

### 11.3 Monitoring & Observability

- Metrics: [Prometheus, etc. if any].
- Logging aggregation.
- Alerting rules (if any available).

### 11.4 Migrations & Rollouts

- Database migrations process.
- Index rebuild strategy.
- Backward compatibility assumptions.
```

---

## 15. Phase L – Architectural Decisions & Indices (Sections 12 & 13)

### 15.1 Section 12 – Architectural Decisions & History (ADRs)

**Goal:** Capture important design decisions and their rationale.

**Steps**

1. **Search for existing ADRs or RFCs**

   * Files named `ADR-*.md`, `docs/rfcs/`, etc.
   * Summarize key ones here, or link them.

2. **If none exist, create a few ADRs for major decisions**

   * E.g., “Use FAISS for vector search instead of X.”
   * Use a standard ADR template:

     * Context
     * Decision
     * Alternatives
     * Consequences

3. **In Section 12, list ADRs:**

```markdown
## 12. Architectural Decisions & History

- ADR-001: [Title] – [1–2 sentence summary]
- ADR-002: ...
```

### 15.2 Section 13 – Indices & Cross-References

**Goal:** Make it easy for humans and LLMs to navigate between concepts, code, and this document.

**Steps**

1. **Create symbol index**

   * For key classes/modules, create a table:

```markdown
### 13.1 Symbol Index

| Symbol                                | Description                          | File Path                         | Relevant Sections          |
|--------------------------------------|--------------------------------------|-----------------------------------|----------------------------|
| `package.module.FooManager`          | Manages [X]                          | `package/module.py`              | 6.?, 5.?                   |
| `package.services.IndexService`      | Orchestrates indexing flow          | `package/services/index.py`      | 5.?, 9.?                   |
```

2. **Create module index**

   * Map module paths to section references.

3. **Cross-link sections**

   * When describing a module in Section 6, link back to:

     * Flows (Section 5) that use it.
     * Change recipes (Section 9) that modify it.

---

## 16. Phase M – Validation & Coverage Check

**Goal:** Ensure the architecture narrative is consistent, comprehensive, and grounded.

### Steps

1. **Coverage sanity check**

   * Verify that:

     * Every top-level package has at least a mention in Sections 1 or 6.
     * Every high fan-in module has a detailed entry.
     * Each major flow from Section 5 is grounded in real code.

2. **Consistency check**

   * Search for:

     * Terms used in the narrative and ensure they map to actual code concepts.
   * Check for:

     * Conflicting statements (e.g., “X must never call Y” vs code that clearly does).

3. **Hyperlink & reference check (if environment supports)**

   * Ensure all file paths and symbol names are correctly spelled and exist.

4. **Explicitly list known gaps**

   * At the end of the doc, optionally add:

```markdown
### Appendix: Known Gaps & Open Questions

- [Area]: [What’s unclear or incomplete, and what evidence you’d need to resolve it.]
```

This makes limitations of the narrative explicit and gives future agents a to-do list.

---

## 17. Ongoing Maintenance Instructions (for Future Agents)

At the top or bottom of the document, add a small maintenance note like:

```markdown
### Maintenance Rules (For AI Agents & Engineers)

- When you make significant architectural changes (new layers, major refactors, new external systems), you **must** update this document in the same change set.
- If you modify a module that has a Section 6 entry:
  - Review and update that entry’s Role, Public Surface, Dependencies, Invariants, and Extension Points.
- When you add a new major change pattern (e.g., new extensibility mechanism), add a recipe to Section 9.
- Do not remove content from this narrative without confirming it is outdated and reflected nowhere in the code.
```

This ensures your architecture narrative stays alive rather than decaying.

---

If you’d like, I can now turn this playbook into a concrete `ARCHITECTURE_NARRATIVE_GENERATION_PLAYBOOK.md` (or an `AGENTS-ARCHITECTURE.md` section) with repo-agnostic wording cleaned up for direct copy-paste into your AGENTS docs.
