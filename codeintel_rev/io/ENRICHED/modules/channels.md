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

- variable: `Capabilities` (line 16)
- variable: `ResolvedPaths` (line 17)
- variable: `Settings` (line 18)
- class: `ChannelContext` (line 24)
- class: `Channel` (line 32)
- class: `ChannelError` (line 44)

## Dependency Graph

- **fan_in**: 3
- **fan_out**: 5
- **cycle_group**: 42

## Declared Exports (__all__)

Channel, ChannelContext, ChannelError

## Tags

public-api
