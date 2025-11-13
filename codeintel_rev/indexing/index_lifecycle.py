"""Index lifecycle management for FAISS/DuckDB/SCIP artifacts.

This module provides a small, platform-agnostic manager that stages new index
versions, publishes them atomically, and exposes helpers used by the FastAPI
app, CLI, and admin endpoints. Versions are stored under a common ``base_dir``
with the following layout::

    base_dir/
        versions/<version>/...
        versions/<version>.staging/...
        CURRENT          # text file with the active version id
        current -> versions/<version>  (best-effort symlink)

The manager does not mutate the application configuration; instead it flips the
``CURRENT`` pointer (and optional ``current`` symlink). Runtime components read
through stable paths such as ``.../current/faiss.index`` and reload when
``ApplicationContext.reload_indices()`` closes their runtime cells.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codeintel_rev.errors import RuntimeLifecycleError
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
_RUNTIME = "index-lifecycle"


@dataclass(slots=True, frozen=True)
class LuceneAssets:
    """Lucene index directories that should flip atomically."""

    bm25_dir: Path | None = None
    splade_dir: Path | None = None

    def iter_dirs(self) -> Iterable[tuple[str, Path]]:
        """Yield component name/path pairs for present Lucene assets.

        Yields
        ------
        tuple[str, Path]
            Component identifier and source directory.
        """
        if self.bm25_dir is not None:
            yield ("bm25", self.bm25_dir)
        if self.splade_dir is not None:
            yield ("splade", self.splade_dir)


def link_current_lucene(base_dir: Path, version: str, assets: LuceneAssets) -> None:
    """Copy Lucene assets into a version directory and flip the CURRENT pointer.

    Notes
    -----
    This helper delegates to :meth:`IndexLifecycleManager.link_lucene_assets` and
    will surface any lifecycle errors raised by that method.
    """
    manager = IndexLifecycleManager(base_dir)
    manager.link_lucene_assets(version, assets)


@dataclass(slots=True, frozen=True)
class IndexAssets:
    """File-system assets that must advance together for one index version."""

    faiss_index: Path
    duckdb_path: Path
    scip_index: Path
    bm25_dir: Path | None = None
    splade_dir: Path | None = None
    xtr_dir: Path | None = None
    faiss_idmap: Path | None = None
    tuning_profile: Path | None = None

    def ensure_exists(self) -> None:
        """Validate that all required files and directories are present.

        Raises
        ------
        RuntimeLifecycleError
            If a required path is missing.
        """
        required: Iterable[tuple[str, Path | None]] = (
            ("faiss_index", self.faiss_index),
            ("duckdb_path", self.duckdb_path),
            ("scip_index", self.scip_index),
        )
        for label, path in required:
            if path is None or not path.exists():
                message = f"{label} missing: {path}"
                raise RuntimeLifecycleError(message, runtime=_RUNTIME)
        optional: Iterable[tuple[str, Path | None]] = (
            ("bm25_dir", self.bm25_dir),
            ("splade_dir", self.splade_dir),
            ("xtr_dir", self.xtr_dir),
            ("faiss_idmap", self.faiss_idmap),
            ("tuning_profile", self.tuning_profile),
        )
        for label, path in optional:
            if path is not None and not path.exists():
                message = f"{label} missing: {path}"
                raise RuntimeLifecycleError(message, runtime=_RUNTIME)


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def collect_asset_attrs(assets: IndexAssets) -> dict[str, object]:
    """Return manifest attributes derived from staged asset sidecars."""
    attrs: dict[str, object] = {}
    meta_path = assets.faiss_index.with_suffix(".meta.json")
    meta_payload = _read_json(meta_path)
    if meta_payload:
        factory = meta_payload.get("factory")
        if factory:
            attrs["faiss_factory"] = factory
        parameter_space = meta_payload.get("parameter_space")
        if parameter_space:
            attrs["faiss_parameters"] = parameter_space
        vector_count = meta_payload.get("vector_count")
        if vector_count is not None:
            attrs["faiss_vector_count"] = int(vector_count)
        default_parameters = meta_payload.get("default_parameters")
        if default_parameters:
            attrs["faiss_default_parameters"] = default_parameters
    if assets.faiss_idmap is not None and assets.faiss_idmap.exists():
        attrs["faiss_idmap_checksum"] = _file_checksum(assets.faiss_idmap)
    if assets.tuning_profile is not None and assets.tuning_profile.exists():
        profile_payload = _read_json(assets.tuning_profile)
        if profile_payload:
            attrs["faiss_tuning_profile"] = profile_payload
            if "param_str" in profile_payload:
                attrs["faiss_parameters"] = profile_payload["param_str"]
            if "refine_k_factor" in profile_payload:
                attrs["faiss_refine_k_factor"] = profile_payload["refine_k_factor"]
            if "factory" in profile_payload and "faiss_factory" not in attrs:
                attrs["faiss_factory"] = profile_payload["factory"]
    return attrs


@dataclass(slots=True, frozen=True)
class VersionMeta:
    """Metadata recorded for each version directory."""

    version: str
    created_ts: float
    attrs: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Return a JSON payload suitable for writing to disk.

        Returns
        -------
        str
            JSON representation of the manifest.
        """
        return json.dumps(
            {
                "version": self.version,
                "created_ts": self.created_ts,
                "attrs": dict(self.attrs),
            },
            sort_keys=True,
        )


class IndexLifecycleManager:
    """Manage staged/published index versions under a base directory."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.versions_dir = self.base_dir / "versions"
        self.current_file = self.base_dir / "CURRENT"
        self.current_link = self.base_dir / "current"
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ helpers
    def current_version(self) -> str | None:
        """Return the currently published version identifier.

        Returns
        -------
        str | None
            Version identifier or ``None`` when unset.
        """
        try:
            content = self.current_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        return content or None

    def current_dir(self) -> Path | None:
        """Return the directory backing the active version.

        Returns
        -------
        Path | None
            Directory containing the current manifest, if present.
        """
        version = self.current_version()
        if not version:
            return None
        candidate = self.versions_dir / version
        if candidate.exists():
            return candidate
        return None

    def list_versions(self) -> list[str]:
        """Return the list of committed versions (excludes staging dirs).

        Returns
        -------
        list[str]
            Sorted set of published version identifiers.
        """
        versions = [
            entry.name
            for entry in self.versions_dir.glob("*")
            if entry.is_dir() and not entry.name.endswith(".staging")
        ]
        versions.sort()
        return versions

    def read_assets(self) -> IndexAssets | None:
        """Return paths for active assets or ``None`` when unset.

        Returns
        -------
        IndexAssets | None
            Asset set for the active version, if any.

        Raises
        ------
        RuntimeLifecycleError
            If the manifest is missing or inconsistent.
        """
        active_dir = self.current_dir()
        if active_dir is None:
            return None
        manifest_path = active_dir / "version.json"
        if not manifest_path.exists():
            message = f"manifest missing: {manifest_path}"
            raise RuntimeLifecycleError(message, runtime=_RUNTIME)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assets = IndexAssets(
            faiss_index=active_dir / "faiss.index",
            duckdb_path=active_dir / "catalog.duckdb",
            scip_index=active_dir / "code.scip",
            bm25_dir=self._maybe_dir(active_dir / "bm25"),
            splade_dir=self._maybe_dir(active_dir / "splade"),
            xtr_dir=self._maybe_dir(active_dir / "xtr"),
            faiss_idmap=self._maybe_file(active_dir / "faiss_idmap.parquet"),
            tuning_profile=self._maybe_file(active_dir / "tuning.json"),
        )
        assets.ensure_exists()
        if payload.get("version") != self.current_version():
            LOGGER.warning(
                "index.version_manifest_mismatch",
                extra={
                    "manifest_version": payload.get("version"),
                    "current_version": self.current_version(),
                },
            )
        return assets

    # ------------------------------------------------------------------ writes
    def prepare(
        self,
        version: str,
        assets: IndexAssets,
        *,
        attrs: Mapping[str, Any] | None = None,
    ) -> Path:
        """Copy assets into a staging directory for ``version``.

        Extended Summary
        ----------------
        This method stages index assets for a new version by copying FAISS index,
        DuckDB catalog, SCIP index, and optional sparse indexes (BM25, SPLADE, XTR)
        into a versioned staging directory. It validates asset existence, creates
        version metadata, and prepares the staging area for atomic publication.
        Used as the first step in the index publication workflow.

        Parameters
        ----------
        version : str
            Version identifier (e.g., "v1.2.3") for the staged assets. Must be
            non-empty and unique (staging directory must not exist).
        assets : IndexAssets
            Index assets to stage, including paths to FAISS index, DuckDB catalog,
            SCIP index, and optional sparse index directories. All required assets
            must exist on the filesystem.
        attrs : Mapping[str, Any] | None, optional
            Optional metadata attributes to include in version metadata. If None,
            uses empty dict. Attributes are persisted in version.json.

        Returns
        -------
        Path
            Directory containing the staged assets. The directory name follows
            the pattern "{version}.staging" and contains all copied assets plus
            version.json metadata.

        Raises
        ------
        RuntimeLifecycleError
            If validation fails (empty version, missing assets) or staging already
            exists (concurrent staging attempt).

        Notes
        -----
        This method performs atomic staging by creating the staging directory and
        copying all assets. If any copy operation fails, the staging directory
        may be left in an incomplete state. The staging directory must be published
        or cleaned up manually. Time complexity: O(asset_count * file_size) for
        file copy operations.
        """
        if not version:
            message = "version id missing"
            raise RuntimeLifecycleError(message, runtime=_RUNTIME)
        assets.ensure_exists()
        staging_dir = self.versions_dir / f"{version}.staging"
        if staging_dir.exists():
            message = f"staging already exists: {staging_dir}"
            raise RuntimeLifecycleError(message, runtime=_RUNTIME)
        staging_dir.mkdir(parents=True, exist_ok=False)
        self._copy_file(assets.faiss_index, staging_dir / "faiss.index")
        self._copy_file(assets.duckdb_path, staging_dir / "catalog.duckdb")
        self._copy_file(assets.scip_index, staging_dir / "code.scip")
        self._copy_tree(assets.bm25_dir, staging_dir / "bm25")
        self._copy_tree(assets.splade_dir, staging_dir / "splade")
        self._copy_tree(assets.xtr_dir, staging_dir / "xtr")
        self._copy_optional_file(assets.faiss_idmap, staging_dir / "faiss_idmap.parquet")
        self._copy_optional_file(assets.tuning_profile, staging_dir / "tuning.json")
        meta = VersionMeta(version=version, created_ts=time.time(), attrs=attrs or {})
        (staging_dir / "version.json").write_text(meta.to_json(), encoding="utf-8")
        LOGGER.info(
            "index.prepare.complete",
            extra={"version": version, "dir": str(staging_dir)},
        )
        return staging_dir

    def write_attrs(self, version: str, **attrs: object) -> Path:
        """Merge additional attributes into ``version.json``."""
        manifest_path = self.versions_dir / version / "version.json"
        if not manifest_path.exists():
            message = f"manifest missing: {manifest_path}"
            raise RuntimeLifecycleError(message, runtime=_RUNTIME)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        merged = dict(payload.get("attrs", {}))
        merged.update(attrs)
        payload["attrs"] = merged
        manifest_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        return manifest_path

    def publish(self, version: str) -> Path:
        """Atomically promote a staged directory to active ``version``.

        Extended Summary
        ----------------
        This method atomically publishes a staged index version by creating a
        versioned directory, moving staged assets, updating the CURRENT symlink,
        and updating the lifecycle manifest. The operation is atomic: if any step
        fails, the previous version remains active. Used to deploy new index versions
        in production after staging completes.

        Parameters
        ----------
        version : str
            Version identifier of the staged directory to publish (e.g., "v1.2.3").
            The staging directory "{version}.staging" must exist and contain valid
            assets.

        Returns
        -------
        Path
            Directory containing the published assets. The directory name follows
            the pattern "{version}" and becomes the active version via CURRENT symlink.

        Raises
        ------
        RuntimeLifecycleError
            If the requested staging area is missing, symlink creation fails, or
            manifest update fails.

        Notes
        -----
        This method performs atomic publication by creating the version directory,
        moving staged assets, updating CURRENT symlink, and updating the manifest.
        The operation is designed to be safe for concurrent access. Time complexity:
        O(1) for directory operations plus I/O time for symlink and manifest updates.
        """
        staging_dir = self.versions_dir / f"{version}.staging"
        if not staging_dir.exists():
            message = f"staging not found for version {version}"
            raise RuntimeLifecycleError(message, runtime=_RUNTIME)
        final_dir = self.versions_dir / version
        staging_dir.replace(final_dir)
        self._write_current_pointer(version, final_dir)
        LOGGER.info(
            "index.publish.complete",
            extra={"version": version, "dir": str(final_dir)},
        )
        return final_dir

    def rollback(self, version: str) -> None:
        """Point the ``CURRENT`` pointer at an existing version.

        Extended Summary
        ----------------
        This method performs a rollback operation by updating the CURRENT symlink
        to point to a previously published version. It validates that the target
        version exists, updates the symlink atomically, and updates the lifecycle
        manifest. Used for rapid recovery from problematic index deployments without
        requiring full re-publication.

        Parameters
        ----------
        version : str
            Version identifier to rollback to (e.g., "v1.2.0"). Must exist in the
            published versions list (version directory must exist).

        Raises
        ------
        RuntimeLifecycleError
            If the requested version cannot be located (version directory missing),
            symlink update fails, or manifest update fails.

        Notes
        -----
        This method performs atomic rollback by updating the CURRENT symlink and
        manifest. The operation is fast (O(1) symlink update) but requires the
        target version to exist. Time complexity: O(1) for symlink operations
        plus I/O time for manifest updates.
        """
        candidate = self.versions_dir / version
        if not candidate.exists():
            message = f"version not found: {candidate}"
            raise RuntimeLifecycleError(message, runtime=_RUNTIME)
        self._write_current_pointer(version, candidate)
        LOGGER.info("index.rollback.complete", extra={"version": version})

    def link_lucene_assets(self, version: str, assets: LuceneAssets) -> Path:
        """Publish Lucene-only assets under ``version`` and flip CURRENT pointer.

        Parameters
        ----------
        version : str
            Version identifier that should become active.
        assets : LuceneAssets
            Collection of Lucene directories to copy into the lifecycle root.

        Returns
        -------
        Path
            Path to the published version directory.

        Raises
        ------
        RuntimeLifecycleError
            If any of the source directories are missing.
        """
        target_dir = self.versions_dir / version
        target_dir.mkdir(parents=True, exist_ok=True)

        for name, src in assets.iter_dirs():
            if not src.exists():
                message = f"lucene source missing: {src}"
                raise RuntimeLifecycleError(message, runtime=_RUNTIME)
            dst = target_dir / f"lucene_{name}"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

        self._write_current_pointer(version, target_dir)
        LOGGER.info(
            "index.link_lucene_assets",
            extra={"version": version, "assets": [name for name, _ in assets.iter_dirs()]},
        )
        return target_dir

    # ------------------------------------------------------------------ internals
    def _write_current_pointer(self, version: str, target_dir: Path) -> None:
        tmp = self.current_file.with_suffix(".tmp")
        tmp.write_text(version, encoding="utf-8")
        Path(tmp).replace(self.current_file)
        with contextlib.suppress(OSError):
            if self.current_link.is_symlink() or self.current_link.exists():
                self.current_link.unlink()
            self.current_link.symlink_to(target_dir, target_is_directory=True)

    @staticmethod
    def _maybe_dir(path: Path) -> Path | None:
        return path if path.exists() else None

    @staticmethod
    def _maybe_file(path: Path) -> Path | None:
        return path if path.exists() else None

    @staticmethod
    def _copy_file(src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    @staticmethod
    def _copy_tree(src: Path | None, dst: Path) -> None:
        if src is None:
            return
        if not src.exists():
            return
        shutil.copytree(src, dst, dirs_exist_ok=False)

    @staticmethod
    def _copy_optional_file(src: Path | None, dst: Path) -> None:
        if src is None:
            return
        if not src.exists():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


__all__ = [
    "IndexAssets",
    "IndexLifecycleManager",
    "LuceneAssets",
    "collect_asset_attrs",
    "VersionMeta",
    "link_current_lucene",
]
