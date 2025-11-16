"""Tests for plugin registry: channel discovery and entry point loading."""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import cast

import pytest
from codeintel_rev.app.config_context import ResolvedPaths
from codeintel_rev.config.settings import Settings
from codeintel_rev.plugins import registry as registry_module
from codeintel_rev.plugins.channels import Channel, ChannelContext
from codeintel_rev.plugins.registry import ChannelRegistry
from codeintel_rev.retrieval.types import SearchHit

from tests._helpers import assertions


class _ToyChannel(Channel):
    name = "toy"
    cost = 0.1
    requires = frozenset()

    @staticmethod
    def search(query: str, limit: int) -> Sequence[SearchHit]:
        """Stub search method.

        Parameters
        ----------
        query : str
            Search query string.
        limit : int
            Maximum number of results.

        Returns
        -------
        Sequence[SearchHit]
            List of search hits.
        """
        assertions.expect_true(bool(query), reason="query should be non-empty")
        _ = limit
        return [SearchHit(doc_id="1", rank=0, score=1.0, source="toy")]


class _FakeEntryPoint:
    def __init__(self, factory: object) -> None:
        """Initialize fake entry point.

        Parameters
        ----------
        factory : object
            Factory function to return.
        """
        self.name = "toy"
        self._factory = factory

    def load(self) -> object:
        return self._factory


def test_registry_discovers_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that channel registry discovers channels via entry points."""

    def fake_entry_points(*, group: str) -> list[_FakeEntryPoint]:
        assertions.expect_equal(group, "codeintel_rev.channels")

        def _factory(_: ChannelContext) -> _ToyChannel:
            return _ToyChannel()

        return [_FakeEntryPoint(_factory)]

    monkeypatch.setattr(registry_module, "entry_points", fake_entry_points)

    context = ChannelContext(
        settings=cast("Settings", SimpleNamespace()),
        paths=cast("ResolvedPaths", SimpleNamespace()),
    )
    registry = ChannelRegistry.discover(context)
    channels = registry.channels()
    assertions.expect_equal(len(channels), 1)
    assertions.expect_equal(channels[0].name, "toy")
