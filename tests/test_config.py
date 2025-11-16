"""Tests for configuration management with pydantic_settings."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from kgfoundry_common.config import AppSettings, load_config
from tests._helpers import assertions


def test_defaults() -> None:
    """Test default configuration values."""
    # Clear any existing env vars
    os.environ.pop("LOG_LEVEL", None)
    os.environ.pop("LOG_FORMAT", None)

    # Load fresh config
    load_config(reload=True)
    settings = AppSettings()

    assertions.expect_equal(settings.log_level, "INFO")
    assertions.expect_equal(settings.log_format, "json")


def test_env_override() -> None:
    """Test environment variable overrides."""
    os.environ["LOG_LEVEL"] = "DEBUG"
    os.environ["LOG_FORMAT"] = "text"

    settings = AppSettings()

    assertions.expect_equal(settings.log_level, "DEBUG")
    assertions.expect_equal(settings.log_format, "text")

    # Cleanup
    os.environ.pop("LOG_LEVEL", None)
    os.environ.pop("LOG_FORMAT", None)


def test_case_insensitive() -> None:
    """Test that log level validation is case-insensitive."""
    os.environ["LOG_LEVEL"] = "debug"

    settings = AppSettings()

    assertions.expect_equal(settings.log_level, "DEBUG")

    # Cleanup
    os.environ.pop("LOG_LEVEL", None)


def test_invalid_log_level() -> None:
    """Test that invalid log level raises ValueError."""
    os.environ["LOG_LEVEL"] = "INVALID"

    with pytest.raises(ValueError, match="Invalid log level"):
        AppSettings()

    # Cleanup
    os.environ.pop("LOG_LEVEL", None)


def test_invalid_log_format() -> None:
    """Test that invalid log format raises ValueError."""
    os.environ["LOG_FORMAT"] = "xml"

    with pytest.raises(ValueError, match="Invalid log format"):
        AppSettings()

    # Cleanup
    os.environ.pop("LOG_FORMAT", None)


def test_frozen() -> None:
    """Test that AppSettings is frozen (immutable)."""
    settings = AppSettings()
    field_name = "log_level"
    with pytest.raises(ValidationError):
        setattr(settings, field_name, "WARNING")


def test_load_config_caching() -> None:
    """Test that load_config caches results."""
    # Clear cache and load fresh
    load_config(reload=True)
    config1 = load_config()
    config2 = load_config()

    # Should be the same object (cached)
    assertions.expect_true(config1 is config2, reason="load_config should cache results")


def test_load_config_reload() -> None:
    """Test that reload=True clears cache."""
    os.environ["LOG_LEVEL"] = "INFO"

    # Load and cache
    config1 = load_config(reload=True)
    assertions.expect_equal(config1.log_level, "INFO")

    # Change env var
    os.environ["LOG_LEVEL"] = "WARNING"

    # Without reload, should return cached config
    config2 = load_config(reload=False)
    assertions.expect_equal(config2.log_level, "INFO")

    # With reload, should get fresh config
    config3 = load_config(reload=True)
    assertions.expect_equal(config3.log_level, "WARNING")

    # Cleanup
    os.environ.pop("LOG_LEVEL", None)


@pytest.mark.parametrize(
    "log_level",
    [
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ],
)
def test_valid_log_levels(log_level: str) -> None:
    """Test all valid log levels."""
    os.environ["LOG_LEVEL"] = log_level

    settings = AppSettings()

    assertions.expect_equal(settings.log_level, log_level)

    # Cleanup
    os.environ.pop("LOG_LEVEL", None)


@pytest.mark.parametrize(
    "log_format",
    [
        "json",
        "text",
    ],
)
def test_valid_log_formats(log_format: str) -> None:
    """Test all valid log formats."""
    os.environ["LOG_FORMAT"] = log_format

    settings = AppSettings()

    assertions.expect_equal(settings.log_format, log_format)

    # Cleanup
    os.environ.pop("LOG_FORMAT", None)
