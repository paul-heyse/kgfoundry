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
- from **(absolute)** import shlex
- from **(absolute)** import signal
- from **(absolute)** import subprocess
- from **(absolute)** import sys
- from **(absolute)** import time
- from **collections.abc** import Sequence
- from **contextlib** import suppress
- from **pathlib** import Path
- from **(absolute)** import httpx

## Definitions

- variable: `DEFAULT_HOST` (line 21)
- variable: `DEFAULT_PORT` (line 22)
- variable: `DEFAULT_MODEL` (line 23)
- variable: `DEFAULT_PID_FILE` (line 24)
- variable: `DEFAULT_BASE_URL` (line 25)
- variable: `DEFAULT_HF_CACHE` (line 26)
- function: `_infer_host_port` (line 33)
- function: `_health_url` (line 44)
- function: `_build_server_argv` (line 50)
- function: `_env_for_cache` (line 85)
- function: `_wait_until_ready` (line 95)
- function: `cmd_serve_http` (line 114)
- function: `_wait_for_exit` (line 147)
- function: `cmd_shutdown` (line 158)
- function: `build_parser` (line 187)
- function: `main` (line 219)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 0
- **cycle_group**: 82

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Standalone helpers for managing a local vLLM HTTP server.
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

- score: 1.60

## Side Effects

- filesystem
- network
- subprocess

## Complexity

- branches: 31
- cyclomatic: 32
- loc: 227

## Doc Coverage

- `_infer_host_port` (function): summary=no, examples=no
- `_health_url` (function): summary=no, examples=no
- `_build_server_argv` (function): summary=no, examples=no
- `_env_for_cache` (function): summary=no, examples=no
- `_wait_until_ready` (function): summary=no, examples=no
- `cmd_serve_http` (function): summary=no, examples=no
- `_wait_for_exit` (function): summary=no, examples=no
- `cmd_shutdown` (function): summary=no, examples=no
- `build_parser` (function): summary=no, examples=no
- `main` (function): summary=no, examples=no

## Tags

low-coverage
