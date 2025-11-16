"""Tests for orchestration configuration models.

This module verifies that IndexCliConfig and ArtifactValidationConfig are correctly implemented with
proper defaults, immutability, and type safety.
"""

from __future__ import annotations

import tempfile

from orchestration.config import ArtifactValidationConfig, IndexCliConfig
from tests._helpers import assertions
from tests.helpers import assert_frozen_attribute


class TestIndexCliConfig:
    """Tests for IndexCliConfig dataclass."""

    def test_basic_construction(self) -> None:
        """Test basic construction with all required parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=f"{tmpdir}/index.idx",
                factory="Flat",
                metric="ip",
            )
            assertions.expect_equal(config.dense_vectors, "vectors.json")
            assertions.expect_equal(config.index_path, f"{tmpdir}/index.idx")
            assertions.expect_equal(config.factory, "Flat")
            assertions.expect_equal(config.metric, "ip")

    def test_custom_factory(self) -> None:
        """Test with custom FAISS factory string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=f"{tmpdir}/index.idx",
                factory="OPQ64,IVF8192,PQ64",
                metric="l2",
            )
            assertions.expect_equal(config.factory, "OPQ64,IVF8192,PQ64")
            assertions.expect_equal(config.metric, "l2")

    def test_immutability(self) -> None:
        """Test that IndexCliConfig is frozen."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=f"{tmpdir}/index.idx",
                factory="Flat",
                metric="ip",
            )
            assert_frozen_attribute(config, "dense_vectors", value="other.json")

    def test_equality(self) -> None:
        """Test equality comparison."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config1 = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=f"{tmpdir}/index.idx",
                factory="Flat",
                metric="ip",
            )
            config2 = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=f"{tmpdir}/index.idx",
                factory="Flat",
                metric="ip",
            )
            assertions.expect_equal(config1, config2)

    def test_inequality(self) -> None:
        """Test inequality comparison."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config1 = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=f"{tmpdir}/index.idx",
                factory="Flat",
                metric="ip",
            )
            config2 = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=f"{tmpdir}/index.idx",
                factory="Flat",
                metric="l2",
            )
            assertions.expect_true(config1 != config2, reason="should not be equal")


class TestArtifactValidationConfig:
    """Tests for ArtifactValidationConfig dataclass."""

    def test_default_construction(self) -> None:
        """Test construction with default values."""
        config = ArtifactValidationConfig()
        assertions.expect_true(config.strict_mode, reason="config.strict_mode should be True")
        assertions.expect_false(
            config.fail_on_warnings, reason="config.fail_on_warnings should be False"
        )

    def test_custom_construction(self) -> None:
        """Test construction with custom values."""
        config = ArtifactValidationConfig(
            strict_mode=False,
            fail_on_warnings=True,
        )
        assertions.expect_false(config.strict_mode, reason="config.strict_mode should be False")
        assertions.expect_true(
            config.fail_on_warnings, reason="config.fail_on_warnings should be True"
        )

    def test_partial_construction(self) -> None:
        """Test construction with partial overrides."""
        config = ArtifactValidationConfig(strict_mode=False)
        assertions.expect_false(config.strict_mode, reason="config.strict_mode should be False")
        assertions.expect_false(
            config.fail_on_warnings, reason="config.fail_on_warnings should be False"
        )

    def test_immutability(self) -> None:
        """Test that ArtifactValidationConfig is frozen."""
        config = ArtifactValidationConfig()
        assert_frozen_attribute(config, "strict_mode", value=False)

    def test_equality(self) -> None:
        """Test equality comparison."""
        config1 = ArtifactValidationConfig(strict_mode=True, fail_on_warnings=False)
        config2 = ArtifactValidationConfig(strict_mode=True, fail_on_warnings=False)
        assertions.expect_equal(config1, config2)

    def test_inequality(self) -> None:
        """Test inequality comparison."""
        config1 = ArtifactValidationConfig(strict_mode=True, fail_on_warnings=False)
        config2 = ArtifactValidationConfig(strict_mode=False, fail_on_warnings=False)
        assertions.expect_true(config1 != config2, reason="should not be equal")


class TestConfigComparison:
    """Tests for comparing different config types."""

    def test_different_types(self) -> None:
        """Test that different config types are distinct."""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_config = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=f"{tmpdir}/index.idx",
                factory="Flat",
                metric="ip",
            )
            validation_config = ArtifactValidationConfig()
            assertions.expect_true(
                isinstance(index_config, IndexCliConfig),
                reason="index_config should be IndexCliConfig",
            )
            assertions.expect_true(
                isinstance(validation_config, ArtifactValidationConfig),
                reason="validation_config should be ArtifactValidationConfig",
            )

    def test_attribute_presence(self) -> None:
        """Test that configs have expected attributes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_config = IndexCliConfig(
                dense_vectors="vectors.json",
                index_path=f"{tmpdir}/index.idx",
                factory="Flat",
                metric="ip",
            )
            assertions.expect_true(
                hasattr(index_config, "dense_vectors"), reason='should have "dense_vectors"'
            )
            assertions.expect_true(
                hasattr(index_config, "index_path"), reason='should have "index_path"'
            )
            assertions.expect_true(hasattr(index_config, "factory"), reason='should have "factory"')
            assertions.expect_true(hasattr(index_config, "metric"), reason='should have "metric"')

            validation_config = ArtifactValidationConfig()
            assertions.expect_true(
                hasattr(validation_config, "strict_mode"), reason='should have "strict_mode"'
            )
            assertions.expect_true(
                hasattr(validation_config, "fail_on_warnings"),
                reason='should have "fail_on_warnings"',
            )


class TestConfigDefaults:
    """Tests for default value semantics."""

    def test_artifact_validation_defaults(self) -> None:
        """Test ArtifactValidationConfig default values."""
        config1 = ArtifactValidationConfig()
        config2 = ArtifactValidationConfig()
        assertions.expect_equal(config1, config2)
        assertions.expect_true(config1.strict_mode, reason="config1.strict_mode should be True")
        assertions.expect_false(
            config1.fail_on_warnings, reason="config1.fail_on_warnings should be False"
        )

    def test_both_flags_false(self) -> None:
        """Test with both validation flags set to False."""
        config = ArtifactValidationConfig(strict_mode=False, fail_on_warnings=False)
        assertions.expect_false(config.strict_mode, reason="config.strict_mode should be False")
        assertions.expect_false(
            config.fail_on_warnings, reason="config.fail_on_warnings should be False"
        )

    def test_both_flags_true(self) -> None:
        """Test with both validation flags set to True."""
        config = ArtifactValidationConfig(strict_mode=True, fail_on_warnings=True)
        assertions.expect_true(config.strict_mode, reason="config.strict_mode should be True")
        assertions.expect_true(
            config.fail_on_warnings, reason="config.fail_on_warnings should be True"
        )
