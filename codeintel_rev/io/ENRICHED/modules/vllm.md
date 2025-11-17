# cli/vllm.py

## Docstring

```
Standalone helpers for managing a local vLLM HTTP server.

Usage:
    python -m codeintel_rev.cli.vllm serve-http --model /path/to/model
    python -m codeintel_rev.cli.vllm shutdown
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import argparse
- from **(absolute)** import os
- from **(absolute)** import signal
- from **(absolute)** import sys
- from **(absolute)** import tempfile
- from **(absolute)** import time
- from **collections.abc** import Sequence
- from **contextlib** import suppress
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import Final
- from **kgfoundry_common.subprocess_utils** import spawn_background_process
- from **(absolute)** import httpx

## Definitions

- variable: `httpx` (line 27)
- variable: `DEFAULT_HOST` (line 29)
- variable: `DEFAULT_PORT` (line 30)
- variable: `DEFAULT_MODEL` (line 31)
- variable: `DEFAULT_PID_FILE` (line 32)
- variable: `DEFAULT_BASE_URL` (line 35)
- variable: `DEFAULT_HF_CACHE` (line 36)
- variable: `HTTP_OK` (line 41)
- class: `ServerLaunchOptions` (line 45)
- function: `_infer_host_port` (line 57)
- function: `_health_url` (line 69)
- function: `_build_server_argv` (line 75)
- function: `_env_for_cache` (line 103)
- function: `_wait_until_ready` (line 113)
- function: `cmd_serve_http` (line 132)
- function: `_wait_for_exit` (line 178)
- function: `cmd_shutdown` (line 189)
- function: `build_parser` (line 227)
- function: `main` (line 277)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 1
- **cycle_group**: 91

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 5
- recent churn 90: 5

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Standalone helpers for managing a local vLLM HTTP server.
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

- score: 1.92

## Side Effects

- filesystem
- network

## Complexity

- branches: 36
- cyclomatic: 37
- loc: 300

## Doc Coverage

- `ServerLaunchOptions` (class): summary=yes, examples=no — Configuration for launching a vLLM HTTP server.
- `_infer_host_port` (function): summary=no, examples=no
- `_health_url` (function): summary=no, examples=no
- `_build_server_argv` (function): summary=no, examples=no
- `_env_for_cache` (function): summary=no, examples=no
- `_wait_until_ready` (function): summary=no, examples=no
- `cmd_serve_http` (function): summary=yes, params=ok, examples=no — Launch and manage a vLLM HTTP server process.
- `_wait_for_exit` (function): summary=no, examples=no
- `cmd_shutdown` (function): summary=yes, params=ok, examples=no — Shutdown a running vLLM server process.
- `build_parser` (function): summary=yes, params=ok, examples=no — Build the command-line argument parser for vLLM server management.

## Tags

low-coverage
