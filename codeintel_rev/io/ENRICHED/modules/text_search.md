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
- from **typing** import TYPE_CHECKING, cast
- from **codeintel_rev.app.middleware** import get_session_id
- from **codeintel_rev.mcp_server.common.observability** import Observation, observe_duration
- from **codeintel_rev.mcp_server.schemas** import Match, ScopeIn
- from **codeintel_rev.mcp_server.scope_utils** import get_effective_scope, merge_scope_filters
- from **codeintel_rev.observability.otel** import record_span_event
- from **codeintel_rev.observability.semantic_conventions** import Attrs, to_label_str
- from **codeintel_rev.telemetry.context** import current_run_id
- from **codeintel_rev.telemetry.decorators** import span_context
- from **kgfoundry_common.errors** import VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.subprocess_utils** import SubprocessError, SubprocessTimeoutError, run_subprocess
- from **codeintel_rev.app.config_context** import ApplicationContext

## Definitions

- variable: `SEARCH_TIMEOUT_SECONDS` (line 37)
- variable: `MAX_PREVIEW_CHARS` (line 38)
- variable: `GREP_SPLIT_PARTS` (line 39)
- variable: `COMMAND_NOT_FOUND_RETURN_CODE` (line 40)
- variable: `COMPONENT_NAME` (line 41)
- variable: `LOGGER` (line 42)
- class: `TextSearchOptions` (line 46)
- function: `_bool_override` (line 121)
- function: `_sequence_override` (line 148)
- function: `_int_override` (line 181)
- function: `search_text` (line 208)
- function: `_search_text_sync` (line 291)
- function: `_fallback_grep` (line 435)
- class: `RipgrepCommandParams` (line 554)
- function: `_build_ripgrep_command` (line 566)
- function: `_parse_ripgrep_output` (line 606)
- function: `_preview_text` (line 673)
- function: `_clean_attrs` (line 698)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 10
- **cycle_group**: 137

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 27
- recent churn 90: 27

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

- score: 2.76

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 64
- cyclomatic: 65
- loc: 718

## Doc Coverage

- `TextSearchOptions` (class): summary=yes, examples=no — Parameters controlling ripgrep execution.
- `_bool_override` (function): summary=yes, params=ok, examples=no — Return a boolean override for the given key.
- `_sequence_override` (function): summary=yes, params=ok, examples=no — Return a sequence override if the value is a valid sequence of strings.
- `_int_override` (function): summary=yes, params=ok, examples=no — Return an integer override for the given key.
- `search_text` (function): summary=yes, params=mismatch, examples=no — Fast text search using ripgrep (async wrapper).
- `_search_text_sync` (function): summary=no, examples=no
- `_fallback_grep` (function): summary=yes, params=ok, examples=no — Fallback to basic grep if ripgrep unavailable.
- `RipgrepCommandParams` (class): summary=yes, examples=no — Parameter bundle for constructing ripgrep commands.
- `_build_ripgrep_command` (function): summary=yes, params=ok, examples=no — Assemble the ripgrep command arguments.
- `_parse_ripgrep_output` (function): summary=yes, params=ok, examples=no — Parse ripgrep JSON output into structured matches.

## Tags

low-coverage, public-api
