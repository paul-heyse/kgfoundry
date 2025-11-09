from __future__ import annotations

from collections.abc import Iterable, Iterator

import pytest

from kgfoundry_common.navmap_loader import (
    NavMetadataModel,
    clear_navmap_caches,
    load_nav_metadata,
)


@pytest.fixture(autouse=True)
def _reset_navmap_caches() -> Iterator[None]:
    clear_navmap_caches()
    yield
    clear_navmap_caches()


def _symbol_names(sections: object) -> set[str]:
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
    metadata = load_nav_metadata("download.cli", ("app", "harvest"))
    assert isinstance(metadata, NavMetadataModel)
    assert metadata.module_meta.owner == "@data-platform"
    assert metadata.symbols["harvest"].handler is not None
    # Sections should reflect CLI tag groups and include harvest symbol.
    section_symbol_names = _symbol_names(metadata["sections"])
    assert "harvest" in section_symbol_names


def test_sidecar_metadata_validates() -> None:
    metadata = load_nav_metadata("registry.helper", ("DuckDBRegistryHelper",))
    assert isinstance(metadata, NavMetadataModel)
    assert metadata.module_meta.owner == "@registry"
    assert "DuckDBRegistryHelper" in metadata.symbols
