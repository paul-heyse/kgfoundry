"""Tests for plugin registry factory validation and error handling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast

import pytest
from tools.docstring_builder.config import BuilderConfig
from tools.docstring_builder.plugins import (
    load_plugins,
)
from tools.docstring_builder.plugins.base import (
    PluginFactory,
    PluginRegistryError,
    TransformerPlugin,
)
from tools.docstring_builder.plugins.dataclass_fields import DataclassFieldDocPlugin

from kgfoundry_common.errors import KgFoundryError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


def expect_context(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        message = "Expected error context to be populated"
        raise AssertionError(message)
    return value


class TestPluginRegistryError:
    """Test PluginRegistryError behavior."""

    def test_is_kgfoundry_error(self) -> None:
        """PluginRegistryError is a KgFoundryError."""
        error = PluginRegistryError("test error")
        assert isinstance(error, KgFoundryError)

    def test_includes_context(self) -> None:
        """PluginRegistryError includes context fields."""
        error = PluginRegistryError(
            "Registration failed",
            context={"plugin_name": "test", "stage": "formatter"},
        )
        context = expect_context(error.context)
        assert context["plugin_name"] == "test"
        assert context["stage"] == "formatter"

    def test_has_problem_details(self) -> None:
        """PluginRegistryError can be converted to Problem Details."""
        error = PluginRegistryError("test error", context={"stage": "formatter"})
        details = error.to_problem_details(instance="/api/plugins/test")
        # Cast to ensure all fields are present
        assert (
            cast("str", details.get("type")) == "https://kgfoundry.dev/problems/configuration-error"
        )
        assert cast("int", details.get("status")) == 500
        assert cast("str", details.get("detail")) == "test error"
        assert cast("str", details.get("instance")) == "/api/plugins/test"

    def test_with_cause(self) -> None:
        """PluginRegistryError preserves cause chain."""
        cause = ValueError("underlying issue")
        error = PluginRegistryError("Plugin error", cause=cause)
        assert error.__cause__ is cause


class TestPluginFactory:
    """Test PluginFactory Protocol behavior."""

    def test_concrete_class_is_factory(self) -> None:
        """Concrete plugin class satisfies PluginFactory."""
        assert isinstance(DataclassFieldDocPlugin, PluginFactory)

    def test_factory_callable(self) -> None:
        """Factory can be invoked to create plugin instance."""
        plugin = DataclassFieldDocPlugin()
        assert isinstance(plugin, TransformerPlugin)
        assert plugin.name == "dataclass_field_docs"
        assert plugin.stage == "transformer"


class TestBuiltInPlugins:
    """Test built-in plugins work as factories."""

    def test_builtin_plugins_load(self, tmp_path: Path) -> None:
        """Built-in plugins load without errors."""
        config = BuilderConfig()
        manager = load_plugins(config, tmp_path)

        # Check that built-in plugins are available
        assert "dataclass_field_docs" in manager.available
        assert "llm_summary_rewriter" in manager.available
        assert "normalize_numpy_params" in manager.available

    def test_builtin_plugins_registered(self, tmp_path: Path) -> None:
        """Built-in plugins are registered in correct stages."""
        config = BuilderConfig()
        manager = load_plugins(config, tmp_path)

        # All built-in plugins are transformers
        assert len(manager.transformers) == 3
        assert len(manager.harvesters) == 0
        assert len(manager.formatters) == 0

        # Check names
        plugin_names = {p.name for p in manager.transformers}
        assert plugin_names == {
            "dataclass_field_docs",
            "llm_summary_rewriter",
            "normalize_numpy_params",
        }

    def test_disabled_plugins_excluded(self, tmp_path: Path) -> None:
        """Disabled plugins are excluded from registration."""
        config = BuilderConfig()
        manager = load_plugins(
            config,
            tmp_path,
            disable=["dataclass_field_docs"],
        )

        # One plugin should be disabled
        assert "dataclass_field_docs" in manager.disabled
        assert len(manager.transformers) == 2

        names = {p.name for p in manager.transformers}
        assert "dataclass_field_docs" not in names


class TestPluginValidation:
    """Test plugin registry validation."""

    def test_rejects_protocol_class(self, tmp_path: Path) -> None:
        """Registry rejects Protocol classes."""
        config = BuilderConfig()

        class MyProtocol(Protocol):
            """A protocol (not allowed)."""

            name: str
            stage: str

        # This should fail because MyProtocol is a Protocol
        with pytest.raises(PluginRegistryError):
            load_plugins(
                config,
                tmp_path,
                builtin=cast("Sequence[Any]", [MyProtocol]),
            )

    def test_accepts_concrete_class(self, tmp_path: Path) -> None:
        """Registry accepts concrete plugin classes."""
        config = BuilderConfig()

        # DataclassFieldDocPlugin is concrete - should work
        manager = load_plugins(
            config,
            tmp_path,
            builtin=cast("Sequence[Any]", [DataclassFieldDocPlugin]),
        )

        assert len(manager.transformers) == 1
        assert manager.transformers[0].name == "dataclass_field_docs"


class TestPluginStageDetection:
    """Test plugin stage detection and routing."""

    def test_transformers_stage(self, tmp_path: Path) -> None:
        """Transformer plugins go to transformers list."""
        config = BuilderConfig()
        manager = load_plugins(config, tmp_path)

        for plugin in manager.transformers:
            assert plugin.stage == "transformer"

    def test_enabled_plugins_list(self, tmp_path: Path) -> None:
        """enabled_plugins returns correct order."""
        config = BuilderConfig()
        manager = load_plugins(config, tmp_path)

        names = manager.enabled_plugins()
        assert len(names) == 3
        assert all(isinstance(name, str) for name in names)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
