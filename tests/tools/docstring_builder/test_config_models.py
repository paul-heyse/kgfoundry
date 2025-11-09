"""Unit tests for docstring builder configuration models.

This test module verifies that all configuration objects:
1. Load with correct defaults
2. Validate constraints in __post_init__
3. Raise ConfigurationError for invalid values
4. Detect conflicting flag combinations
"""

from __future__ import annotations

import pytest
from tools.docstring_builder.config_models import (
    CachePolicy,
    DocstringApplyConfig,
    DocstringBuildConfig,
    FileProcessConfig,
)

from kgfoundry_common.errors import ConfigurationError
from tests.helpers import assert_frozen_attribute


class TestCachePolicy:
    """Tests for CachePolicy enum."""

    def test_cache_policy_values(self) -> None:
        """Verify all cache policy values are defined."""
        assert CachePolicy.READ_ONLY.value == "read_only"
        assert CachePolicy.WRITE_ONLY.value == "write_only"
        assert CachePolicy.READ_WRITE.value == "read_write"
        assert CachePolicy.DISABLED.value == "disabled"

    def test_cache_policy_from_string(self) -> None:
        """Verify we can look up cache policy by value."""
        policy = CachePolicy("read_write")
        assert policy == CachePolicy.READ_WRITE


class TestDocstringBuildConfig:
    """Tests for DocstringBuildConfig."""

    def test_defaults(self) -> None:
        """Verify default configuration values."""
        config = DocstringBuildConfig()
        assert config.cache_policy == CachePolicy.READ_WRITE
        assert config.enable_plugins is True
        assert config.emit_diff is False
        assert config.timeout_seconds == 600
        assert config.dynamic_probes is False
        assert config.normalize_sections is False

    def test_custom_values(self) -> None:
        """Verify we can set custom values."""
        config = DocstringBuildConfig(
            cache_policy=CachePolicy.READ_ONLY,
            enable_plugins=True,  # Required when emit_diff=True
            emit_diff=True,
            timeout_seconds=300,
            dynamic_probes=True,
            normalize_sections=True,
        )
        assert config.cache_policy == CachePolicy.READ_ONLY
        assert config.enable_plugins is True
        assert config.emit_diff is True
        assert config.timeout_seconds == 300
        assert config.dynamic_probes is True
        assert config.normalize_sections is True

    def test_timeout_must_be_positive(self) -> None:
        """Verify negative timeout raises ConfigurationError."""
        with pytest.raises(
            ConfigurationError, match="timeout_seconds must be positive"
        ):
            DocstringBuildConfig(timeout_seconds=-1)

    def test_timeout_zero_invalid(self) -> None:
        """Verify zero timeout raises ConfigurationError."""
        with pytest.raises(
            ConfigurationError, match="timeout_seconds must be positive"
        ):
            DocstringBuildConfig(timeout_seconds=0)

    def test_emit_diff_requires_plugins(self) -> None:
        """Verify emit_diff=True requires enable_plugins=True."""
        with pytest.raises(
            ConfigurationError, match="emit_diff requires enable_plugins=True"
        ):
            DocstringBuildConfig(emit_diff=True, enable_plugins=False)

    def test_emit_diff_allowed_with_plugins(self) -> None:
        """Verify emit_diff=True works when plugins are enabled."""
        config = DocstringBuildConfig(emit_diff=True, enable_plugins=True)
        assert config.emit_diff is True
        assert config.enable_plugins is True

    def test_config_is_frozen(self) -> None:
        """Verify configuration dataclass is frozen."""
        config = DocstringBuildConfig()
        assert_frozen_attribute(config, "emit_diff", value=False)

    @pytest.mark.parametrize(
        "cache_policy",
        [
            CachePolicy.READ_ONLY,
            CachePolicy.WRITE_ONLY,
            CachePolicy.READ_WRITE,
            CachePolicy.DISABLED,
        ],
    )
    def test_all_cache_policies_accepted(self, cache_policy: CachePolicy) -> None:
        """Verify all cache policies are valid."""
        config = DocstringBuildConfig(cache_policy=cache_policy)
        assert config.cache_policy == cache_policy


class TestFileProcessConfig:
    """Tests for FileProcessConfig."""

    def test_defaults(self) -> None:
        """Verify default file process configuration values."""
        config = FileProcessConfig()
        assert config.skip_existing is False
        assert config.skip_cache is False
        assert config.max_errors_per_file == 10

    def test_custom_values(self) -> None:
        """Verify we can set custom file process values."""
        config = FileProcessConfig(
            skip_existing=True,
            skip_cache=True,
            max_errors_per_file=5,
        )
        assert config.skip_existing is True
        assert config.skip_cache is True
        assert config.max_errors_per_file == 5

    def test_max_errors_must_be_positive(self) -> None:
        """Verify non-positive max_errors_per_file raises ConfigurationError."""
        with pytest.raises(
            ConfigurationError, match="max_errors_per_file must be positive"
        ):
            FileProcessConfig(max_errors_per_file=-1)

    def test_max_errors_zero_invalid(self) -> None:
        """Verify zero max_errors_per_file raises ConfigurationError."""
        with pytest.raises(
            ConfigurationError, match="max_errors_per_file must be positive"
        ):
            FileProcessConfig(max_errors_per_file=0)

    def test_config_is_frozen(self) -> None:
        """Verify file process config is immutable."""
        config = FileProcessConfig()
        assert_frozen_attribute(config, "max_errors_per_file", value=20)

    @pytest.mark.parametrize("max_errors", [1, 5, 10, 100])
    def test_positive_max_errors_accepted(self, max_errors: int) -> None:
        """Verify all positive max_errors values are valid."""
        config = FileProcessConfig(max_errors_per_file=max_errors)
        assert config.max_errors_per_file == max_errors


class TestDocstringApplyConfig:
    """Tests for DocstringApplyConfig."""

    def test_defaults(self) -> None:
        """Verify default apply configuration values."""
        config = DocstringApplyConfig()
        assert config.write_changes is True
        assert config.create_backups is True
        assert config.atomic_writes is True

    def test_custom_values(self) -> None:
        """Verify we can set custom apply values."""
        config = DocstringApplyConfig(
            write_changes=False,
            create_backups=False,
            atomic_writes=False,
        )
        assert config.write_changes is False
        assert config.create_backups is False
        assert config.atomic_writes is False

    def test_atomic_writes_requires_write_changes(self) -> None:
        """Verify atomic_writes=True requires write_changes=True."""
        with pytest.raises(
            ConfigurationError, match="atomic_writes requires write_changes=True"
        ):
            DocstringApplyConfig(atomic_writes=True, write_changes=False)

    def test_atomic_writes_allowed_when_writing(self) -> None:
        """Verify atomic_writes=True works when write_changes=True."""
        config = DocstringApplyConfig(atomic_writes=True, write_changes=True)
        assert config.atomic_writes is True
        assert config.write_changes is True

    def test_dry_run_mode(self) -> None:
        """Verify dry-run configuration (write_changes=False)."""
        config = DocstringApplyConfig(
            write_changes=False,
            atomic_writes=False,  # Cannot use atomic with dry-run
        )
        assert config.write_changes is False
        assert config.create_backups is True  # Default still applies
        assert config.atomic_writes is False  # Cannot use atomic with dry-run

    def test_config_is_frozen(self) -> None:
        """Verify apply config is immutable."""
        config = DocstringApplyConfig()
        assert_frozen_attribute(config, "write_changes", value=False)


class TestConfigurationErrorContext:
    """Tests for ConfigurationError context tracking."""

    def test_build_config_error_includes_context(self) -> None:
        """Verify ConfigurationError includes context on validation failure."""
        with pytest.raises(
            ConfigurationError, match="timeout_seconds must be positive"
        ):
            DocstringBuildConfig(timeout_seconds=-1)

    def test_conflict_error_includes_conflicting_fields(self) -> None:
        """Verify conflict errors identify the conflicting fields."""
        with pytest.raises(
            ConfigurationError, match="emit_diff requires enable_plugins=True"
        ):
            DocstringBuildConfig(emit_diff=True, enable_plugins=False)
