"""Typed plugin protocol definitions and compatibility adapters."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, TypeVar, cast, runtime_checkable

from kgfoundry_common.errors import KgFoundryError
from kgfoundry_common.errors.codes import ErrorCode
from tools.docstring_builder.harvest import HarvestResult
from tools.docstring_builder.schema import DocstringEdit
from tools.docstring_builder.semantics import SemanticResult

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tools.docstring_builder.config import BuilderConfig

PluginStage = Literal["harvester", "transformer", "formatter"]
type DocstringPayload = HarvestResult | SemanticResult | DocstringEdit

InputT_contra = TypeVar("InputT_contra", contravariant=True)
OutputT_co = TypeVar("OutputT_co", covariant=True)
T_Plugin_co = TypeVar("T_Plugin_co", covariant=True)


@dataclass(slots=True, frozen=True)
class PluginContext:
    """Context supplied to plugins when they execute."""

    config: BuilderConfig
    repo_root: Path
    file_path: Path | None = None


@runtime_checkable
class PluginFactory(Protocol[T_Plugin_co]):
    """Factory callable for creating plugin instances.

    Parameters
    ----------
    T_Plugin_co : TypeVar
        Type of plugin instance produced by the factory.

    Examples
    --------
    >>> from tools.docstring_builder.plugins.base import (
    ...     PluginFactory,
    ...     FormatterPlugin,
    ...     PluginContext,
    ... )
    >>> def my_formatter_factory() -> FormatterPlugin:
    ...     class MyFormatter:
    ...         name = "my-formatter"
    ...         stage = "formatter"
    ...
    ...         def on_start(self, context: PluginContext) -> None:
    ...             pass
    ...
    ...         def on_finish(self, context: PluginContext) -> None:
    ...             pass
    ...
    ...         def apply(self, context: PluginContext, payload):
    ...             return payload
    ...
    ...     return MyFormatter()
    """

    def __call__(self, **kwargs: object) -> T_Plugin_co:
        """Invoke the factory to create a new plugin instance.

        Parameters
        ----------
        **kwargs : object
            Keyword arguments passed to the plugin factory (ignored by default).

        Returns
        -------
        T_Plugin_co
            A concrete plugin instance.
        """
        ...


class PluginRegistryError(KgFoundryError):
    """Raised when plugin registration or validation fails.

    This exception is raised when a plugin cannot be registered or
    validated, typically due to incorrect plugin type or configuration
    issues.

    Initializes plugin registry error.

    Parameters
    ----------
    message : str
        Human-readable error message describing the failure.
    cause : Exception | None, optional
        The underlying exception that caused this error. Defaults to None.
    context : dict[str, object] | None, optional
        Additional context fields for Problem Details. Defaults to None.
    """

    def __init__(
        self,
        message: str,
        cause: Exception | None = None,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            message,
            code=ErrorCode.CONFIGURATION_ERROR,
            http_status=500,
            cause=cause,
            context=context or {},
        )


@runtime_checkable
class DocstringBuilderPlugin(Protocol[InputT_contra, OutputT_co]):
    """Generic protocol implemented by all docstring builder plugins.

    Implementations receive a :class:`PluginContext` and stage-specific
    payload type before returning an output payload. Plugins SHOULD raise
    :class:`~tools.docstring_builder.models.PluginExecutionError` (or allow the
    manager to wrap unexpected exceptions into that error) so failures surface
    RFC 9457 Problem Details responses consistent with
    ``schema/examples/tools/problem_details/tool-execution-error.json``.
    """

    name: str
    stage: PluginStage

    def on_start(self, context: PluginContext) -> None:
        """Run plugin-specific setup before execution begins."""
        ...

    def on_finish(self, context: PluginContext) -> None:
        """Perform teardown after plugin execution completes."""
        ...

    def apply(self, context: PluginContext, payload: InputT_contra) -> OutputT_co:
        """Execute the plugin for ``payload`` and return the processed object."""
        ...


@runtime_checkable
class HarvesterPlugin(DocstringBuilderPlugin[HarvestResult, HarvestResult], Protocol):
    """Plugins operating on harvested module metadata."""

    stage: PluginStage

    def apply(self, context: PluginContext, payload: HarvestResult) -> HarvestResult:
        """Transform harvested metadata before semantic analysis."""
        ...


@runtime_checkable
class TransformerPlugin(
    DocstringBuilderPlugin[SemanticResult, SemanticResult],
    Protocol,
):
    """Plugins refining semantic analysis results."""

    stage: PluginStage

    def apply(self, context: PluginContext, payload: SemanticResult) -> SemanticResult:
        """Mutate semantic results before rendering."""
        ...


@runtime_checkable
class FormatterPlugin(DocstringBuilderPlugin[DocstringEdit, DocstringEdit], Protocol):
    """Plugins adjusting rendered docstring edits."""

    stage: PluginStage

    def apply(self, context: PluginContext, payload: DocstringEdit) -> DocstringEdit:
        """Amend rendered docstring edits prior to writing."""
        ...


@runtime_checkable
class LegacyPluginProtocol(Protocol):
    """Legacy plugin signature prior to the typed ``apply`` API."""

    stage: PluginStage
    name: str

    def run(
        self, context: PluginContext, payload: DocstringPayload
    ) -> DocstringPayload:
        """Execute the legacy plugin implementation."""
        ...


class LegacyPluginAdapter(DocstringBuilderPlugin[DocstringPayload, DocstringPayload]):
    """Adapt legacy ``run`` plugins to the typed ``apply`` protocol.

    Attributes
    ----------
    name : str
        Plugin name.
    stage : PluginStage
        Plugin stage (harvester, transformer, or formatter).

    Parameters
    ----------
    plugin : LegacyPluginProtocol
        Legacy plugin instance to wrap.

    Raises
    ------
    TypeError
        If plugin stage is invalid or unsupported.
    """

    name: str
    stage: PluginStage

    def __init__(self, plugin: LegacyPluginProtocol) -> None:
        stage_candidate: object = getattr(plugin, "stage", None)
        valid_stages: dict[str, PluginStage] = {
            "harvester": "harvester",
            "transformer": "transformer",
            "formatter": "formatter",
        }
        if not isinstance(stage_candidate, str) or stage_candidate not in valid_stages:
            message = f"Unsupported legacy plugin stage: {stage_candidate!r}"
            raise TypeError(message)
        self.stage = valid_stages[stage_candidate]
        self._plugin = plugin
        self._warned = False
        name_attr: object = getattr(plugin, "name", None)
        resolved_name = (
            name_attr if isinstance(name_attr, str) else plugin.__class__.__name__
        )
        self.name = resolved_name

    @classmethod
    def create(cls, plugin: LegacyPluginProtocol, /, cls) -> _AnyLegacyAdapter:
        """Return a typed adapter for the legacy ``plugin`` instance.

        Parameters
        ----------
        plugin : LegacyPluginProtocol
            Legacy plugin instance to adapt.

        Returns
        -------
        _AnyLegacyAdapter
            Typed adapter instance (harvester, transformer, or formatter).
        """
        adapter = cls(plugin)
        if adapter.stage == "harvester":
            return cls.wrap_harvester(adapter)
        if adapter.stage == "transformer":
            return cls.wrap_transformer(adapter)
        return cls.wrap_formatter(adapter)

    @classmethod
    def wrap_harvester(
        cls, adapter: LegacyPluginAdapter, /, cls
    ) -> _LegacyHarvesterAdapter:
        """Wrap ``adapter`` as a harvester plugin.

        Parameters
        ----------
        adapter : LegacyPluginAdapter
            Base adapter instance.

        Returns
        -------
        _LegacyHarvesterAdapter
            Harvester adapter instance.

        Raises
        ------
        TypeError
            If adapter stage is not "harvester".
        """
        if adapter.stage != "harvester":
            message = f"Expected harvester plugin, received stage {adapter.stage!r}"
            raise TypeError(message)
        return _LegacyHarvesterAdapter(adapter)

    @classmethod
    def wrap_transformer(
        cls, adapter: LegacyPluginAdapter, /, cls
    ) -> _LegacyTransformerAdapter:
        """Wrap ``adapter`` as a transformer plugin.

        Parameters
        ----------
        adapter : LegacyPluginAdapter
            Base adapter instance.

        Returns
        -------
        _LegacyTransformerAdapter
            Transformer adapter instance.

        Raises
        ------
        TypeError
            If adapter stage is not "transformer".
        """
        if adapter.stage != "transformer":
            message = f"Expected transformer plugin, received stage {adapter.stage!r}"
            raise TypeError(message)
        return _LegacyTransformerAdapter(adapter)

    @classmethod
    def wrap_formatter(
        cls, adapter: LegacyPluginAdapter, /, cls
    ) -> _LegacyFormatterAdapter:
        """Wrap ``adapter`` as a formatter plugin.

        Parameters
        ----------
        adapter : LegacyPluginAdapter
            Base adapter instance.

        Returns
        -------
        _LegacyFormatterAdapter
            Formatter adapter instance.

        Raises
        ------
        TypeError
            If adapter stage is not "formatter".
        """
        if adapter.stage != "formatter":
            message = f"Expected formatter plugin, received stage {adapter.stage!r}"
            raise TypeError(message)
        return _LegacyFormatterAdapter(adapter)

    def on_start(self, context: PluginContext) -> None:
        """Invoke the legacy ``on_start`` hook if present."""
        hook: object = getattr(self._plugin, "on_start", None)
        if callable(hook):
            start_hook = cast("Callable[[PluginContext], object]", hook)
            start_hook(context)

    def on_finish(self, context: PluginContext) -> None:
        """Invoke the legacy ``on_finish`` hook if present."""
        hook: object = getattr(self._plugin, "on_finish", None)
        if callable(hook):
            finish_hook = cast("Callable[[PluginContext], object]", hook)
            finish_hook(context)

    def apply(
        self, context: PluginContext, payload: DocstringPayload
    ) -> DocstringPayload:
        """Delegate to the legacy ``run`` implementation with a warning.

        Parameters
        ----------
        context : PluginContext
            Plugin context.
        payload : DocstringPayload
            Payload to process.

        Returns
        -------
        DocstringPayload
            Processed payload from legacy plugin.
        """
        self._warn()
        return self._plugin.run(context, payload)

    def _warn(self) -> None:
        if self._warned:
            return
        warnings.warn(
            f"Plugin {self.name!r} uses the legacy run() API; update to apply().",
            DeprecationWarning,
            stacklevel=3,
        )
        self._warned = True


class _LegacyHarvesterAdapter(HarvesterPlugin):
    """Adapter that narrows ``apply`` to ``HarvestResult`` payloads.

    Attributes
    ----------
    stage : PluginStage
        Plugin stage, always "harvester".

    Parameters
    ----------
    adapter : LegacyPluginAdapter
        Base adapter instance.
    """

    stage: PluginStage = "harvester"

    def __init__(self, adapter: LegacyPluginAdapter) -> None:
        self._adapter = adapter
        self.name = adapter.name

    def on_start(self, context: PluginContext) -> None:
        """Invoke adapter's on_start hook.

        Parameters
        ----------
        context : PluginContext
            Plugin execution context.
        """
        self._adapter.on_start(context)

    def on_finish(self, context: PluginContext) -> None:
        """Invoke adapter's on_finish hook.

        Parameters
        ----------
        context : PluginContext
            Plugin execution context.
        """
        self._adapter.on_finish(context)

    def apply(self, context: PluginContext, payload: HarvestResult) -> HarvestResult:
        """Apply plugin transformation to payload.

        Parameters
        ----------
        context : PluginContext
            Plugin execution context.
        payload : HarvestResult
            Input harvest result.

        Returns
        -------
        HarvestResult
            Transformed harvest result.

        Raises
        ------
        TypeError
            If plugin returns incorrect type.
        """
        result = self._adapter.apply(context, payload)
        if not isinstance(result, HarvestResult):
            message = f"Legacy harvester {self.name!r} returned {type(result)!r}; expected HarvestResult"
            raise TypeError(message)
        return result


class _LegacyTransformerAdapter(TransformerPlugin):
    """Adapter that narrows ``apply`` to ``SemanticResult`` payloads.

    Attributes
    ----------
    stage : PluginStage
        Plugin stage, always "transformer".

    Parameters
    ----------
    adapter : LegacyPluginAdapter
        Base adapter instance.
    """

    stage: PluginStage = "transformer"

    def __init__(self, adapter: LegacyPluginAdapter) -> None:
        self._adapter = adapter
        self.name = adapter.name

    def on_start(self, context: PluginContext) -> None:
        """Invoke adapter's on_start hook.

        Parameters
        ----------
        context : PluginContext
            Plugin execution context.
        """
        self._adapter.on_start(context)

    def on_finish(self, context: PluginContext) -> None:
        """Invoke adapter's on_finish hook.

        Parameters
        ----------
        context : PluginContext
            Plugin execution context.
        """
        self._adapter.on_finish(context)

    def apply(self, context: PluginContext, payload: SemanticResult) -> SemanticResult:
        """Apply plugin transformation to payload.

        Parameters
        ----------
        context : PluginContext
            Plugin execution context.
        payload : SemanticResult
            Input semantic result.

        Returns
        -------
        SemanticResult
            Transformed semantic result.

        Raises
        ------
        TypeError
            If plugin returns incorrect type.
        """
        result = self._adapter.apply(context, payload)
        if not isinstance(result, SemanticResult):
            message = f"Legacy transformer {self.name!r} returned {type(result)!r}; expected SemanticResult"
            raise TypeError(message)
        return result


class _LegacyFormatterAdapter(FormatterPlugin):
    """Adapter that narrows ``apply`` to ``DocstringEdit`` payloads.

    Attributes
    ----------
    stage : PluginStage
        Plugin stage, always "formatter".

    Parameters
    ----------
    adapter : LegacyPluginAdapter
        Base adapter instance.
    """

    stage: PluginStage = "formatter"

    def __init__(self, adapter: LegacyPluginAdapter) -> None:
        self._adapter = adapter
        self.name = adapter.name

    def on_start(self, context: PluginContext) -> None:
        """Invoke adapter's on_start hook.

        Parameters
        ----------
        context : PluginContext
            Plugin execution context.
        """
        self._adapter.on_start(context)

    def on_finish(self, context: PluginContext) -> None:
        """Invoke adapter's on_finish hook.

        Parameters
        ----------
        context : PluginContext
            Plugin execution context.
        """
        self._adapter.on_finish(context)

    def apply(self, context: PluginContext, payload: DocstringEdit) -> DocstringEdit:
        """Apply plugin transformation to payload.

        Parameters
        ----------
        context : PluginContext
            Plugin execution context.
        payload : DocstringEdit
            Input docstring edit.

        Returns
        -------
        DocstringEdit
            Transformed docstring edit.

        Raises
        ------
        TypeError
            If plugin returns incorrect type.
        """
        result = self._adapter.apply(context, payload)
        if not isinstance(result, DocstringEdit):
            message = f"Legacy formatter {self.name!r} returned {type(result)!r}; expected DocstringEdit"
            raise TypeError(message)
        return result


type _AnyLegacyAdapter = (
    LegacyPluginAdapter
    | _LegacyHarvesterAdapter
    | _LegacyTransformerAdapter
    | _LegacyFormatterAdapter
)

__all__ = [
    "DocstringBuilderPlugin",
    "DocstringPayload",
    "FormatterPlugin",
    "HarvesterPlugin",
    "InputT_contra",
    "LegacyPluginAdapter",
    "LegacyPluginProtocol",
    "OutputT_co",
    "PluginContext",
    "PluginFactory",
    "PluginRegistryError",
    "PluginStage",
    "T_Plugin_co",
    "TransformerPlugin",
]
