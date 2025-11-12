# plugins/channels.py

## Docstring

```
Channel plugin contracts for hybrid retrieval.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass
- from **typing** import TYPE_CHECKING, Any, Protocol
- from **codeintel_rev.retrieval.types** import ChannelHit
- from **codeintel_rev.app.capabilities** import Capabilities
- from **codeintel_rev.app.config_context** import ResolvedPaths
- from **codeintel_rev.config.settings** import Settings

## Definitions

- class: `ChannelContext` (line 24)
- class: `Channel` (line 32)
- function: `search` (line 39)
- class: `ChannelError` (line 44)
- function: `__init__` (line 47)

## Tags

overlay-needed, public-api
