"""Channel plugin contracts for hybrid retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

from codeintel_rev.config.api import AppConfig
from codeintel_rev.config.paths import ResolvedPaths
from codeintel_rev.config.shim import settings_from_app_config
from codeintel_rev.retrieval.types import SearchHit

if TYPE_CHECKING:
    from codeintel_rev.app.capabilities import Capabilities
    from codeintel_rev.config.settings import Settings
else:  # pragma: no cover - runtime values supplied by the app context
    Capabilities = Any
    Settings = Any

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
    _settings: Settings | None = None

    @property
    def settings(self) -> Settings:
        """Return legacy Settings shim for backwards compatibility."""
        cached = self._settings
        if cached is not None:
            return cached
        shim = settings_from_app_config(self.app_config)
        object.__setattr__(self, "_settings", shim)
        return cast("Settings", shim)


class Channel(Protocol):
    """Retrieval channel plugin interface."""

    name: str
    cost: float
    requires: frozenset[str]

    def search(self, query: str, limit: int) -> Sequence[SearchHit]:
        """Return channel hits for ``query`` with per-channel cutoff ``limit``."""
        ...


class ChannelError(RuntimeError):
    """Raised by channels when they cannot satisfy a search request."""

    def __init__(self, message: str, *, reason: str = "provider_error") -> None:
        """Initialize channel error.

        Parameters
        ----------
        message : str
            Human-readable error message.
        reason : str, optional
            Error reason code (default: "provider_error").
        """
        super().__init__(message)
        self.reason = reason
