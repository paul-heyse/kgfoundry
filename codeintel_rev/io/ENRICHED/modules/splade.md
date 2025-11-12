# cli/splade.py

## Docstring

```
Command-line interface for SPLADE artifact management.
```

## Imports

- from **__future__** import annotations
- from **pathlib** import Path
- from **typing** import Annotated
- from **(absolute)** import msgspec
- from **(absolute)** import typer
- from **tools** import CliContext, EnvelopeBuilder, cli_operation, sha256_file
- from **codeintel_rev.config.settings** import load_settings
- from **codeintel_rev.io.splade_manager** import SpladeArtifactsManager, SpladeBenchmarkOptions, SpladeBuildOptions, SpladeEncodeOptions, SpladeEncoderService, SpladeExportOptions, SpladeIndexManager

## Definitions

- function: `_create_artifacts_manager` (line 55)
- function: `_create_encoder_service` (line 66)
- function: `_create_index_manager` (line 77)
- function: `_add_metadata_artifact` (line 88)
- function: `export_onnx` (line 107)
- function: `_run` (line 117)
- function: `encode` (line 196)
- function: `_run` (line 207)
- function: `build_index` (line 308)
- function: `_run` (line 319)
- function: `bench` (line 369)
- function: `_run` (line 437)
- function: `main` (line 480)

## Tags

cli, overlay-needed
