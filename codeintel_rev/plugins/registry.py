"""Entry-point driven registry for retrieval channels."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from importlib.metadata import EntryPoint, entry_points
from typing import cast

from codeintel_rev.plugins.channels import Channel, ChannelContext
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)

__all__ = ["ChannelRegistry"]

_FACTORY_ERRORS = (ImportError, AttributeError, RuntimeError, ValueError)


class ChannelRegistry:
    """Registry that discovers channel plugins via Python entry points."""

    def __init__(self, channels: Sequence[Channel]) -> None:
        self._channels = list(channels)

    @classmethod
    def discover(cls, context: ChannelContext) -> ChannelRegistry:
        """Return a registry populated by entry-point factories.

        Extended Summary
        ----------------
        This class method discovers channel plugins via Python entry points and
        creates a registry containing all successfully loaded channels. It iterates
        through entry points in the "codeintel_rev.channels" group, loads factory
        functions, instantiates channels, and collects them into a registry. Used
        during application startup to auto-discover available retrieval channels.

        Parameters
        ----------
        context : ChannelContext
            Channel context providing index paths and configuration. Passed to
            each factory function during channel instantiation.

        Returns
        -------
        ChannelRegistry
            Registry containing every channel whose factory loaded successfully.
            Channels that fail to load are logged and skipped.

        Notes
        -----
        This method performs dynamic plugin discovery via entry points. Factory
        failures are logged but don't stop discovery. Time complexity: O(n) where
        n is the number of entry points in the channel group.
        """
        discovered: list[Channel] = []
        for entry_point in _iter_entry_points():
            factory = _load_factory(entry_point)
            if factory is None:
                continue
            try:
                channel = factory(context)
            except _FACTORY_ERRORS as exc:  # pragma: no cover - defensive logging
                LOGGER.warning(
                    "channel.factory.failed",
                    extra={"entry_point": entry_point.name, "error": repr(exc)},
                )
                continue
            discovered.append(channel)
        return cls(discovered)

    @classmethod
    def from_channels(cls, channels: Sequence[Channel]) -> ChannelRegistry:
        """Construct a registry from an explicit channel list.

        Extended Summary
        ----------------
        This class method creates a registry from an explicitly provided sequence
        of channels. Used for testing and when programmatic channel configuration
        is preferred over entry point discovery. The channels are stored in the
        order provided.

        Parameters
        ----------
        channels : Sequence[Channel]
            Explicit sequence of channel instances to include in the registry.
            Channels are stored in the order provided.

        Returns
        -------
        ChannelRegistry
            Registry containing the provided channel sequence. The registry
            provides access to channels via the `channels()` method.

        Notes
        -----
        This method creates a registry without entry point discovery. Useful for
        testing and programmatic configuration. Time complexity: O(n) where n is
        the number of channels.
        """
        return cls(list(channels))

    def channels(self) -> tuple[Channel, ...]:
        """Return the known channels.

        Returns
        -------
        tuple[Channel, ...]
            Tuple of registered channel instances.
        """
        return tuple(self._channels)


def _iter_entry_points() -> Iterable[EntryPoint]:
    """Return entry points for the channel group across Python versions.

    Returns
    -------
    Iterable[EntryPoint]
        Iterable of entry point definitions for channel plugins.
    """
    try:  # Python 3.12+ supports ``group=`` directly.
        eps = entry_points(group="codeintel_rev.channels")
    except TypeError:  # pragma: no cover - <3.10 compatibility branch
        eps = entry_points()
        select = getattr(eps, "select", None)
        if callable(select):
            selector = cast("Callable[..., Iterable[EntryPoint]]", select)
            return tuple(selector(group="codeintel_rev.channels"))
        get = getattr(eps, "get", None)
        if callable(get):
            getter = cast("Callable[[str, Iterable[EntryPoint]], Iterable[EntryPoint]]", get)
            return tuple(getter("codeintel_rev.channels", ()))
        return ()
    else:
        if isinstance(eps, dict):  # pragma: no cover - deprecated style fallback
            return tuple(eps.get("codeintel_rev.channels", ()))
        return tuple(eps)


def _load_factory(entry_point: EntryPoint) -> Callable[[ChannelContext], Channel] | None:
    """Return a callable factory if the entry point loads successfully.

    Extended Summary
    ----------------
    This helper loads a channel factory function from a Python entry point. It
    attempts to load the entry point's target (module:function), validates that
    it's callable, and returns it. Used during channel discovery to load factory
    functions from plugin entry points.

    Parameters
    ----------
    entry_point : EntryPoint
        Python entry point definition pointing to a channel factory function.
        The entry point target should be a callable that accepts ChannelContext
        and returns a Channel instance.

    Returns
    -------
    Callable[[ChannelContext], Channel] | None
        Factory function if loading succeeds, None if loading fails (module not
        found, function not found, not callable, etc.). Failures are logged.

    Notes
    -----
    This helper defensively handles entry point loading failures. Import errors
    and validation failures are caught and logged, allowing discovery to continue
    with other entry points. Time complexity: O(1) for entry point loading.
    """
    try:
        factory = entry_point.load()
    except _FACTORY_ERRORS as exc:  # pragma: no cover - defensive logging
        LOGGER.warning(
            "channel.entry_point.load_failed",
            extra={"entry_point": entry_point.name, "error": repr(exc)},
        )
        return None
    return factory
