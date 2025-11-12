# io/git_client.py

## Docstring

```
Typed Git operations wrapper using GitPython.

This module provides typed Python APIs for Git operations (blame, history) using
GitPython instead of subprocess calls. Benefits include:
- 50-80ms latency reduction (no subprocess overhead)
- Structured data returns (no text parsing)
- Automatic Unicode/locale handling
- Specific typed exceptions
- Unit testable (mock git.Repo)

Example Usage
-------------
Initialize client with repository path:

>>> from pathlib import Path
>>> git_client = GitClient(repo_path=Path("/path/to/repo"))

Get blame for line range:

>>> entries = git_client.blame_range("src/main.py", start_line=10, end_line=20)
>>> for entry in entries:
...     print(f"Line {entry['line']}: {entry['author']} - {entry['message']}")

Get commit history:

>>> commits = git_client.file_history("README.md", limit=10)
>>> for commit in commits:
...     print(f"{commit['sha']}: {commit['message']}")

Async wrapper for non-blocking operations:

>>> async_client = AsyncGitClient(git_client)
>>> entries = await async_client.blame_range("src/main.py", 10, 20)

See Also
--------
codeintel_rev.mcp_server.adapters.history : Adapters using GitClient
GitPython documentation : https://gitpython.readthedocs.io/
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **collections.abc** import Iterable, Sequence
- from **dataclasses** import dataclass, field, replace
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, cast
- from **(absolute)** import git
- from **(absolute)** import git.exc
- from **codeintel_rev.observability.timeline** import current_timeline
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.mcp_server.schemas** import GitBlameEntry

## Definitions

- variable: `LOGGER` (line 58)
- function: `_string_attr` (line 61)
- function: `_commit_iso_date` (line 66)
- function: `_author_field` (line 76)
- function: `_short_sha` (line 84)
- function: `_normalize_line_numbers` (line 89)
- function: `_coerce_blame_tuple` (line 102)
- class: `GitClient` (line 117)
- class: `AsyncGitClient` (line 486)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 28

## Declared Exports (__all__)

AsyncGitClient, GitClient

## Doc Metrics

- **summary**: Typed Git operations wrapper using GitPython.
- has summary: yes
- param parity: yes
- examples present: yes

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 29
- cyclomatic: 30
- loc: 612

## Doc Coverage

- `_string_attr` (function): summary=no, examples=no
- `_commit_iso_date` (function): summary=no, examples=no
- `_author_field` (function): summary=no, examples=no
- `_short_sha` (function): summary=no, examples=no
- `_normalize_line_numbers` (function): summary=no, examples=no
- `_coerce_blame_tuple` (function): summary=no, examples=no
- `GitClient` (class): summary=yes, examples=yes — Typed wrapper around GitPython for blame and history operations.
- `AsyncGitClient` (class): summary=yes, examples=yes — Async wrapper around GitClient using asyncio.to_thread.

## Tags

public-api
