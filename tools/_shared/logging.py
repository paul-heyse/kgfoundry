"""Shared logging adapters built on :mod:`kgfoundry_common.logging`.

This module keeps the historical ``tools._shared.logging`` import surface alive
without depending on GPU-era logging helpers. It re-exports the structured
logging utilities from :mod:`kgfoundry_common.logging` so existing tooling can
continue to call ``get_logger`` and ``with_fields``.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

from kgfoundry_common.logging import LoggerAdapter as StructuredLoggerAdapter
from kgfoundry_common.logging import get_logger as _get_logger
from kgfoundry_common.logging import with_fields as _with_fields

LogValue = str | int | float | bool | None

__all__ = [
    "LogValue",
    "StructuredLoggerAdapter",
    "get_logger",
    "with_fields",
]


def get_logger(name: str) -> StructuredLoggerAdapter:
    """Return a structured logger adapter scoped to ``name``.

    Parameters
    ----------
    name : str
        Logger name to use for the underlying stdlib logger.

    Returns
    -------
    StructuredLoggerAdapter
        Adapter that emits JSON logs compatible with kgfoundry_common conventions.
    """
    return _get_logger(name)


def with_fields(
    logger: StructuredLoggerAdapter,
    **fields: LogValue,
) -> AbstractContextManager[StructuredLoggerAdapter]:
    """Bind structured fields to ``logger`` within a context manager.

    Parameters
    ----------
    logger : StructuredLoggerAdapter
        Logger to wrap.
    **fields : LogValue
        Structured key/value pairs to inject for the duration of the context.

    Returns
    -------
    AbstractContextManager[StructuredLoggerAdapter]
        Context manager yielding a logger adapter with the provided fields applied.
    """
    return _with_fields(logger, **fields)
