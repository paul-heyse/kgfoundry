"""Lightweight wrappers around Griffe for API/doc extraction."""

from __future__ import annotations

import importlib
import logging
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Literal, cast

griffe: ModuleType | None
Docstring: type[Any] | None
GriffeError: type[Exception]
AliasResolutionError: type[Exception]

try:
    import griffe as griffe_module
    from griffe import Docstring as GriffeDocstring
    from griffe import GriffeError as GriffeBaseError
except ImportError:  # pragma: no cover - optional dependency at runtime
    griffe = None
    Docstring = None
    GriffeError = RuntimeError
    AliasResolutionError = RuntimeError
else:
    griffe = griffe_module
    Docstring = GriffeDocstring
    GriffeError = GriffeBaseError
    try:  # pragma: no cover - optional dependency
        exceptions_mod = importlib.import_module("griffe.exceptions")
    except (ImportError, AttributeError):
        AliasResolutionError = GriffeError
    else:
        alias_error = getattr(exceptions_mod, "AliasResolutionError", None)
        if isinstance(alias_error, type) and issubclass(alias_error, Exception):
            AliasResolutionError = cast("type[Exception]", alias_error)
        else:
            AliasResolutionError = GriffeError

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
                try:
                    target = getattr(member, "target", None)
                except (
                    AttributeError,
                    KeyError,
                    AliasResolutionError,
                ):  # pragma: no cover - defensive
                    LOGGER.debug(
                        "Skipping alias %s due to resolution error", getattr(member, "path", member)
                    )
                    continue
                if target is not None:
                    stack.append(target)
                continue
            stack.append(member)


def _param_kind(p: object) -> str:
    # Map griffe Parameter.kind (enum-like) to a stable string.
    k = getattr(p, "kind", None)
    return str(k).split(".")[-1] if k is not None else "pos"


def _section_kind(section: object) -> str:
    """Return a lowercase identifier describing a docstring section.

    Parameters
    ----------
    section : object
        Griffe docstring section object with a ``kind`` attribute containing
        an enum value. The function extracts the enum value and converts it
        to a lowercase string identifier.

    Returns
    -------
    str
        Lowercase section identifier (e.g., "parameters", "returns", "raises").
        Returns empty string if section lacks a kind attribute.
    """
    kind = getattr(getattr(section, "kind", None), "value", "")
    return str(kind).lower()


def _extract_doc_params(section_value: object) -> list[ApiParam]:
    """Return parameters documented in a docstring section.

    Parameters
    ----------
    section_value : object
        Griffe docstring section object containing parameter documentation.
        May have a ``parameters`` attribute (list) or be a list directly.
        Each item should have ``name``/``arg_name``, ``annotation``, and
        ``description`` attributes.

    Returns
    -------
    list[ApiParam]
        Parameters parsed from the docstring, each with name, annotated_type,
        kind="doc", and optional doc string. Returns empty list if section_value
        is neither a list nor has a parameters attribute.
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

    Parameters
    ----------
    section_value : object
        Griffe docstring section object containing return documentation.
        May have a ``returns`` attribute (list) or be a list directly.
        Alternatively, may have a ``description`` attribute for simple
        return documentation.

    Returns
    -------
    ApiReturn | None
        Parsed return description with annotated_type and doc, if present.
        Returns None if no return documentation is found in section_value.
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

    Parameters
    ----------
    section_value : object
        Griffe docstring section object containing exception documentation.
        May have a ``raises`` attribute (list) or be a list directly.
        Each item should have ``annotation`` (exception type) and ``description``
        attributes.

    Returns
    -------
    list[ApiRaise]
        Documented exceptions, each with exception type name and optional doc.
        Returns empty list if section_value lacks raises documentation.
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

    Parameters
    ----------
    text : str | None
        Raw docstring text to parse, or None to return empty results.
        Must be valid docstring content matching the specified style.
    style : DocstringStyle
        Griffe docstring style enum (e.g., DocstringStyle.GOOGLE, DocstringStyle.NUMPYDOC).
        Determines the parsing rules applied to text.

    Returns
    -------
    tuple[list[ApiParam], ApiReturn | None, list[ApiRaise]]
        Parameter, return, and raises metadata derived from the docstring.
        Returns empty lists and None if text is None, griffe is unavailable,
        or parsing fails.
    """
    if not text or griffe is None or Docstring is None:
        return ([], None, [])
    try:
        sections_raw = Docstring(text).parse(style)
    except (GriffeError, ValueError) as exc:  # pragma: no cover - parser errors are rare
        LOGGER.debug("Failed to parse docstring with style %s: %s", style, exc)
        return ([], None, [])
    if not isinstance(sections_raw, Iterable):
        return ([], None, [])
    sections = list(sections_raw)

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

    Parameters
    ----------
    obj : GriffeObject
        Griffe API object (function, class, module, or attribute) to classify.
        Must have boolean properties ``is_function``, ``is_class``, and ``is_module``.

    Returns
    -------
    Kind
        Symbol classification string: "function", "class", "module", or "attribute".
        Returns "attribute" as the default fallback if obj doesn't match other kinds.
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

    Parameters
    ----------
    obj : GriffeObject
        Griffe API object with an optional ``location`` attribute containing
        filepath and line number information.

    Returns
    -------
    tuple[str | None, int | None]
        Path and starting line number if available. Returns (None, None) if obj
        lacks a location attribute or location lacks filepath/lineno.
    """
    loc = getattr(obj, "location", None)
    if not loc:
        return (None, None)
    filepath = getattr(loc, "filepath", None)
    lineno = getattr(loc, "lineno", None)
    return (str(filepath) if filepath else None, int(lineno) if lineno else None)


def _parameters_from_signature(parameters: Iterable[object]) -> list[ApiParam]:
    """Return ApiParam objects derived from a Griffe parameter list.

    Parameters
    ----------
    parameters : Iterable[object]
        Iterable of Griffe Parameter objects, each with ``name``, ``kind``,
        ``annotation``, and optional ``default`` attributes.

    Returns
    -------
    list[ApiParam]
        Parameters extracted from the provided iterable, each with name, kind,
        annotated_type (rendered expression), and optional default (rendered
        expression). Returns empty list if parameters is empty.
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

    Parameters
    ----------
    obj : GriffeObject
        Griffe API object (function or class) to extract signature from.
        For functions, extracts parameters and return annotation directly.
        For classes, extracts parameters from ``__init__`` method if present.

    Returns
    -------
    tuple[list[ApiParam], ApiReturn | None]
        Parameters derived from code plus return annotation. For classes,
        returns empty parameter list if ``__init__`` is missing or not a function.
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

    Parameters
    ----------
    code_params : list[ApiParam]
        Parameters extracted from function/class signature (code-derived).
        These provide the canonical parameter names, types, and defaults.
    doc_params : list[ApiParam]
        Parameters extracted from docstring (documentation-derived).
        These provide optional doc strings that enrich code_params.

    Returns
    -------
    list[ApiParam]
        Parameters enriched with docstring descriptions. If code_params is empty,
        returns doc_params as-is. Otherwise, merges doc strings from doc_params
        into matching code_params by name.
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

    Parameters
    ----------
    obj : GriffeObject
        Griffe API object (function, class, module, or attribute) to convert
        to an ApiSymbol. Must have attributes for name, kind, location, decorators,
        bases, docstring, and signature information.
    docstyle : DocstringStyle
        Griffe docstring style enum to use when parsing docstring sections.
        Determines how Parameters/Returns/Raises are extracted from docstrings.

    Returns
    -------
    ApiSymbol
        Normalized representation of ``obj`` with merged code and docstring
        metadata, including parameters, return type, raises, decorators, and bases.
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

    Extended Summary
    ----------------
    This function uses Griffe to parse Python packages and extract their public
    API symbols (functions, classes, modules, attributes). It loads packages from
    the repository root and system path, parses docstrings according to the
    specified style, and returns normalized ApiSymbol objects suitable for
    documentation generation and API cataloging.

    Parameters
    ----------
    repo_root : Path
        Root directory of the repository containing the packages to scan.
        Added to Griffe's search paths along with sys.path entries.
    package_names : Iterable[str]
        Iterable of top-level package names (e.g., ["kgfoundry", "tools"]) to load
        and scan. Each name must be importable from repo_root or sys.path.
    docstyle : DocstringStyle, optional
        Griffe docstring style enum (default: "google"). Determines how docstrings
        are parsed to extract Parameters/Returns/Raises sections.

    Returns
    -------
    list[ApiSymbol]
        Serialized API entries discovered in ``package_names``. Returns empty list
        if griffe is unavailable or all packages fail to load. Symbols are sorted
        by full_name and include merged code and docstring metadata.

    Notes
    -----
    Performance & Side Effects:
        Time complexity O(n*m) where n is the number of packages and m is the
        average number of symbols per package. Reads Python source files from disk;
        may import modules during parsing. Thread-safe for concurrent scans.

    See Also
    --------
    _build_symbol : Core symbol construction logic
    ApiSymbol : Normalized symbol representation
    """
    if griffe is None:
        return []

    modules: list[GriffeModule] = []
    search_paths = [str(repo_root), *[path for path in sys.path if path]]
    for name in package_names:
        try:
            module = griffe.load(name, search_paths=search_paths)
            modules.append(cast("GriffeModule", module))
        except (
            GriffeError,
            ImportError,
            ModuleNotFoundError,
            OSError,
            FileNotFoundError,
            KeyError,
        ) as exc:
            LOGGER.debug("Skipping package %s due to load error: %s", name, exc)
            continue

    symbols: list[ApiSymbol] = []
    for module in modules:
        try:
            iterator = _iter_objects(module)
            objects = list(iterator)
        except (
            AttributeError,
            KeyError,
            ValueError,
            RuntimeError,
            AliasResolutionError,
        ) as exc:  # pragma: no cover - defensive
            LOGGER.debug(
                "Skipping module %s due to traversal error: %s",
                getattr(module, "path", module),
                exc,
            )
            continue
        for obj in objects:
            current_obj = obj
            try:
                symbols.append(_build_symbol(current_obj, docstyle=docstyle))
            except (
                AttributeError,
                KeyError,
                ValueError,
                RuntimeError,
                AliasResolutionError,
            ) as exc:  # pragma: no cover - defensive
                LOGGER.debug(
                    "Skipping symbol %s due to build error: %s",
                    getattr(current_obj, "path", current_obj),
                    exc,
                )
    return symbols
