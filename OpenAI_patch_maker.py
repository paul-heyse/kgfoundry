"""Generate repository-agnostic patch series for AI agent-friendly scaffolding."""

import datetime
import os
import pathlib
import random
import string
import textwrap
import zipfile

base_dir = "/mnt/data/patches"
pathlib.Path(base_dir).mkdir(exist_ok=True, parents=True)

author_name = "AI Maintainer Bot"
author_email = "bot@example.com"
now = datetime.datetime.utcnow()
date_str = now.strftime("%a, %d %b %Y %H:%M:%S +0000")


def random_sha() -> str:
    """Generate a random 40-character hexadecimal SHA string.

    Returns
    -------
    str
        Random hexadecimal string of length 40, suitable for use as a git commit SHA.
    """
    return "".join(random.choices("0123456789abcdef", k=40))


def diffstat_plus_signs(n: int) -> str:
    """Generate diffstat-style plus signs for a given number of lines.

    Parameters
    ----------
    n : int
        Number of lines added.

    Returns
    -------
    str
        String of plus signs scaled roughly like git's diffstat, with at least
        1 plus and at most 60 plus signs.
    """
    return "+" * max(1, min(60, (n + 2) // 3))


def make_patch(n: int, total: int, title: str, files: list[dict[str, str]]) -> str:
    """Generate a git patch file in unified diff format.

    Parameters
    ----------
    n : int
        Patch number in the series (1-indexed).
    total : int
        Total number of patches in the series.
    title : str
        Patch title/subject line.
    files : list[dict[str, str]]
        List of file dictionaries, each containing:
        - "path": File path relative to repository root.
        - "content": Full file content as string.
        - "mode": Optional file mode (defaults to "100644").

    Returns
    -------
    str
        Complete patch file content in git unified diff format.
    """
    # Compute diffstat
    files_changed = len(files)
    insertions = sum(len(f["content"].splitlines()) for f in files)
    sha = random_sha()

    header = []
    header.append(f"From {sha} Mon Sep 17 00:00:00 2001")
    header.append(f"From: {author_name} <{author_email}>")
    header.append(f"Date: {date_str}")
    header.append(f"Subject: [PATCH {n}/{total}] {title}")
    header.append("")
    header.append("---")

    # diffstat lines
    for f in files:
        lines = len(f["content"].splitlines())
        header.append(f" {f['path']} | {lines} {diffstat_plus_signs(lines)}")
    header.append(f" {files_changed} files changed, {insertions} insertions(+)")
    for f in files:
        header.append(f" create mode {f.get('mode', '100644')} {f['path']}")

    header.append("")
    body = []

    # diffs
    for f in files:
        content_lines = f["content"].splitlines()
        body.append(f"diff --git a/{f['path']} b/{f['path']}")
        body.append(f"new file mode {f.get('mode', '100644')}")
        body.append("index 0000000..1111111")
        body.append("--- /dev/null")
        body.append(f"+++ b/{f['path']}")
        body.append(f"@@ -0,0 +{len(content_lines)} @@")
        for line in content_lines:
            body.append("+" + line)
        body.append("")

    # trailer (simulated git version, not required but nice)
    body.append("-- ")
    body.append("2.39.2")

    patch_text = "\n".join(header + body) + "\n"
    return patch_text


# ---------- File contents (repo-agnostic, best-practice scaffolding) ----------

editorconfig = textwrap.dedent("""\
    # Editor configuration, see https://editorconfig.org
    root = true

    [*]
    charset = utf-8
    end_of_line = lf
    insert_final_newline = true
    trim_trailing_whitespace = true
    indent_style = space
    indent_size = 2

    [*.md]
    trim_trailing_whitespace = false

    [Makefile]
    indent_style = tab
    indent_size = 4
""").strip()

gitattributes = textwrap.dedent("""\
    # Auto-detect text files and normalize line endings.
    * text=auto eol=lf

    # Treat images and archives as binary.
    *.png binary
    *.jpg binary
    *.jpeg binary
    *.gif binary
    *.svg text eol=lf
    *.pdf binary
    *.zip binary
    *.gz binary
    *.7z binary

    # Mark docs as documentation for linguist.
    docs/** linguist-documentation
""").strip()

gitignore = textwrap.dedent("""\
    # Global ignores (OS/editor)
    .DS_Store
    Thumbs.db
    .idea/
    .vscode/
    *.swp
    *.swo

    # Python
    __pycache__/
    *.py[cod]
    .venv/
    venv/
    .pytest_cache/
    .mypy_cache/
    .ruff_cache/
    .coverage
    coverage.xml
    .env
    .env.*

    # Node/JS
    node_modules/
    npm-debug.log*
    yarn-error.log*
    .pnpm-store/
    dist/
    build/
    coverage/

    # Go
    bin/
    *.test

    # Rust
    target/

    # Java/Gradle/Maven
    *.class
    .gradle/
    build/
    target/
    .mvn/
    dependency-reduced-pom.xml

    # PHP/Composer
    vendor/

    # Misc
    *.log
    .cache/
    .tox/
""").strip()

issue_bug = textwrap.dedent("""\
    name: Bug Report
    description: Report a reproducible problem
    labels: ["bug", "triage"]
    body:
      - type: markdown
        attributes:
          value: |
            Thanks for taking the time to fill out this bug report!
      - type: input
        id: version
        attributes:
          label: Version/Commit
          description: What version or commit hash are you running?
      - type: textarea
        id: description
        attributes:
          label: What happened?
          description: A clear and concise description of the bug.
      - type: textarea
        id: expected
        attributes:
          label: What did you expect to happen?
      - type: textarea
        id: reproduction
        attributes:
          label: Reproduction steps
          description: Minimal steps to reproduce the issue
          placeholder: |
            1. ...
            2. ...
            3. ...
      - type: textarea
        id: logs
        attributes:
          label: Logs/Stack traces
          render: shell
      - type: dropdown
        id: impact
        attributes:
          label: Impact
          options:
            - low
            - medium
            - high
        validations:
          required: true
""").strip()

issue_feature = textwrap.dedent("""\
    name: Feature Request
    description: Suggest an idea or improvement
    labels: ["enhancement"]
    body:
      - type: input
        id: summary
        attributes:
          label: Summary
          description: One-sentence description of the feature
      - type: textarea
        id: motivation
        attributes:
          label: Motivation
          description: Why is this needed? What problem does it solve?
      - type: textarea
        id: proposal
        attributes:
          label: Proposed solution
          description: Technical proposal / acceptance criteria
      - type: textarea
        id: alternatives
        attributes:
          label: Alternatives considered
      - type: dropdown
        id: scope
        attributes:
          label: Scope
          options:
            - small
            - medium
            - large
""").strip()

issue_config = textwrap.dedent("""\
    blank_issues_enabled: false
    contact_links:
      - name: Security issue?
        url: https://example.com/security
        about: Please report security vulnerabilities via SECURITY.md, not a public issue.
""").strip()

pr_template = textwrap.dedent("""\
    ## Summary
    <!-- What does this change do? Why? -->

    ## Type
    - [ ] Bug fix
    - [ ] Feature
    - [ ] Refactor/Chore
    - [ ] Docs

    ## Checklist (quality gates)
    - [ ] Tests added/updated or not applicable
    - [ ] Lint passes (`pre-commit run --all-files` or CI)
    - [ ] Backwards compatibility assessed
    - [ ] Security/secret scan clean
    - [ ] Docs updated (README/CHANGELOG if needed)

    ## Risk & Rollback
    <!-- Outline risk, user impact, and a rollback plan -->
""").strip()

codeowners = textwrap.dedent("""\
    # CODEOWNERS
    # Replace the placeholders below with your actual org/team or usernames.
    # Example: * @acme-inc/maintainers
    *       @OWNER_ORG/maintainers @GITHUB_USERNAME
""").strip()

security_md = textwrap.dedent("""\
    # Security Policy

    ## Reporting a Vulnerability
    Please email **security@example.com** with details and reproduction steps.
    Do not open public issues for security problems.

    ## Triage & SLA
    - Acknowledgement within 1 business day.
    - Initial assessment within 3 business days.
    - Coordinated disclosure and patch timelines agreed on a case-by-case basis.

    ## Supported Versions
    We generally support the latest minor release on the default branch.
""").strip()

coc_md = textwrap.dedent("""\
    # Code of Conduct

    We are committed to a respectful, inclusive, and harassment-free community.
    Be kind, assume good intent, and welcome constructive feedback.

    Unacceptable behavior includes harassment, discrimination, or personal attacks.
    Maintainers may take action including warnings or removal of contributions.

    If you experience or witness a problem, contact **conduct@example.com**.
""").strip()

pre_commit_yaml = textwrap.dedent("""\
    repos:
      - repo: https://github.com/pre-commit/pre-commit-hooks
        rev: v4.6.0
        hooks:
          - id: end-of-file-fixer
          - id: trailing-whitespace
          - id: check-added-large-files
          - id: check-merge-conflict
          - id: check-yaml
          - id: check-json
          - id: detect-private-key
          - id: mixed-line-ending
      - repo: https://github.com/psf/black
        rev: 23.12.1
        hooks:
          - id: black
            args: [--check]
            additional_dependencies: []
            exclude: "\\.venv/|venv/|node_modules/"
      - repo: https://github.com/charliermarsh/ruff-pre-commit
        rev: v0.4.7
        hooks:
          - id: ruff
            args: [--exit-zero]
            exclude: "\\.venv/|venv/|node_modules/"
""").strip()

install_hooks_sh = textwrap.dedent("""\
    #!/usr/bin/env bash
    set -euo pipefail
    if ! command -v pre-commit >/dev/null 2>&1; then
      python3 -m pip install --user pre-commit || pip install --user pre-commit
    fi
    pre-commit install
    echo "Pre-commit hooks installed."
""").strip()

ci_sh = textwrap.dedent("""\
    #!/usr/bin/env bash
    set -euo pipefail

    echo "Running repository-agnostic CI checks..."

    # Use Makefile if available
    if [ -f Makefile ] && make -n test >/dev/null 2>&1; then
      echo "Detected Makefile; running 'make test'"
      make test || true
    fi

    # Node/JS
    if [ -f package.json ]; then
      echo "Detected Node project"
      if command -v corepack >/dev/null 2>&1; then corepack enable || true; fi
      if [ -f pnpm-lock.yaml ]; then
        echo "Using pnpm"
        npm i -g pnpm >/dev/null 2>&1 || true
        pnpm install --frozen-lockfile || pnpm install
        pnpm run -r build --if-present || true
        pnpm run -r lint --if-present || true
        pnpm run -r test --if-present || true
      elif [ -f yarn.lock ]; then
        echo "Using yarn"
        npm i -g yarn >/dev/null 2>&1 || true
        yarn install --frozen-lockfile || yarn install
        yarn build || true
        yarn lint || true
        yarn test || true
      else
        echo "Using npm"
        npm ci || npm install
        npm run build --if-present || true
        npm run lint --if-present || true
        npm test --if-present || true
      fi
    fi

    # Python
    if [ -f pyproject.toml ] || [ -f requirements.txt ]; then
      echo "Detected Python project"
      python3 -m pip install --upgrade pip wheel setuptools || true
      if [ -f requirements.txt ]; then python3 -m pip install -r requirements.txt || true; fi
      if [ -f pyproject.toml ]; then python3 -m pip install -e . || true; fi

      # Lint and test if available
      if python3 -c "import ruff" 2>/dev/null; then ruff check . || true; fi
      if python3 -c "import black" 2>/dev/null; then black --check . || true; fi
      if python3 -c "import pytest" 2>/dev/null; then python3 -m pytest -q || true; fi
    fi

    # Go
    if [ -f go.mod ]; then
      echo "Detected Go project"
      go test ./... || true
    fi

    # Rust
    if [ -f Cargo.toml ]; then
      echo "Detected Rust project"
      cargo test --all --locked || cargo test --all || true
    fi

    # Java (Maven/Gradle)
    if [ -f pom.xml ]; then
      echo "Detected Maven project"
      mvn -q -B -DskipTests=false test || true
    fi
    if [ -f build.gradle ] || [ -f build.gradle.kts ]; then
      echo "Detected Gradle project"
      chmod +x ./gradlew || true
      ./gradlew test || true
    fi

    # PHP/Composer
    if [ -f composer.json ]; then
      echo "Detected PHP/Composer project"
      composer install --no-interaction --prefer-dist || true
      composer test || true
    fi

    # Pre-commit (if configured)
    if [ -f .pre-commit-config.yaml ]; then
      echo "Running pre-commit across the repo"
      python3 -m pip install --user pre-commit || pip install --user pre-commit || true
      pre-commit run --all-files --show-diff-on-failure || true
    fi

    echo "CI script finished."
""").strip()

ci_workflow = textwrap.dedent("""\
    name: CI (universal)
    on:
      push:
        branches: ["**"]
      pull_request:
        branches: ["**"]

    concurrency:
      group: ${{ github.workflow }}-${{ github.ref }}
      cancel-in-progress: true

    permissions:
      contents: read

    jobs:
      build:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4

          - name: Set up Node
            uses: actions/setup-node@v4
            with:
              node-version: "20"

          - name: Set up Python
            uses: actions/setup-python@v5
            with:
              python-version: "3.x"

          - name: Set up Go (if needed)
            if: ${{ hashFiles('**/go.mod') != '' }}
            uses: actions/setup-go@v5
            with:
              go-version: "1.22.x"

          - name: Set up Java (if needed)
            if: ${{ or(hashFiles('**/pom.xml') != '', hashFiles('**/build.gradle') != '', hashFiles('**/build.gradle.kts') != '') }}
            uses: actions/setup-java@v4
            with:
              distribution: temurin
              java-version: "17"

          - name: Run universal CI
            run: |
              chmod +x scripts/ci.sh
              scripts/ci.sh
""").strip()

dependabot = textwrap.dedent("""\
    version: 2
    updates:
      - package-ecosystem: "github-actions"
        directory: "/"
        schedule:
          interval: "weekly"
      - package-ecosystem: "npm"
        directory: "/"
        schedule:
          interval: "weekly"
      - package-ecosystem: "pip"
        directory: "/"
        schedule:
          interval: "weekly"
      - package-ecosystem: "gomod"
        directory: "/"
        schedule:
          interval: "weekly"
      - package-ecosystem: "maven"
        directory: "/"
        schedule:
          interval: "weekly"
      - package-ecosystem: "gradle"
        directory: "/"
        schedule:
          interval: "weekly"
      - package-ecosystem: "cargo"
        directory: "/"
        schedule:
          interval: "weekly"
      - package-ecosystem: "docker"
        directory: "/"
        schedule:
          interval: "weekly"
      - package-ecosystem: "composer"
        directory: "/"
        schedule:
          interval: "weekly"
""").strip()

ai_agents_md = textwrap.dedent("""\
    # AI Programming Agents – Operational Playbook

    This document sets expectations and guardrails for autonomous or semi-autonomous
    coding agents operating in this repository.

    ## Mission & Non-Goals
    - **Mission:** Safely produce small, reviewable, reversible changes that improve
      product quality, velocity, or security.
    - **Non-goals:** Large refactors without design review, invasive dependency
      changes, or policy overrides.

    ## Working Agreement
    1. Create a branch named `agent/<task>-<short-id>`.
    2. Make **small, incremental** commits with clear messages (Conventional Commits
       preferred, e.g., `fix: handle empty input`).
    3. Update or add tests for behavior changes.
    4. Keep PRs under ~300 lines changed where feasible.
    5. No secrets, tokens, or production data in commits or PR text.

    ## Invariants
    - CI must pass.
    - Linting and formatting must pass (`pre-commit` hooks).
    - Backwards compatibility maintained unless explicitly authorized.
    - All user-visible changes are documented in PR description.

    ## Quality Gates (PR checklist)
    - ✅ Tests updated/added
    - ✅ Lint/format clean
    - ✅ Security/secret scan clean
    - ✅ Rollback plan described

    ## Commit Message Guidance
    Use short imperative subject lines, ~50 chars; follow with context and “why”.
    Reference issues like `Fixes #123` when appropriate.

    ## Getting Unstuck
    - Attempt a minimal, self-contained reproduction.
    - Submit a draft PR and request human feedback.
    - Defer changes that require significant design discussion.

    ## Prohibited Actions
    - Writing or rotating secrets.
    - Modifying branch protection or CI permission settings.
    - Self-merging without review.

    ## Example task prompts
    - "Add input validation for empty usernames; include tests; avoid breaking API."
    - "Introduce fast path for `parse()` keeping identical results; add benchmarks if present."

    ## Observability of Changes
    - Prefer small telemetry additions behind feature flags (if available).
    - Link dashboards or test artifacts when relevant.

    ## Rollback
    - If a change causes failures after merge, revert promptly via `git revert` and
      open a follow-up issue with learnings.
""").strip()

architecture_md = textwrap.dedent("""\
    # Architecture (skeleton)

    > Replace this skeleton with a system diagram and ownership map.

    ## Components
    - Core modules/packages
    - External services/dependencies
    - Data flows and key invariants

    ## Build & Run
    - How to build, run, and test locally

    ## Extension Points
    - Public interfaces and integration guidance
""").strip()

contributing_md = textwrap.dedent("""\
    # Contributing

    Thank you for your interest in contributing!

    ## Quickstart
    1. Clone and create a branch: `git checkout -b feature/short-desc`.
    2. Install hooks: `./scripts/install-hooks.sh`.
    3. Run tests locally (see `scripts/ci.sh` for hints).
    4. Submit a PR with a clear description, risk/rollback, and links to issues.

    ## Coding Standards
    - Keep changes small and focused.
    - Prefer clarity over cleverness.
    - Update docs when behavior changes.

    ## Review Process
    - Two approvals required for risky changes (as defined by maintainers).
    - CI must be green.
""").strip()

license_mit = textwrap.dedent("""\
    MIT License

    Copyright (c) 2025 YOUR NAME OR ORG

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
""").strip()

# ---------------------- Patch definitions ----------------------
patches = []

# 0001
patches.append(
    {
        "title": "Repo hygiene: add .editorconfig, .gitattributes, and a universal .gitignore",
        "files": [
            {"path": ".editorconfig", "content": editorconfig},
            {"path": ".gitattributes", "content": gitattributes},
            {"path": ".gitignore", "content": gitignore},
        ],
    }
)

# 0002
patches.append(
    {
        "title": "GitHub templates and CODEOWNERS for consistent triage and review",
        "files": [
            {"path": ".github/ISSUE_TEMPLATE/bug_report.yml", "content": issue_bug},
            {"path": ".github/ISSUE_TEMPLATE/feature_request.yml", "content": issue_feature},
            {"path": ".github/ISSUE_TEMPLATE/config.yml", "content": issue_config},
            {"path": ".github/PULL_REQUEST_TEMPLATE.md", "content": pr_template},
            {"path": "CODEOWNERS", "content": codeowners},
        ],
    }
)

# 0003
patches.append(
    {
        "title": "Security posture and community: SECURITY.md and Code of Conduct",
        "files": [
            {"path": "SECURITY.md", "content": security_md},
            {"path": "CODE_OF_CONDUCT.md", "content": coc_md},
        ],
    }
)

# 0004
patches.append(
    {
        "title": "Pre-commit hooks and installation script",
        "files": [
            {"path": ".pre-commit-config.yaml", "content": pre_commit_yaml},
            {"path": "scripts/install-hooks.sh", "content": install_hooks_sh, "mode": "100755"},
        ],
    }
)

# 0005
patches.append(
    {
        "title": "Universal CI workflow and language-aware CI script",
        "files": [
            {"path": "scripts/ci.sh", "content": ci_sh, "mode": "100755"},
            {"path": ".github/workflows/ci.yml", "content": ci_workflow},
        ],
    }
)

# 0006
patches.append(
    {
        "title": "Automated dependency updates via Dependabot",
        "files": [
            {"path": ".github/dependabot.yml", "content": dependabot},
        ],
    }
)

# 0007
patches.append(
    {
        "title": "Docs for agents and architecture skeleton",
        "files": [
            {"path": "docs/AI-AGENTS.md", "content": ai_agents_md},
            {"path": "docs/ARCHITECTURE.md", "content": architecture_md},
            {"path": "CONTRIBUTING.md", "content": contributing_md},
        ],
    }
)

# 0008
patches.append(
    {
        "title": "Add MIT LICENSE template",
        "files": [
            {"path": "LICENSE", "content": license_mit},
        ],
    }
)

# Create patches and write to disk
written = []
total = len(patches)

for i, p in enumerate(patches, start=1):
    fname = f"{i:04d}-{p['title'].lower().replace(' ', '-').replace('/', '-')}.patch"
    # sanitize filename
    fname = "".join(ch for ch in fname if ch in string.ascii_letters + string.digits + "-._")
    patch_text = make_patch(i, total, p["title"], p["files"])
    path = os.path.join(base_dir, fname)
    with pathlib.Path(path).open("w", encoding="utf-8") as f:
        f.write(patch_text)
    written.append(path)

# Create a cover letter
cover = textwrap.dedent(f"""\
    Patch series: agent-friendly repo scaffolding
    Date: {date_str}
    Author: {author_name} <{author_email}>

    This series adds repository-agnostic scaffolding to improve developer velocity
    and safety—especially when using autonomous coding agents. It includes:
      1. Core hygiene (.editorconfig, .gitattributes, .gitignore)
      2. Issue/PR templates and CODEOWNERS
      3. SECURITY.md and Code of Conduct
      4. Pre-commit and install script
      5. Universal CI workflow + language-aware CI script
      6. Dependabot updates
      7. AI agent playbook and architecture skeleton
      8. MIT license template

    Apply with:
      git checkout -b chore/agent-ready-patchset
      git am patches/*.patch

    If your repo already contains any of these files, adjust or cherry-pick the
    corresponding patches to avoid conflicts.
""").strip()

cover_path = os.path.join(base_dir, "0000-COVER-LETTER.txt")
with pathlib.Path(cover_path).open("w", encoding="utf-8") as f:
    f.write(cover)

# Create a series file
series_txt = "\n".join(os.path.basename(p) for p in written)
with pathlib.Path(os.path.join(base_dir, "series.txt")).open("w", encoding="utf-8") as f:
    f.write(series_txt)

# Zip archive for easy download
zip_path = "/mnt/data/agent-ready-patchset.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.write(cover_path, arcname="patches/0000-COVER-LETTER.txt")
    zf.write(os.path.join(base_dir, "series.txt"), arcname="patches/series.txt")
    for p in written:
        zf.write(p, arcname=f"patches/{os.path.basename(p)}")

# Return a manifest of created files.
{
    "zip_path": zip_path,
    "patches_dir": base_dir,
    "patches": [os.path.basename(p) for p in written],
    "cover": os.path.basename(cover_path),
}
