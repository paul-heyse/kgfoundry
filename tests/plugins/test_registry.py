"""Tests for plugin registry: channel discovery and entry point loading."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from importlib.metadata import EntryPoint
from types import SimpleNamespace
from typing import cast

from codeintel_rev.config.paths import ResolvedPaths
from codeintel_rev.config.settings import Settings
from codeintel_rev.plugins.channels import Channel, ChannelContext
from codeintel_rev.plugins.registry import ChannelRegistry, override_channel_entry_points
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


def test_registry_discovers_entry_points() -> None:
    """Test that channel registry discovers channels via entry points."""

    def _factory(_: ChannelContext) -> _ToyChannel:
        return _ToyChannel()

    entry_points = cast("Iterable[EntryPoint]", [_FakeEntryPoint(_factory)])
    context = ChannelContext(
        settings=cast("Settings", SimpleNamespace()),
        paths=cast("ResolvedPaths", SimpleNamespace()),
    )
    with override_channel_entry_points(entry_points):
        registry = ChannelRegistry.discover(context)
    channels = registry.channels()
    assertions.expect_equal(len(channels), 1)
    assertions.expect_equal(channels[0].name, "toy")
