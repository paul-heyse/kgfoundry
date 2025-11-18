# SPDX-License-Identifier: MIT
"""Overlay configuration and generation helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import typer

from codeintel_rev.enrich.scip_reader import SCIPIndex
from codeintel_rev.enrich.stubs_overlay import (
    OverlayInputs,
    OverlayPolicy,
    generate_overlay_for_file,
)
from codeintel_rev.services.enrich.context import (
    EXPORT_HUB_THRESHOLD,
    OverlayCLIOptions,
    OverlayContext,
    PipelineContext,
    PipelineOptions,
)
from codeintel_rev.services.enrich.models import ModuleRecord as SimpleModuleRecord
from codeintel_rev.typedness import collect_type_signals

try:  # pragma: no cover - optional dependency
    import yaml as yaml_module
except ImportError:  # pragma: no cover
    yaml_module = None


def _yaml_errors() -> tuple[type[BaseException], ...]:
    """Return exception tuple for YAML parsing failures.

    Returns
    -------
    tuple[type[BaseException], ...]
        Exception classes emitted by the available YAML parser.
    """
    if yaml_module is None:
        return (ValueError,)
    return (yaml_module.YAMLError,)


YAML_ERRORS = _yaml_errors()


def load_overlay_options(config_path: Path | None, overrides: list[str]) -> OverlayCLIOptions:
    """Load overlay options from config + CLI overrides.

    Parameters
    ----------
    config_path :
        Optional path to a JSON/YAML config file.
    overrides :
        CLI ``KEY=VALUE`` overrides.

    Returns
    -------
    OverlayCLIOptions
        Fully resolved overlay options.

    Raises
    ------
    typer.BadParameter
        Raised when overrides cannot be parsed.
    """
    options = OverlayCLIOptions()
    if config_path is not None:
        config_data = read_overlay_config(config_path)
        for key, value in config_data.items():
            set_overlay_option(options, key, value)
    for override in overrides:
        if "=" not in override:
            message = "Override values must use the KEY=VALUE format."
            raise typer.BadParameter(message)
        key, value = override.split("=", 1)
        set_overlay_option(options, key, value)
    return options


def read_overlay_config(path: Path) -> Mapping[str, Any]:
    """Parse overlay config supporting YAML or JSON.

    Returns
    -------
    Mapping[str, Any]
        Parsed option mapping from the config file.

    Raises
    ------
    typer.BadParameter
        Raised when parsing fails or payload is invalid.
    """
    payload = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        if yaml_module is None:
            message = "PyYAML is required to parse YAML overlay configs."
            raise typer.BadParameter(message)
        data = yaml_module.safe_load(payload)
    else:
        data = json.loads(payload)
    if not isinstance(data, Mapping):
        message = "Overlay config must be a mapping of option names to values."
        raise typer.BadParameter(message)
    return data


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    message = f"Cannot interpret '{value}' as a boolean."
    raise typer.BadParameter(message)


def _resolve_path(path_value: Path | None) -> Path | None:
    if path_value is None:
        return None
    return path_value.expanduser().resolve()


def _parse_int_option(raw_value: object, *, option: str) -> int:
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return int(raw_value, 10)
        except ValueError as exc:  # pragma: no cover - defensive parsing
            message = f"Overlay option '{option}' must be an integer."
            raise typer.BadParameter(message) from exc
    message = f"Overlay option '{option}' must be an integer."
    raise typer.BadParameter(message)


def _parse_path_option(raw_value: object, *, option: str) -> Path:
    if isinstance(raw_value, Path):
        return raw_value
    if isinstance(raw_value, str):
        return Path(raw_value)
    message = f"Overlay option '{option}' must be a filesystem path."
    raise typer.BadParameter(message)


def set_overlay_option(options: OverlayCLIOptions, key: str, raw_value: object) -> None:
    """Update overlay CLI options with validated values.

    Raises
    ------
    typer.BadParameter
        Raised when the override cannot be parsed.
    """
    attr = key.strip().lower()
    if attr in {"stubs_root", "overlays_root"}:
        candidate = _parse_path_option(raw_value, option=attr)
        resolved = _resolve_path(candidate)
        if resolved is None:
            message = f"Overlay option '{attr}' must be a filesystem path."
            raise typer.BadParameter(message)
        setattr(options, attr, resolved)
    elif attr in {"min_errors", "max_overlays"}:
        setattr(options, attr, _parse_int_option(raw_value, option=attr))
    elif attr in {
        "include_public_defs",
        "inject_getattr_any",
        "dry_run",
        "activate",
        "deactivate_all_first",
        "type_error_overlays",
    }:
        setattr(options, attr, _parse_bool(raw_value))
    else:
        message = f"Unknown overlay option '{key}'."
        raise typer.BadParameter(message)


def load_overlay_tagged_paths(out_dir: Path, overlay_tag: str) -> frozenset[str]:
    """Return cached overlay-needed paths from ``tags_index.yaml``.

    Returns
    -------
    frozenset[str]
        Paths previously marked with ``overlay_tag``.
    """
    if not overlay_tag:
        return frozenset()
    tags_file = out_dir / "tags" / "tags_index.yaml"
    if not tags_file.exists() or yaml_module is None:
        return frozenset()
    try:
        payload = yaml_module.safe_load(tags_file.read_text(encoding="utf-8"))
    except YAML_ERRORS:  # pragma: no cover - defensive parsing
        return frozenset()
    if not isinstance(payload, Mapping):
        return frozenset()
    entries = payload.get(overlay_tag, [])
    if not isinstance(entries, list):
        return frozenset()
    return frozenset(str(item) for item in entries if isinstance(item, str))


def build_overlay_context(
    pipeline: PipelineOptions,
    options: OverlayCLIOptions,
) -> OverlayContext:
    """Construct overlay context using pipeline inputs.

    Returns
    -------
    OverlayContext
        Aggregated context objects for overlay generation.

    Raises
    ------
    typer.BadParameter
        Raised when the ``--scip`` path is missing.
    """
    if pipeline.scip is None:
        message = "The --scip option is required for overlay generation."
        raise typer.BadParameter(message)
    root_resolved = pipeline.root.resolve()
    package_name = root_resolved.name
    overlays_target_root = (options.overlays_root / package_name).resolve()
    stubs_target_root = (options.stubs_root / package_name).resolve()
    scip_index = SCIPIndex.load(pipeline.scip)
    type_signal_lookup = collect_type_signals(
        pyrefly_report=str(pipeline.pyrefly_json) if pipeline.pyrefly_json else None,
        pyright_json=str(root_resolved),
    )
    type_counts: dict[str, int] = {
        path: signals.total
        for path, signals in type_signal_lookup.items()
        if not Path(path).is_absolute()
    }
    policy = OverlayPolicy(
        overlays_root=overlays_target_root,
        include_public_defs=options.include_public_defs,
        inject_module_getattr_any=options.inject_getattr_any,
        when_type_errors=options.type_error_overlays,
        min_type_errors=options.min_errors,
        max_overlays=options.max_overlays,
        export_hub_threshold=EXPORT_HUB_THRESHOLD,
        overlay_tag="overlay-needed",
    )
    overlay_tagged_paths = load_overlay_tagged_paths(pipeline.out, policy.overlay_tag)
    return OverlayContext(
        root=root_resolved,
        package_name=package_name,
        overlays_root=overlays_target_root,
        stubs_root=stubs_target_root,
        scip_index=scip_index,
        type_counts=type_counts,
        policy=policy,
        inputs=OverlayInputs(
            scip=scip_index,
            type_error_counts=type_counts,
            overlay_tagged_paths=overlay_tagged_paths,
        ),
    )


def ensure_package_overlays(  # noqa: PLR0913
    *,
    rel_path: Path,
    generated: list[str],
    generated_set: set[str],
    manifest_entries: list[str],
    package_name: str,
    package_overlays: set[str],
    root: Path,
    scip_index: SCIPIndex,
    policy: OverlayPolicy,
    type_error_counts: Mapping[str, int],
) -> bool:
    """Ensure package ``__init__`` overlays exist for ancestors of ``rel_path``.

    Returns
    -------
    bool
        ``True`` when the overlay budget is exhausted.
    """
    current = rel_path.parent
    root_marker = Path()
    limit = policy.max_overlays
    while current != root_marker:
        init_rel = current / "__init__.py"
        rel_key = str(init_rel).replace("\\", "/")
        if rel_key in package_overlays:
            current = current.parent
            continue
        package_overlays.add(rel_key)
        init_abs = root / init_rel
        if not init_abs.exists():
            current = current.parent
            continue
        result = generate_overlay_for_file(
            py_file=init_abs,
            package_root=root,
            policy=policy,
            inputs=OverlayInputs(
                scip=scip_index,
                type_error_counts=type_error_counts,
                force=True,
            ),
        )
        if result.created:
            if rel_key not in generated_set:
                generated.append(rel_key)
                generated_set.add(rel_key)
                manifest_entries.append(f"{package_name}/{rel_key}")
            if len(generated) >= limit:
                return True
        current = current.parent
    return False


def _load_overlay_file(path: Path) -> dict[str, dict[str, Any]]:
    """Load overlay metadata from either JSON or JSONL.

    Returns
    -------
    dict[str, dict[str, Any]]
        Mapping of module names to metadata dictionaries.
    """
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
        if isinstance(data, Mapping):
            return {str(key): dict(value) for key, value in data.items()}
    except json.JSONDecodeError:
        pass
    merged: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        module = str(row.get("module") or "")
        if not module:
            continue
        payload = dict(row)
        payload.pop("module", None)
        merged.setdefault(module, {}).update(payload)
    return merged


def apply_overlays(
    ctx: PipelineContext,
    records: list[SimpleModuleRecord],
    overlay_files: Iterable[Path],
) -> list[SimpleModuleRecord]:
    """Merge overlay metadata into scanned records.

    Returns
    -------
    list[SimpleModuleRecord]
        Updated module records containing overlay metadata.
    """
    merged_overlays: dict[str, dict[str, Any]] = {}
    files = list(overlay_files)
    for overlay_path in files:
        try:
            data = _load_overlay_file(overlay_path)
        except OSError as exc:  # pragma: no cover - file read errors
            ctx.logger.warning("Skipping overlay %s: %s", overlay_path, exc)
            continue
        for module, payload in data.items():
            merged_overlays.setdefault(module, {}).update(payload)
    enriched: list[SimpleModuleRecord] = []
    for record in records:
        meta = dict(record.meta)
        if record.module in merged_overlays:
            meta.update(merged_overlays[record.module])
        enriched.append(
            SimpleModuleRecord(
                path=record.path,
                module=record.module,
                language=record.language,
                loc=record.loc,
                tags=record.tags,
                meta=meta,
            )
        )
    ctx.logger.info("Applied overlays from %d file(s)", len(files))
    return enriched


__all__ = [
    "apply_overlays",
    "build_overlay_context",
    "ensure_package_overlays",
    "load_overlay_options",
    "load_overlay_tagged_paths",
    "read_overlay_config",
    "set_overlay_option",
]
