# plugins/registry.py

## Docstring

```
Entry-point driven registry for retrieval channels.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Callable, Iterable, Sequence
- from **importlib.metadata** import EntryPoint, entry_points
- from **typing** import cast
- from **codeintel_rev.plugins.channels** import Channel, ChannelContext
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 12)
- class: `ChannelRegistry` (line 19)
- function: `_iter_entry_points` (line 113)
- function: `_load_factory` (line 140)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 69

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

ChannelRegistry

## Doc Health

- **summary**: Entry-point driven registry for retrieval channels.
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

- score: 1.79

## Side Effects

- none detected

## Complexity

- branches: 8
- cyclomatic: 9
- loc: 178

## Doc Coverage

- `ChannelRegistry` (class): summary=yes, examples=no — Registry that discovers channel plugins via Python entry points.
- `_iter_entry_points` (function): summary=yes, params=ok, examples=no — Return entry points for the channel group across Python versions.
- `_load_factory` (function): summary=yes, params=ok, examples=no — Return a callable factory if the entry point loads successfully.

## Tags

low-coverage, public-api
