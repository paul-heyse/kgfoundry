"""Lightweight wrappers around Griffe for API/doc extraction."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

try:
    import griffe
    from griffe import Docstring, GriffeError
except ImportError:  # pragma: no cover - optional dependency at runtime
    griffe = None  # type: ignore[assignment]
    Docstring = None  # type: ignore[assignment]
    GriffeError = RuntimeError  # type: ignore[assignment]

type DocstringStyle = Literal["google", "numpy", "sphinx", "auto"]

if TYPE_CHECKING:
    from griffe import Module as GriffeModule
    from griffe import Object as GriffeObject
else:  # pragma: no cover - typing-only shim
    GriffeModule = GriffeObject = object

LOGGER = logging.getLogger(__name__)


Kind = Literal["module", "class", "function", "attribute"]


@dataclass(slots=True, frozen=True)
class ApiParam:
    """Description of a single callable parameter."""

    name: str
    kind: str  # posonly, pos, kwonly, vararg, varkw (best-effort)
    annotated_type: str | None = None
    default: str | None = None
    doc: str | None = None


@dataclass(slots=True, frozen=True)
class ApiReturn:
    """Return annotation extracted from code/docs."""

    annotated_type: str | None = None
    doc: str | None = None


@dataclass(slots=True, frozen=True)
class ApiRaise:
    """Raised exception documented in the API."""

    exception: str
    doc: str | None = None


@dataclass(slots=True, frozen=True)
class ApiSymbol:
    """Normalized public symbol emitted by the Griffe scanner."""

    full_name: str
    short_name: str
    kind: Kind
    file: str | None
    lineno: int | None
    bases: tuple[str, ...] = field(default_factory=tuple)
    decorators: tuple[str, ...] = field(default_factory=tuple)
    params: tuple[ApiParam, ...] = field(default_factory=tuple)
    returns: ApiReturn | None = None
    raises: tuple[ApiRaise, ...] = field(default_factory=tuple)
    doc_summary: str | None = None
    doc_raw: str | None = None
    docstyle: str | None = None  # "google" | "numpy" | "sphinx" best-effort


def _render_expr(expr: object) -> str | None:
    # Griffe Expressions render as strings; fall back gracefully.
    try:
        if expr is None:
            return None
        # Recent griffe Expr has .render(); older falls back to str()
        expr_any: Any = expr
        return expr_any.render() if hasattr(expr_any, "render") else str(expr_any)
    except (AttributeError, ValueError, TypeError):
        return None


def _doc_summary(text: str | None) -> str | None:
    if not text:
        return None
    ls = text.strip().splitlines()
    return (ls[0].strip() if ls else None) or None


def _iter_objects(root: GriffeModule) -> Iterator[GriffeObject]:
    stack: list[GriffeObject] = [root]
    while stack:
        obj = stack.pop()
        yield obj
        # Include declared (non-inherited) members
        for member in obj.members.values():
            if getattr(member, "is_alias", False):
                target = getattr(member, "target", None)
                if target is not None:
                    stack.append(cast("GriffeObject", target))
                continue
            stack.append(cast("GriffeObject", member))


def _param_kind(p: object) -> str:
    # Map griffe Parameter.kind (enum-like) to a stable string.
    k = getattr(p, "kind", None)
    return str(k).split(".")[-1] if k is not None else "pos"


def _section_kind(section: object) -> str:
    """Return a lowercase identifier describing a docstring section.

    Returns
    -------
    str
        Lowercase section identifier.
    """
    kind = getattr(getattr(section, "kind", None), "value", "")
    return str(kind).lower()


def _extract_doc_params(section_value: object) -> list[ApiParam]:
    """Return parameters documented in a docstring section.

    Returns
    -------
    list[ApiParam]
        Parameters parsed from the docstring.
    """
    params_source = getattr(section_value, "parameters", None)
    if isinstance(params_source, list):
        entries = params_source
    elif isinstance(section_value, list):
        entries = section_value
    else:
        return []
    return [
        ApiParam(
            name=getattr(item, "name", None) or getattr(item, "arg_name", None) or "",
            kind="doc",
            annotated_type=str(getattr(item, "annotation", None))
            if getattr(item, "annotation", None)
            else None,
            default=None,
            doc=getattr(item, "description", None) or None,
        )
        for item in entries
    ]


def _extract_doc_return(section_value: object) -> ApiReturn | None:
    """Return the documented return record, if any.

    Returns
    -------
    ApiReturn | None
        Parsed return description, if present.
    """
    entries_source = getattr(section_value, "returns", None)
    if isinstance(entries_source, list):
        entries = entries_source
    elif isinstance(section_value, list):
        entries = section_value
    else:
        entries = []
    if entries:
        r0 = entries[0]
        rdoc = getattr(r0, "description", None) or None
        rtype = getattr(r0, "annotation", None)
        return ApiReturn(annotated_type=str(rtype) if rtype else None, doc=rdoc)
    description = getattr(section_value, "description", None)
    if description:
        return ApiReturn(annotated_type=None, doc=description)
    return None


def _extract_doc_raises(section_value: object) -> list[ApiRaise]:
    """Return exceptions documented in the docstring.

    Returns
    -------
    list[ApiRaise]
        Documented exceptions.
    """
    entries_source = getattr(section_value, "raises", None)
    if isinstance(entries_source, list):
        entries = entries_source
    elif isinstance(section_value, list):
        entries = section_value
    else:
        entries = []
    results: list[ApiRaise] = []
    for item in entries:
        ename = getattr(item, "annotation", None)
        edoc = getattr(item, "description", None) or None
        if ename:
            results.append(ApiRaise(exception=str(ename), doc=edoc))
    return results


def _parse_doc_sections(
    text: str | None, style: DocstringStyle
) -> tuple[list[ApiParam], ApiReturn | None, list[ApiRaise]]:
    """Parse structured docstring sections using Griffe's parser.

    Returns
    -------
    tuple[list[ApiParam], ApiReturn | None, list[ApiRaise]]
        Parameter, return, and raises metadata derived from the docstring.
    """
    if not text or griffe is None or Docstring is None:
        return ([], None, [])
    try:
        sections = Docstring(text).parse(style)
    except (GriffeError, ValueError) as exc:  # pragma: no cover - parser errors are rare
        LOGGER.debug("Failed to parse docstring with style %s: %s", style, exc)
        return ([], None, [])

    params: list[ApiParam] = []
    returns: ApiReturn | None = None
    raises: list[ApiRaise] = []

    for section in sections:
        kind_name = _section_kind(section)
        value = getattr(section, "value", None)
        if value is None:
            continue
        if "param" in kind_name:
            params.extend(_extract_doc_params(value))
        elif "return" in kind_name:
            returns = returns or _extract_doc_return(value)
        elif "raise" in kind_name or "exception" in kind_name:
            raises.extend(_extract_doc_raises(value))

    return (params, returns, raises)


def _symbol_kind(obj: GriffeObject) -> Kind:
    """Return a normalized symbol kind for a Griffe object.

    Returns
    -------
    Kind
        Symbol classification (module/class/function/attribute).
    """
    if obj.is_function:
        return "function"
    if obj.is_class:
        return "class"
    if obj.is_module:
        return "module"
    return "attribute"


def _symbol_location(obj: GriffeObject) -> tuple[str | None, int | None]:
    """Return (filepath, lineno) for a Griffe object.

    Returns
    -------
    tuple[str | None, int | None]
        Path and starting line number if available.
    """
    loc = getattr(obj, "location", None)
    if not loc:
        return (None, None)
    filepath = getattr(loc, "filepath", None)
    lineno = getattr(loc, "lineno", None)
    return (str(filepath) if filepath else None, int(lineno) if lineno else None)


def _parameters_from_signature(parameters: Iterable[object]) -> list[ApiParam]:
    """Return ApiParam objects derived from a Griffe parameter list.

    Returns
    -------
    list[ApiParam]
        Parameters extracted from the provided iterable.
    """
    return [
        ApiParam(
            name=getattr(parameter, "name", ""),
            kind=_param_kind(parameter),
            annotated_type=_render_expr(getattr(parameter, "annotation", None)),
            default=_render_expr(getattr(parameter, "default", None)),
        )
        for parameter in parameters
    ]


def _signature_from_object(obj: GriffeObject) -> tuple[list[ApiParam], ApiReturn | None]:
    """Extract signature parameters and return annotation from code.

    Returns
    -------
    tuple[list[ApiParam], ApiReturn | None]
        Parameters derived from code plus return annotation.
    """
    params: list[ApiParam] = []
    returns: ApiReturn | None = None

    if obj.is_function:
        params = _parameters_from_signature(getattr(obj, "parameters", []) or [])
        returns = ApiReturn(annotated_type=_render_expr(getattr(obj, "returns", None)))
    elif obj.is_class:
        init_method = obj.members.get("__init__")
        if init_method and getattr(init_method, "is_function", False):
            params = _parameters_from_signature(getattr(init_method, "parameters", []) or [])

    return params, returns


def _merge_param_docs(code_params: list[ApiParam], doc_params: list[ApiParam]) -> list[ApiParam]:
    """Merge docstring parameter descriptions into code-derived parameters.

    Returns
    -------
    list[ApiParam]
        Parameters enriched with docstring descriptions.
    """
    if not code_params:
        return doc_params
    doc_map = {param.name: param for param in doc_params if param.name}
    return [
        ApiParam(
            name=param.name,
            kind=param.kind,
            annotated_type=param.annotated_type,
            default=param.default,
            doc=(doc_entry.doc if (doc_entry := doc_map.get(param.name)) else None),
        )
        for param in code_params
    ]


def _build_symbol(obj: GriffeObject, *, docstyle: DocstringStyle) -> ApiSymbol:
    """Construct an ApiSymbol for a Griffe object.

    Returns
    -------
    ApiSymbol
        Normalized representation of ``obj``.
    """
    kind = _symbol_kind(obj)
    file, lineno = _symbol_location(obj)
    decorators = tuple(
        filter(None, (_render_expr(d.value) for d in getattr(obj, "decorators", []) or []))
    )
    bases = tuple(filter(None, (_render_expr(b) for b in getattr(obj, "bases", []) or [])))

    params, returns = _signature_from_object(obj)
    raw_doc: str | None = getattr(getattr(obj, "docstring", None), "value", None)
    doc_params, doc_return, doc_raises = _parse_doc_sections(raw_doc, docstyle)

    merged_params = _merge_param_docs(params, doc_params)
    if not returns and doc_return:
        returns = doc_return
    elif returns and doc_return:
        returns = ApiReturn(
            annotated_type=returns.annotated_type or doc_return.annotated_type,
            doc=doc_return.doc,
        )

    return ApiSymbol(
        full_name=obj.path,
        short_name=obj.name,
        kind=kind,
        file=file,
        lineno=lineno,
        bases=bases,
        decorators=decorators,
        params=tuple(merged_params),
        returns=returns,
        raises=tuple(doc_raises),
        doc_summary=_doc_summary(raw_doc),
        doc_raw=raw_doc,
        docstyle=docstyle,
    )


def collect_api_symbols_with_griffe(
    repo_root: Path,
    package_names: Iterable[str],
    docstyle: DocstringStyle = "google",
) -> list[ApiSymbol]:
    """Load one or more top-level packages with Griffe and emit normalized API symbols.

    Returns
    -------
    list[ApiSymbol]
        Serialized API entries discovered in ``package_names``.
    """
    if griffe is None:
        return []

    modules: list[GriffeModule] = []
    search_paths = [str(repo_root), *[path for path in sys.path if path]]
    for name in package_names:
        try:
            module = griffe.load(name, search_paths=search_paths)
            modules.append(cast("GriffeModule", module))
        except (GriffeError, ImportError, ModuleNotFoundError, OSError, FileNotFoundError) as exc:
            LOGGER.debug("Skipping package %s due to load error: %s", name, exc)
            continue

    symbols: list[ApiSymbol] = []
    for module in modules:
        symbols.extend(_build_symbol(obj, docstyle=docstyle) for obj in _iter_objects(module))
    return symbols
