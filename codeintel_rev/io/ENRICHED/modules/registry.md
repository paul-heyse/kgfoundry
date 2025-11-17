# plugins/registry.py

## Docstring

```
Entry-point driven registry for retrieval channels.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Callable, Iterable, Iterator, Sequence
- from **contextlib** import contextmanager
- from **importlib.metadata** import EntryPoint, entry_points
- from **typing** import cast
- from **codeintel_rev.plugins.channels** import Channel, ChannelContext

## Definitions

- class: `ChannelRegistry` (line 18)
- function: `_iter_entry_points` (line 109)
- function: `_entry_point_provider` (line 136)
- function: `_load_factory` (line 146)
- function: `override_channel_entry_points` (line 183)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 30

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

ChannelRegistry, override_channel_entry_points

## Doc Health

- **summary**: Entry-point driven registry for retrieval channels.
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

- score: 1.87

## Side Effects

- none detected

## Complexity

- branches: 11
- cyclomatic: 12
- loc: 200

## Doc Coverage

- `ChannelRegistry` (class): summary=yes, examples=no — Registry that discovers channel plugins via Python entry points.
- `_iter_entry_points` (function): summary=yes, params=ok, examples=no — Return entry points for the channel group across Python versions.
- `_entry_point_provider` (function): summary=no, examples=no
- `_load_factory` (function): summary=yes, params=ok, examples=no — Return a callable factory if the entry point loads successfully.
- `override_channel_entry_points` (function): summary=yes, params=mismatch, examples=no — Temporarily override channel entry points for discovery.

## Tags

low-coverage, public-api
