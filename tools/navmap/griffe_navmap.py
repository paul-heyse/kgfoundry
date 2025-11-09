"""Griffe-based navmap generator.

This script builds an alternative navmap JSON using Griffe's semantic model. It is
designed to coexist with the existing navmap tooling while providing richer support
for alias resolution, re-exports, and inherited members. The generator assumes
project docstrings follow the NumPy documentation style and configures Griffe with
the ``"numpy"`` parser by default, matching the conventions used across the
codebase. The default configuration enables common Griffe extensions—such as
``griffe_inherited_docstrings``, ``griffe_typingdoc``, and ``griffe_pydantic``—when
present in the environment, and additional extensions can be appended via the
``--ext`` flag.

The CLI mirrors the behaviour proposed in the Griffe-first blueprint: load one or
more packages, expand their public surfaces, resolve alias chains, and emit a flat
list of symbols tagged with source location metadata. The resulting payload can be
consumed by documentation or IDE tooling that expects `path`, `kind`, and anchor
information for every exported symbol.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from griffe import (
    Alias,
    AliasResolutionError,
    BuiltinModuleError,
    CyclicAliasError,
    Docstring,
    GriffeLoader,
    Module,
    load_extensions,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from griffe import Object

LOGGER = logging.getLogger(__name__)

DEFAULT_SEARCH_PATHS: list[str] = ["src", "."]
DEFAULT_EXTENSIONS: list[str] = [
    "griffe_inherited_docstrings",
    "griffe_typingdoc",
    "griffe_pydantic",
    "griffe_fieldz",
    "griffe_public_wildcard_imports",
]


@dataclass(slots=True, frozen=True)
class Symbol:
    """Serialized representation of a single symbol discovered during navmap generation.

    A symbol represents any Python construct (module, class, function, etc.) that
    was discovered during the traversal of package roots. This class captures
    essential metadata including location information, docstring summaries, and
    relationship metadata (aliases, inheritance).

    Attributes
    ----------
    path : str
        Fully qualified path of the symbol (e.g., ``pkg.module.Class.method``).
    kind : str
        Symbol kind such as ``module``, ``class``, ``function``, or ``alias``.
    file : str | None
        Repository-relative file path containing the symbol definition.
    lineno : int | None
        Starting line number for the symbol definition in the source file.
    endlineno : int | None
        Ending line number for the symbol definition in the source file.
    summary : str | None
        First line of the docstring, if present, used as a brief description.
    origin : str | None
        Fully qualified target when the symbol is an alias or inherited member,
        indicating where the symbol originally comes from.
    inherited : bool
        Flag indicating whether the symbol originates from inheritance rather than
        being defined directly in the current class.
    is_alias : bool
        Flag indicating whether the symbol is represented as a Griffe alias,
        meaning it's imported or re-exported from another module.

    Parameters
    ----------
    path : str
        Fully qualified path of the symbol (e.g., ``pkg.module.Class.method``).
    kind : str
        Symbol kind such as ``module``, ``class``, ``function``, or ``alias``.
    file : str | None
        Repository-relative file path containing the symbol.
    lineno : int | None
        Starting line number for the symbol definition.
    endlineno : int | None
        Ending line number for the symbol definition.
    summary : str | None
        First line of the docstring, if present.
    origin : str | None
        Fully qualified target when the symbol is an alias or inherited member.
    inherited : bool
        Flag indicating whether the symbol originates from inheritance.
    is_alias : bool
        Flag indicating whether the symbol is represented as a Griffe alias.
    """

    path: str
    kind: str
    file: str | None
    lineno: int | None
    endlineno: int | None
    summary: str | None
    origin: str | None
    inherited: bool
    is_alias: bool


@dataclass(slots=True, frozen=True)
class NavMap:
    """Container for navmap metadata capturing the symbol structure of a codebase.

    A NavMap represents a snapshot of the symbol structure discovered during
    a traversal of package roots. It includes metadata about the generation
    context (commit SHA) and organizes all discovered symbols for efficient
    lookup and navigation.

    Attributes
    ----------
    commit : str | None
        Commit SHA used to generate the navmap, providing traceability to
        the exact code version that was analyzed.
    roots : list[str]
        Package roots that were loaded during navmap generation, indicating
        which top-level packages were included in the analysis.
    symbols : list[Symbol]
        Symbols discovered during traversal, representing all Python constructs
        (modules, classes, functions, etc.) found in the scanned packages.

    Parameters
    ----------
    commit : str | None
        Commit SHA used to generate the navmap.
    roots : list[str]
        Package roots that were loaded.
    symbols : list[Symbol]
        Symbols discovered during traversal.
    """

    commit: str | None
    roots: list[str]
    symbols: list[Symbol]


@dataclass(slots=True, frozen=True)
class NavmapBuildSettings:
    """Configuration flags controlling navmap generation."""

    docstring_parser: str | None
    include_inherited: bool
    resolve_external: bool


def _git_commit_sha() -> str | None:
    """Return the current Git commit SHA if available.

    Returns
    -------
    str | None
        Commit hash string when ``git`` is available, otherwise ``None``.
    """
    repo_root = Path.cwd()
    head_path = repo_root / ".git" / "HEAD"
    try:
        head_value = head_path.read_text(encoding="utf-8").strip()
    except OSError:  # pragma: no cover - git metadata unavailable
        return None
    if head_value.startswith("ref: "):
        ref = head_value[5:].strip()
        ref_path = repo_root / ".git" / ref
        try:
            content = ref_path.read_text(encoding="utf-8").strip()
        except OSError:  # pragma: no cover - ref missing
            return None
        else:
            return content or None
    return head_value or None


def _short_summary(doc: Docstring | None) -> str | None:
    """Return the first line of a docstring.

    Parameters
    ----------
    doc : Docstring | None
        Docstring instance retrieved from Griffe.

    Returns
    -------
    str | None
        First line of the docstring if present; ``None`` when unavailable.
    """
    if not doc:
        return None
    value = (doc.value or "").strip()
    if not value:
        return None
    return value.splitlines()[0]


def _symbol_kind(obj: Object | Alias) -> str:
    """Return a lowercase symbol kind for the provided object.

    Parameters
    ----------
    obj : Object | Alias
        Griffe model describing the symbol.

    Returns
    -------
    str
        Symbol kind in lowercase form (for example ``"function"``).
    """
    kind = getattr(obj, "kind", None)
    if isinstance(kind, str):
        return kind.lower()
    kind_name = getattr(kind, "name", None)
    if isinstance(kind_name, str):
        return kind_name.lower()
    return "alias" if isinstance(obj, Alias) else "object"


def _relpath(root: Path, path: Path | None) -> str | None:
    """Return ``path`` relative to ``root`` when possible.

    Parameters
    ----------
    root : Path
        Repository root used as reference.
    path : Path | None
        Path to relativize.

    Returns
    -------
    str | None
        Relative path string or ``None`` when ``path`` is not provided.
    """
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _safe_attr(obj: Object | Alias, attribute: str) -> object | None:
    """Return ``attribute`` from ``obj`` while guarding alias resolution failures.

    Parameters
    ----------
    obj : Object | Alias
        Griffe object whose attribute is accessed.
    attribute : str
        Attribute name to retrieve.

    Returns
    -------
    object | None
        Attribute value when available, otherwise ``None`` if resolution fails.
    """
    try:
        return getattr(obj, attribute)
    except (AliasResolutionError, BuiltinModuleError, CyclicAliasError, AttributeError):
        return None


def _collect_symbols(
    obj: Object | Alias,
    repo_root: Path,
    out: list[Symbol],
    seen: set[str],
    *,
    include_inherited: bool,
) -> None:
    """Traverse an object tree and append symbol records to ``out``.

    Parameters
    ----------
    obj : Object | Alias
        Griffe model representing the current object.
    repo_root : Path
        Repository root used to compute relative file paths.
    out : list[Symbol]
        Destination list for serialized symbols.
    seen : set[str]
        Set of object identifiers used to prevent infinite recursion.
    include_inherited : bool
        Whether inherited members should be traversed in addition to declared ones.
    """
    identifier = getattr(obj, "path", None) or getattr(obj, "name", None) or str(id(obj))
    if identifier in seen:
        return
    seen.add(identifier)

    is_alias = isinstance(obj, Alias)
    inherited = bool(getattr(obj, "inherited", False))
    origin: str | None = None
    if is_alias:
        origin_obj = _safe_attr(obj, "final_target")
        if origin_obj is not None and hasattr(origin_obj, "path"):
            origin = cast("str | None", getattr(origin_obj, "path", None))
        else:
            origin = cast("str | None", _safe_attr(obj, "target_path"))

    filepath_attr = _safe_attr(obj, "filepath")
    filepath = filepath_attr if isinstance(filepath_attr, Path) else None

    lineno_attr = _safe_attr(obj, "lineno")
    lineno = cast("int | None", lineno_attr) if isinstance(lineno_attr, int) else None

    endlineno_attr = _safe_attr(obj, "endlineno")
    endlineno = cast("int | None", endlineno_attr) if isinstance(endlineno_attr, int) else None

    doc_attr = _safe_attr(obj, "docstring")
    doc = cast("Docstring | None", doc_attr) if isinstance(doc_attr, Docstring) else None

    out.append(
        Symbol(
            path=obj.path,
            kind=_symbol_kind(obj),
            file=_relpath(repo_root, filepath),
            lineno=lineno,
            endlineno=endlineno,
            summary=_short_summary(doc),
            origin=origin,
            inherited=inherited,
            is_alias=is_alias,
        )
    )

    members = {} if is_alias else getattr(obj, "members", {})
    for member in members.values():
        _collect_symbols(member, repo_root, out, seen, include_inherited=include_inherited)

    if include_inherited and not is_alias:
        inherited_members = getattr(obj, "inherited_members", {})
        for inherited_member in inherited_members.values():
            _collect_symbols(
                inherited_member,
                repo_root,
                out,
                seen,
                include_inherited=include_inherited,
            )


def build_navmap(
    packages: Iterable[str],
    search_paths: Iterable[str],
    extensions: Iterable[str],
    settings: NavmapBuildSettings,
) -> NavMap:
    """Build a navmap using Griffe model traversal.

    Parameters
    ----------
    packages : Iterable[str]
        Package names to load.
    search_paths : Iterable[str]
        Additional search paths for module discovery.
    extensions : Iterable[str]
        Griffe extensions to enable.
    settings : NavmapBuildSettings
        Behavioural flags controlling docstring parsing, inheritance, and alias
        resolution preferences.

    Returns
    -------
    NavMap
        Dataclass containing commit metadata and discovered symbols.

    Raises
    ------
    ValueError
        Raised when the requested docstring parser is not supported by Griffe.
    """
    raw_parser = settings.docstring_parser
    if raw_parser is None:
        docstring_parser: Literal["auto", "google", "numpy", "sphinx"] | None = None
    elif raw_parser in {"auto", "google", "numpy", "sphinx"}:
        parser_map: dict[str, Literal["auto", "google", "numpy", "sphinx"]] = {
            "auto": "auto",
            "google": "google",
            "numpy": "numpy",
            "sphinx": "sphinx",
        }
        docstring_parser = parser_map[raw_parser]
    else:  # pragma: no cover - defensive guard
        message = f"Unsupported docstring parser '{raw_parser}'"
        raise ValueError(message)

    loader = GriffeLoader(
        search_paths=list(search_paths),
        allow_inspection=True,
        docstring_parser=docstring_parser,
        extensions=load_extensions(*extensions) if extensions else None,
    )

    modules: list[Module] = []
    for package in packages:
        module_obj = loader.load(package)
        if not isinstance(module_obj, Module):  # pragma: no cover - defensive guard
            LOGGER.warning("Loader returned non-module for package %s", package)
            continue
        module: Module = module_obj
        expand_exports = getattr(loader, "expand_exports", None)
        if callable(expand_exports):
            expand_exports(module)
        expand_wildcards = getattr(loader, "expand_wildcards", None)
        if callable(expand_wildcards):
            expand_wildcards(module)
        modules.append(module)

    resolve_aliases = getattr(loader, "resolve_aliases", None)
    if callable(resolve_aliases):
        try:
            resolve_aliases(
                implicit=True,
                external=settings.resolve_external or None,
            )
        except (
            AliasResolutionError,
            CyclicAliasError,
            ImportError,
            RuntimeError,
        ) as exc:  # pragma: no cover - degradation path
            LOGGER.warning(
                "Alias resolution encountered an error (external=%s): %s",
                settings.resolve_external,
                exc,
            )

    repo_root = Path.cwd()
    symbols: list[Symbol] = []
    seen: set[str] = set()
    for module in modules:
        _collect_symbols(
            module,
            repo_root,
            symbols,
            seen,
            include_inherited=settings.include_inherited,
        )

    return NavMap(commit=_git_commit_sha(), roots=list(packages), symbols=symbols)


def parse_args() -> argparse.Namespace:
    """Return parsed CLI arguments.

    Returns
    -------
    argparse.Namespace
        Namespace containing parsed command-line options.
    """
    parser = argparse.ArgumentParser(description="Generate a navmap JSON using Griffe's API model.")
    parser.set_defaults(include_inherited=True)
    parser.add_argument(
        "-p",
        "--package",
        action="append",
        required=True,
        help="Package to load (repeatable).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="tools/mkdocs_suite/site/_build/navmap/navmap.json",
        help="Destination JSON file for the navmap output.",
    )
    parser.add_argument(
        "--search-path",
        action="append",
        help="Additional module search path (repeatable).",
    )
    parser.add_argument(
        "--ext",
        action="append",
        help="Griffe extension to enable (repeatable).",
    )
    parser.add_argument(
        "--resolve-external",
        action="store_true",
        help="Resolve aliases pointing to external packages (may increase runtime).",
    )
    parser.add_argument(
        "--no-inherited",
        dest="include_inherited",
        action="store_false",
        help="Exclude inherited members from the navmap output.",
    )
    parser.add_argument(
        "--parser",
        default="numpy",
        choices=["numpy", "google", "sphinx", "auto"],
        help="Docstring parser to use when loading modules.",
    )
    args = parser.parse_args()

    if args.search_path is None:
        args.search_path = DEFAULT_SEARCH_PATHS.copy()
    if args.ext is None:
        args.ext = DEFAULT_EXTENSIONS.copy()
    if args.include_inherited is None:
        args.include_inherited = True

    return args


def main() -> None:
    """Entry point for the CLI."""
    args = parse_args()
    docstring_parser = None if args.parser == "auto" else args.parser

    settings = NavmapBuildSettings(
        docstring_parser=docstring_parser,
        include_inherited=args.include_inherited,
        resolve_external=args.resolve_external,
    )

    navmap = build_navmap(
        packages=args.package,
        search_paths=args.search_path,
        extensions=args.ext,
        settings=settings,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(navmap), handle, indent=2, ensure_ascii=False)
    LOGGER.info("Wrote navmap to %s", output_path)


if __name__ == "__main__":
    main()
