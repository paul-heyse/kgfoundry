#!/usr/bin/env python3
"""Generate symbol index delta between two builds for documentation caching."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from tools import (
    ProblemDetailsParams,
    build_problem_details,
    get_logger,
    observe_tool_run,
    render_problem,
    run_tool,
)
from tools._shared.proc import ToolExecutionError

from docs._scripts import shared
from docs._scripts.validation import validate_against_schema
from docs.types.artifacts import (
    SymbolDeltaChange,
    symbol_delta_to_payload,
)
from docs.types.artifacts import SymbolDeltaPayload as TypedSymbolDeltaPayload
from kgfoundry_common.errors import DeserializationError, SchemaValidationError, SerializationError

if TYPE_CHECKING:
    from tools import (
        ToolRunResult,
    )

ENV = shared.detect_environment()
shared.ensure_sys_paths(ENV)
SETTINGS = shared.load_settings()

DOCS_BUILD = SETTINGS.docs_build_dir
SYMBOLS_PATH = DOCS_BUILD / "symbols.json"
DEFAULT_DELTA_PATH = DOCS_BUILD / "symbols.delta.json"
SCHEMA_DIR = ENV.root / "schema" / "docs"
SYMBOL_DELTA_SCHEMA = SCHEMA_DIR / "symbol-delta.schema.json"

BASE_LOGGER = get_logger(__name__)
DELTA_LOG = shared.make_logger("symbol_delta", artifact="symbols.delta.json", logger=BASE_LOGGER)

GIT_TIMEOUT_SECONDS = 30.0
TRACKED_KEYS = {
    "canonical_path",
    "signature",
    "kind",
    "file",
    "lineno",
    "endlineno",
    "doc",
    "owner",
    "stability",
    "since",
    "deprecated_in",
    "section",
    "package",
    "module",
    "tested_by",
    "is_async",
    "is_property",
}

JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
JsonPayload = Mapping[str, JsonValue] | Sequence[JsonValue] | JsonValue
ProblemDetailsDict = dict[str, JsonValue]


def _validate_git_ref(ref: str) -> str:
    candidate = ref.strip()
    if not candidate:
        message = "Git reference must not be empty"
        raise ValueError(message)
    if candidate.startswith("-"):
        message = "Git reference must not begin with '-'"
        raise ValueError(message)
    return candidate


@dataclass(frozen=True, slots=True)
class SymbolRow:
    """Normalized symbol row extracted from ``symbols.json``."""

    path: str
    canonical_path: str | None = None
    signature: str | None = None
    kind: str | None = None
    file: str | None = None
    lineno: int | None = None
    endlineno: int | None = None
    doc: str | None = None
    owner: str | None = None
    stability: str | None = None
    since: str | None = None
    deprecated_in: str | None = None
    section: str | None = None
    package: str | None = None
    module: str | None = None
    tested_by: tuple[str, ...] = ()
    is_async: bool | None = None
    is_property: bool | None = None

    def to_payload(self) -> dict[str, JsonValue]:
        """Serialise the symbol row into a JSON-compatible mapping.

        Returns
        -------
        dict[str, JsonValue]
            JSON-compatible dictionary representation of the symbol row.
        """
        return {
            "path": self.path,
            "canonical_path": self.canonical_path,
            "signature": self.signature,
            "kind": self.kind,
            "file": self.file,
            "lineno": self.lineno,
            "endlineno": self.endlineno,
            "doc": self.doc,
            "owner": self.owner,
            "stability": self.stability,
            "since": self.since,
            "deprecated_in": self.deprecated_in,
            "section": self.section,
            "package": self.package,
            "module": self.module,
            "tested_by": list(self.tested_by),
            "is_async": self.is_async,
            "is_property": self.is_property,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, JsonValue]) -> SymbolRow | None:
        """Create a symbol row from ``payload`` when core fields are present.

        Parameters
        ----------
        payload : Mapping[str, JsonValue]
            Dictionary payload containing symbol metadata.

        Returns
        -------
        SymbolRow | None
            Symbol row instance if valid payload, None otherwise.
        """
        path_value = payload.get("path")
        if not isinstance(path_value, str):
            return None

        def _str_field(key: str) -> str | None:
            value = payload.get(key)
            return value if isinstance(value, str) else None

        def _int_field(key: str) -> int | None:
            value = payload.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
            return None

        def _bool_field(key: str) -> bool | None:
            value = payload.get(key)
            return value if isinstance(value, bool) else None

        tested_by_value = payload.get("tested_by")
        if isinstance(tested_by_value, list):
            tested_by = tuple(str(item) for item in tested_by_value)
        elif isinstance(tested_by_value, str):
            tested_by = (tested_by_value,)
        else:
            tested_by = ()

        return cls(
            path=path_value,
            canonical_path=_str_field("canonical_path"),
            signature=_str_field("signature"),
            kind=_str_field("kind"),
            file=_str_field("file"),
            lineno=_int_field("lineno"),
            endlineno=_int_field("endlineno"),
            doc=_str_field("doc"),
            owner=_str_field("owner"),
            stability=_str_field("stability"),
            since=_str_field("since"),
            deprecated_in=_str_field("deprecated_in"),
            section=_str_field("section"),
            package=_str_field("package"),
            module=_str_field("module"),
            tested_by=tested_by,
            is_async=_bool_field("is_async"),
            is_property=_bool_field("is_property"),
        )


def _coerce_json_value(value: object) -> JsonValue:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_coerce_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(k): _coerce_json_value(v) for k, v in value.items()}
    return str(value)


def _make_symbol_row(payload: Mapping[str, JsonValue]) -> SymbolRow | None:
    return SymbolRow.from_mapping(payload)


def _coerce_symbol_rows(data: object, *, source: str) -> list[SymbolRow]:
    if not isinstance(data, Sequence):
        message = f"{source} is not a JSON array"
        raise TypeError(message)
    rows: list[SymbolRow] = []
    for entry in data:
        if isinstance(entry, Mapping):
            candidate = _make_symbol_row(cast("Mapping[str, JsonValue]", entry))
            if candidate is not None:
                rows.append(candidate)
    return rows


def _load_symbol_rows(path: Path) -> list[SymbolRow]:
    """Load symbol rows from a JSON file.

    Parameters
    ----------
    path : Path
        Path to the JSON file containing symbol rows.

    Returns
    -------
    list[SymbolRow]
        Parsed symbol rows.

    Raises
    ------
    ValueError
        If the file cannot be read or parsed.
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - I/O error
        message = f"Failed to load symbol rows from {path}"
        raise ValueError(message) from exc
    return _coerce_symbol_rows(raw, source=str(path))


def _symbols_from_git_blob(blob: str, *, source: str) -> list[SymbolRow]:
    """Extract symbol rows from a Git blob content string.

    Parameters
    ----------
    blob : str
        JSON string content from a Git blob.
    source : str
        Source identifier for error messages.

    Returns
    -------
    list[SymbolRow]
        Parsed symbol rows.

    Raises
    ------
    ValueError
        If the blob does not contain valid JSON.
    """
    try:
        data: object = json.loads(blob)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        message = f"{source} does not contain valid JSON"
        raise ValueError(message) from exc
    return _coerce_symbol_rows(data, source=source)


def _git_rev_parse(ref: str) -> str | None:
    try:
        result: ToolRunResult = run_tool(
            ["git", "rev-parse", ref],
            cwd=ENV.root,
            timeout=GIT_TIMEOUT_SECONDS,
            check=True,
        )
    except ToolExecutionError:
        return None
    sha = result.stdout.strip()
    return sha or None


def _load_base_snapshot(arg: str) -> tuple[list[SymbolRow], str | None]:
    candidate = Path(arg)
    if candidate.exists():
        return _load_symbol_rows(candidate), _git_rev_parse("HEAD")

    try:
        ref = _validate_git_ref(arg)
    except ValueError as exc:
        message = str(exc)
        raise SystemExit(message) from exc

    try:
        result: ToolRunResult = run_tool(
            ["git", "show", f"{ref}:docs/_build/symbols.json"],
            cwd=ENV.root,
            timeout=GIT_TIMEOUT_SECONDS,
            check=True,
        )
    except ToolExecutionError:
        DELTA_LOG.warning(
            "No baseline symbols.json at git ref",
            extra={"status": "missing_baseline", "ref": ref},
        )
        return [], _git_rev_parse(ref)

    rows = _symbols_from_git_blob(result.stdout, source=f"git:{ref}")
    return rows, _git_rev_parse(ref)


def _index_rows(rows: list[SymbolRow]) -> dict[str, SymbolRow]:
    indexed: dict[str, SymbolRow] = {}
    for row in rows:
        indexed[row.path] = row
    return indexed


def _diff_rows(
    base: dict[str, SymbolRow],
    head: dict[str, SymbolRow],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[SymbolDeltaChange, ...]]:
    base_paths = set(base)
    head_paths = set(head)

    added = tuple(sorted(head_paths - base_paths))
    removed = tuple(sorted(base_paths - head_paths))

    changes: list[SymbolDeltaChange] = []
    for path in sorted(base_paths & head_paths):
        before_row = base[path]
        after_row = head[path]
        reasons: list[str] = []
        before_subset: dict[str, JsonValue] = {}
        after_subset: dict[str, JsonValue] = {}
        before_payload = before_row.to_payload()
        after_payload = after_row.to_payload()
        for key in sorted(TRACKED_KEYS):
            before_val = before_payload.get(key)
            after_val = after_payload.get(key)
            if before_val != after_val:
                reasons.append(key)
                if key in before_payload:
                    before_subset[key] = _coerce_json_value(before_payload[key])
                if key in after_payload:
                    after_subset[key] = _coerce_json_value(after_payload[key])
        if reasons:
            changes.append(
                SymbolDeltaChange(
                    path=path,
                    before=before_subset,
                    after=after_subset,
                    reasons=cast("tuple[str, ...]", tuple(reasons)),
                )
            )

    return added, removed, tuple(changes)


def _build_delta(
    *,
    base_rows: list[SymbolRow],
    head_rows: list[SymbolRow],
    base_sha: str | None,
    head_sha: str | None,
) -> TypedSymbolDeltaPayload:
    added, removed, changed = _diff_rows(_index_rows(base_rows), _index_rows(head_rows))
    return TypedSymbolDeltaPayload(
        base_sha=base_sha,
        head_sha=head_sha,
        added=added,
        removed=removed,
        changed=changed,
    )


def load_symbol_rows(path: Path) -> list[SymbolRow]:
    """Public wrapper for :func:`_load_symbol_rows`.

    Parameters
    ----------
    path : Path
        Path to the JSON file containing symbol rows.

    Returns
    -------
    list[SymbolRow]
        Parsed symbol rows.
    """
    return _load_symbol_rows(path)


def load_base_snapshot(arg: str) -> tuple[list[SymbolRow], str | None]:
    """Public wrapper for :func:`_load_base_snapshot`.

    Parameters
    ----------
    arg : str
        Git reference or path to baseline symbols.json snapshot.

    Returns
    -------
    tuple[list[SymbolRow], str | None]
        Tuple of (symbol rows, optional git SHA for the baseline).
    """
    return _load_base_snapshot(arg)


def git_rev_parse(ref: str) -> str | None:
    """Public wrapper for :func:`_git_rev_parse`.

    Parameters
    ----------
    ref : str
        Git reference to resolve.

    Returns
    -------
    str | None
        Git SHA of the reference, or None if the reference cannot be resolved.
    """
    return _git_rev_parse(ref)


def build_delta_payload(
    *,
    base_rows: list[SymbolRow],
    head_rows: list[SymbolRow],
    base_sha: str | None,
    head_sha: str | None,
) -> TypedSymbolDeltaPayload:
    """Public wrapper for :func:`_build_delta`.

    Parameters
    ----------
    base_rows : list[SymbolRow]
        Symbol rows from the baseline snapshot.
    head_rows : list[SymbolRow]
        Symbol rows from the current snapshot.
    base_sha : str | None
        Git SHA of the baseline snapshot, if available.
    head_sha : str | None
        Git SHA of the current snapshot, if available.

    Returns
    -------
    TypedSymbolDeltaPayload
        Symbol delta payload containing added, removed, and changed symbols.
    """
    return _build_delta(
        base_rows=base_rows,
        head_rows=head_rows,
        base_sha=base_sha,
        head_sha=head_sha,
    )


def write_delta(delta_path: Path, payload: TypedSymbolDeltaPayload) -> bool:
    """Write ``payload`` to ``delta_path`` and return True when a change occurred.

    Parameters
    ----------
    delta_path : Path
        Output file path for the delta.
    payload : TypedSymbolDeltaPayload
        Symbol delta payload to write.

    Returns
    -------
    bool
        True if file was written or changed, False if unchanged.
    """
    builtins_payload = symbol_delta_to_payload(payload)
    validate_against_schema(
        cast("JsonPayload", builtins_payload),
        SYMBOL_DELTA_SCHEMA,
        artifact=delta_path.name,
    )
    serialized = json.dumps(builtins_payload, indent=2, ensure_ascii=False) + "\n"
    if delta_path.exists():
        existing = delta_path.read_text(encoding="utf-8")
        if existing == serialized:
            DELTA_LOG.info(
                "Delta unchanged",
                extra={"status": "unchanged", "destination": str(delta_path)},
            )
            return False
    delta_path.parent.mkdir(parents=True, exist_ok=True)
    delta_path.write_text(serialized, encoding="utf-8")
    DELTA_LOG.info(
        "Delta written",
        extra={
            "status": "updated",
            "destination": str(delta_path),
            "added": len(payload.added),
            "removed": len(payload.removed),
            "changed": len(payload.changed),
        },
    )
    return True


def _emit_problem(problem: ProblemDetailsDict | None, *, default_message: str) -> None:
    payload = problem or build_problem_details(
        ProblemDetailsParams(
            type="https://kgfoundry.dev/problems/docs-symbol-delta",
            title="Symbol delta computation failed",
            status=500,
            detail=default_message,
            instance="urn:docs:symbol-delta:unknown",
        )
    )
    sys.stderr.write(render_problem(payload) + "\n")


@dataclass(slots=True, frozen=True)
class DeltaArgs:
    """Command-line arguments controlling delta computation."""

    base: str
    output: str


def parse_args(argv: Sequence[str] | None) -> DeltaArgs:
    """Parse CLI arguments and return a ``DeltaArgs`` instance.

    Parameters
    ----------
    argv : Sequence[str] | None
        Command-line arguments, defaults to sys.argv.

    Returns
    -------
    DeltaArgs
        Parsed arguments instance.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="HEAD~1",
        help="Git ref or path to the baseline symbols.json snapshot (default: HEAD~1)",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_DELTA_PATH),
        help="Destination delta file",
    )
    namespace = parser.parse_args(argv)
    base_arg = cast("str", getattr(namespace, "base", "HEAD~1"))
    output_arg = cast("str", getattr(namespace, "output", str(DEFAULT_DELTA_PATH)))
    return DeltaArgs(base=base_arg, output=output_arg)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for generating symbol delta artifacts.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Command-line arguments, defaults to sys.argv.

    Returns
    -------
    int
        Exit code: 0 on success, 1 on error, 130 on cancellation.

    Raises
    ------
    ToolExecutionError
        When git operations fail or baseline snapshot cannot be loaded.
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)

    args = parse_args(argv)
    delta_path = Path(args.output)

    if not SYMBOLS_PATH.exists():
        message = f"Missing current snapshot: {SYMBOLS_PATH}"
        _emit_problem(
            build_problem_details(
                ProblemDetailsParams(
                    type="https://kgfoundry.dev/problems/docs-symbol-delta",
                    title="Symbol delta computation failed",
                    status=404,
                    detail=message,
                    instance="urn:docs:symbol-delta:missing-current",
                )
            ),
            default_message=message,
        )
        return 1

    with observe_tool_run(["docs-symbol-delta"], cwd=ENV.root, timeout=None) as observation:
        try:
            head_rows = _load_symbol_rows(SYMBOLS_PATH)
            base_rows, base_sha = _load_base_snapshot(args.base)
            head_sha = _git_rev_parse("HEAD")
            payload = _build_delta(
                base_rows=base_rows,
                head_rows=head_rows,
                base_sha=base_sha,
                head_sha=head_sha,
            )
            write_delta(delta_path, payload)
        except ToolExecutionError as e:
            _emit_problem(e.problem, default_message=str(e))
            raise
        except KeyboardInterrupt:
            observation.failure("cancelled", returncode=130)
            DELTA_LOG.info("Symbol delta computation cancelled by user")
            return 130
        except (
            DeserializationError,
            SerializationError,
            SchemaValidationError,
            OSError,
            RuntimeError,
            json.JSONDecodeError,
        ) as exc:
            observation.failure("exception", returncode=1)
            problem = build_problem_details(
                ProblemDetailsParams(
                    type="https://kgfoundry.dev/problems/docs-symbol-delta",
                    title="Symbol delta computation failed",
                    status=500,
                    detail=str(exc),
                    instance="urn:docs:symbol-delta:unexpected-error",
                )
            )
            _emit_problem(problem, default_message=str(exc))
            return 1
        else:
            observation.success(0)

    DELTA_LOG.info(
        "Delta computation complete",
        extra={
            "status": "success",
            "destination": str(delta_path),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
