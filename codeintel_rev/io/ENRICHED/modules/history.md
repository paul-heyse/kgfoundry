# mcp_server/adapters/history.py

## Docstring

```
Git history adapter for blame and log operations.

Provides git blame and commit history using GitPython via GitClient.
This replaces subprocess-based Git operations with typed Python APIs for
better performance (50-80ms latency reduction) and reliability.
```

## Imports

- from **__future__** import annotations
- from **typing** import TYPE_CHECKING
- from **(absolute)** import git.exc
- from **codeintel_rev.errors** import GitOperationError, PathNotFoundError
- from **codeintel_rev.io.path_utils** import resolve_within_repo
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.app.config_context** import ApplicationContext

## Definitions

- variable: `LOGGER` (line 21)
- function: `blame_range` (line 24)
- function: `file_history` (line 119)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 4
- **cycle_group**: 148

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 11
- recent churn 90: 11

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

blame_range, file_history

## Doc Health

- **summary**: Git history adapter for blame and log operations.
- has summary: yes
- param parity: yes
- examples present: yes

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 1.77

## Side Effects

- none detected

## Complexity

- branches: 5
- cyclomatic: 6
- loc: 204

## Doc Coverage

- `blame_range` (function): summary=yes, params=ok, examples=yes — Get git blame for line range using GitPython (async).
- `file_history` (function): summary=yes, params=ok, examples=yes — Get commit history for file using GitPython (async).

## Tags

low-coverage, public-api
