# mcp_server/common/observability.py

## Docstring

```
Unified observability helpers for CodeIntel MCP adapters.

The adapters previously duplicated more than sixty lines of metrics boilerplate.
This module centralises the logic, delegates to :mod:`kgfoundry_common`
observability primitives, and keeps behaviour backward compatible with existing
Prometheus dashboards.

Examples
--------
Basic usage in an adapter:

>>> from codeintel_rev.mcp_server.common.observability import observe_duration
>>> with observe_duration("search", "text_search") as observation:
...     result = perform_search()
...     observation.mark_success()

Graceful degradation when metrics are unavailable:

>>> with observe_duration("semantic_search", "codeintel_mcp") as observation:
...     try:
...         perform_semantic_search()
...         observation.mark_success()
...     except RuntimeError:
...         observation.mark_error()
...         raise
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterator
- from **contextlib** import contextmanager
- from **typing** import Protocol
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.observability** import MetricsProvider
- from **kgfoundry_common.observability** import observe_duration

## Definitions

- function: `_supports_histogram_labels` (line 46)
- class: `_NoopObservation` (line 69)
- function: `mark_error` (line 72)
- function: `mark_success` (line 75)
- class: `Observation` (line 79)
- function: `mark_error` (line 82)
- function: `mark_success` (line 85)
- function: `observe_duration` (line 90)

## Tags

overlay-needed, public-api
