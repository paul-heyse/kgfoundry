"""Plugin discovery and execution helpers for the docstring builder."""

from __future__ import annotations

import inspect
import logging
import threading
import typing as t
from dataclasses import dataclass, field
from importlib import metadata
from inspect import isclass
from typing import TYPE_CHECKING, TypeGuard, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
else:
    Callable = t.Callable
    Iterable = t.Iterable
    Sequence = t.Sequence

from tools._shared.logging import get_logger
from tools.docstring_builder.models import (
    DocstringBuilderError,
    PluginExecutionError,
)
from tools.docstring_builder.plugins._inspection import (
    get_signature,
    has_required_parameters,
)
from tools.docstring_builder.plugins.base import (
    DocstringBuilderPlugin,
    DocstringPayload,
    FormatterPlugin,
    HarvesterPlugin,
    LegacyPluginAdapter,
    LegacyPluginProtocol,
    PluginContext,
    PluginFactory,
    PluginRegistryError,
    TransformerPlugin,
)
from tools.docstring_builder.plugins.dataclass_fields import DataclassFieldDocPlugin
from tools.docstring_builder.plugins.llm_summary import LLMSummaryRewritePlugin
from tools.docstring_builder.plugins.normalize_numpy_params import (
    NormalizeNumpyParamsPlugin,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tools.docstring_builder.config import BuilderConfig
    from tools.docstring_builder.harvest import HarvestResult
    from tools.docstring_builder.plugins._inspection import InspectableCallable
    from tools.docstring_builder.plugins.base import PluginStage
    from tools.docstring_builder.schema import DocstringEdit
    from tools.docstring_builder.semantics import SemanticResult

ENTRY_POINT_GROUP = "kgfoundry.docstrings.plugins"

logging.getLogger(__name__).addHandler(logging.NullHandler())
_LOGGER = get_logger(__name__)

PayloadT = TypeVar("PayloadT")
ResultT = TypeVar("ResultT")

type PluginInstance = DocstringBuilderPlugin[t.Any, t.Any] | LegacyPluginProtocol
type PluginFactoryCandidateT = PluginFactory[PluginInstance] | Callable[[], PluginInstance]
type RegisteredPlugin = HarvesterPlugin | TransformerPlugin | FormatterPlugin | LegacyPluginAdapter


def _empty_harvester_list() -> list[HarvesterPlugin]:
    return []


def _empty_transformer_list() -> list[TransformerPlugin]:
    return []


def _empty_formatter_list() -> list[FormatterPlugin]:
    return []


def _empty_str_list() -> list[str]:
    return []


_PLUGIN_RUNTIME_ERRORS: tuple[type[Exception], ...] = (
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
    KeyError,
)

_PLUGIN_CONFIGURATION_ERRORS: tuple[type[Exception], ...] = (
    ImportError,
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
    KeyError,
    DocstringBuilderError,
)


class PluginConfigurationError(DocstringBuilderError):
    """Raised when plugin discovery or filtering fails."""


def _extract_stage(source: object, default: str | None = "unknown") -> str | None:
    stage_attr: object = getattr(source, "stage", default)
    if isinstance(stage_attr, str):
        return stage_attr
    return default


@dataclass(slots=True, frozen=True)
class PluginManager:
    """Coordinate plugin execution across builder stages."""

    config: BuilderConfig
    repo_root: Path
    harvesters: list[HarvesterPlugin] = field(default_factory=_empty_harvester_list)
    transformers: list[TransformerPlugin] = field(default_factory=_empty_transformer_list)
    formatters: list[FormatterPlugin] = field(default_factory=_empty_formatter_list)
    available: list[str] = field(default_factory=_empty_str_list)
    disabled: list[str] = field(default_factory=_empty_str_list)
    skipped: list[str] = field(default_factory=_empty_str_list)

    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def _context(self, file_path: Path | None = None) -> PluginContext:
        return PluginContext(config=self.config, repo_root=self.repo_root, file_path=file_path)

    def start(self) -> None:
        """Invoke ``on_start`` for all registered plugins."""
        context = self._context()
        with self._lock:
            for plugin in self._iter_plugins():
                plugin.on_start(context)

    def finish(self) -> None:
        """Invoke ``on_finish`` for registered plugins in reverse order."""
        context = self._context()
        with self._lock:
            for plugin in reversed(list(self._iter_plugins())):
                plugin.on_finish(context)

    def apply_harvest(self, file_path: Path, result: HarvestResult) -> HarvestResult:
        """Run harvester plugins sequentially.

        Parameters
        ----------
        file_path : Path
            File path being processed.
        result : HarvestResult
            Harvest result to process.

        Returns
        -------
        HarvestResult
            Processed harvest result after applying all harvester plugins.
        """
        context = self._context(file_path)
        with self._lock:
            return _run_harvest_pipeline(self.harvesters, context, result)

    def apply_transformers(
        self, file_path: Path, semantics: Iterable[SemanticResult]
    ) -> list[SemanticResult]:
        """Run transformer plugins sequentially for each semantic result.

        Parameters
        ----------
        file_path : Path
            File path being processed.
        semantics : Iterable[SemanticResult]
            Semantic results to transform.

        Returns
        -------
        list[SemanticResult]
            Transformed semantic results after applying all transformer plugins.
        """
        context = self._context(file_path)
        processed: list[SemanticResult] = []
        for entry in semantics:
            with self._lock:
                processed.append(_run_transformer_pipeline(self.transformers, context, entry))
        return processed

    def apply_formatters(
        self, file_path: Path, edits: Iterable[DocstringEdit]
    ) -> list[DocstringEdit]:
        """Run formatter plugins sequentially for each edit.

        Parameters
        ----------
        file_path : Path
            File path being processed.
        edits : Iterable[DocstringEdit]
            Docstring edits to format.

        Returns
        -------
        list[DocstringEdit]
            Formatted docstring edits after applying all formatter plugins.
        """
        context = self._context(file_path)
        processed: list[DocstringEdit] = []
        for entry in edits:
            with self._lock:
                processed.append(_run_formatter_pipeline(self.formatters, context, entry))
        return processed

    def enabled_plugins(self) -> list[str]:
        """Return the names of active plugins in execution order.

        Returns
        -------
        list[str]
            List of plugin names in execution order.
        """
        return [plugin.name for plugin in self._iter_plugins()]

    def _iter_plugins(self) -> Iterable[RegisteredPlugin]:
        """Yield all registered plugins in execution order.

        Yields
        ------
        RegisteredPlugin
            Registered plugin instances.
        """
        yield from self.harvesters
        yield from self.transformers
        yield from self.formatters


def _run_harvest_pipeline(
    plugins: Iterable[HarvesterPlugin],
    context: PluginContext,
    payload: HarvestResult,
) -> HarvestResult:
    """Execute harvester plugins sequentially for ``payload``.

    Parameters
    ----------
    plugins : Iterable[HarvesterPlugin]
        Harvester plugins to execute.
    context : PluginContext
        Plugin context.
    payload : HarvestResult
        Harvest result to process.

    Returns
    -------
    HarvestResult
        Processed harvest result.
    """
    result = payload
    for plugin in plugins:
        result = _invoke_apply(plugin, context, result)
    return result


def _run_transformer_pipeline(
    plugins: Iterable[TransformerPlugin],
    context: PluginContext,
    payload: SemanticResult,
) -> SemanticResult:
    """Execute transformer plugins sequentially for ``payload``.

    Parameters
    ----------
    plugins : Iterable[TransformerPlugin]
        Transformer plugins to execute.
    context : PluginContext
        Plugin context.
    payload : SemanticResult
        Semantic result to transform.

    Returns
    -------
    SemanticResult
        Transformed semantic result.
    """
    result = payload
    for plugin in plugins:
        result = _invoke_apply(plugin, context, result)
    return result


def _run_formatter_pipeline(
    plugins: Iterable[FormatterPlugin],
    context: PluginContext,
    payload: DocstringEdit,
) -> DocstringEdit:
    """Execute formatter plugins sequentially for ``payload``.

    Parameters
    ----------
    plugins : Iterable[FormatterPlugin]
        Formatter plugins to execute.
    context : PluginContext
        Plugin context.
    payload : DocstringEdit
        Docstring edit to format.

    Returns
    -------
    DocstringEdit
        Formatted docstring edit.
    """
    result = payload
    for plugin in plugins:
        result = _invoke_apply(plugin, context, result)
    return result


def _invoke_apply(
    plugin: DocstringBuilderPlugin[PayloadT, ResultT],
    context: PluginContext,
    payload: PayloadT,
) -> ResultT:
    """Invoke ``plugin.apply`` with structured error reporting.

    Parameters
    ----------
    plugin : DocstringBuilderPlugin[PayloadT, ResultT]
        Plugin instance to invoke.
    context : PluginContext
        Plugin context.
    payload : PayloadT
        Payload to process.

    Returns
    -------
    ResultT
        Result from plugin application.

    Raises
    ------
    DocstringBuilderError
        Propagated if plugin raises a DocstringBuilderError.
    PluginExecutionError
        If plugin raises a runtime error during execution.
    """
    try:
        return plugin.apply(context, payload)
    except DocstringBuilderError:
        raise
    except _PLUGIN_RUNTIME_ERRORS as exc:  # pragma: no cover - defensive guard
        message = f"Plugin {plugin.name!r} failed during {plugin.stage} execution"
        file_path = str(context.file_path) if context.file_path is not None else None
        _LOGGER.exception(
            "Plugin execution failed",
            extra={
                "operation": "docstring_builder.plugins",
                "status": "error",
                "plugin": plugin.name,
                "stage": plugin.stage,
                "file_path": file_path,
            },
        )
        raise PluginExecutionError(message) from exc


def _validate_factory_signature(
    factory: object,
    name: str,
    stage: PluginStage,
) -> None:
    """Validate that factory is a callable with no required parameters.

    Parameters
    ----------
    factory : object
        The factory candidate to validate.
    name : str
        The plugin name for error reporting.
    stage : PluginStage
        The plugin stage for error reporting.

    Raises
    ------
    PluginRegistryError
        If factory is not callable or has required parameters.
    """
    if not callable(factory):
        msg = f"Plugin factory {name!r} must be callable"
        raise PluginRegistryError(
            msg,
            context={
                "plugin_name": name,
                "stage": stage,
                "reason": "not-callable",
            },
        ) from None

    # Validate signature using typed inspection module
    _validate_callable_signature(factory, name, stage)


def _validate_callable_signature(
    factory: object,
    name: str,
    stage: PluginStage,
) -> None:
    """Validate a callable's signature has no required parameters.

    Parameters
    ----------
    factory : object
        The factory callable (must already be checked as callable).
    name : str
        The plugin name for error reporting.
    stage : PluginStage
        The plugin stage for error reporting.

    Raises
    ------
    PluginRegistryError
        If the callable has required parameters.
    """
    # Use typed inspection module instead of raw inspect
    has_required_params: bool
    try:
        callable_factory = cast("InspectableCallable", factory)
        has_required_params = has_required_parameters(callable_factory)
    except (ValueError, TypeError) as exc:
        msg = f"Could not inspect factory signature for {name!r}"
        raise PluginRegistryError(
            msg,
            cause=exc,
            context={
                "plugin_name": name,
                "stage": stage,
                "reason": "signature-inspection-failed",
            },
        ) from exc

    if has_required_params:
        msg = f"Plugin factory {name!r} has required parameters"
        raise PluginRegistryError(
            msg,
            context={
                "plugin_name": name,
                "stage": stage,
                "reason": "required-parameters",
            },
        )


def _is_protocol_class(candidate: object) -> bool:
    """Check if candidate is a Protocol class.

    Parameters
    ----------
    candidate : object
        The object to check.

    Returns
    -------
    bool
        True if candidate is a Protocol class.
    """
    if not inspect.isclass(candidate):
        return False
    type_candidate = cast("type[object]", candidate)
    protocol_flag_attr: object = getattr(type_candidate, "_is_protocol", False)
    return bool(protocol_flag_attr)


def _is_abstract_class(candidate: object) -> bool:
    """Check if candidate is an abstract base class.

    Parameters
    ----------
    candidate : object
        The object to check.

    Returns
    -------
    bool
        True if candidate is abstract.
    """
    if not inspect.isclass(candidate):
        return False
    type_candidate = cast("type[object]", candidate)
    abstract_methods: object | None = getattr(type_candidate, "__abstractmethods__", None)
    return bool(abstract_methods)


def _instantiate_plugin_from_factory(
    factory: PluginFactoryCandidateT,
    name: str,
    stage: PluginStage,
) -> PluginInstance:
    """Invoke factory to create a plugin instance, with validation.

    Parameters
    ----------
    factory : PluginFactoryCandidateT
        The factory callable.
    name : str
        The plugin name.
    stage : PluginStage
        The plugin stage.

    Returns
    -------
    PluginInstance
        A concrete plugin instance.

    Raises
    ------
    PluginRegistryError
        If factory invocation fails or factory is invalid.
    """
    # Validate factory before invoking
    _validate_factory_signature(factory, name, stage)

    try:
        instance = factory()
    except _PLUGIN_CONFIGURATION_ERRORS as exc:
        message = f"Failed to invoke factory for plugin {name!r}"
        raise PluginRegistryError(
            message,
            cause=exc,
            context={
                "plugin_name": name,
                "stage": stage,
                "reason": "factory-invocation-failed",
            },
        ) from exc

    return instance


def _resolve_factory(candidate: object) -> PluginFactoryCandidateT:
    """Resolve a candidate to a factory callable.

    Parameters
    ----------
    candidate : object
        A plugin class, factory callable, or instance.

    Returns
    -------
    PluginFactoryCandidateT
        A factory callable.

    Raises
    ------
    PluginRegistryError
        If candidate cannot be resolved to a factory.
    """
    name = _resolve_plugin_name(candidate)
    stage: PluginStage | object

    # If it's already a plugin instance, wrap it
    if _is_registered_plugin(candidate):
        plugin_instance: RegisteredPlugin = candidate

        def factory() -> PluginInstance:
            """Return plugin instance factory.

            Returns
            -------
            PluginInstance
                Plugin instance.
            """
            return plugin_instance

        return factory

    if _is_legacy_plugin(candidate):
        legacy_instance: LegacyPluginProtocol = candidate

        def factory() -> PluginInstance:
            """Return plugin instance factory.

            Returns
            -------
            PluginInstance
                Plugin instance.
            """
            return legacy_instance

        return factory

    # If it's a class, check if it's Protocol or abstract
    if isclass(candidate):
        plugin_class = cast("type[object]", candidate)
        if _is_protocol_class(plugin_class):
            stage = _extract_stage(plugin_class)
            message = f"Cannot register Protocol class {name!r} as plugin"
            raise PluginRegistryError(
                message,
                context={
                    "plugin_name": name,
                    "stage": stage,
                    "reason": "is-protocol",
                },
            )
        if _is_abstract_class(plugin_class):
            stage = _extract_stage(plugin_class)
            message = f"Cannot register abstract class {name!r} as plugin"
            raise PluginRegistryError(
                message,
                context={
                    "plugin_name": name,
                    "stage": stage,
                    "reason": "is-abstract",
                },
            )
        # It's a concrete class, treat as factory
        return cast("PluginFactoryCandidateT", plugin_class)

    # If it's callable, treat as factory
    if callable(candidate):
        return cast("PluginFactoryCandidateT", candidate)

    message = f"Unsupported plugin candidate {name!r}: not callable"
    raise PluginRegistryError(
        message,
        context={
            "plugin_name": name,
            "reason": "not-callable",
        },
    )


def _instantiate_plugin(candidate: object) -> RegisteredPlugin:
    name = _resolve_plugin_name(candidate)
    try:
        factory = _resolve_factory(candidate)
        instance = _instantiate_plugin_from_factory(factory, name, "formatter")
    except PluginRegistryError:
        raise
    except _PLUGIN_CONFIGURATION_ERRORS as exc:  # pragma: no cover - defensive guard
        message = f"Failed to instantiate plugin {name!r}"
        raise PluginConfigurationError(message) from exc
    return _ensure_plugin_instance(instance)


def _resolve_plugin_name(candidate: object) -> str:
    name_attr: object = getattr(candidate, "name", None)
    if isinstance(name_attr, str) and name_attr:
        return name_attr
    qualname_attr: object = getattr(candidate, "__name__", None)
    if isinstance(qualname_attr, str) and qualname_attr:
        return qualname_attr
    return candidate.__class__.__name__


def _resolve_plugin_name_strict(candidate: object) -> str:
    name_attr: object = getattr(candidate, "name", None)
    if isinstance(name_attr, str) and name_attr:
        return name_attr
    qualname_attr: object = getattr(candidate, "__name__", None)
    if isinstance(qualname_attr, str) and qualname_attr:
        return qualname_attr
    message = "Discovered plugin without a name attribute"
    raise PluginConfigurationError(message)


def _ensure_plugin_instance(obj: object) -> RegisteredPlugin:
    name = obj.__class__.__name__
    name_attr: object = getattr(obj, "name", None)
    if isinstance(name_attr, str) and name_attr:
        name = name_attr
    stage_attr: object = getattr(obj, "stage", None)
    if not _is_valid_stage(stage_attr):
        message = f"Plugin {name!r} declares invalid stage {stage_attr!r}"
        raise PluginConfigurationError(message)
    if _is_registered_plugin(obj):  # pragma: no cover - runtime check
        return obj
    if _is_legacy_plugin(obj):
        try:
            return LegacyPluginAdapter.create(obj)
        except _PLUGIN_CONFIGURATION_ERRORS as exc:  # pragma: no cover - defensive guard
            message = f"Legacy plugin {name!r} is misconfigured"
            raise PluginConfigurationError(message) from exc
    message = f"Plugin {name!r} must define apply() or run()"
    raise PluginConfigurationError(message)


def _register_plugin(manager: PluginManager, plugin: RegisteredPlugin) -> None:
    # getattr on dynamic attributes returns Any per Python's type system
    stage = _extract_stage(plugin, default=None)
    if stage == "harvester":
        manager.harvesters.append(cast("HarvesterPlugin", plugin))
        return
    if stage == "transformer":
        manager.transformers.append(cast("TransformerPlugin", plugin))
        return
    if stage == "formatter":
        manager.formatters.append(cast("FormatterPlugin", plugin))
        return
    message = f"Unsupported plugin stage: {stage!r}"
    raise PluginConfigurationError(message)


def _is_registered_plugin(candidate: object) -> TypeGuard[RegisteredPlugin]:
    if inspect.isclass(candidate):
        return False
    return isinstance(
        candidate,
        (HarvesterPlugin, TransformerPlugin, FormatterPlugin, LegacyPluginAdapter),
    )


def _is_legacy_plugin(candidate: object) -> TypeGuard[LegacyPluginProtocol]:
    if inspect.isclass(candidate):
        return False
    return isinstance(candidate, LegacyPluginProtocol)


def _is_valid_stage(value: object) -> TypeGuard[PluginStage]:
    return value in {"harvester", "transformer", "formatter"}


def _load_entry_points() -> list[object]:
    loaded: list[object] = []
    for entry_point in metadata.entry_points().select(group=ENTRY_POINT_GROUP):
        try:
            candidate: object = entry_point.load()
            loaded.append(candidate)
        except _PLUGIN_CONFIGURATION_ERRORS as exc:  # pragma: no cover - best effort guard
            message = f"Failed to load plugin entry point {entry_point.name!r}"
            raise PluginConfigurationError(message) from exc
    return loaded


def _builtin_candidates(
    builtin: Sequence[PluginFactoryCandidateT] | None,
) -> tuple[PluginFactoryCandidateT, ...]:
    if builtin is None:
        return cast(
            "tuple[PluginFactoryCandidateT, ...]",
            (
                DataclassFieldDocPlugin,
                LLMSummaryRewritePlugin,
                NormalizeNumpyParamsPlugin,
            ),
        )
    return tuple(builtin)


def load_plugins(
    config: BuilderConfig,
    repo_root: Path,
    *,
    only: Sequence[str] | None = None,
    disable: Sequence[str] | None = None,
    builtin: Sequence[PluginFactoryCandidateT] | None = None,
) -> PluginManager:
    """Discover, filter, and instantiate plugins for the current run.

    Parameters
    ----------
    config : BuilderConfig
        Builder configuration.
    repo_root : Path
        Repository root directory.
    only : Sequence[str] | None, optional
        Plugin names to include (whitelist).
    disable : Sequence[str] | None, optional
        Plugin names to disable (blacklist).
    builtin : Sequence[PluginFactoryCandidateT] | None, optional
        Built-in plugin candidates.

    Returns
    -------
    PluginManager
        Initialized plugin manager with discovered and filtered plugins.

    Raises
    ------
    PluginConfigurationError
        If unknown plugins are specified in only or disable lists.
    """
    builtin_candidates = _builtin_candidates(builtin)

    discovered: dict[str, object] = {
        _resolve_plugin_name(candidate): candidate for candidate in builtin_candidates
    }

    for candidate in _load_entry_points():
        name = _resolve_plugin_name_strict(candidate)
        if name not in discovered:
            discovered[name] = candidate

    only_set = {entry.strip() for entry in only or [] if entry.strip()}
    disable_set = {entry.strip() for entry in disable or [] if entry.strip()}

    missing_only = sorted(name for name in only_set if name not in discovered)
    missing_disable = sorted(name for name in disable_set if name not in discovered)
    if missing_only or missing_disable:
        missing = ", ".join([*missing_only, *missing_disable])
        message = f"Unknown plugin(s): {missing}"
        raise PluginConfigurationError(message)

    available_plugins = sorted(discovered)
    manager = PluginManager(
        config=config,
        repo_root=repo_root,
        available=available_plugins,
    )

    for name in manager.available:
        if only_set and name not in only_set:
            manager.skipped.append(name)
            continue
        if name in disable_set:
            manager.disabled.append(name)
            manager.skipped.append(name)
            continue
        plugin = _instantiate_plugin(discovered[name])
        _register_plugin(manager, plugin)

    return manager


__all__ = [
    "DocstringPayload",
    "PluginConfigurationError",
    "PluginManager",
    "PluginRegistryError",
    "get_signature",
    "load_plugins",
]
