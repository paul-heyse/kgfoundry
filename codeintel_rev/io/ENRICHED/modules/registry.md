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

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 42

## Declared Exports (__all__)

ChannelRegistry

## Tags

public-api
