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
- **cycle_group**: 61

## Declared Exports (__all__)

Channel, ChannelContext, ChannelError

## Doc Metrics

- **summary**: Channel plugin contracts for hybrid retrieval.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot Score

- score: 1.75

## Side Effects

- none detected

## Complexity

- branches: 1
- cyclomatic: 2
- loc: 50

## Doc Coverage

- `ChannelContext` (class): summary=yes, examples=no — Context passed to channel factories when they are constructed.
- `Channel` (class): summary=yes, examples=no — Retrieval channel plugin interface.
- `ChannelError` (class): summary=yes, examples=no — Raised by channels when they cannot satisfy a search request.

## Tags

low-coverage, public-api
