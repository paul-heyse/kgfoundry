"""Tests for the optional MkDocs D2 plugin wrapper."""

from __future__ import annotations

import logging

import pytest
from tools.mkdocs_suite.plugins import optional_d2


def test_logger_uses_null_handler() -> None:
    """Ensure the optional D2 plugin logger installs a ``NullHandler``."""
    assert any(isinstance(handler, logging.NullHandler) for handler in optional_d2.LOGGER.handlers)


def test_missing_dependency_warning_requires_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Surface warnings only when a real handler is registered."""
    message = "mkdocs-d2-plugin is not installed; skipping D2 diagram rendering."
    monkeypatch.setattr(optional_d2, "D2Plugin", None)

    plugin_without_handler = optional_d2.OptionalD2Plugin()
    errors, warnings = plugin_without_handler.load_config({}, None)

    assert list(errors) == []
    assert list(warnings) == [message]

    records: list[str] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = Collector()
    handler.setLevel(logging.WARNING)
    optional_d2.LOGGER.addHandler(handler)

    try:
        plugin_with_handler = optional_d2.OptionalD2Plugin()
        _, warnings_with_handler = plugin_with_handler.load_config({}, None)
    finally:
        optional_d2.LOGGER.removeHandler(handler)

    assert list(warnings_with_handler) == [message]
    assert records == [message]
