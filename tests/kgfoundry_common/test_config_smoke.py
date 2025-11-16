"""Smoke tests for configuration validation.

These tests verify that configuration fails fast with clear error messages when required fields are
missing or invalid.
"""

from __future__ import annotations

import base64

import pytest

from kgfoundry_common.config import AppSettings
from tests._helpers import assertions


def make_settings(**overrides: object) -> AppSettings:
    """Construct AppSettings using typed overrides.

    Parameters
    ----------
    **overrides : object
        Field overrides for AppSettings.

    Returns
    -------
    AppSettings
        Configured AppSettings instance.
    """
    overrides_dict: dict[str, object] = dict(overrides)
    app_settings_cls: type[AppSettings] = AppSettings
    return app_settings_cls.from_dict(overrides_dict)


class TestConfigurationValidation:
    """Test suite for AppSettings validation."""

    def test_valid_minimal_config(self) -> None:
        """Test that minimal valid configuration loads."""
        # Minimal config should work with defaults
        settings = make_settings()
        assertions.expect_equal(settings.log_level, "INFO")
        assertions.expect_equal(settings.log_format, "json")
        assertions.expect_equal(settings.subprocess_timeout, 300)
        assertions.expect_equal(settings.request_timeout, 30)

    def test_log_level_validation(self) -> None:
        """Test log level validation rejects invalid values."""
        with pytest.raises(ValueError, match="Invalid log level"):
            make_settings(log_level="INVALID")

    def test_log_level_case_insensitive(self) -> None:
        """Test log level accepts any case."""
        settings = make_settings(log_level="debug")
        assertions.expect_equal(settings.log_level, "DEBUG")

    def test_log_format_validation(self) -> None:
        """Test log format validation rejects invalid values."""
        with pytest.raises(ValueError, match="Invalid log format"):
            make_settings(log_format="invalid")

    def test_subprocess_timeout_validation(self) -> None:
        """Test subprocess timeout must be positive and within bounds."""
        # Too small
        with pytest.raises(ValueError, match="greater than or equal to 1"):
            make_settings(subprocess_timeout=0)

        # Too large
        with pytest.raises(ValueError, match="less than or equal to 3600"):
            make_settings(subprocess_timeout=3601)

        # Valid
        settings = make_settings(subprocess_timeout=300)
        assertions.expect_equal(settings.subprocess_timeout, 300)

    def test_request_timeout_validation(self) -> None:
        """Test request timeout must be positive and within bounds."""
        # Too small
        with pytest.raises(ValueError, match="greater than or equal to 1"):
            make_settings(request_timeout=0)

        # Too large
        with pytest.raises(ValueError, match="less than or equal to 3600"):
            make_settings(request_timeout=3601)

        # Valid
        settings = make_settings(request_timeout=30)
        assertions.expect_equal(settings.request_timeout, 30)


class TestSigningKeyValidation:
    """Test suite for signing key validation."""

    def test_signing_key_optional(self) -> None:
        """Test that signing key is optional."""
        settings = make_settings()
        assertions.expect_equal(settings.signing_key, None)

    def test_signing_key_cannot_be_empty(self) -> None:
        """Test that signing key cannot be empty string."""
        with pytest.raises(ValueError, match="cannot be empty"):
            make_settings(signing_key="")

    def test_signing_key_must_be_base64(self) -> None:
        """Test that signing key must be valid base64."""
        # Invalid base64 (too short, not properly formatted)
        with pytest.raises(ValueError, match="must be valid base64"):
            make_settings(signing_key="!!!invalid base64!!!")

    def test_signing_key_minimum_length(self) -> None:
        """Test that signing key must be at least 32 bytes when decoded."""
        # Create a 31-byte key (too short)
        short_key = base64.b64encode(b"x" * 31).decode()
        with pytest.raises(ValueError, match="must be ≥32 bytes"):
            make_settings(signing_key=short_key)

    def test_signing_key_valid(self) -> None:
        """Test that valid signing key is accepted."""
        # Create a 32-byte key (valid minimum)
        valid_key = base64.b64encode(b"x" * 32).decode()
        settings = make_settings(signing_key=valid_key)
        assertions.expect_equal(settings.signing_key, valid_key)

    @pytest.mark.parametrize(
        "timeout_value",
        [1, 30, 300, 3600],
    )
    def test_valid_timeout_values(self, timeout_value: int) -> None:
        """Test that valid timeout values are accepted."""
        settings = make_settings(
            subprocess_timeout=timeout_value,
            request_timeout=timeout_value,
        )
        assertions.expect_equal(settings.subprocess_timeout, timeout_value)
        assertions.expect_equal(settings.request_timeout, timeout_value)

    @pytest.mark.parametrize(
        "timeout_value",
        [-1, 0, 3601, 10000],
    )
    def test_invalid_timeout_values(self, timeout_value: int) -> None:
        """Test that invalid timeout values are rejected."""
        with pytest.raises(
            ValueError,
            match=r"(greater than or equal to 1|less than or equal to 3600)",
        ):
            make_settings(subprocess_timeout=timeout_value)

        with pytest.raises(
            ValueError,
            match=r"(greater than or equal to 1|less than or equal to 3600)",
        ):
            make_settings(request_timeout=timeout_value)


class TestConfigurationErrorMessages:
    """Test that error messages are clear and actionable."""

    def test_log_level_error_message_helpful(self) -> None:
        """Test that log level error message suggests valid options."""
        try:
            make_settings(log_level="TRACE")
        except ValueError as exc:
            error_msg = str(exc)
            # Should mention valid options
            assertions.expect_true(
                "DEBUG" in error_msg or "INFO" in error_msg,
                reason="error should mention valid options",
            )

    def test_signing_key_error_message_helpful(self) -> None:
        """Test that signing key error message guides remediation."""
        short_key = base64.b64encode(b"short").decode()
        try:
            make_settings(signing_key=short_key)
        except ValueError as exc:
            error_msg = str(exc)
            # Should mention length requirement
            assertions.expect_true(
                "32" in error_msg or "bytes" in error_msg,
                reason="error should mention length requirement",
            )
