from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.errors import RuntimeLifecycleError
from codeintel_rev.indexing.index_lifecycle import IndexAssets, IndexLifecycleManager


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
