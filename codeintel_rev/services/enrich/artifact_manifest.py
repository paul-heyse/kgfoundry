# SPDX-License-Identifier: MIT
"""Typed helper for reading enrichment export manifests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """Resolved artifact paths emitted by the enrich exports stage."""

    modules_jsonl: Path
    repo_map: Path
    tag_index: Path
    markdown_dir: Path
    module_count: int | None
    analytics: Mapping[str, Path]
    graphs: Mapping[str, Path]
    goid: Mapping[str, Path]
    ast: Mapping[str, Path]

    @classmethod
    def load(cls, manifest_path: Path, *, strict: bool = False) -> ArtifactManifest:
        """Read and validate a manifest.

        Parameters
        ----------
        manifest_path : Path
            Location of ``exports_manifest.json``.
        strict : bool, optional
            If True, require the manifest to exist; otherwise returns a
            ValueError on missing path. Defaults to False.

        Returns
        -------
        ArtifactManifest
            Parsed manifest with paths resolved to absolute filesystem paths.

        """
        payload = _read_manifest_payload(manifest_path, strict=strict)
        modules_jsonl = _required_path(payload, "modules_jsonl")
        repo_map = _required_path(payload, "repo_map")
        tag_index = _required_path(payload, "tag_index")
        markdown_dir = _required_path(payload, "markdown_dir")
        module_count_raw = payload.get("module_count")
        module_count = module_count_raw if isinstance(module_count_raw, int) else None
        return cls(
            modules_jsonl=modules_jsonl,
            repo_map=repo_map,
            tag_index=tag_index,
            markdown_dir=markdown_dir,
            module_count=module_count,
            analytics=_optional_section(payload, "analytics"),
            graphs=_optional_section(payload, "graphs"),
            goid=_optional_section(payload, "goid"),
            ast=_optional_section(payload, "ast"),
        )


def resolve_from_manifest(
    manifest_path: Path | None,
    *,
    fallback_modules: Path,
    fallback_repo_map: Path | None = None,
    fallback_tag_index: Path | None = None,
) -> tuple[Path, Path | None, Path | None]:
    """Resolve primary artifacts (modules/repo map/tag index) from a manifest.

    Returns
    -------
    tuple[Path, Path | None, Path | None]
        Paths for modules_jsonl, repo_map, and tag_index respectively.
    """
    if manifest_path is None:
        return fallback_modules, fallback_repo_map, fallback_tag_index
    try:
        manifest = ArtifactManifest.load(manifest_path)
    except (FileNotFoundError, ValueError):
        return fallback_modules, fallback_repo_map, fallback_tag_index
    return manifest.modules_jsonl, manifest.repo_map, manifest.tag_index


__all__ = ["ArtifactManifest", "resolve_from_manifest"]


def _read_manifest_payload(manifest_path: Path, *, strict: bool) -> Mapping[str, object]:
    if not manifest_path.exists():
        message = f"Manifest not found: {manifest_path}"
        if strict:
            raise FileNotFoundError(message)
        raise ValueError(message)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        message = f"Invalid JSON in manifest at {manifest_path}: {exc}"
        raise ValueError(message) from exc
    if not isinstance(payload, dict):
        message = f"Manifest must decode to a mapping, got {type(payload)!r}"
        raise TypeError(message)
    return payload


def _required_path(payload: Mapping[str, object], key: str) -> Path:
    value = payload.get(key)
    if not isinstance(value, str):
        message = f"Manifest missing required path for '{key}'"
        raise TypeError(message)
    return Path(value).resolve()


def _optional_section(payload: Mapping[str, object], name: str) -> dict[str, Path]:
    section = payload.get(name, {}) or {}
    if not isinstance(section, dict):
        return {}
    result: dict[str, Path] = {}
    for key, value in section.items():
        if isinstance(key, str) and isinstance(value, str):
            result[key] = Path(value).resolve()
    return result
