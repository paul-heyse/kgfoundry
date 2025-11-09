#!/usr/bin/env python3
"""Build schema-validated symbol index artifacts for the documentation pipeline."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable
from uuid import uuid4

from tools import (
    CliEnvelope,
    CliEnvelopeBuilder,
    ProblemDetailsParams,
    build_problem_details,
    get_logger,
    render_cli_envelope,
    render_problem,
    with_fields,
)
from tools._shared.error_codes import format_error_message
from tools._shared.proc import ToolExecutionError

from docs._scripts import cli_context, shared
from docs._scripts.validation import validate_against_schema
from kgfoundry_common.errors import (
    DeserializationError,
    SchemaValidationError,
    SerializationError,
)
from kgfoundry_common.optional_deps import OptionalDependencyError, safe_import_griffe

if TYPE_CHECKING:
    from collections.abc import Iterable

    from tools import (
        StructuredLoggerAdapter,
    )

    from kgfoundry_common.logging import LoggerAdapter


def _resolve_alias_resolution_error() -> type[Exception]:
    try:
        griffe_module = safe_import_griffe()
    except OptionalDependencyError:
        return Exception

    candidates: list[type[Exception] | None] = []

    exceptions_module = getattr(griffe_module, "exceptions", None)
    candidates.append(getattr(exceptions_module, "AliasResolutionError", None))

    internal_module = getattr(griffe_module, "_internal", None)
    if internal_module is not None:
        internal_exceptions = getattr(internal_module, "exceptions", None)
        candidates.append(getattr(internal_exceptions, "AliasResolutionError", None))

    for candidate in candidates:
        if isinstance(candidate, type) and issubclass(candidate, Exception):
            return candidate

    return Exception


AliasResolutionErrorType = _resolve_alias_resolution_error()

ENV = shared.detect_environment()
shared.ensure_sys_paths(ENV)
SETTINGS = shared.load_settings()
LOADER = shared.make_loader(ENV)

DOCS_BUILD = SETTINGS.docs_build_dir
SCHEMA_DIR = ENV.root / "schema" / "docs"
SYMBOLS_PATH = DOCS_BUILD / "symbols.json"
BY_FILE_PATH = DOCS_BUILD / "by_file.json"
BY_MODULE_PATH = DOCS_BUILD / "by_module.json"
SYMBOL_INDEX_SCHEMA = SCHEMA_DIR / "symbol-index.schema.json"
BASE_LOGGER = get_logger(__name__)

JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
JsonPayload = Mapping[str, JsonValue] | Sequence[JsonValue] | JsonValue
ProblemDetailsDict = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class LineSpan:
    """Start/end line span for a symbol."""

    start: int | None
    end: int | None


@dataclass(frozen=True, slots=True)
class NavLookup:
    """Lookup tables derived from the navmap payload."""

    symbol_meta: Mapping[str, Mapping[str, JsonValue]]
    module_meta: Mapping[str, Mapping[str, JsonValue]]
    sections: Mapping[str, str]

    @classmethod
    def empty(cls) -> NavLookup:
        """Return an empty nav lookup with default mappings.

        Returns
        -------
        NavLookup
            Empty nav lookup instance.
        """
        return cls(symbol_meta={}, module_meta={}, sections={})


@dataclass(frozen=True, slots=True)
class SymbolIndexRow:
    """In-memory representation of a symbol entry."""

    path: str
    canonical_path: str | None
    kind: str
    package: str | None
    module: str | None
    file: str | None
    span: LineSpan
    doc: str
    signature: str | None
    is_async: bool
    is_property: bool
    owner: str | None
    stability: str | None
    since: str | None
    deprecated_in: str | None
    section: str | None
    tested_by: tuple[str, ...]
    source_link: Mapping[str, str]

    def to_payload(self) -> dict[str, JsonValue]:
        """Return a JSON-compatible payload for the row.

        Returns
        -------
        dict[str, JsonValue]
            JSON-compatible dictionary representation.
        """
        return {
            "path": self.path,
            "canonical_path": self.canonical_path,
            "kind": self.kind,
            "package": self.package,
            "module": self.module,
            "file": self.file,
            "lineno": self.span.start,
            "endlineno": self.span.end,
            "doc": self.doc,
            "signature": self.signature,
            "is_async": self.is_async,
            "is_property": self.is_property,
            "owner": self.owner,
            "stability": self.stability,
            "since": self.since,
            "deprecated_in": self.deprecated_in,
            "section": self.section,
            "tested_by": list(self.tested_by),
            "source_link": dict(self.source_link),
        }


@dataclass(frozen=True, slots=True)
class SymbolIndexArtifacts:
    """Bundle of symbol index artifacts emitted by this script."""

    rows: tuple[SymbolIndexRow, ...]
    by_file: Mapping[str, tuple[str, ...]]
    by_module: Mapping[str, tuple[str, ...]]

    @property
    def symbol_count(self) -> int:
        """Return the number of symbols captured in the artifact.

        Returns
        -------
        int
            Number of symbol rows.
        """
        return len(self.rows)

    def rows_payload(self) -> list[dict[str, JsonValue]]:
        """Serialise the symbol rows into JSON-compatible dictionaries.

        Returns
        -------
        list[dict[str, JsonValue]]
            List of JSON-compatible row dictionaries.
        """
        return [row.to_payload() for row in self.rows]

    def by_file_payload(self) -> dict[str, list[str]]:
        """Return the file-to-symbol mapping as primitive JSON data.

        Returns
        -------
        dict[str, list[str]]
            File to symbol paths mapping.
        """
        return {key: list(values) for key, values in sorted(self.by_file.items())}

    def by_module_payload(self) -> dict[str, list[str]]:
        """Return the module-to-symbol mapping as primitive JSON data.

        Returns
        -------
        dict[str, list[str]]
            Module to symbol paths mapping.
        """
        return {key: list(values) for key, values in sorted(self.by_module.items())}


@dataclass(frozen=True, slots=True)
class SchemaValidation:
    """Schema validation metadata applied before writing an artifact."""

    schema: Path


@runtime_checkable
class GriffeNode(Protocol):
    """Subset of Griffe attributes consumed by the symbol index builder."""

    path: str
    canonical_path: object | None
    kind: object
    members: Mapping[str, GriffeNode] | None
    docstring: object | None
    relative_package_filepath: object | None
    relative_filepath: object | None
    lineno: int | float | None
    endlineno: int | float | None
    is_async: bool | None
    is_property: bool | None


def safe_getattr(
    obj: object, name: str, default: object | None = None
) -> object | None:
    """Return ``getattr`` with defensive error handling.

    This function safely retrieves attributes from objects, catching common
    exceptions that can occur during attribute access (AttributeError,
    RuntimeError, AliasResolutionError). It returns the default value when
    attribute access fails, making it useful for traversing potentially unstable
    object graphs.

    Parameters
    ----------
    obj : object
        Object to retrieve attribute from.
    name : str
        Attribute name to access.
    default : object | None, optional
        Default value to return if attribute cannot be accessed.
        Defaults to None.

    Returns
    -------
    object | None
        Attribute value or default if not found or error occurs.
    """
    try:
        return cast("object", getattr(obj, name, default))
    except (AttributeError, RuntimeError, AliasResolutionErrorType):
        return default


def _normalize_kind(node: GriffeNode) -> str | None:
    kind_obj = safe_getattr(node, "kind")
    if isinstance(kind_obj, str):
        return kind_obj
    value = safe_getattr(kind_obj, "value")
    return value if isinstance(value, str) else None


def _canonical_path(node: GriffeNode) -> str | None:
    canonical = safe_getattr(node, "canonical_path")
    if canonical is None:
        return None
    path_attr = safe_getattr(canonical, "path")
    if isinstance(path_attr, str):
        return path_attr
    if path_attr is not None:
        return str(path_attr)
    return str(canonical)


def _relative_file(node: GriffeNode) -> str | None:
    candidate = safe_getattr(node, "relative_package_filepath")
    if candidate is None:
        candidate = safe_getattr(node, "relative_filepath")
    if isinstance(candidate, Path):
        return candidate.as_posix()
    if isinstance(candidate, str):
        return candidate
    return None


def _coerce_int(value: object | None) -> int | None:
    if isinstance(value, bool):  # Guard against bool being int subclass
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _normalize_start_lineno(value: object | None) -> int:
    number = _coerce_int(value)
    if number is None or number <= 0:
        return 1
    return number


def _normalize_end_lineno(value: object | None) -> int | None:
    number = _coerce_int(value)
    if number is None or number <= 0:
        return None
    return number


def _doc_first_paragraph(node: GriffeNode) -> str:
    doc_obj = safe_getattr(node, "docstring")
    value = safe_getattr(doc_obj, "value")
    if isinstance(value, str):
        text = value.strip()
        if text:
            first = text.split("\n\n", 1)[0]
            return first.strip()
    return ""


def _normalize_tests(value: object | None) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(str(item) for item in value)
    return ()


def _module_for(path: str | None, kind: str) -> str | None:
    if path is None:
        return None
    if kind in {"module", "package"}:
        return path
    if "." in path:
        return path.rsplit(".", 1)[0]
    return path


def _package_for(module: str | None, path: str | None) -> str | None:
    target = module or path
    if not target:
        return None
    return target.split(".", 1)[0]


def _join_symbol(module: str, symbol: str) -> str:
    if symbol.startswith(module):
        return symbol
    if "." in symbol:
        return symbol
    return f"{module}.{symbol}"


def _meta_value(
    symbol_meta: Mapping[str, JsonValue] | None,
    module_defaults: Mapping[str, JsonValue] | None,
    key: str,
) -> str | None:
    if symbol_meta and key in symbol_meta:
        value = symbol_meta[key]
        if isinstance(value, str):
            return value
    if module_defaults and key in module_defaults:
        fallback = module_defaults[key]
        if isinstance(fallback, str):
            return fallback
    return None


def _row_section(
    nav: NavLookup,
    module: str | None,
    path: str,
    canonical: str | None,
    kind: str,
) -> str | None:
    direct = nav.sections.get(path)
    if direct:
        return direct
    if canonical:
        canonical_section = nav.sections.get(canonical)
        if canonical_section:
            return canonical_section
    if module:
        module_section = nav.sections.get(module)
        if module_section:
            return module_section
    if kind == "module":
        return "module"
    if kind == "class":
        return "class"
    return None


def _build_source_links(file_rel: str | None, span: LineSpan) -> dict[str, str]:
    if not file_rel:
        return {}
    absolute = (ENV.root / file_rel).resolve()
    links: dict[str, str] = {}
    start_line = span.start or 1
    if SETTINGS.link_mode in {"editor", "both"}:
        links["editor"] = f"vscode://file/{absolute}:{start_line}:1"
    if SETTINGS.link_mode in {"github", "both"}:
        github = build_github_permalink(Path(file_rel), span)
        if github:
            links["github"] = github
    return links


def _clean_meta(meta: Mapping[str, JsonValue] | None) -> dict[str, JsonValue]:
    if not isinstance(meta, Mapping):
        return {}
    return {key: value for key, value in meta.items() if value is not None}


def _record_module_defaults(
    module_name: str,
    payload: Mapping[str, JsonValue],
    module_meta: dict[str, dict[str, JsonValue]],
    symbol_meta: dict[str, dict[str, JsonValue]],
) -> dict[str, JsonValue]:
    defaults = _clean_meta(
        cast("Mapping[str, JsonValue] | None", payload.get("module_meta"))
    )
    module_meta[module_name] = defaults
    if defaults:
        symbol_meta.setdefault(module_name, dict(defaults))
    return defaults


def _record_symbol_meta(
    module_name: str,
    per_symbol_meta: Mapping[str, JsonValue] | None,
    symbol_meta: dict[str, dict[str, JsonValue]],
) -> None:
    if not isinstance(per_symbol_meta, Mapping):
        return
    for name, meta in per_symbol_meta.items():
        if not isinstance(name, str) or not isinstance(meta, Mapping):
            continue
        fq_name = _join_symbol(module_name, name)
        symbol_meta[fq_name] = _clean_meta(meta)


def _record_sections(
    module_name: str,
    sections_payload: Sequence[JsonValue] | None,
    sections: dict[str, str],
) -> None:
    if sections_payload is None:
        return
    for section_obj in sections_payload:
        if not isinstance(section_obj, Mapping):
            continue
        section_id = section_obj.get("id")
        if not isinstance(section_id, str):
            continue
        symbols = section_obj.get("symbols")
        if not isinstance(symbols, Sequence):
            continue
        for symbol in symbols:
            if not isinstance(symbol, str):
                continue
            fq_name = _join_symbol(module_name, symbol)
            sections[fq_name] = section_id


def _navmap_from_payload(data: Mapping[str, JsonValue]) -> NavLookup:
    symbol_meta: dict[str, dict[str, JsonValue]] = {}
    module_meta: dict[str, dict[str, JsonValue]] = {}
    sections: dict[str, str] = {}

    modules_value = data.get("modules")
    if not isinstance(modules_value, Mapping):
        return NavLookup.empty()
    modules_mapping = cast("Mapping[str, JsonValue]", modules_value)

    for module_name, payload in modules_mapping.items():
        if not isinstance(module_name, str) or not isinstance(payload, Mapping):
            continue
        payload_mapping = cast("Mapping[str, JsonValue]", payload)
        _record_module_defaults(module_name, payload_mapping, module_meta, symbol_meta)
        _record_symbol_meta(
            module_name,
            cast("Mapping[str, JsonValue] | None", payload_mapping.get("meta")),
            symbol_meta,
        )
        _record_sections(
            module_name,
            cast("Sequence[JsonValue] | None", payload_mapping.get("sections")),
            sections,
        )

    return NavLookup(
        symbol_meta=symbol_meta, module_meta=module_meta, sections=sections
    )


def load_nav_lookup() -> NavLookup:
    """Return navmap metadata if available.

    Returns
    -------
    NavLookup
        Nav lookup instance with metadata, or empty if unavailable.
    """
    for candidate in SETTINGS.navmap_candidates:
        if not candidate.exists():
            continue
        try:
            payload = cast(
                "JsonPayload", json.loads(candidate.read_text(encoding="utf-8"))
            )
        except json.JSONDecodeError as exc:
            BASE_LOGGER.warning(
                "Failed to parse navmap candidate",
                extra={
                    "status": "invalid_navmap",
                    "candidate": str(candidate),
                    "reason": str(exc),
                },
            )
            continue
        if isinstance(payload, Mapping):
            lookup = _navmap_from_payload(payload)
            BASE_LOGGER.info(
                "NavMap metadata loaded",
                extra={
                    "status": "loaded",
                    "candidate": str(candidate),
                    "symbol_meta": len(lookup.symbol_meta),
                    "module_meta": len(lookup.module_meta),
                    "sections": len(lookup.sections),
                },
            )
            return lookup
    BASE_LOGGER.info(
        "NavMap metadata unavailable",
        extra={"status": "missing_navmap"},
    )
    return NavLookup.empty()


def load_test_map() -> dict[str, JsonValue]:
    """Return the optional test map produced earlier in the docs pipeline.

    Returns
    -------
    dict[str, JsonValue]
        Test map dictionary, or empty dict if unavailable.
    """
    path = DOCS_BUILD / "test_map.json"
    if not path.exists():
        return {}
    try:
        payload = cast("JsonPayload", json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        BASE_LOGGER.warning(
            "Failed to parse test_map.json",
            extra={"status": "invalid_test_map", "path": str(path), "reason": str(exc)},
        )
        return {}
    if isinstance(payload, Mapping):
        return {str(key): value for key, value in payload.items()}
    return {}


def _iter_members(node: GriffeNode) -> Iterable[GriffeNode]:
    members = safe_getattr(node, "members")
    if isinstance(members, Mapping):
        return tuple(cast("GriffeNode", member) for member in members.values())
    return ()


def _row_from_node(
    node: GriffeNode,
    *,
    nav: NavLookup,
    test_map: Mapping[str, JsonValue],
) -> SymbolIndexRow | None:
    path_obj = safe_getattr(node, "path")
    if not isinstance(path_obj, str):
        return None

    kind = _normalize_kind(node)
    if kind is None:
        return None

    module = _module_for(path_obj, kind)
    package = _package_for(module, path_obj)
    file_rel = _relative_file(node)

    lineno = _normalize_start_lineno(safe_getattr(node, "lineno"))
    endlineno = _normalize_end_lineno(safe_getattr(node, "endlineno"))
    span = LineSpan(start=lineno, end=endlineno)

    canonical = _canonical_path(node)
    symbol_meta = nav.symbol_meta.get(path_obj)
    if symbol_meta is None and canonical:
        symbol_meta = nav.symbol_meta.get(canonical)
    module_defaults = nav.module_meta.get(module or "")

    tested_by = _normalize_tests(test_map.get(path_obj))
    if not tested_by and canonical:
        tested_by = _normalize_tests(test_map.get(canonical))

    signature_obj = safe_getattr(node, "signature")
    signature = str(signature_obj) if signature_obj is not None else None

    return SymbolIndexRow(
        path=path_obj,
        canonical_path=canonical,
        kind=kind,
        package=package,
        module=module,
        file=file_rel,
        span=span,
        doc=_doc_first_paragraph(node),
        signature=signature,
        is_async=bool(safe_getattr(node, "is_async")),
        is_property=bool(safe_getattr(node, "is_property")),
        owner=_meta_value(symbol_meta, module_defaults, "owner"),
        stability=_meta_value(symbol_meta, module_defaults, "stability"),
        since=_meta_value(symbol_meta, module_defaults, "since"),
        deprecated_in=_meta_value(symbol_meta, module_defaults, "deprecated_in"),
        section=_row_section(nav, module, path_obj, canonical, kind),
        tested_by=tested_by,
        source_link=_build_source_links(file_rel, span),
    )


def _collect_rows(
    node: GriffeNode,
    *,
    nav: NavLookup,
    test_map: Mapping[str, JsonValue],
) -> list[SymbolIndexRow]:
    """Collect symbol index rows from a Griffe node tree.

    Parameters
    ----------
    node : GriffeNode
        Root Griffe node to traverse.
    nav : NavLookup
        Navigation lookup for metadata.
    test_map : Mapping[str, JsonValue]
        Test mapping for symbol metadata.

    Returns
    -------
    list[SymbolIndexRow]
        List of collected symbol index rows.
    """
    rows: list[SymbolIndexRow] = []
    stack: list[GriffeNode] = [node]
    while stack:
        current = stack.pop()
        row = _row_from_node(current, nav=nav, test_map=test_map)
        if row is not None:
            rows.append(row)
        stack.extend(_iter_members(current))
    return rows


def _build_reverse_map(
    rows: Sequence[SymbolIndexRow], attribute: str
) -> dict[str, tuple[str, ...]]:
    """Build reverse mapping from attribute value to symbol paths.

    Parameters
    ----------
    rows : Sequence[SymbolIndexRow]
        Symbol index rows to process.
    attribute : str
        Attribute name to use for mapping.

    Returns
    -------
    dict[str, tuple[str, ...]]
        Mapping from attribute value to sorted tuple of symbol paths.
    """
    mapping: dict[str, set[str]] = {}
    for row in rows:
        value = cast("object", getattr(row, attribute))
        if isinstance(value, str):
            if value not in mapping:
                mapping[value] = set()
            mapping[value].add(row.path)
    return {key: tuple(sorted(paths)) for key, paths in sorted(mapping.items())}


def generate_index(
    packages: Sequence[str],
    loader: shared.GriffeLoader,
) -> SymbolIndexArtifacts:
    """Produce typed symbol index artifacts for ``packages``.

    Parameters
    ----------
    packages : Sequence[str]
        Package names to index.
    loader : shared.GriffeLoader
        Griffe loader instance.

    Returns
    -------
    SymbolIndexArtifacts
        Complete symbol index artifacts bundle.
    """
    nav_lookup = load_nav_lookup()
    test_map = load_test_map()
    rows: list[SymbolIndexRow] = []
    for package in packages:
        root = cast("GriffeNode", loader.load(package))
        rows.extend(_collect_rows(root, nav=nav_lookup, test_map=test_map))

    def get_row_path(row: SymbolIndexRow) -> str:
        """Extract path for sorting.

        Parameters
        ----------
        row : SymbolIndexRow
            Symbol index row.

        Returns
        -------
        str
            Symbol path.
        """
        return row.path

    rows_sorted = tuple(sorted(rows, key=get_row_path))
    by_file = _build_reverse_map(rows_sorted, "file")
    by_module = _build_reverse_map(rows_sorted, "module")
    return SymbolIndexArtifacts(rows=rows_sorted, by_file=by_file, by_module=by_module)


@lru_cache(maxsize=1)
def _git_sha() -> str:
    """Return the Git SHA for permalink construction.

    Returns
    -------
    str
        Git commit SHA.
    """
    return shared.resolve_git_sha(ENV, SETTINGS, logger=BASE_LOGGER)


def build_github_permalink(file: Path, span: LineSpan) -> str | None:
    """Return a commit-stable GitHub permalink for ``file`` when configured.

    Parameters
    ----------
    file : Path
        Source file path.
    span : LineSpan
        Line span for fragment.

    Returns
    -------
    str | None
        GitHub permalink URL, or None if not configured.
    """
    if not (SETTINGS.github_org and SETTINGS.github_repo):
        return None
    sha = _git_sha()
    fragment = ""
    if span.start is not None and span.end is not None and span.end >= span.start:
        fragment = f"#L{span.start}-L{span.end}"
    elif span.start is not None:
        fragment = f"#L{span.start}"
    relative = file.as_posix()
    return (
        "https://github.com/"
        f"{SETTINGS.github_org}/{SETTINGS.github_repo}/blob/{sha}/{relative}{fragment}"
    )


def write_artifact(
    path: Path,
    payload: object,
    *,
    logger: StructuredLoggerAdapter,
    artifact: str,
    validation: SchemaValidation | None = None,
) -> bool:
    """Validate (when configured) and write ``payload`` to ``path`` if it changed.

    Parameters
    ----------
    path : Path
        Output file path.
    payload : object
        Payload to serialize.
    logger : StructuredLoggerAdapter
        Logger instance.
    artifact : str
        Artifact name for logging.
    validation : SchemaValidation | None, optional
        Optional schema validation configuration.

    Returns
    -------
    bool
        True if file was written, False if unchanged.
    """
    if validation is not None:
        validate_against_schema(
            cast("JsonPayload", payload),
            validation.schema,
            artifact=artifact,
        )
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == serialized:
            logger.info(
                "Artifact already up-to-date",
                extra={"status": "unchanged", "path": str(path)},
            )
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")
    logger.info(
        "Artifact written",
        extra={"status": "updated", "path": str(path)},
    )
    return True


def iter_packages() -> list[str]:
    """Return packages configured for documentation builds (compatibility helper).

    Returns
    -------
    list[str]
        List of package names.
    """
    return list(SETTINGS.packages)


def safe_attr(node: object, attr: str, default: object | None = None) -> object | None:
    """Compatibility wrapper delegating to :func:`safe_getattr`.

    Parameters
    ----------
    node : object
        Object to get attribute from.
    attr : str
        Attribute name.
    default : object | None, optional
        Default value if attribute not found.

    Returns
    -------
    object | None
        Attribute value or default.
    """
    return safe_getattr(node, attr, default)


def _coerce_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_coerce_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _coerce_json_value(item) for key, item in value.items()}
    return str(value)


def _normalize_json_mapping(values: Mapping[str, object]) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {}
    for key, value in values.items():
        payload[str(key)] = _coerce_json_value(value)
    return payload


_CLI_DEFINITION = cli_context.get_cli_definition("docs-build-symbol-index")
_CLI_COMMAND = _CLI_DEFINITION.command
_CLI_SUBCOMMAND = "build"
_CLI_OPERATION_ID = _CLI_DEFINITION.operation_ids["build"]
_CLI_ENVELOPE_DIR = cli_context.REPO_ROOT / "site" / "_build" / "cli"
_PROBLEM_TYPE = "https://kgfoundry.dev/problems/docs-symbol-index"


def _envelope_path(subcommand: str) -> Path:
    safe = subcommand or "root"
    return _CLI_ENVELOPE_DIR / f"{_CLI_DEFINITION.command}-{safe}.json"


def _write_envelope(envelope: CliEnvelope, *, logger: LoggerAdapter) -> Path:
    _CLI_ENVELOPE_DIR.mkdir(parents=True, exist_ok=True)
    path = _envelope_path(_CLI_SUBCOMMAND)
    rendered = render_cli_envelope(envelope)
    path.write_text(f"{rendered}\n", encoding="utf-8")
    logger.debug(
        "CLI envelope written",
        extra={"status": envelope.status, "cli_envelope": str(path)},
    )
    return path


def _build_failure_problem(
    detail: str,
    *,
    status: int,
    extras: Mapping[str, object] | None = None,
) -> ProblemDetailsDict:
    extensions = _normalize_json_mapping(extras) if extras else None
    return build_problem_details(
        ProblemDetailsParams(
            type=_PROBLEM_TYPE,
            title="Symbol index build failed",
            status=status,
            detail=detail,
            instance=f"urn:cli:{_CLI_DEFINITION.command}:{_CLI_SUBCOMMAND}",
            extensions=extensions,
        )
    )


@dataclass(slots=True, frozen=True)
class _FailureContext:
    """Contextual information captured when the CLI fails."""

    duration_seconds: float
    message: str
    exit_code: int
    exc_info: BaseException | None


def _handle_tool_error(
    exc: ToolExecutionError,
    packages: Sequence[str],
    *,
    logger: LoggerAdapter,
    start_time: float,
) -> int:
    duration = time.monotonic() - start_time
    extras: dict[str, object] = {
        "packages": list(packages),
        "command": list(exc.command),
        "returncode": exc.returncode,
    }
    problem = exc.problem or _build_failure_problem(str(exc), status=500, extras=extras)
    message = format_error_message(
        "KGF-DOC-SYM-001",
        "Symbol index build failed",
        details=str(exc),
    )
    context = _FailureContext(
        duration_seconds=duration,
        message=message,
        exit_code=exc.returncode if exc.returncode is not None else 1,
        exc_info=exc,
    )
    failure_builder = CliEnvelopeBuilder.create(
        command=_CLI_DEFINITION.command,
        status="error",
        subcommand=_CLI_SUBCOMMAND,
    )
    failure_builder = failure_builder.add_error(
        status="error", message=context.message, problem=problem
    )
    failure_builder = failure_builder.set_problem(problem)
    for path in (SYMBOLS_PATH, BY_FILE_PATH, BY_MODULE_PATH):
        failure_builder = failure_builder.add_file(
            path=str(path),
            status="error",
            message="Artifact not updated due to failure",
            problem=problem,
        )
    envelope = failure_builder.finish(duration_seconds=context.duration_seconds)
    path = _write_envelope(envelope, logger=logger)
    sys.stderr.write(render_problem(problem) + "\n")
    logger.error(
        context.message,
        extra={
            "status": "error",
            "cli_envelope": str(path),
            "duration_seconds": context.duration_seconds,
            "exit_code": context.exit_code,
        },
        exc_info=context.exc_info,
    )
    return context.exit_code


def _handle_keyboard_interrupt(
    exc: BaseException,
    packages: Sequence[str],
    *,
    logger: LoggerAdapter,
    start_time: float,
) -> int:
    duration = time.monotonic() - start_time
    problem = _build_failure_problem(
        "Symbol index build cancelled",
        status=499,
        extras={"packages": list(packages)},
    )
    context = _FailureContext(
        duration_seconds=duration,
        message="Symbol index build cancelled",
        exit_code=130,
        exc_info=exc,
    )
    failure_builder = CliEnvelopeBuilder.create(
        command=_CLI_DEFINITION.command,
        status="error",
        subcommand=_CLI_SUBCOMMAND,
    )
    failure_builder = failure_builder.add_error(
        status="error", message=context.message, problem=problem
    )
    failure_builder = failure_builder.set_problem(problem)
    for path in (SYMBOLS_PATH, BY_FILE_PATH, BY_MODULE_PATH):
        failure_builder = failure_builder.add_file(
            path=str(path),
            status="error",
            message="Artifact not updated due to failure",
            problem=problem,
        )
    envelope = failure_builder.finish(duration_seconds=context.duration_seconds)
    path = _write_envelope(envelope, logger=logger)
    sys.stderr.write(render_problem(problem) + "\n")
    logger.error(
        context.message,
        extra={
            "status": "error",
            "cli_envelope": str(path),
            "duration_seconds": context.duration_seconds,
            "exit_code": context.exit_code,
        },
        exc_info=context.exc_info,
    )
    return context.exit_code


def _handle_unexpected_error(
    exc: Exception,
    packages: Sequence[str],
    *,
    logger: LoggerAdapter,
    start_time: float,
) -> int:
    duration = time.monotonic() - start_time
    problem = _build_failure_problem(
        str(exc),
        status=500,
        extras={"packages": list(packages)},
    )
    message = format_error_message(
        "KGF-DOC-SYM-002",
        "Symbol index build failed",
        details=str(exc),
    )
    context = _FailureContext(
        duration_seconds=duration,
        message=message,
        exit_code=1,
        exc_info=exc,
    )
    failure_builder = CliEnvelopeBuilder.create(
        command=_CLI_DEFINITION.command,
        status="error",
        subcommand=_CLI_SUBCOMMAND,
    )
    failure_builder = failure_builder.add_error(
        status="error", message=context.message, problem=problem
    )
    failure_builder = failure_builder.set_problem(problem)
    for path in (SYMBOLS_PATH, BY_FILE_PATH, BY_MODULE_PATH):
        failure_builder = failure_builder.add_file(
            path=str(path),
            status="error",
            message="Artifact not updated due to failure",
            problem=problem,
        )
    envelope = failure_builder.finish(duration_seconds=context.duration_seconds)
    path = _write_envelope(envelope, logger=logger)
    sys.stderr.write(render_problem(problem) + "\n")
    logger.error(
        context.message,
        extra={
            "status": "error",
            "cli_envelope": str(path),
            "duration_seconds": context.duration_seconds,
            "exit_code": context.exit_code,
        },
        exc_info=context.exc_info,
    )
    return context.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """Build documentation symbol index artifacts with CLI envelope output.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Command-line arguments. Currently unused, reserved for future CLI arguments.

    Returns
    -------
    int
        Exit code: ``0`` on success, non-zero when failures occur.
    """
    del argv  # reserved for future CLI arguments

    correlation_id = uuid4().hex
    logger = with_fields(
        get_logger(__name__),
        correlation_id=correlation_id,
        command=_CLI_DEFINITION.command,
        subcommand=_CLI_SUBCOMMAND,
        operation_id=_CLI_OPERATION_ID,
    )
    builder = CliEnvelopeBuilder.create(
        command=_CLI_DEFINITION.command,
        status="success",
        subcommand=_CLI_SUBCOMMAND,
    )

    packages = [str(pkg) for pkg in SETTINGS.packages or ()]
    start = time.monotonic()

    try:
        artifacts = generate_index(packages, LOADER)
        artifact_specs: Sequence[tuple[str, Path, object, SchemaValidation | None]] = (
            (
                "symbols.json",
                SYMBOLS_PATH,
                artifacts.rows_payload(),
                SchemaValidation(schema=SYMBOL_INDEX_SCHEMA),
            ),
            (
                "by_file.json",
                BY_FILE_PATH,
                artifacts.by_file_payload(),
                None,
            ),
            (
                "by_module.json",
                BY_MODULE_PATH,
                artifacts.by_module_payload(),
                None,
            ),
        )
        artifact_results: list[tuple[str, Path, bool]] = []
        for name, path, payload, validation in artifact_specs:
            artifact_logger = with_fields(logger, artifact=name)
            wrote = write_artifact(
                path,
                payload,
                logger=artifact_logger,
                artifact=name,
                validation=validation,
            )
            artifact_results.append((name, path, wrote))
    except ToolExecutionError as exc:
        return _handle_tool_error(exc, packages, logger=logger, start_time=start)
    except KeyboardInterrupt as exc:
        return _handle_keyboard_interrupt(
            exc, packages, logger=logger, start_time=start
        )
    except (
        DeserializationError,
        SerializationError,
        SchemaValidationError,
        OSError,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        return _handle_unexpected_error(exc, packages, logger=logger, start_time=start)

    duration = time.monotonic() - start
    for name, path, wrote in artifact_results:
        builder = builder.add_file(
            path=str(path),
            status="success" if wrote else "skipped",
            message=f"{name} updated" if wrote else f"{name} unchanged",
        )

    envelope = builder.finish(duration_seconds=duration)
    path = _write_envelope(envelope, logger=logger)

    wrote_lookup = {name: wrote for name, _, wrote in artifact_results}
    logger.info(
        "Symbol index build complete",
        extra={
            "status": "success",
            "symbols_entries": artifacts.symbol_count,
            "symbols_updated": wrote_lookup.get("symbols.json", False),
            "by_file_updated": wrote_lookup.get("by_file.json", False),
            "by_module_updated": wrote_lookup.get("by_module.json", False),
            "cli_envelope": str(path),
            "duration_seconds": duration,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
