from __future__ import annotations

import json
from pathlib import Path

import pytest
from codeintel_rev.errors import RuntimeLifecycleError
from codeintel_rev.indexing.index_lifecycle import (
    IndexAssets,
    IndexLifecycleManager,
    collect_asset_attrs,
)


def _make_assets(tmp_path: Path, prefix: str = "a") -> IndexAssets:
    src = tmp_path / prefix
    src.mkdir(parents=True, exist_ok=True)
    faiss = src / "faiss.index"
    duckdb = src / "catalog.duckdb"
    scip = src / "code.scip"
    for file in (faiss, duckdb, scip):
        file.write_bytes(b"data")
    return IndexAssets(
        faiss_index=faiss,
        duckdb_path=duckdb,
        scip_index=scip,
    )


def test_prepare_and_publish(tmp_path: Path) -> None:
    manager = IndexLifecycleManager(tmp_path / "indexes")
    assets = _make_assets(tmp_path, "v1")
    staging = manager.prepare("v1", assets)
    assert staging.name == "v1.staging"
    final_dir = manager.publish("v1")
    assert final_dir.name == "v1"
    assert manager.current_version() == "v1"
    resolved = manager.read_assets()
    assert resolved is not None
    assert resolved.faiss_index.exists()
    assert (manager.base_dir / "CURRENT").read_text().strip() == "v1"


def test_publish_requires_staging(tmp_path: Path) -> None:
    manager = IndexLifecycleManager(tmp_path / "indexes")
    with pytest.raises(RuntimeLifecycleError):
        manager.publish("missing")


def test_prepare_requires_assets(tmp_path: Path) -> None:
    manager = IndexLifecycleManager(tmp_path / "indexes")
    bad_assets = IndexAssets(
        faiss_index=tmp_path / "not_there",
        duckdb_path=tmp_path / "missing.duckdb",
        scip_index=tmp_path / "missing.scip",
    )
    with pytest.raises(RuntimeLifecycleError):
        manager.prepare("v1", bad_assets)


def test_rollback_switches_pointer(tmp_path: Path) -> None:
    manager = IndexLifecycleManager(tmp_path / "indexes")
    assets_v1 = _make_assets(tmp_path, "v1")
    assets_v2 = _make_assets(tmp_path, "v2")
    manager.prepare("alpha", assets_v1)
    manager.publish("alpha")
    manager.prepare("beta", assets_v2)
    manager.publish("beta")
    assert manager.current_version() == "beta"
    manager.rollback("alpha")
    assert manager.current_version() == "alpha"


def test_write_attrs_updates_manifest(tmp_path: Path) -> None:
    manager = IndexLifecycleManager(tmp_path / "indexes")
    assets = _make_assets(tmp_path, "v3")
    manager.prepare("v3", assets, attrs={"initial": True})
    manager.publish("v3")

    manifest_path = manager.versions_dir / "v3" / "manifest.json"
    initial = json.loads(manifest_path.read_text())
    assert initial["attrs"]["initial"] is True

    manager.write_attrs("v3", faiss_factory="Flat", initial=False)
    updated = json.loads(manifest_path.read_text())
    assert updated["attrs"]["faiss_factory"] == "Flat"
    assert updated["attrs"]["initial"] is False


def test_collect_asset_attrs_includes_checksums(tmp_path: Path) -> None:
    assets = _make_assets(tmp_path, "meta")
    idmap = tmp_path / "meta" / "faiss.idmap.parquet"
    idmap.write_bytes(b"idmap")
    tuning = tmp_path / "meta" / "faiss.tuning.json"
    tuning.write_text("{}", encoding="utf-8")
    assets = IndexAssets(
        faiss_index=assets.faiss_index,
        duckdb_path=assets.duckdb_path,
        scip_index=assets.scip_index,
        faiss_idmap=idmap,
        tuning_profile=tuning,
    )
    attrs = collect_asset_attrs(assets)
    assert "faiss_bytes_sha256" in attrs
    assert "duckdb_bytes_sha256" in attrs
    assert "scip_bytes_sha256" in attrs
    assert attrs["faiss_idmap_path"] == "faiss.idmap.parquet"
    assert attrs["faiss_tuning_profile_path"] == "faiss.tuning.json"
