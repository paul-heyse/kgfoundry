"""Tests for docstring builder cache interfaces.

This module verifies that the cache Protocol is properly implemented and that existing cache
implementations satisfy the contract.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, cast

from tests.helpers import load_attribute

if TYPE_CHECKING:
    from tools.docstring_builder.cache import BuilderCache, DocstringBuilderCache

    BuilderCacheType = type[BuilderCache]

# Load concrete implementation at module level to avoid TC002 violations
# This is a runtime variable, not a type - use TYPE_CHECKING import in annotations
_BuilderCacheClass = cast(
    "BuilderCacheType", load_attribute("tools.docstring_builder.cache", "BuilderCache")
)
BuilderCacheClass = (
    _BuilderCacheClass  # Runtime class, use "BuilderCache" in type annotations
)


class TestCacheProtocol:
    """Tests verifying the DocstringBuilderCache Protocol."""

    def test_builder_cache_implements_protocol(self) -> None:
        """Verify BuilderCache can be used as DocstringBuilderCache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache: DocstringBuilderCache = BuilderCacheClass(cache_path)
            assert cache is not None

    def test_cache_path_property(self) -> None:
        """Verify cache.path property works."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = BuilderCacheClass(cache_path)
            assert cache.path == cache_path

    def test_cache_needs_update_new_file(self) -> None:
        """Verify needs_update returns True for new files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = BuilderCacheClass(cache_path)

            # Create a test file
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("# test")

            # New file should need update
            assert cache.needs_update(test_file, "hash123") is True

    def test_cache_update_and_check(self) -> None:
        """Verify update marks file as not needing update."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = BuilderCacheClass(cache_path)

            # Create a test file
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("# test")

            # First check: needs update
            assert cache.needs_update(test_file, "hash123") is True

            # Update the cache
            cache.update(test_file, "hash123")

            # Second check: doesn't need update (same config, same mtime)
            assert cache.needs_update(test_file, "hash123") is False

    def test_cache_detect_config_change(self) -> None:
        """Verify needs_update returns True when config changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = BuilderCacheClass(cache_path)

            # Create a test file
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("# test")

            # Update with hash1
            cache.update(test_file, "hash123")
            assert cache.needs_update(test_file, "hash123") is False

            # Check with hash2 - should need update
            assert cache.needs_update(test_file, "hash456") is True

    def test_cache_write(self) -> None:
        """Verify cache.write() persists to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache = BuilderCacheClass(cache_path)

            # Create a test file
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("# test")

            # Update and write
            cache.update(test_file, "hash123")
            cache.write()

            # Verify file was created
            assert cache_path.exists()

            # Load new cache instance from file
            new_cache = BuilderCacheClass(cache_path)

            # Verify it has the same entries
            assert new_cache.needs_update(test_file, "hash123") is False


class TestCacheProtocolContract:
    """Tests verifying the semantic contract of DocstringBuilderCache."""

    def test_cache_protocol_is_structural(self) -> None:
        """Verify BuilderCache satisfies structural typing (Protocol)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            builder_cache = BuilderCacheClass(cache_path)

            # Assign to Protocol type - this verifies structural typing
            cache: DocstringBuilderCache = builder_cache

            # All methods should be available
            assert hasattr(cache, "path")
            assert hasattr(cache, "needs_update")
            assert hasattr(cache, "update")
            assert hasattr(cache, "write")

    def test_cache_methods_callable(self) -> None:
        """Verify all cache protocol methods are callable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache: DocstringBuilderCache = BuilderCacheClass(cache_path)

            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("# test")

            # All methods should be callable
            assert callable(cache.needs_update)
            assert callable(cache.update)
            assert callable(cache.write)

            # Execute methods to verify they work
            cache.needs_update(test_file, "hash")
            cache.update(test_file, "hash")
            cache.write()
