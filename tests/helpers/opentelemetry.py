"""Helper utilities for loading OpenTelemetry test dependencies.

These helpers keep the test suite resilient to upstream OpenTelemetry layout
changes (e.g., class relocations between modules). They lazily import the
required modules and raise informative errors if the environment is missing the
necessary components so the caller can gracefully skip the associated tests.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, cast


def load_in_memory_span_exporter_type() -> type[Any]:
    """Return the OpenTelemetry in-memory span exporter class.

    Returns
    -------
    type[Any]
        ``InMemorySpanExporter`` class.

    Raises
    ------
    ImportError
        If OpenTelemetry is not installed.
    AttributeError
        If the exporter cannot be located (even after trying the fallback path).
    """
    # ``InMemorySpanExporter`` moved from ``opentelemetry.sdk.trace.export`` to
    # ``opentelemetry.sdk.trace.export.in_memory_span_exporter`` in newer OTel
    # releases. Try the legacy location first for backward compatibility.
    try:
        export_module = import_module("opentelemetry.sdk.trace.export")
    except ModuleNotFoundError as exc:
        msg = "OpenTelemetry is required for telemetry tests"
        raise ImportError(msg) from exc
    exporter = getattr(export_module, "InMemorySpanExporter", None)
    if exporter is None:
        try:
            in_memory_module = import_module("opentelemetry.sdk.trace.export.in_memory_span_exporter")
        except ModuleNotFoundError as exc:
            msg = "OpenTelemetry is required for telemetry tests"
            raise ImportError(msg) from exc
        exporter = getattr(in_memory_module, "InMemorySpanExporter", None)

    if exporter is None or not isinstance(exporter, type):
        msg = "OpenTelemetry InMemorySpanExporter class is unavailable"
        raise AttributeError(msg)
    return cast("type[Any]", exporter)


def load_simple_span_processor_type() -> type[Any]:
    """Return the OpenTelemetry SimpleSpanProcessor class.

    Returns
    -------
    type[Any]
        ``SimpleSpanProcessor`` class.

    Raises
    ------
    ImportError
        If OpenTelemetry is not installed.
    AttributeError
        If the class cannot be located (even after trying fallback paths).
    """
    try:
        export_module = import_module("opentelemetry.sdk.trace.export")
    except ModuleNotFoundError as exc:
        msg = "OpenTelemetry is required for telemetry tests"
        raise ImportError(msg) from exc
    processor = getattr(export_module, "SimpleSpanProcessor", None)
    if processor is None:
        try:
            simple_processor_module = import_module(
                "opentelemetry.sdk.trace.export.simple_span_processor"
            )
        except ModuleNotFoundError as exc:
            msg = "OpenTelemetry is required for telemetry tests"
            raise ImportError(msg) from exc
        processor = getattr(simple_processor_module, "SimpleSpanProcessor", None)

    if processor is None or not isinstance(processor, type):
        msg = "OpenTelemetry SimpleSpanProcessor class is unavailable"
        raise AttributeError(msg)
    return cast("type[Any]", processor)
