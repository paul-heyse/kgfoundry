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

- class: `ChannelRegistry` (line 19)
- function: `__init__` (line 22)
- function: `discover` (line 26)
- function: `from_channels` (line 72)
- function: `channels` (line 102)
- function: `_iter_entry_points` (line 113)
- function: `_load_factory` (line 140)

## Tags

overlay-needed, public-api
