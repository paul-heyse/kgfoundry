"""Channel plugin contracts for hybrid retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from codeintel_rev.retrieval.types import ChannelHit

if TYPE_CHECKING:
    from codeintel_rev.app.capabilities import Capabilities
    from codeintel_rev.app.config_context import ResolvedPaths
    from codeintel_rev.config.settings import Settings
else:  # pragma: no cover - runtime values supplied by the app context
    Capabilities = Any
    ResolvedPaths = Any
    Settings = Any

__all__ = ["Channel", "ChannelContext", "ChannelError"]


@dataclass(slots=True)
class ChannelContext:
    """Context passed to channel factories when they are constructed."""

    settings: Settings
    paths: ResolvedPaths
    capabilities: Capabilities | None = None


class Channel(Protocol):
    """Retrieval channel plugin interface."""

    name: str
    cost: float
    requires: frozenset[str]

    def search(self, query: str, limit: int) -> Sequence[ChannelHit]:
        """Return channel hits for ``query`` with per-channel cutoff ``limit``."""
        ...


class ChannelError(RuntimeError):
    """Raised by channels when they cannot satisfy a search request."""

    def __init__(self, message: str, *, reason: str = "provider_error") -> None:
        super().__init__(message)
        self.reason = reason
