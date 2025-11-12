# bin/eval_coverage.py

## Docstring

```
Command-line entry point for SCIP function coverage evaluation.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import argparse
- from **(absolute)** import json
- from **(absolute)** import sys
- from **pathlib** import Path
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.config.settings** import load_settings
- from **codeintel_rev.evaluation.scip_coverage** import SCIPCoverageEvaluator
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 16)
- function: `build_parser` (line 19)
- function: `main` (line 46)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 3
- **cycle_group**: 54
