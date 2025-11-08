"""Harvest phase using Griffe for structural information."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, TypeGuard, cast, runtime_checkable

import libcst as cst

from tools.docstring_builder.models import SymbolResolutionError
from tools.docstring_builder.parameters import format_parameter_name, normalize_parameter_kind
from tools.griffe_utils import resolve_griffe

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
    from pathlib import Path

    from tools.docstring_builder.config import BuilderConfig
    from tools.docstring_builder.parameters import ParameterKind

try:  # Import lazily so unit tests can patch when griffe is unavailable.
    _GRIFFE_API = resolve_griffe()
except (ModuleNotFoundError, AttributeError) as exc:  # pragma: no cover - runtime guard
    message = "Griffe is required to run the docstring builder. Install the optional dependency via ``uv sync``."
    raise RuntimeError(message) from exc


@runtime_checkable
class GriffeDocstringLike(Protocol):
    """Protocol for docstring-like objects."""

    value: str


@runtime_checkable
class GriffeParameterLike(Protocol):
    """Protocol for parameter-like objects."""

    name: str
    kind: object
    annotation: object | None
    default: object | None


@runtime_checkable
class GriffeFunctionLike(Protocol):
    """Protocol for function-like objects."""

    name: str
    docstring: GriffeDocstringLike | None
    lineno: int | None
    endlineno: int | None
    col_offset: int | None
    parameters: Sequence[GriffeParameterLike]
    decorators: Sequence[object]
    return_annotation: object | None
    returns: object | None
    is_async: bool
    is_generator: bool


@runtime_checkable
class GriffeClassLike(Protocol):
    """Protocol for class-like objects."""

    name: str
    docstring: GriffeDocstringLike | None
    lineno: int | None
    endlineno: int | None
    col_offset: int | None
    members: Mapping[str, object]
    decorators: Sequence[object]
    is_async: bool
    is_generator: bool


@runtime_checkable
class GriffeModuleLike(Protocol):
    """Protocol for module-like objects."""

    name: str
    members: Mapping[str, object]


class GriffeLoaderInstanceLike(Protocol):
    """Protocol for Griffe loader instances."""

    def load(self, module_name: str) -> GriffeModuleLike:
        """Load module by name.

        Parameters
        ----------
        module_name : str
            Module name to load.

        Returns
        -------
        GriffeModuleLike
            Loaded module object.
        """
        ...

    def load_module(self, module_name: str) -> GriffeModuleLike:
        """Load module from file path.

        Parameters
        ----------
        module_name : str
            Module name to load.

        Returns
        -------
        GriffeModuleLike
            Loaded module object.
        """
        ...


class GriffeLoaderFactoryLike(Protocol):
    """Protocol for Griffe loader factory functions."""

    def __call__(self, *, search_paths: Sequence[str]) -> GriffeLoaderInstanceLike:
        """Create loader instance with search paths.

        Parameters
        ----------
        search_paths : Sequence[str]
            Paths to search for modules.

        Returns
        -------
        GriffeLoaderInstanceLike
            Loader instance.
        """
        ...


ClassType = cast("type", _GRIFFE_API.class_type)
FunctionType = cast("type", _GRIFFE_API.function_type)
ModuleType = cast("type", _GRIFFE_API.module_type)
GriffeLoaderFactory = cast("GriffeLoaderFactoryLike", _GRIFFE_API.loader_type)


def _is_griffe_class(obj: object) -> TypeGuard[GriffeClassLike]:
    return isinstance(obj, ClassType)


def _is_griffe_function(obj: object) -> TypeGuard[GriffeFunctionLike]:
    return isinstance(obj, FunctionType)


def _is_griffe_module(obj: object) -> TypeGuard[GriffeModuleLike]:
    return isinstance(obj, ModuleType)


def _safe_getattr(value: object, attr: str) -> object | None:
    try:
        attr_value = cast("object", getattr(value, attr))
    except AttributeError:  # pragma: no cover - defensive fallback
        return None
    return attr_value


def _extract_string_attribute(value: object, attr: str) -> str | None:
    candidate = _safe_getattr(value, attr)
    if isinstance(candidate, str):
        return candidate
    return None


def _docstring_value(docstring: GriffeDocstringLike | None) -> str | None:
    if docstring is None:
        return None
    value = _extract_string_attribute(docstring, "value")
    return value if value is not None else None


@dataclass(slots=True, frozen=True)
class ParameterHarvest:
    """Harvested signature information for a single parameter."""

    name: str
    kind: ParameterKind
    annotation: str | None
    default: str | None

    def display_name(self) -> str:
        """Return the formatted name suitable for docstring rendering.

        Returns
        -------
        str
            Formatted parameter name with appropriate prefix (* or **) if applicable.
        """
        return parameter_display_name(self)


def parameter_display_name(parameter: ParameterHarvest) -> str:
    """Format a harvested parameter for docstring sections.

    Parameters
    ----------
    parameter : ParameterHarvest
        Parameter metadata to format.

    Returns
    -------
    str
        Formatted parameter name with kind prefix.
    """
    return format_parameter_name(parameter.name, parameter.kind)


@dataclass(slots=True, frozen=True)
class SymbolHarvest:
    """Metadata describing a symbol subject to docstring generation."""

    qname: str
    module: str
    kind: Literal["function", "method", "class"]
    parameters: list[ParameterHarvest]
    return_annotation: str | None
    docstring: str | None
    owned: bool
    filepath: Path
    lineno: int
    end_lineno: int | None
    col_offset: int
    decorators: list[str]
    is_async: bool
    is_generator: bool


def _new_cst_index() -> dict[str, cst.CSTNode]:
    return {}


@dataclass(slots=True, frozen=True)
class HarvestResult:
    """Container mapping harvested symbols to CST nodes."""

    module: str
    filepath: Path
    symbols: list[SymbolHarvest]
    cst_index: dict[str, cst.CSTNode] = field(default_factory=_new_cst_index)


def _module_name(root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(root)
    parts = rel.with_suffix("").parts
    if parts and parts[0] in {"src", "tools", "docs"}:
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _load_module(module_name: str, search_paths: Sequence[str]) -> GriffeModuleLike:
    loader = GriffeLoaderFactory(search_paths=tuple(search_paths))
    load_candidate = cast("Callable[[str], object] | None", getattr(loader, "load_module", None))
    if callable(load_candidate):
        load_fn: Callable[[str], object] = load_candidate
    else:
        load_fallback = cast("Callable[[str], object] | None", getattr(loader, "load", None))
        if not callable(load_fallback):  # pragma: no cover - defensive fallback
            message = "Griffe loader is missing a callable 'load' method"
            raise SymbolResolutionError(message)
        load_fn = load_fallback
    try:
        module = load_fn(module_name)
    except ModuleNotFoundError as exc:
        if module_name.endswith(".__init__"):
            package_name = module_name.rsplit(".", 1)[0]
            module = load_fn(package_name)
        else:
            message = f"Unable to load module '{module_name}'"
            raise SymbolResolutionError(message) from exc
    if not _is_griffe_module(module):  # pragma: no cover - defensive fallback
        message = f"Griffe loader returned unsupported module type for '{module_name}'"
        raise SymbolResolutionError(message)
    return module


def _expr_to_str(value: object | None) -> str | None:
    if value is None:
        return "None"
    if isinstance(value, str):
        return value
    as_string = _safe_getattr(value, "as_string")
    if callable(as_string):
        as_string_callable = cast("Callable[[], object]", as_string)
        try:
            candidate = as_string_callable()
        except (TypeError, ValueError):  # pragma: no cover - defensive fallback
            candidate = None
        if isinstance(candidate, str):
            return candidate
    for attribute in ("name", "path", "value"):
        attr_value = _extract_string_attribute(value, attribute)
        if attr_value is not None:
            return attr_value
    try:
        return str(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive fallback
        return None


def _annotation_to_str(annotation: object | None) -> str | None:
    if annotation is None:
        return None
    return _expr_to_str(annotation)


def _default_to_str(default: object | None) -> str | None:
    return _expr_to_str(default)


def _decorator_names(decorators: Iterable[object]) -> list[str]:
    names: list[str] = []
    for decorator in decorators or []:
        name_attr = _safe_getattr(decorator, "name")
        if isinstance(name_attr, str):
            names.append(name_attr)
            continue
        value_attr = _safe_getattr(decorator, "value") or decorator
        name = _expr_to_str(value_attr)
        if name is not None:
            names.append(name)
        else:  # pragma: no cover - defensive fallback
            names.append(str(decorator))
    return names


def _iter_parameters(function: GriffeFunctionLike) -> Iterator[ParameterHarvest]:
    for param in function.parameters:
        yield ParameterHarvest(
            name=param.name,
            kind=normalize_parameter_kind(param.kind),
            annotation=_annotation_to_str(param.annotation),
            default=_default_to_str(param.default),
        )


def _collect_class_symbol(
    class_obj: GriffeClassLike,
    module_name: str,
    file_path: Path,
    config: BuilderConfig,
    prefix: list[str],
) -> Iterator[SymbolHarvest]:
    name = class_obj.name
    qname = ".".join([module_name, *prefix, name])
    docstring = _docstring_value(class_obj.docstring)
    owned = docstring is None or config.ownership_marker in docstring
    if qname in config.package_settings.opt_out:
        owned = False
    col_offset_value = _safe_getattr(class_obj, "col_offset")
    col_offset = col_offset_value if isinstance(col_offset_value, int) else 0
    end_lineno_value = _safe_getattr(class_obj, "endlineno")
    end_lineno = end_lineno_value if isinstance(end_lineno_value, int) else None
    decorators_tuple = tuple(class_obj.decorators)
    lineno_value = _safe_getattr(class_obj, "lineno")
    lineno = lineno_value if isinstance(lineno_value, int) else 1
    yield SymbolHarvest(
        qname=qname,
        module=module_name,
        kind="class",
        parameters=[],
        return_annotation=None,
        docstring=docstring,
        owned=owned,
        filepath=file_path,
        lineno=lineno,
        end_lineno=end_lineno,
        col_offset=col_offset,
        decorators=_decorator_names(decorators_tuple),
        is_async=False,
        is_generator=False,
    )
    yield from _walk_members(class_obj, module_name, file_path, config, [*prefix, name])


def _collect_function_symbol(
    function_obj: GriffeFunctionLike,
    module_name: str,
    file_path: Path,
    config: BuilderConfig,
    prefix: list[str],
) -> Iterator[SymbolHarvest]:
    name = function_obj.name
    qname = ".".join([module_name, *prefix, name])
    parameters = list(_iter_parameters(function_obj))
    docstring = _docstring_value(function_obj.docstring)
    owned = docstring is None or config.ownership_marker in docstring
    if qname in config.package_settings.opt_out:
        owned = False
    return_annotation_obj = _safe_getattr(function_obj, "return_annotation")
    if return_annotation_obj is None:
        return_annotation_obj = _safe_getattr(function_obj, "returns")
    col_offset_value = _safe_getattr(function_obj, "col_offset")
    col_offset = col_offset_value if isinstance(col_offset_value, int) else 0
    end_lineno_value = _safe_getattr(function_obj, "endlineno")
    end_lineno = end_lineno_value if isinstance(end_lineno_value, int) else None
    decorators_tuple = tuple(function_obj.decorators)
    is_async = bool(_safe_getattr(function_obj, "is_async"))
    is_generator = bool(_safe_getattr(function_obj, "is_generator"))
    lineno_value = _safe_getattr(function_obj, "lineno")
    lineno = lineno_value if isinstance(lineno_value, int) else 1
    yield SymbolHarvest(
        qname=qname,
        module=module_name,
        kind="method" if prefix else "function",
        parameters=parameters,
        return_annotation=_annotation_to_str(return_annotation_obj),
        docstring=docstring,
        owned=owned,
        filepath=file_path,
        lineno=lineno,
        end_lineno=end_lineno,
        col_offset=col_offset,
        decorators=_decorator_names(decorators_tuple),
        is_async=is_async,
        is_generator=is_generator,
    )


def _collect_symbols(
    obj: object,
    module_name: str,
    file_path: Path,
    config: BuilderConfig,
    prefix: list[str] | None = None,
) -> Iterator[SymbolHarvest]:
    prefix_list: list[str] = prefix if prefix is not None else []
    if _is_griffe_class(obj):
        class_obj: GriffeClassLike = obj
        yield from _collect_class_symbol(class_obj, module_name, file_path, config, prefix_list)
        return
    if _is_griffe_function(obj):
        function_obj: GriffeFunctionLike = obj
        yield from _collect_function_symbol(
            function_obj,
            module_name,
            file_path,
            config,
            prefix_list,
        )
        return
    if _is_griffe_module(obj):
        module_obj: GriffeModuleLike = obj
        yield from _walk_members(module_obj, module_name, file_path, config, prefix_list)


def _walk_members(
    obj: GriffeModuleLike | GriffeClassLike,
    module_name: str,
    file_path: Path,
    config: BuilderConfig,
    prefix: list[str] | None = None,
) -> Iterator[SymbolHarvest]:
    prefix = prefix or []
    for member in obj.members.values():
        yield from _collect_symbols(member, module_name, file_path, config, prefix)


class _IndexCollector(cst.CSTTransformer):
    """Collect CST nodes for indexing.

    Parameters
    ----------
    module_name : str
        Module qualified name.
    """

    def __init__(self, module_name: str) -> None:
        self.module_name = module_name
        self.namespace: list[str] = []
        self.index: dict[str, cst.CSTNode] = {}

    def _qualify(self, name: str) -> str:
        pieces = [self.module_name, *self.namespace, name]
        return ".".join(piece for piece in pieces if piece)

    def visit_classdef(self, node: cst.ClassDef) -> bool:
        """Visit class definition and index it.

        Parameters
        ----------
        node : cst.ClassDef
            ClassDef CST node.

        Returns
        -------
        bool
            True to continue visiting children.
        """
        self.namespace.append(node.name.value)
        qualified = self._qualify(node.name.value)
        self.index[qualified] = node
        return True

    def leave_classdef(
        self, _original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.CSTNode:
        """Leave class definition and restore namespace.

        Parameters
        ----------
        _original_node : cst.ClassDef
            Original CST node (unused).
        updated_node : cst.ClassDef
            Updated CST node.

        Returns
        -------
        cst.CSTNode
            Updated node.
        """
        self.namespace.pop()
        return updated_node

    def visit_functiondef(self, node: cst.FunctionDef) -> bool:
        """Visit function definition and index it.

        Parameters
        ----------
        node : cst.FunctionDef
            FunctionDef CST node.

        Returns
        -------
        bool
            True to continue visiting children.
        """
        self.namespace.append(node.name.value)
        qualified = self._qualify(node.name.value)
        self.index[qualified] = node
        return True

    def leave_functiondef(
        self, _original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.CSTNode:
        """Leave function definition and restore namespace.

        Parameters
        ----------
        _original_node : cst.FunctionDef
            Original CST node (unused).
        updated_node : cst.FunctionDef
            Updated CST node.

        Returns
        -------
        cst.CSTNode
            Updated node.
        """
        self.namespace.pop()
        return updated_node


def _build_cst_index(module_name: str, file_path: Path) -> dict[str, cst.CSTNode]:
    module = cst.parse_module(file_path.read_text(encoding="utf-8"))
    collector = _IndexCollector(module_name)
    module.visit(collector)
    return collector.index


def harvest_file(file_path: Path, config: BuilderConfig, repo_root: Path) -> HarvestResult:
    """Collect symbol metadata for a single file.

    Parameters
    ----------
    file_path : Path
        Path to the Python file to harvest.
    config : BuilderConfig
        Builder configuration.
    repo_root : Path
        Repository root directory.

    Returns
    -------
    HarvestResult
        Harvested module metadata including symbols and CST index.
    """
    module_name = _module_name(repo_root, file_path)
    if not module_name:
        module_name = file_path.stem
    search_paths = [str(repo_root / "src"), str(repo_root / "tools"), str(repo_root)]
    module = _load_module(module_name, search_paths)
    symbols = list(_walk_members(module, module_name, file_path, config))
    index = _build_cst_index(module_name, file_path)
    return HarvestResult(module=module_name, filepath=file_path, symbols=symbols, cst_index=index)


def iter_target_files(config: BuilderConfig, repo_root: Path) -> Iterator[Path]:
    """Yield files matching include/exclude patterns.

    Parameters
    ----------
    config : BuilderConfig
        Builder configuration with include/exclude patterns.
    repo_root : Path
        Repository root directory.

    Yields
    ------
    Path
        Python file paths matching the include patterns and not excluded.
    """
    for pattern in config.include:
        for candidate in repo_root.glob(pattern):
            if not candidate.is_file() or candidate.suffix != ".py":
                continue
            rel = candidate.relative_to(repo_root)
            if any(rel.match(exclude) for exclude in config.exclude):
                continue
            yield candidate


__all__ = [
    "HarvestResult",
    "ParameterHarvest",
    "SymbolHarvest",
    "harvest_file",
    "iter_target_files",
    "parameter_display_name",
]
