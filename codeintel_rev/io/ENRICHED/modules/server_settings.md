# app/server_settings.py

## Docstring

```
Server-facing configuration for FastAPI + Hypercorn deployment.

This module centralizes HTTP listener parameters, CORS defaults, and proxy
trust knobs so deployments can be tuned via environment variables (or a
``.env`` file) without touching application code. The settings are consumed
by :mod:`codeintel_rev.app.main` when constructing the FastAPI application
and when exporting the Hypercorn-facing ASGI callable.
```

## Imports

- from **__future__** import annotations
- from **functools** import lru_cache
- from **typing** import ClassVar, Literal
- from **pydantic** import Field
- from **pydantic_settings** import BaseSettings, SettingsConfigDict

## Definitions

- class: `ServerSettings` (line 19)
- function: `get_server_settings` (line 106)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 74

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

ServerSettings, get_server_settings

## Doc Health

- **summary**: Server-facing configuration for FastAPI + Hypercorn deployment.
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

## Config References

- app/hypercorn.toml

## Hotspot

- score: 1.19

## Side Effects

- network

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 121

## Doc Coverage

- `ServerSettings` (class): summary=yes, examples=no — Container for server/network level toggles.
- `get_server_settings` (function): summary=yes, params=ok, examples=no — Return (and cache) :class:`ServerSettings` for reuse.

## Tags

low-coverage, public-api, pydantic
