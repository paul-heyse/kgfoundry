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
- from **kgfoundry_common.errors** import VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.subprocess_utils** import SubprocessError, SubprocessTimeoutError, run_subprocess
- from **codeintel_rev.app.config_context** import ApplicationContext

## Definitions

- class: `TextSearchOptions` (line 42)
- function: `from_overrides` (line 65)
- function: `_bool_override` (line 117)
- function: `_sequence_override` (line 144)
- function: `_int_override` (line 177)
- function: `search_text` (line 204)
- function: `_search_text_sync` (line 256)
- function: `_fallback_grep` (line 374)
- class: `RipgrepCommandParams` (line 476)
- function: `_build_ripgrep_command` (line 488)
- function: `_parse_ripgrep_output` (line 528)

## Tags

overlay-needed, public-api
