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

        Returns
        -------
        ChannelRegistry
            Registry containing every channel whose factory loaded successfully.
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

        Returns
        -------
        ChannelRegistry
            Registry containing the provided channel sequence.
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

    Returns
    -------
    Callable[[ChannelContext], Channel] | None
        Factory callable when loading succeeds, otherwise ``None``.
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
