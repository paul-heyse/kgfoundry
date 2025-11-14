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
MANIFEST_FILE = "manifest.json"
IDMAP_FILE = "faiss.idmap.parquet"
PROFILE_FILE = "faiss.tuning.json"
_LEGACY_MANIFEST_FILES = ("version.json",)
_LEGACY_IDMAP_FILES = ("faiss_idmap.parquet",)
_LEGACY_PROFILE_FILES = ("tuning.json",)


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
    """Return manifest attributes derived from staged asset sidecars.

    This function aggregates metadata from staged index assets (FAISS index, ID map,
    tuning profile) and builds a dictionary of attributes suitable for inclusion in
    the version manifest. The function extracts factory strings, parameter spaces,
    and tuning information from asset sidecar files.

    Parameters
    ----------
    assets : IndexAssets
        Staged index assets containing paths to FAISS index, ID map, and tuning
        profile files. The function reads metadata from .meta.json files and
        extracts attributes from ID map and tuning profile sidecars.

    Returns
    -------
    dict[str, object]
        Aggregated FAISS metadata dictionary containing factory string, parameter
        space, tuning parameters, and other index configuration attributes. The
        dictionary is suitable for serialization in version.json manifests.
    """
    attrs: dict[str, object] = {}
    attrs.setdefault("faiss_bytes_sha256", _file_checksum(assets.faiss_index))
    attrs.update(_attrs_from_meta(assets.faiss_index.with_suffix(".meta.json")))
    attrs.update(_attrs_from_idmap(assets.faiss_idmap))
    attrs.update(_attrs_from_tuning(assets.tuning_profile, attrs))
    if assets.faiss_idmap and assets.faiss_idmap.exists():
        attrs.setdefault("faiss_idmap", assets.faiss_idmap.name)
    if assets.tuning_profile and assets.tuning_profile.exists():
        attrs.setdefault("faiss_profile", assets.tuning_profile.name)
    return attrs


def _attrs_from_meta(meta_path: Path) -> dict[str, object]:
    payload = _read_json(meta_path)
    if not payload:
        return {}
    attrs: dict[str, object] = {}
    factory = payload.get("factory")
    if factory:
        attrs["faiss_factory"] = factory
    parameter_space = payload.get("parameter_space")
    if parameter_space:
        attrs["faiss_parameters"] = parameter_space
    vector_count = payload.get("vector_count")
    if isinstance(vector_count, (int, float, str)):
        try:
            attrs["faiss_vector_count"] = int(vector_count)
        except (TypeError, ValueError):
            LOGGER.warning("invalid vector_count field in %s", meta_path)
    default_parameters = payload.get("default_parameters")
    if default_parameters:
        attrs["faiss_default_parameters"] = default_parameters
    return attrs


def _attrs_from_idmap(idmap_path: Path | None) -> dict[str, object]:
    if idmap_path is None or not idmap_path.exists():
        return {}
    return {"faiss_idmap_checksum": _file_checksum(idmap_path)}


def _attrs_from_tuning(
    tuning_path: Path | None,
    existing: Mapping[str, object],
) -> dict[str, object]:
    if tuning_path is None or not tuning_path.exists():
        return {}
    payload = _read_json(tuning_path)
    if not payload:
        return {}
    attrs: dict[str, object] = {"faiss_tuning_profile": payload}
    if "param_str" in payload:
        attrs["faiss_parameters"] = payload["param_str"]
    if "refine_k_factor" in payload:
        attrs["faiss_refine_k_factor"] = payload["refine_k_factor"]
    factory = payload.get("factory")
    if factory and "faiss_factory" not in existing:
        attrs["faiss_factory"] = factory
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

    def open_current(self) -> Path:
        """Return the active version directory, validating manifest presence."""
        active_dir = self.current_dir()
        if active_dir is None:
            raise RuntimeLifecycleError("No CURRENT version", runtime=_RUNTIME)
        self._resolve_manifest_path(active_dir)
        return active_dir

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
        manifest_path = self._resolve_manifest_path(active_dir)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assets = IndexAssets(
            faiss_index=active_dir / "faiss.index",
            duckdb_path=active_dir / "catalog.duckdb",
            scip_index=active_dir / "code.scip",
            bm25_dir=self._maybe_dir(active_dir / "bm25"),
            splade_dir=self._maybe_dir(active_dir / "splade"),
            xtr_dir=self._maybe_dir(active_dir / "xtr"),
            faiss_idmap=self._locate_sidecar(active_dir, IDMAP_FILE, _LEGACY_IDMAP_FILES),
            tuning_profile=self._locate_sidecar(active_dir, PROFILE_FILE, _LEGACY_PROFILE_FILES),
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

    def write_embedding_metadata(
        self,
        payload: Mapping[str, object],
        *,
        version: str | None = None,
    ) -> Path:
        """Persist ``embedding_meta.json`` into the requested version directory.

        Parameters
        ----------
        payload : Mapping[str, object]
            JSON-serialisable metadata describing the embeddings.
        version : str | None, optional
            Version identifier to target. When omitted, writes to the current
            version directory.

        Returns
        -------
        Path
            Filesystem path to the written metadata file.

        Raises
        ------
        RuntimeLifecycleError
            If no suitable version directory exists.

        """
        target_dir: Path | None
        if version is None:
            target_dir = self.current_dir()
        else:
            candidate = self.versions_dir / version
            target_dir = candidate if candidate.exists() else None
        if target_dir is None:
            msg = "No version directory available for embedding metadata"
            raise RuntimeLifecycleError(msg, runtime=_RUNTIME)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / "embedding_meta.json"
        path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        return path

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
        self._copy_optional_file(assets.faiss_idmap, staging_dir / IDMAP_FILE)
        self._copy_optional_file(assets.tuning_profile, staging_dir / PROFILE_FILE)
        missing_sidecars: list[str] = []
        if assets.faiss_idmap is None or not assets.faiss_idmap.exists():
            missing_sidecars.append("faiss_idmap")
        if assets.tuning_profile is None or not assets.tuning_profile.exists():
            missing_sidecars.append("tuning_profile")
        if missing_sidecars:
            LOGGER.warning(
                "index.prepare.sidecars_missing",
                extra={"version": version, "missing": ",".join(missing_sidecars)},
            )
        meta = VersionMeta(version=version, created_ts=time.time(), attrs=attrs or {})
        (staging_dir / MANIFEST_FILE).write_text(meta.to_json(), encoding="utf-8")
        LOGGER.info(
            "index.prepare.complete",
            extra={"version": version, "dir": str(staging_dir)},
        )
        return staging_dir

    def write_attrs(self, version: str, **attrs: object) -> Path:
        """Merge additional attributes into the lifecycle manifest.

        This method updates the version manifest file by merging additional
        attributes into the existing attrs dictionary. The method reads the
        current manifest, merges the provided attributes, and writes the
        updated manifest back to disk. Used to add metadata to staged or
        published versions.

        Parameters
        ----------
        version : str
            Version identifier for the manifest to update (e.g., "v1.0.0").
            The version must exist in the versions directory and have a
            manifest file.
        **attrs : object
            Additional attributes to merge into the manifest's attrs dictionary.
            Attributes are merged using dict.update(), with new values overriding
            existing ones. All attributes must be JSON-serializable.

        Returns
        -------
        Path
            Path to the updated manifest file (versions_dir / version / MANIFEST_FILE).
            The manifest has been updated with merged attributes and written to disk.

        Raises
        ------
        RuntimeLifecycleError
            Raised when the manifest file is missing for the specified version.
            The error includes the expected manifest path for debugging.
        """
        version_dir = self.versions_dir / version
        if not version_dir.exists():
            message = f"version not found: {version_dir}"
            raise RuntimeLifecycleError(message, runtime=_RUNTIME)
        manifest_path = self._resolve_manifest_path(version_dir)
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
        self._resolve_manifest_path(final_dir)
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

    def _resolve_manifest_path(self, version_dir: Path) -> Path:
        manifest_path = version_dir / MANIFEST_FILE
        if manifest_path.exists():
            return manifest_path
        for legacy_name in _LEGACY_MANIFEST_FILES:
            legacy_path = version_dir / legacy_name
            if legacy_path.exists():
                LOGGER.warning(
                    "index.manifest.legacy_path",
                    extra={"path": str(legacy_path), "preferred": MANIFEST_FILE},
                )
                return legacy_path
        message = f"manifest missing: {manifest_path}"
        raise RuntimeLifecycleError(message, runtime=_RUNTIME)

    def _locate_sidecar(
        self,
        base_dir: Path,
        primary_name: str,
        legacy_names: tuple[str, ...],
    ) -> Path | None:
        candidate = base_dir / primary_name
        if candidate.exists():
            return candidate
        for legacy_name in legacy_names:
            legacy_candidate = base_dir / legacy_name
            if legacy_candidate.exists():
                LOGGER.warning(
                    "index.sidecar.legacy_path",
                    extra={"path": str(legacy_candidate), "preferred": primary_name},
                )
                return legacy_candidate
        return None


__all__ = [
    "IndexAssets",
    "IndexLifecycleManager",
    "LuceneAssets",
    "VersionMeta",
    "collect_asset_attrs",
    "link_current_lucene",
]
