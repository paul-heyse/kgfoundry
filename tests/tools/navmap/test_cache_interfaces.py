"""Tests for navmap cache Protocol interfaces and structural typing."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, cast

from tools.navmap.cache import NavmapCollectorCache, NavmapRepairCache

from tests.helpers import load_attribute

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tools.navmap.build_navmap import ModuleInfo
    from tools.navmap.repair_navmaps import RepairResult

    ModuleInfoType = type[ModuleInfo]
    RepairResultType = type[RepairResult]

# Load concrete implementations at module level to avoid TC002 violations
# These are runtime variables, not types - use string literals in type annotations
_ModuleInfoClass = cast(
    "ModuleInfoType", load_attribute("tools.navmap.build_navmap", "ModuleInfo")
)
ModuleInfoClass = (
    _ModuleInfoClass  # Runtime class, use "ModuleInfo" in type annotations
)
_RepairResultClass = cast(
    "RepairResultType", load_attribute("tools.navmap.repair_navmaps", "RepairResult")
)
RepairResultClass = (
    _RepairResultClass  # Runtime class, use "RepairResult" in type annotations
)


class MockCollectorCache:
    """Mock implementation of NavmapCollectorCache for testing.

    This mock cache provides an in-memory implementation of the collector cache
    interface, allowing tests to verify cache behavior without requiring file
    system operations. It stores module metadata in memory and provides the
    same interface as the production cache implementation.

    Parameters
    ----------
    root : Path
        Root directory path that serves as the cache root.
    modules : Sequence[ModuleInfo] | None, optional
        Pre-populated modules to initialize the cache with. When None, the
        cache starts empty.
    """

    def __init__(self, root: Path, modules: Sequence[ModuleInfo] | None = None) -> None:
        self._root = root
        self._modules = list(modules) if modules else []

    @property
    def root(self) -> Path:
        """Return the root directory."""
        return self._root

    def collect_modules(self) -> list[ModuleInfo]:
        """Return collected modules.

        Returns
        -------
        list[ModuleInfo]
            List of collected module info objects.
        """
        return self._modules

    def get_module(self, path: Path) -> ModuleInfo | None:
        """Return a module by path.

        Parameters
        ----------
        path : Path
            Module path to look up.

        Returns
        -------
        ModuleInfo | None
            Module info if found, otherwise None.
        """
        for mod in self._modules:
            if mod.path == path:
                return mod
        return None


class MockRepairCache:
    """Mock implementation of NavmapRepairCache for testing.

    This mock cache provides an in-memory implementation of the repair cache
    interface, allowing tests to verify repair tracking behavior without
    requiring file system operations. It stores repair results in memory and
    provides query methods to inspect recorded repairs.

    Notes
    -----
    The cache starts empty and accumulates repair results as they are recorded
    during test execution. All repairs are stored in memory until explicitly
    cleared or the cache instance is destroyed.
    """

    def __init__(self) -> None:
        self._repairs: list[RepairResult] = []

    def record_repair(self, result: RepairResult) -> None:
        """Record a repair result."""
        self._repairs.append(result)

    def get_repairs(self) -> list[RepairResult]:
        """Return all recorded repairs.

        Returns
        -------
        list[RepairResult]
            List of repair results.
        """
        return list(self._repairs)

    def summary(self) -> dict[str, int]:
        """Return summary statistics.

        Returns
        -------
        dict[str, int]
            Summary dictionary with total, changed, and applied counts.
        """
        total = len(self._repairs)
        changed = sum(1 for r in self._repairs if r.changed)
        applied = sum(1 for r in self._repairs if r.applied)
        return {"total": total, "changed": changed, "applied": applied}


class TestNavmapCollectorCacheProtocol:
    """Test structural typing for NavmapCollectorCache."""

    def test_mock_satisfies_protocol(self) -> None:
        """Verify MockCollectorCache satisfies NavmapCollectorCache Protocol."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "src"
            cache: NavmapCollectorCache = MockCollectorCache(root)
            assert cache.root == root

    def test_root_property_callable(self) -> None:
        """Verify root property is accessible."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "src"
            cache: NavmapCollectorCache = MockCollectorCache(root)
            assert isinstance(cache.root, Path)

    def test_collect_modules_callable(self) -> None:
        """Verify collect_modules method is callable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "src"
            cache: NavmapCollectorCache = MockCollectorCache(root)
            result = cache.collect_modules()
            assert isinstance(result, list)

    def test_get_module_callable(self) -> None:
        """Verify get_module method is callable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "src"
            cache: NavmapCollectorCache = MockCollectorCache(root)
            result = cache.get_module(root / "module.py")
            assert result is None


class TestNavmapRepairCacheProtocol:
    """Test structural typing for NavmapRepairCache."""

    def test_mock_satisfies_protocol(self) -> None:
        """Verify MockRepairCache satisfies NavmapRepairCache Protocol."""
        cache: NavmapRepairCache = MockRepairCache()
        assert hasattr(cache, "record_repair")

    def test_record_repair_callable(self) -> None:
        """Verify record_repair method is callable."""
        cache: NavmapRepairCache = MockRepairCache()
        result = RepairResultClass(
            module=Path("test.py"),
            messages=["test"],
            changed=False,
            applied=False,
        )
        cache.record_repair(result)  # Should not raise

    def test_get_repairs_callable(self) -> None:
        """Verify get_repairs method returns list."""
        cache: NavmapRepairCache = MockRepairCache()
        result = cache.get_repairs()
        assert isinstance(result, list)

    def test_summary_callable(self) -> None:
        """Verify summary method returns dict."""
        cache: NavmapRepairCache = MockRepairCache()
        result = cache.summary()
        assert isinstance(result, dict)

    def test_summary_statistics(self) -> None:
        """Verify summary returns correct statistics."""
        cache = MockRepairCache()
        cache.record_repair(
            RepairResultClass(
                module=Path("a.py"), messages=[], changed=True, applied=True
            )
        )
        cache.record_repair(
            RepairResultClass(
                module=Path("b.py"), messages=[], changed=False, applied=False
            )
        )
        summary = cache.summary()
        assert summary["total"] == 2
        assert summary["changed"] == 1
        assert summary["applied"] == 1


class TestCacheInterfaceContracts:
    """Test interface contracts and invariants."""

    def test_collector_empty_by_default(self) -> None:
        """Verify collector returns empty list for fresh cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "src"
            cache = MockCollectorCache(root)
            assert cache.collect_modules() == []

    def test_collector_returns_provided_modules(self) -> None:
        """Verify collector returns modules provided at initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "src"
            modules: list[ModuleInfo] = []
            cache = MockCollectorCache(root, modules)
            assert cache.collect_modules() == modules

    def test_repair_empty_by_default(self) -> None:
        """Verify repair cache starts empty."""
        cache = MockRepairCache()
        assert cache.get_repairs() == []

    def test_repair_records_multiple(self) -> None:
        """Verify repair cache can record multiple results."""
        cache = MockRepairCache()
        results = [
            RepairResultClass(
                module=Path(f"{i}.py"), messages=[], changed=False, applied=False
            )
            for i in range(3)
        ]
        for result in results:
            cache.record_repair(result)
        assert len(cache.get_repairs()) == 3

    def test_repair_summary_zero_stats(self) -> None:
        """Verify summary shows zeros when no repairs recorded."""
        cache = MockRepairCache()
        summary = cache.summary()
        assert summary["total"] == 0
        assert summary["changed"] == 0
        assert summary["applied"] == 0


class TestProtocolDocumentation:
    """Test that Protocol docstrings are complete."""

    def test_collector_protocol_has_docstring(self) -> None:
        """Verify NavmapCollectorCache has a docstring."""
        assert NavmapCollectorCache.__doc__ is not None
        assert len(NavmapCollectorCache.__doc__) > 0

    def test_repair_protocol_has_docstring(self) -> None:
        """Verify NavmapRepairCache has a docstring."""
        assert NavmapRepairCache.__doc__ is not None
        assert len(NavmapRepairCache.__doc__) > 0
