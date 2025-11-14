# app/serve_hypercorn.py

## Docstring

```
Hypercorn runner with graceful signal handling.

Exposes helpers so deployments (systemd, tests, dev scripts) can start the
ASGI stack without relying on shell-specific wrappers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **(absolute)** import os
- from **(absolute)** import signal
- from **collections.abc** import Awaitable, Callable
- from **contextlib** import suppress
- from **pathlib** import Path
- from **typing** import cast
- from **hypercorn.asyncio** import serve
- from **hypercorn.config** import Config
- from **hypercorn.typing** import ASGIFramework
- from **codeintel_rev.app** import main

## Definitions

- variable: `ShutdownTrigger` (line 25)
- function: `_load_config` (line 28)
- function: `_build_shutdown_trigger` (line 50)
- function: `serve_app` (line 67)
- function: `main` (line 88)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 2
- **cycle_group**: 59

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Hypercorn runner with graceful signal handling.
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

## Config References

- app/hypercorn.toml

## Hotspot

- score: 1.68

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 8
- cyclomatic: 9
- loc: 96

## Doc Coverage

- `_load_config` (function): summary=yes, params=ok, examples=no — Return a Hypercorn :class:`Config` from the given TOML path.
- `_build_shutdown_trigger` (function): summary=yes, params=ok, examples=no — Create an asyncio event and shutdown trigger callable.
- `serve_app` (function): summary=yes, params=mismatch, examples=no — Run Hypercorn with signal-aware shutdown semantics.
- `main` (function): summary=yes, params=ok, examples=no — Execute Hypercorn with the repo default configuration.

## Tags

low-coverage
