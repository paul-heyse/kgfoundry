# runtime/request_context.py

## Docstring

```
Shared request-scoped context variables for runtime components.

These context variables are defined in the runtime package so that both
middleware layers and lower-level runtime primitives (like :mod:`runtime.cells`)
can exchange session metadata without introducing circular imports between the
``codeintel_rev.app`` and ``codeintel_rev.runtime`` packages.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import contextvars
- from **typing** import Final

## Tags

overlay-needed, public-api
