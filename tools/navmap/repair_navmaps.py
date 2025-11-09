"""Overview of repair navmaps.

This module bundles repair navmaps logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

from __future__ import annotations

import argparse
import ast
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from pprint import pformat
from typing import TYPE_CHECKING, cast

from tools import (
    CliEnvelopeBuilder,
    ProblemDetailsParams,
    build_problem_details,
    get_logger,
    render_cli_envelope,
    validate_cli_envelope,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from tools import (
        CliEnvelope,
    )
    from tools.navmap.build_navmap import ModuleInfo

LOGGER = get_logger(__name__)

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"

try:
    from tools.navmap.build_navmap import collect_module_info
except (
    ModuleNotFoundError
) as exc:  # pragma: no cover - clearer guidance for packaging installs
    message = (
        "tools.navmap.repair_navmaps requires the tooling optional extra. "
        "Install with `pip install kgfoundry[tools]` (or `pip install -e .[tools]` in development) "
        "before invoking this script."
    )
    raise ModuleNotFoundError(message) from exc

type SymbolMetadata = dict[str, str]


@dataclass(frozen=True)
class RepairResult:
    """Aggregate outcome for repairing a single module."""

    module: Path
    messages: list[str]
    changed: bool
    applied: bool


@dataclass(frozen=True)
class RepairExecutionConfig:
    """Execution options controlling how repairs are applied and reported."""

    apply_changes: bool = False
    emit_json: bool = False


@dataclass(frozen=True)
class RepairArgs:
    """CLI arguments normalized for downstream consumption."""

    root: Path
    config: RepairExecutionConfig


def _collect_modules(root: Path) -> list[ModuleInfo]:
    """Collect all modules under root directory.

    Parameters
    ----------
    root : Path
        Root directory to scan for Python modules.

    Returns
    -------
    list[ModuleInfo]
        List of module metadata objects.
    """
    modules: list[ModuleInfo] = []
    for py in sorted(root.rglob("*.py")):
        info = collect_module_info(py)
        if info:
            modules.append(info)
    return modules


def _load_tree(path: Path) -> ast.Module:
    """Parse Python file and return AST module.

    Parameters
    ----------
    path : Path
        Python file to parse.

    Returns
    -------
    ast.Module
        Parsed AST module.
    """
    text = path.read_text(encoding="utf-8")
    return ast.parse(text, filename=str(path))


def _definition_lines(tree: ast.Module) -> dict[str, int]:
    """Extract line numbers for top-level definitions.

    Parameters
    ----------
    tree : ast.Module
        Module AST to extract definitions from.

    Returns
    -------
    dict[str, int]
        Dictionary mapping symbol names to their line numbers.
    """
    lines: dict[str, int] = {}
    for node in tree.body:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                lines[node.name] = node.lineno
            case ast.ClassDef():
                lines[node.name] = node.lineno
            case ast.Assign(targets=targets):
                for target in targets:
                    if isinstance(target, ast.Name):
                        lines[target.id] = node.lineno
            case ast.AnnAssign(target=target):
                if isinstance(target, ast.Name):
                    lines[target.id] = node.lineno
    return lines


def _docstring_end(tree: ast.Module) -> int | None:
    """Return the ending line number of the module docstring.

    Parameters
    ----------
    tree : ast.Module
        Module AST to inspect.

    Returns
    -------
    int | None
        Ending line number of docstring, | None if no docstring.
    """
    if not tree.body:
        return None
    node = tree.body[0]
    if (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ):
        end_lineno = cast("int | None", getattr(node, "end_lineno", None))
        return end_lineno if isinstance(end_lineno, int) else node.lineno
    return None


def _all_assignment_end(tree: ast.Module) -> int | None:
    """Return the ending line number of the __all__ assignment.

    Parameters
    ----------
    tree : ast.Module
        Module AST to inspect.

    Returns
    -------
    int | None
        Ending line number of __all__ assignment, | None if not found.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    end_lineno = cast("int | None", getattr(node, "end_lineno", None))
                    return end_lineno if isinstance(end_lineno, int) else node.lineno
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
        ):
            end_lineno = cast("int | None", getattr(node, "end_lineno", None))
            return end_lineno if isinstance(end_lineno, int) else node.lineno
    return None


def _navmap_assignment_span(tree: ast.Module) -> tuple[int, int] | None:
    """Return the line span of the __navmap__ assignment.

    Parameters
    ----------
    tree : ast.Module
        Module AST to inspect.

    Returns
    -------
    tuple[int, int] | None
        Tuple of (start_line, end_line) for __navmap__ assignment,
        | None if not found.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: Iterable[ast.expr] = node.targets
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.expr):
            targets = (node.target,)
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "__navmap__":
                start = node.lineno
                end_lineno = cast("int | None", getattr(node, "end_lineno", None))
                end = end_lineno if isinstance(end_lineno, int) else start
                return start, end
    return None


def _serialize_navmap(navmap: Mapping[str, object]) -> list[str]:
    """Serialize navmap dictionary to source code lines.

    Parameters
    ----------
    navmap : Mapping[str, object]
        Navmap dictionary to serialize.

    Returns
    -------
    list[str]
        List of source code lines representing __navmap__ assignment.
    """
    literal = "__navmap__ = " + pformat(dict(navmap), width=88, sort_dicts=True)
    return literal.splitlines()


def _ensure_navmap_structure(info: ModuleInfo) -> dict[str, object]:
    """Ensure navmap has required structure with defaults applied.

    Parameters
    ----------
    info : ModuleInfo
        Module metadata to build navmap structure from.

    Returns
    -------
    dict[str, object]
        Normalized navmap dictionary.
    """
    raw_navmap = info.navmap_dict if info.navmap_dict else {}
    navmap = cast("dict[str, object]", dict(raw_navmap))
    exports = _normalize_exports(navmap.get("exports"), info.exports)
    navmap["exports"] = exports

    section_dicts = _collect_section_dicts(navmap.get("sections"))
    navmap["sections"] = _build_sections(section_dicts, exports)

    module_meta = _normalized_module_meta(navmap)
    if module_meta:
        navmap["module_meta"] = module_meta

    symbols_meta = _normalized_symbols(navmap.get("symbols"))
    _apply_symbol_defaults(symbols_meta, exports, module_meta)
    navmap["symbols"] = symbols_meta

    return navmap


def repair_module(
    info: ModuleInfo,
    *,
    execution: RepairExecutionConfig,
) -> RepairResult:
    """Repair a single module's navmap metadata and optionally persist fixes.

    This function analyzes a module's navmap metadata and applies automated fixes
    including: inserting missing anchor markers, adding public API sections, and
    synchronizing the navmap literal with actual module exports. Changes can be
    applied in dry-run mode (inspection only) or persisted to disk.

    Parameters
    ----------
    info : ModuleInfo
        Metadata describing the target module discovered by ``build_navmap``,
        including file path, exports, and existing navmap structure.
    execution : RepairExecutionConfig
        Execution options controlling whether changes are applied to disk or
        only reported. Includes flags for dry-run mode and change persistence.

    Returns
    -------
    RepairResult
        Outcome describing emitted messages alongside change and apply flags.
        The messages list contains human-readable descriptions of all fixes
        that were applied or would be applied.
    """
    path = info.path
    original_text = path.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    tree = _load_tree(path)

    exports = _normalize_exports((info.navmap_dict or {}).get("exports"), info.exports)
    messages: list[str] = []

    insertions, anchor_messages = _collect_anchor_insertions(
        info, exports, _definition_lines(tree)
    )
    messages.extend(anchor_messages)

    section_insertion = _public_api_insertion(info, tree)
    if section_insertion is not None:
        insertions.append(section_insertion)
        messages.append(
            f"{path}: inserted [nav:section public-api] after line {section_insertion[0]}"
        )

    changed = _apply_insertions(lines, insertions)

    nav_changed, nav_messages = _sync_navmap_literal(
        info, tree, original_text, lines, exports
    )
    changed = changed or nav_changed
    messages.extend(nav_messages)

    if changed and execution.apply_changes:
        new_text = "\n".join(lines)
        if not new_text.endswith("\n"):
            new_text += "\n"
        path.write_text(new_text, encoding="utf-8")

    return RepairResult(
        module=path,
        messages=messages,
        changed=changed,
        applied=changed and execution.apply_changes,
    )


def repair_all(root: Path, *, execution: RepairExecutionConfig) -> list[RepairResult]:
    """Repair every module under ``root`` and aggregate the results.

    Parameters
    ----------
    root : Path
        Root directory to scan for modules.
    execution : RepairExecutionConfig
        Execution configuration controlling repair behavior.

    Returns
    -------
    list[RepairResult]
        List of repair results for all modules found.
    """
    return [repair_module(info, execution=execution) for info in _collect_modules(root)]


def _parse_args(argv: list[str] | None = None) -> RepairArgs:
    """Parse CLI arguments for navmap repair utility.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments, by default None.

    Returns
    -------
    RepairArgs
        Parsed arguments and configuration.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=SRC,
        help="Directory tree to scan for navmap metadata (default: %(default)s).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write fixes back to disk instead of printing suggested changes.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable results to stdout using the base CLI envelope schema.",
    )
    namespace = parser.parse_args(argv)
    root_arg = cast("Path", namespace.root)
    apply_flag = cast("bool", namespace.apply)
    json_flag = cast("bool", namespace.json)
    execution = RepairExecutionConfig(apply_changes=apply_flag, emit_json=json_flag)
    return RepairArgs(root=root_arg, config=execution)


def _build_json_envelope(
    messages: list[str],
    duration: float,
    *,
    has_issues: bool,
    execution: RepairExecutionConfig,
) -> CliEnvelope:
    """Build CLI envelope JSON payload for repair results.

    Parameters
    ----------
    messages : list[str]
        List of repair messages.
    duration : float
        Operation duration in seconds.
    has_issues : bool
        Whether any issues were detected.
    execution : RepairExecutionConfig
        Execution configuration used for the repair.

    Returns
    -------
    CliEnvelope
        CLI envelope JSON payload.
    """
    builder = CliEnvelopeBuilder.create(
        command="repair_navmaps",
        status="violation" if has_issues else "success",
        subcommand="repair",
    )

    if has_issues:
        for msg in messages:
            if ": " in msg:
                file_path, detail = msg.split(": ", 1)
                builder = builder.add_file(
                    path=file_path,
                    status="violation",
                    message=detail,
                )
                builder = builder.add_error(
                    status="violation",
                    message=detail,
                    file=file_path,
                )
            else:
                builder = builder.add_error(
                    status="violation",
                    message=msg,
                )

        if not execution.apply_changes:
            builder = builder.set_problem(
                build_problem_details(
                    ProblemDetailsParams(
                        type="https://kgfoundry.dev/problems/navmap-repair-needed",
                        title="Navmap repair needed",
                        status=422,
                        detail=(
                            f"Found {len(messages)} issue(s) requiring repair. Re-run with --apply to write fixes."
                        ),
                        instance="urn:navmap:repair:issues-detected",
                        extensions={
                            "issue_count": len(messages),
                            "apply_required": True,
                        },
                    )
                )
            )

    return builder.finish(duration_seconds=duration)


def _build_error_envelope(exc: Exception, duration: float) -> CliEnvelope:
    """Build CLI envelope JSON payload for error cases.

    Parameters
    ----------
    exc : Exception
        Exception that occurred.
    duration : float
        Operation duration in seconds.

    Returns
    -------
    CliEnvelope
        CLI envelope JSON payload with error details.
    """
    builder = CliEnvelopeBuilder.create(
        command="repair_navmaps", status="error", subcommand="repair"
    )
    builder = builder.add_error(
        status="error",
        message=str(exc),
    )
    builder = builder.set_problem(
        build_problem_details(
            ProblemDetailsParams(
                type="https://kgfoundry.dev/problems/navmap-repair-error",
                title="Navmap repair failed",
                status=500,
                detail=str(exc),
                instance="urn:navmap:repair:error",
                extensions={"exception_type": exc.__class__.__name__},
            )
        )
    )
    return builder.finish(duration_seconds=duration)


def main(argv: list[str] | None = None) -> int:
    """Run navmap repair utility and return exit code.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments, by default None.

    Returns
    -------
    int
        Exit code (0 on success, 1 on errors).
    """
    start_time = time.monotonic()
    args = _parse_args(argv)
    root = args.root.resolve()

    try:
        results = repair_all(root, execution=args.config)
        messages = [msg for result in results for msg in result.messages]
        duration = time.monotonic() - start_time
        has_issues = any(result.changed or result.messages for result in results)

        if args.config.emit_json:
            envelope = _build_json_envelope(
                messages,
                duration,
                has_issues=has_issues,
                execution=args.config,
            )
            validate_cli_envelope(envelope)
            sys.stdout.write(render_cli_envelope(envelope))
            sys.stdout.write("\n")
            return 1 if has_issues else 0

        # Non-JSON output (existing behavior)
        if not messages:
            LOGGER.info("navmap repair: no issues detected")
            return 0
        LOGGER.info("\n".join(messages))
        if not args.config.apply_changes:
            LOGGER.info("\nRe-run with --apply to write these fixes.")
        else:
            LOGGER.info("\nnavmap repair: applied fixes")
    except Exception as exc:
        duration = time.monotonic() - start_time
        if args.config.emit_json:
            envelope = _build_error_envelope(exc, duration)
            try:
                validate_cli_envelope(envelope)
                sys.stdout.write(render_cli_envelope(envelope))
                sys.stdout.write("\n")
            except Exception as validation_exc:
                LOGGER.exception("Failed to validate error envelope")
                sys.stderr.write(f"Error: {validation_exc}\n")
            return 1
        LOGGER.exception("navmap repair failed")
        return 1
    else:
        return 1 if has_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())


def _collect_section_dicts(raw: object) -> list[dict[str, object]]:
    """Return section dictionaries extracted from ``raw`` when possible.

    Parameters
    ----------
    raw : object
        Value to extract sections from.

    Returns
    -------
    list[dict[str, object]]
        List of section dictionaries, empty if raw is not a list.
    """
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def _build_sections(
    sections: Iterable[dict[str, object]], exports: list[str]
) -> list[dict[str, object]]:
    """Return the canonical ``sections`` payload with the public API section first.

    Parameters
    ----------
    sections : Iterable[dict[str, object]]
        Existing section dictionaries.
    exports : list[str]
        List of exported symbols.

    Returns
    -------
    list[dict[str, object]]
        Sections list with public-api section first.
    """
    remaining = [section for section in sections if section.get("id") != "public-api"]
    return [{"id": "public-api", "symbols": exports}, *remaining]


def _collect_top_level_meta(navmap: Mapping[str, object]) -> dict[str, object]:
    """Return module metadata declared at the root of ``navmap``.

    Parameters
    ----------
    navmap : Mapping[str, object]
        Navmap dictionary to extract metadata from.

    Returns
    -------
    dict[str, object]
        Module metadata dictionary.
    """
    return {
        key: value
        for key in ("owner", "stability", "since", "deprecated_in")
        if isinstance((value := navmap.get(key)), str) and value
    }


def _normalized_module_meta(navmap: dict[str, object]) -> dict[str, object]:
    """Return module metadata after merging root-level defaults.

    Parameters
    ----------
    navmap : dict[str, object]
        Navmap dictionary to normalize.

    Returns
    -------
    dict[str, object]
        Normalized module metadata dictionary.
    """
    module_meta = _coerce_dict(navmap.get("module_meta"))
    top_level = _collect_top_level_meta(navmap)
    module_meta.update(top_level)
    for key in top_level:
        navmap.pop(key, None)
    return module_meta


def _normalized_symbols(raw: object) -> dict[str, SymbolMetadata]:
    """Return symbol metadata dictionaries keyed by symbol name.

    Parameters
    ----------
    raw : object
        Raw symbol metadata to normalize.

    Returns
    -------
    dict[str, SymbolMetadata]
        Dictionary mapping symbol names to their metadata.
    """
    if not isinstance(raw, dict):
        return {}
    return {
        name: filtered
        for name, meta in raw.items()
        if isinstance(name, str) and isinstance(meta, dict)
        if (
            filtered := {
                key: value
                for key, value in meta.items()
                if isinstance(key, str) and isinstance(value, str) and value
            }
        )
    }


def _apply_symbol_defaults(
    symbols_meta: dict[str, SymbolMetadata],
    exports: Iterable[str],
    module_meta: Mapping[str, object],
) -> None:
    """Ensure every exported symbol inherits module-level defaults.

    Parameters
    ----------
    symbols_meta : dict[str, SymbolMetadata]
        Symbol metadata dictionary to update in-place.
    exports : Iterable[str]
        List of exported symbols.
    module_meta : Mapping[str, object]
        Module-level metadata defaults.
    """
    owner_default = module_meta.get("owner", "@todo-owner")
    if not isinstance(owner_default, str) or not owner_default:
        owner_default = "@todo-owner"

    stability_default = module_meta.get("stability", "experimental")
    if not isinstance(stability_default, str) or not stability_default:
        stability_default = "experimental"

    since_default = module_meta.get("since", "0.0.0")
    if not isinstance(since_default, str) or not since_default:
        since_default = "0.0.0"

    deprecated_raw = module_meta.get("deprecated_in")
    deprecated_default = deprecated_raw if isinstance(deprecated_raw, str) else None

    for name in exports:
        if name not in symbols_meta:
            symbols_meta[name] = _empty_symbol_meta()
        fields = symbols_meta[name]
        fields.setdefault("owner", owner_default)
        fields.setdefault("stability", stability_default)
        fields.setdefault("since", since_default)
        if deprecated_default is not None:
            fields.setdefault("deprecated_in", deprecated_default)


def _normalize_exports(value: object, fallback: Iterable[str]) -> list[str]:
    """Return a deduplicated list of exports derived from ``value`` or ``fallback``.

    Parameters
    ----------
    value : object
        Value to extract exports from.
    fallback : Iterable[str]
        Fallback exports if value is not usable.

    Returns
    -------
    list[str]
        Deduplicated list of export names.
    """
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        candidates = value
    else:
        candidates = fallback

    exports: list[str] = [item for item in candidates if isinstance(item, str)]
    seen: set[str] = set()
    result: list[str] = []
    for item in exports:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _coerce_dict(value: object) -> dict[str, object]:
    """Return ``value`` as a shallow ``dict[str, object]`` when possible.

    Parameters
    ----------
    value : object
        Value to coerce to dictionary.

    Returns
    -------
    dict[str, object]
        Dictionary with string keys, empty if value is not a dict.
    """
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if isinstance(k, str)}
    return {}


def _empty_symbol_meta() -> SymbolMetadata:
    """Return an empty symbol metadata mapping.

    Returns
    -------
    SymbolMetadata
        Empty dictionary for symbol metadata.
    """
    return {}


def _collect_anchor_insertions(
    info: ModuleInfo,
    exports: Iterable[str],
    definition_lines: Mapping[str, int],
) -> tuple[list[tuple[int, str]], list[str]]:
    """Return anchor insertion edits and messages for missing exports.

    Parameters
    ----------
    info : ModuleInfo
        Module metadata.
    exports : Iterable[str]
        List of exported symbols.
    definition_lines : Mapping[str, int]
        Mapping of symbol names to their line numbers.

    Returns
    -------
    tuple[list[tuple[int, str]], list[str]]
        Tuple of insertion edits (line_index, content) and messages.
    """
    anchors = set(info.anchors)
    insertions: list[tuple[int, str]] = []
    messages: list[str] = []
    for name in exports:
        if name in anchors:
            continue
        line_no = definition_lines.get(name)
        if not line_no:
            messages.append(
                f"{info.path}: unable to locate definition for '{name}' to add anchor"
            )
            continue
        insertions.append((line_no - 1, f"# [nav:anchor {name}]"))
        messages.append(f"{info.path}: inserted [nav:anchor {name}] at line {line_no}")
    return insertions, messages


def _public_api_insertion(info: ModuleInfo, tree: ast.Module) -> tuple[int, str] | None:
    """Return an insertion that ensures the public API section exists.

    Parameters
    ----------
    info : ModuleInfo
        Module metadata.
    tree : ast.Module
        Module AST.

    Returns
    -------
    tuple[int, str] | None
        Insertion tuple (line_index, content) if needed, None otherwise.
    """
    if "public-api" in set(info.sections):
        return None
    doc_end = _docstring_end(tree) or 0
    return doc_end, "# [nav:section public-api]"


def _insertion_index(entry: tuple[int, str]) -> int:
    """Return the insertion index for sorting.

    Parameters
    ----------
    entry : tuple[int, str]
        Insertion entry (line_index, content).

    Returns
    -------
    int
        Line index for sorting.
    """
    return entry[0]


def _apply_insertions(lines: list[str], insertions: list[tuple[int, str]]) -> bool:
    """Apply ``insertions`` to ``lines`` preserving relative order.

    Parameters
    ----------
    lines : list[str]
        Source lines to modify.
    insertions : list[tuple[int, str]]
        List of (line_index, content) insertions.

    Returns
    -------
    bool
        True if any insertions were applied, False otherwise.
    """
    if not insertions:
        return False
    insertions.sort(key=_insertion_index)
    for offset, (index, content) in enumerate(insertions):
        lines.insert(index + offset, content)
    return True


def _sync_navmap_literal(
    info: ModuleInfo,
    tree: ast.Module,
    original_text: str,
    lines: list[str],
    exports: Sequence[str],
) -> tuple[bool, list[str]]:
    """Update the inline ``__navmap__`` literal when necessary.

    Parameters
    ----------
    info : ModuleInfo
        Module metadata.
    tree : ast.Module
        Module AST.
    original_text : str
        Original file contents.
    lines : list[str]
        Current file lines to modify.
    exports : Sequence[str]
        List of exported symbols.

    Returns
    -------
    tuple[bool, list[str]]
        Tuple of (changed, messages) indicating if navmap was updated.
    """
    messages: list[str] = []
    if not exports:
        return False, messages

    navmap_span = _navmap_assignment_span(tree)
    navmap_exists = navmap_span is not None and "__navmap__" in original_text
    updated_navmap = _ensure_navmap_structure(info)
    if navmap_exists and navmap_span is not None:
        start, end = navmap_span
        navmap_lines = _serialize_navmap(updated_navmap)
        start_idx = start - 1
        end_idx = end
        if lines[start_idx:end_idx] != navmap_lines:
            lines[start_idx:end_idx] = navmap_lines
            messages.append(f"{info.path}: normalized __navmap__ literal")
            return True, messages
        return False, messages

    all_end = _all_assignment_end(tree) or 0
    navmap_lines = [*_serialize_navmap(updated_navmap), ""]
    lines[all_end:all_end] = navmap_lines
    messages.append(f"{info.path}: created __navmap__ stub with defaults")
    return True, messages
