"""Channel plugin contracts for hybrid retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from codeintel_rev.config.api import AppConfig
from codeintel_rev.config.paths import ResolvedPaths
from codeintel_rev.retrieval.types import SearchHit

if TYPE_CHECKING:
    from codeintel_rev.app.capabilities import Capabilities
else:  # pragma: no cover - runtime values supplied by the app context
    Capabilities = Any

__all__ = ["Channel", "ChannelContext", "ChannelError"]


@dataclass(slots=True, frozen=True)
class ChannelContext:
    """Context passed to channel factories when they are constructed.

    Attributes
    ----------
    app_config : AppConfig
        Immutable application configuration containing channel data.
    paths : ResolvedPaths
        Resolved filesystem paths for channel resources.
    capabilities : Capabilities | None, optional
        Optional capabilities metadata. None if capabilities are not available.
        Defaults to None.
    """

    app_config: AppConfig
    paths: ResolvedPaths
    capabilities: Capabilities | None = None


class Channel(Protocol):
    """Retrieval channel plugin interface."""

    name: str
    cost: float
    requires: frozenset[str]

    def search(self, query: str, limit: int) -> Sequence[SearchHit]:
        """Return channel hits for ``query`` with per-channel cutoff ``limit``."""
        ...


class ChannelError(RuntimeError):
    """Raised by channels when they cannot satisfy a search request.

    Parameters
    ----------
    message : str
        Human-readable error message.
    reason : str, optional
        Error reason code (default: "provider_error").
    """

    def __init__(self, message: str, *, reason: str = "provider_error") -> None:
        super().__init__(message)
        self.reason = reason
