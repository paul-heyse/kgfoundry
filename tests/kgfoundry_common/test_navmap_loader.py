"""Tests for navigation map loader: CLI contracts and sidecar metadata validation."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import pytest

from kgfoundry_common.navmap_loader import (
    NavMetadataModel,
    clear_navmap_caches,
    load_nav_metadata,
)
from tests._helpers import assertions


@pytest.fixture(autouse=True)
def _reset_navmap_caches() -> Iterator[None]:
    """Reset navmap caches before and after each test.

    Yields
    ------
    None
        Fixture yields control to test execution.
    """
    clear_navmap_caches()
    yield
    clear_navmap_caches()


def _symbol_names(sections: object) -> set[str]:
    """Extract symbol names from navigation sections.

    Parameters
    ----------
    sections : object
        Navigation sections object.

    Returns
    -------
    set[str]
        Set of symbol names found in sections.
    """
    names: set[str] = set()
    if sections is None:
        return names
    if isinstance(sections, Iterable) and not isinstance(sections, (str, bytes)):
        for section in sections:
            symbols = section.get("symbols", []) if isinstance(section, dict) else []
            if isinstance(symbols, Iterable):
                for symbol in symbols:
                    if isinstance(symbol, str):
                        names.add(symbol)
    return names


def test_cli_nav_metadata_derives_from_cli_contracts() -> None:
    """Test that CLI navigation metadata is derived from CLI contracts."""
    metadata = load_nav_metadata("download.cli", ("app", "harvest"))
    assertions.expect_true(
        isinstance(metadata, NavMetadataModel), reason="metadata should be NavMetadataModel"
    )
    assertions.expect_equal(metadata.module_meta.owner, "kgfoundry")
    assertions.expect_true(
        metadata.symbols["harvest"].handler is not None, reason="harvest handler should be set"
    )
    # Sections should reflect CLI tag groups and include harvest symbol.
    section_symbol_names = _symbol_names(metadata["sections"])
    assertions.expect_in("harvest", section_symbol_names)


def test_sidecar_metadata_validates() -> None:
    """Test that sidecar metadata validates correctly."""
    metadata = load_nav_metadata("registry.helper", ("DuckDBRegistryHelper",))
    assertions.expect_true(
        isinstance(metadata, NavMetadataModel), reason="metadata should be NavMetadataModel"
    )
    assertions.expect_equal(metadata.module_meta.owner, "@registry")
    assertions.expect_in("DuckDBRegistryHelper", metadata.symbols)
