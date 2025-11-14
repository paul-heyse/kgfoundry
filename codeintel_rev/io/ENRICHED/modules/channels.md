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
- from **codeintel_rev.retrieval.types** import SearchHit
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

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 5
- **cycle_group**: 43

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

Channel, ChannelContext, ChannelError

## Doc Health

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

## Hotspot

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
