# mcp_server/adapters/text_search.py

## Docstring

```
Text search adapter using ripgrep.

Fast text search with regex support.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **(absolute)** import json
- from **collections.abc** import Mapping, Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Protocol, cast
- from **codeintel_rev.app.middleware** import get_session_id
- from **codeintel_rev.mcp_server.schemas** import Match, ScopeIn
- from **codeintel_rev.mcp_server.scope_utils** import get_effective_scope, merge_scope_filters
- from **kgfoundry_common.errors** import VectorSearchError
- from **kgfoundry_common.subprocess_utils** import SubprocessError, SubprocessTimeoutError, run_subprocess
- from **codeintel_rev.app.config_context** import ApplicationContext

## Definitions

- variable: `SEARCH_TIMEOUT_SECONDS` (line 31)
- variable: `SEARCH_MAX_RESULTS` (line 32)
- variable: `MAX_PREVIEW_CHARS` (line 33)
- variable: `GREP_SPLIT_PARTS` (line 34)
- variable: `COMMAND_NOT_FOUND_RETURN_CODE` (line 35)
- class: `SubprocessRunner` (line 38)
- class: `TextSearchOptions` (line 52)
- class: `_ResolvedFilters` (line 128)
- function: `_bool_override` (line 136)
- function: `_sequence_override` (line 163)
- function: `_int_override` (line 196)
- function: `search_text` (line 223)
- function: `_resolve_glob_filters` (line 289)
- function: `_search_text_sync` (line 318)
- function: `_fallback_grep` (line 386)
- class: `RipgrepCommandParams` (line 481)
- function: `_build_ripgrep_command` (line 493)
- function: `_parse_ripgrep_output` (line 533)
- function: `_preview_text` (line 600)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 5
- **cycle_group**: 125

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 34
- recent churn 90: 34

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

search_text

## Doc Health

- **summary**: Text search adapter using ripgrep.
- has summary: yes
- param parity: no
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 2.44

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 49
- cyclomatic: 50
- loc: 626

## Doc Coverage

- `SubprocessRunner` (class): summary=yes, examples=no — Protocol describing the subprocess runner used by text search.
- `TextSearchOptions` (class): summary=yes, examples=no — Parameters controlling ripgrep execution.
- `_ResolvedFilters` (class): summary=yes, examples=no — Normalized scope and override filters for ripgrep.
- `_bool_override` (function): summary=yes, params=ok, examples=no — Return a boolean override for the given key.
- `_sequence_override` (function): summary=yes, params=ok, examples=no — Return a sequence override if the value is a valid sequence of strings.
- `_int_override` (function): summary=yes, params=ok, examples=no — Return an integer override for the given key.
- `search_text` (function): summary=yes, params=mismatch, examples=no — Fast text search using ripgrep (async wrapper).
- `_resolve_glob_filters` (function): summary=no, examples=no
- `_search_text_sync` (function): summary=no, examples=no
- `_fallback_grep` (function): summary=yes, params=ok, examples=no — Fallback to basic grep if ripgrep unavailable.

## Tags

low-coverage, public-api
