"""Utilities for formatting annotations into human-readable strings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal, cast, get_args, get_origin

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["format_annotation"]


def format_annotation(
    annotation: object,
    module_globals: Mapping[str, object] | None = None,
) -> str | None:
    """Return a human-readable representation of ``annotation``.

    Parameters
    ----------
    annotation : object
        Type annotation to format.
    module_globals : Mapping[str, object] | None, optional
        Module globals dictionary for resolving forward references.

    Returns
    -------
    str | None
        Formatted annotation string, | None if formatting fails.
    """
    simple = _format_simple_type(annotation)
    if simple is not None:
        return simple

    union = _format_union_type(annotation, module_globals)
    if union is not None:
        return union

    annotated = _format_annotated_type(annotation, module_globals)
    if annotated is not None:
        return annotated

    literal = _format_literal_type(annotation)
    if literal is not None:
        return literal

    for formatter in (
        _format_class_type,
        _format_collection_type,
        _format_generic_type,
        _format_module_attribute,
    ):
        formatted = formatter(annotation, module_globals)
        if formatted is not None:
            return formatted

    return repr(annotation) if annotation is not None else None


def _format_simple_type(annotation: object) -> str | None:
    """Format simple built-in types.

    Parameters
    ----------
    annotation : object
        Type annotation to format.

    Returns
    -------
    str | None
        Formatted string for simple types, None otherwise.
    """
    if annotation is None:
        return "None"
    if isinstance(annotation, str):
        return annotation
    if isinstance(annotation, type) and annotation in {int, float, bool, str}:
        return annotation.__name__
    return None


def _format_union_type(
    annotation: object,
    module_globals: Mapping[str, object] | None,
) -> str | None:
    """Format union types (including collections and generics).

    Parameters
    ----------
    annotation : object
        Type annotation to format.
    module_globals : Mapping[str, object] | None
        Module globals for resolving forward references.

    Returns
    -------
    str | None
        Formatted union/collection string, None if not applicable.
    """
    origin = get_origin(annotation)
    if origin is None or origin is Literal:
        return None

    formatted: str | None = None
    args = get_args(annotation)
    if origin is tuple and args and args[-1] is ...:
        tail_args = tuple(args[:-1])
        inner_list = [
            format_annotation(arg, module_globals) or "Any" for arg in tail_args
        ]
        formatted = "tuple[" + ", ".join(inner_list) + ", ...]"
    elif origin in {list, set, dict, tuple}:
        parts = [format_annotation(arg, module_globals) or "Any" for arg in args]
        inner_str = ", ".join(parts)
        origin_name = getattr(origin, "__name__", None)
        if origin_name is None:
            return None
        formatted = f"{origin_name}[{inner_str}]"
    elif origin is Annotated:
        base, *_ = args
        formatted = format_annotation(base, module_globals)
    elif args:
        parts = [format_annotation(arg, module_globals) or "Any" for arg in args]
        formatted = " | ".join(parts)
    return formatted


def _format_annotated_type(
    annotation: object,
    module_globals: Mapping[str, object] | None,
) -> str | None:
    """Format Annotated types by extracting the base type.

    Parameters
    ----------
    annotation : object
        Type annotation to format.
    module_globals : Mapping[str, object] | None
        Module globals for resolving forward references.

    Returns
    -------
    str | None
        Formatted base type string, None if not Annotated.
    """
    if get_origin(annotation) is Annotated:
        base, *_ = get_args(annotation)
        return format_annotation(base, module_globals)
    return None


def _format_literal_type(annotation: object) -> str | None:
    """Format Literal types.

    Parameters
    ----------
    annotation : object
        Type annotation to format.

    Returns
    -------
    str | None
        Formatted Literal string, None if not Literal.
    """
    if get_origin(annotation) is Literal:
        values = ", ".join(repr(value) for value in get_args(annotation))
        return f"Literal[{values}]"
    return None


def _format_class_type(
    annotation: object,
    module_globals: Mapping[str, object] | None,
) -> str | None:
    if not isinstance(annotation, type):
        return None
    module_name = getattr(annotation, "__module__", "")
    qualname = getattr(annotation, "__qualname__", annotation.__name__)
    if module_name == "builtins":
        return qualname
    if module_globals:
        alias = _alias_for_type(annotation, module_globals)
        if alias:
            return alias
        module_alias = _module_alias(module_name, module_globals)
        if module_alias:
            return f"{module_alias}.{qualname}"
    return f"{module_name}.{qualname}" if module_name else qualname


def _format_collection_type(
    annotation: object,
    module_globals: Mapping[str, object] | None,
) -> str | None:
    origin = get_origin(annotation)
    if origin not in {list, set, tuple, dict}:
        return None
    args = get_args(annotation)
    if origin is tuple and args and args[-1] is ...:
        inner = format_annotation(args[0], module_globals) or "Any"
        return f"tuple[{inner}, ...]"
    if not args:
        if isinstance(origin, type):
            return origin.__name__
        return None
    parts = [format_annotation(arg, module_globals) or "Any" for arg in args]
    inner = ", ".join(parts)
    origin_name = getattr(origin, "__name__", None)
    if origin_name is None:
        return None
    return f"{origin_name}[{inner}]"


def _format_generic_type(
    annotation: object,
    module_globals: Mapping[str, object] | None,
) -> str | None:
    origin = get_origin(annotation)
    if origin is None:
        return None
    module_name = getattr(origin, "__module__", "")
    qualname = getattr(origin, "__qualname__", getattr(origin, "__name__", ""))
    if module_name == "typing":
        module_alias = _module_alias(module_name, module_globals)
        prefix = module_alias or qualname
    elif module_name == "builtins":
        prefix = qualname
    else:
        module_alias = _module_alias(module_name, module_globals)
        prefix = (
            f"{module_alias}.{qualname}"
            if module_alias
            else f"{module_name}.{qualname}"
        )
    args = get_args(annotation)
    if not args:
        return prefix
    formatted_args = [format_annotation(arg, module_globals) or "Any" for arg in args]
    return f"{prefix}[{', '.join(formatted_args)}]"


def _format_module_attribute(
    annotation: object,
    module_globals: Mapping[str, object] | None,
) -> str | None:
    module_name = getattr(annotation, "__module__", None)
    qualname = getattr(annotation, "__qualname__", None)
    if module_name is None or qualname is None:
        return None
    qualname_str = cast("str", qualname)
    if module_name in {"builtins", "typing", "collections.abc"}:
        return qualname_str
    module_alias = _module_alias(module_name, module_globals)
    if module_alias:
        return f"{module_alias}.{qualname_str}"
    return f"{module_name}.{qualname_str}"


def _alias_for_type(
    annotation: object, module_globals: Mapping[str, object]
) -> str | None:
    for name, value in module_globals.items():
        if value is annotation:
            return name
    return None


def _module_alias(
    module_name: str, module_globals: Mapping[str, object] | None
) -> str | None:
    if not module_globals:
        return None
    for name, value in module_globals.items():
        if getattr(value, "__name__", None) == module_name:
            return name
    return None
