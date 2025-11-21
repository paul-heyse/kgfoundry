# SPDX-License-Identifier: MIT
"""Utility to copy artifacts from an exports manifest into a destination folder."""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Iterable
from pathlib import Path

from codeintel_rev.services.enrich.artifact_manifest import ArtifactManifest


def _copy_file(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


try:  # pragma: no cover - optional dependency
    import duckdb  # type: ignore[import]
except ImportError:  # pragma: no cover - optional dependency
    duckdb = None


def _emit_sidecar(source: Path, dest_dir: Path) -> Path | None:
    if source.suffix != ".parquet":
        return None
    jsonl_path = dest_dir / f"{source.stem}.jsonl"
    if duckdb is None:
        return None
    con = duckdb.connect()
    try:
        con.execute(
            "COPY (SELECT * FROM read_parquet(?)) TO ? (FORMAT JSON, ARRAY false)",
            [str(source), str(jsonl_path)],
        )
    finally:
        con.close()
    return jsonl_path


def _copy_section(items: Iterable[tuple[str, Path]], dest_dir: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for name, src in items:
        if not src.exists():
            continue
        target = dest_dir / name
        _copy_file(src, target)
        records.append({"source": str(src), "dest": str(target)})
        sidecar = _emit_sidecar(src, dest_dir)
        if sidecar is not None:
            records.append({"source": str(src), "dest": str(sidecar)})
    return records


def copy_from_manifest(
    manifest_path: Path, dest_root: Path, *, index_path: Path | None = None
) -> list[dict[str, str]]:
    """Copy artifacts referenced in the manifest into dest_root.

    Copies primary artifacts (modules, repo_map, tag_index, manifest itself)
    and sections (analytics, graphs, goid, ast) while emitting JSONL sidecars
    for any Parquet files.

    Returns
    -------
    list[dict[str, str]]
        Records of copied artifacts: source and destination pairs.
    """
    manifest = ArtifactManifest.load(manifest_path, strict=True)
    dest_root.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, str]] = []
    for source, dest in (
        (manifest_path, dest_root / manifest_path.name),
        (manifest.modules_jsonl, dest_root / "modules.jsonl"),
        (manifest.repo_map, dest_root / "repo_map.json"),
        (manifest.tag_index, dest_root / "tag_index.json"),
    ):
        _copy_file(source, dest)
        records.append({"source": str(source), "dest": str(dest)})

    records.extend(_copy_section(manifest.analytics.items(), dest_root / "analytics"))
    records.extend(_copy_section(manifest.graphs.items(), dest_root / "graphs"))
    records.extend(_copy_section(manifest.goid.items(), dest_root / "goid"))
    records.extend(_copy_section(manifest.ast.items(), dest_root / "ast"))

    if index_path is not None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records


def main() -> None:
    """CLI entrypoint for copying manifest artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to exports_manifest.json",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        required=True,
        help="Destination root directory for copied artifacts",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=None,
        help="Optional path to write promoted artifacts index JSON.",
    )
    args = parser.parse_args()
    copy_from_manifest(args.manifest, args.dest, index_path=args.index)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
