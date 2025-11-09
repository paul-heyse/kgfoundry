"""Overview of build test map.

This module bundles build test map logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from tools._shared.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

LOGGER = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
OUTDIR = ROOT / "docs" / "_build"
OUTDIR.mkdir(parents=True, exist_ok=True)

OUTFILE_MAP = OUTDIR / "test_map.json"
OUTFILE_COV = OUTDIR / "test_map_coverage.json"
OUTFILE_SUM = OUTDIR / "test_map_summary.json"
OUTFILE_LINT = OUTDIR / "test_map_lint.json"

MAX_CONTEXT_WINDOWS: Final[int] = 5
DOTTED_IDENTIFIER = re.compile(r"[A-Za-z_][\w\.]+")

JSONPrimitive = str | int | float | bool | None
type JSONValue = JSONPrimitive | dict[str, JSONValue] | list[JSONValue]

NAVMAP_MISSING_MESSAGE = "navmap.json is missing. Build the documentation navigation map before running this script."


class NavMapLoadError(RuntimeError):
    """Model the NavMapLoadError.

    Represent the navmaploaderror data structure used throughout the project. The class encapsulates
    behaviour behind a well-defined interface for collaborating components. Instances are typically
    created by factories or runtime orchestrators documented nearby.
    """


WINDOW = int(os.getenv("TESTMAP_WINDOW", "3"))
COV_JSON = Path(os.getenv("TESTMAP_COVERAGE_JSON", str(OUTDIR / "coverage.json")))
FAIL_BUDGET = int(os.getenv("TESTMAP_FAIL_BUDGET", "5"))
FAIL_ON_UNTESTED = os.getenv("TESTMAP_FAIL_ON_UNTESTED", "0") == "1"


def _load_json(path: Path) -> JSONValue | None:
    """Return JSON data from ``path`` or ``None`` if the file is unreadable.

    Parameters
    ----------
    path : Path
        Path to JSON file.

    Returns
    -------
    JSONValue | None
        Parsed JSON data | None if file is unreadable.
    """
    try:
        return cast("JSONValue", json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None


def _normalize_module_name(name: str) -> str:
    """Collapse ``__init__`` suffixes to create a canonical module path.

    Parameters
    ----------
    name : str
        Module name.

    Returns
    -------
    str
        Normalized module name.
    """
    return name[: -len(".__init__")] if name.endswith(".__init__") else name


def _add_exports(
    bucket: set[str],
    module_name: str,
    exports: Iterable[object] | None = None,
) -> None:
    """Record ``module_name`` and any exported symbols in ``bucket``."""
    module = _normalize_module_name(module_name)
    if not module:
        return

    bucket.add(module)

    if exports is None:
        return

    for symbol in exports:
        if not isinstance(symbol, str) or not symbol:
            continue
        qualified = symbol if symbol.startswith(f"{module}.") else f"{module}.{symbol}"
        bucket.add(qualified)


def _candidates_from_symbols_json(symbols_json: Path) -> set[str]:
    """Load module paths from the symbol index produced during docs generation.

    Parameters
    ----------
    symbols_json : Path
        Path to symbols JSON file.

    Returns
    -------
    set[str]
        Set of module names.
    """
    payload = _load_json(symbols_json)
    if not isinstance(payload, list):
        return set()

    candidates: set[str] = set()
    for row in payload:
        if isinstance(row, Mapping):
            path = row.get("path")
            if isinstance(path, str):
                _add_exports(candidates, path)
    return candidates


def _candidates_from_navmap(navmap_json: Path) -> set[str]:
    """Load modules and exports from the navigation map.

    Parameters
    ----------
    navmap_json : Path
        Path to navmap JSON file.

    Returns
    -------
    set[str]
        Set of module names and exported symbols.
    """
    payload = _load_json(navmap_json)
    if not isinstance(payload, Mapping):
        return set()

    modules = payload.get("modules")
    if not isinstance(modules, Mapping):
        return set()

    candidates: set[str] = set()
    for module_name, entry in modules.items():
        if not isinstance(module_name, str):
            continue
        exports: Iterable[object] | None = None
        if isinstance(entry, Mapping):
            raw_exports = entry.get("exports")
            if isinstance(raw_exports, list):
                exports = raw_exports
        _add_exports(candidates, module_name, exports)
    return candidates


def _candidates_from_source_tree() -> set[str]:
    """Derive module names by scanning the ``src`` tree.

    Returns
    -------
    set[str]
        Set of module names discovered from source tree.
    """
    candidates: set[str] = set()
    for pyfile in SRC.rglob("*.py"):
        try:
            rel = pyfile.relative_to(SRC)
        except ValueError:
            continue
        module = _normalize_module_name(".".join(rel.with_suffix("").parts))
        if module:
            candidates.add(module)
    return candidates


def load_symbol_candidates() -> set[str]:
    """Return potential module and attribute targets for documentation lookup.

    Returns
    -------
    set[str]
        Set of module names and exported symbols.
    """
    symbols_json = ROOT / "docs" / "_build" / "symbols.json"
    if symbols_json.exists():
        candidates = _candidates_from_symbols_json(symbols_json)
        if candidates:
            return candidates

    navmap_json = ROOT / "site" / "_build" / "navmap" / "navmap.json"
    if navmap_json.exists():
        candidates = _candidates_from_navmap(navmap_json)
        if candidates:
            return candidates

    return _candidates_from_source_tree()


def load_symbol_spans() -> dict[str, dict[str, Any]]:
    """Compute load symbol spans.

    Carry out the load symbol spans operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Returns
    -------
    dict[str, dict[str, Any]]
        Description of return value.

    Examples
    --------
    >>> from tools.docs.build_test_map import load_symbol_spans
    >>> result = load_symbol_spans()
    >>> result  # doctest: +ELLIPSIS
    """
    out: dict[str, dict[str, Any]] = {}
    symbols_json = ROOT / "docs" / "_build" / "symbols.json"
    if not symbols_json.exists():
        return out
    try:
        rows = json.loads(symbols_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        rows = []
    for r in rows:
        p = r.get("path")
        f = r.get("file")
        ln = r.get("lineno")
        en = r.get("endlineno")
        if en is None and isinstance(r, Mapping):
            candidate = r.get("end_lineno")
            if isinstance(candidate, int):
                en = candidate
        mod = r.get("module") or ".".join((p or "").split(".")[:-1])
        if isinstance(p, str) and isinstance(f, str) and isinstance(ln, int):
            out[p] = {
                "file": f,
                "lineno": ln,
                "endlineno": en or ln,
                "module": mod,
            }
    return out


def load_public_symbols() -> set[str]:
    """Compute load public symbols.

    Carry out the load public symbols operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Returns
    -------
    set[str]
        Description of return value.

    Raises
    ------
    NavMapLoadError
        Raised when validation fails.

    Examples
    --------
    >>> from tools.docs.build_test_map import load_public_symbols
    >>> result = load_public_symbols()
    >>> result  # doctest: +ELLIPSIS
    """
    nav = ROOT / "site" / "_build" / "navmap" / "navmap.json"
    if not nav.exists():
        raise NavMapLoadError(NAVMAP_MISSING_MESSAGE)
    try:
        j = json.loads(nav.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        message = f"Failed to parse {nav}: {exc}"
        raise NavMapLoadError(message) from exc
    except OSError as exc:
        message = f"Failed to read {nav}: {exc}"
        raise NavMapLoadError(message) from exc
    exports: set[str] = set()
    modules = j.get("modules")
    if not isinstance(modules, Mapping):
        return exports

    for module_name, entry in modules.items():
        if not isinstance(module_name, str) or not isinstance(entry, Mapping):
            continue
        raw_exports = entry.get("exports")
        if not isinstance(raw_exports, list):
            continue
        for symbol in raw_exports:
            if isinstance(symbol, str):
                fully_qualified = (
                    symbol
                    if symbol.startswith(f"{module_name}.")
                    else f"{module_name}.{symbol}"
                )
                exports.add(fully_qualified)
    return exports


def _collect_import(node: ast.Import, names: set[str]) -> None:
    """Collect import.

    Parameters
    ----------
    node : ast.Import
        Import AST node.
    names : set[str]
        Set to add imported names to.
    """
    for alias in node.names:
        names.add(alias.name)


def _collect_import_from(node: ast.ImportFrom, names: set[str]) -> None:
    """Collect import from.

    Parameters
    ----------
    node : ast.ImportFrom
        ImportFrom AST node.
    names : set[str]
        Set to add imported names to.
    """
    module = node.module or ""
    if module:
        names.add(module)
    for alias in node.names:
        if module:
            names.add(f"{module}.{alias.name}")
        names.add(alias.name)


def _collect_attribute(node: ast.Attribute, names: set[str]) -> None:
    """Collect attribute.

    Parameters
    ----------
    node : ast.Attribute
        Attribute AST node.
    names : set[str]
        Set to add attribute names to.
    """
    if isinstance(node.value, ast.Name):
        names.add(f"{node.value.id}.{node.attr}")


def _names_from_ast(tree: ast.AST | None) -> set[str]:
    """Return identifiers discovered while walking ``tree``.

    Parameters
    ----------
    tree : ast.AST | None
        AST to walk.

    Returns
    -------
    set[str]
        Set of discovered identifiers.
    """
    names: set[str] = set()
    if tree is None:
        return names

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _collect_import(node, names)
        elif isinstance(node, ast.ImportFrom):
            _collect_import_from(node, names)
        elif isinstance(node, ast.Attribute):
            _collect_attribute(node, names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names


def _read_source(path: Path) -> str | None:
    """Read source.

    Parameters
    ----------
    path : Path
        Path to source file.

    Returns
    -------
    str | None
        Source text | None if file cannot be read.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _parse_source(text: str) -> ast.AST | None:
    """Parse source.

    Parameters
    ----------
    text : str
        Source code text.

    Returns
    -------
    ast.AST | None
        Parsed AST | None if syntax error.
    """
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def _symbol_tail(symbol: str) -> str:
    """Symbol tail.

    Parameters
    ----------
    symbol : str
        Symbol name.

    Returns
    -------
    str
        Last component of dotted symbol name.
    """
    return symbol.rsplit(".", 1)[-1]


def _match_reason(
    symbol: str, dotted_tokens: set[str], ast_tokens: set[str]
) -> str | None:
    """Match reason.

    Parameters
    ----------
    symbol : str
        Symbol to match.
    dotted_tokens : set[str]
        Dotted tokens found in source.
    ast_tokens : set[str]
        AST tokens found in source.

    Returns
    -------
    str | None
        Match reason string | None if no match.
    """
    top = symbol.split(".", 1)[0]
    tail = _symbol_tail(symbol)
    if symbol in dotted_tokens:
        return "dotted"
    if symbol in ast_tokens:
        return "ast_fqn"
    if top in ast_tokens:
        return "ast_top"
    if tail in dotted_tokens:
        return "tail"
    return None


def _line_hits(text: str, symbol: str) -> list[int]:
    """Line hits.

    Parameters
    ----------
    text : str
        Source text to search.
    symbol : str
        Symbol name to find.

    Returns
    -------
    list[int]
        List of line numbers where symbol appears.
    """
    tail = _symbol_tail(symbol)
    hits: list[int] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if symbol in raw or (tail and tail in raw):
            hits.append(lineno)
            if len(hits) >= MAX_CONTEXT_WINDOWS:
                break
    return hits


def _context_windows(line_hits: Iterable[int]) -> list[dict[str, int]]:
    """Context windows.

    Parameters
    ----------
    line_hits : Iterable[int]
        Line numbers.

    Returns
    -------
    list[dict[str, int]]
        List of context window dictionaries with start/end line numbers.
    """
    return [
        {"start": max(1, line - WINDOW), "end": line + WINDOW} for line in line_hits
    ]


def _relative_repo_path(path: Path) -> str:
    """Relative repo path.

    Parameters
    ----------
    path : Path
        Path to convert.

    Returns
    -------
    str
        Relative path string, or absolute path if not relative to repo root.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def scan_test_file(path: Path, symbols: set[str]) -> dict[str, list[dict[str, object]]]:
    """Return symbol matches discovered inside ``path`` for reporting.

    Parameters
    ----------
    path : Path
        Path to test file.
    symbols : set[str]
        Set of symbols to search for.

    Returns
    -------
    dict[str, list[dict[str, object]]]
        Mapping of symbol to list of match dictionaries.
    """
    text = _read_source(path)
    if text is None:
        return {}

    tree = _parse_source(text)
    dotted_tokens = set(DOTTED_IDENTIFIER.findall(text))
    ast_tokens = _names_from_ast(tree)
    matches: dict[str, list[dict[str, object]]] = {}

    for symbol in symbols:
        reason = _match_reason(symbol, dotted_tokens, ast_tokens)
        if reason is None:
            continue
        line_hits = _line_hits(text, symbol)
        if len(line_hits) >= MAX_CONTEXT_WINDOWS:
            break
        windows = _context_windows(line_hits)
        matches.setdefault(symbol, []).append(
            {
                "file": _relative_repo_path(path),
                "lines": line_hits,
                "windows": windows,
                "reason": reason,
            }
        )
    return matches


# ---------------------------- coverage ingestion -----------------------------


def _normalize_repo_rel(path_like: str) -> str:
    """Normalize repo rel.

    Parameters
    ----------
    path_like : str
        Path-like string.

    Returns
    -------
    str
        Normalized relative path string.
    """
    try:
        p = Path(path_like)
    except TypeError:
        return str(path_like)

    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        raw = str(p)
        root = str(ROOT)
        idx = raw.find(root)
        if idx != -1:
            return raw[idx + len(root) :].lstrip(os.sep)
        return raw


def _executed_lines(info: Mapping[str, object]) -> set[int]:
    """Return executed line numbers.

    Parameters
    ----------
    info : Mapping[str, object]
        Coverage info dictionary.

    Returns
    -------
    set[int]
        Set of executed line numbers.
    """
    raw = info.get("executed_lines")
    if not isinstance(raw, list):
        return set()
    return {line for line in raw if isinstance(line, int)}


def _contexts_for_file(
    info: Mapping[str, object], rel: str
) -> dict[tuple[str, int], set[str]]:
    """Contexts for file.

    Parameters
    ----------
    info : Mapping[str, object]
        Coverage info dictionary.
    rel : str
        Relative file path.

    Returns
    -------
    dict[tuple[str, int], set[str]]
        Mapping of (file, line) to set of context names.
    """
    contexts = info.get("contexts")
    if not isinstance(contexts, Mapping):
        return {}
    by_line: dict[tuple[str, int], set[str]] = {}
    for ctx_name, ln_list in contexts.items():
        if not isinstance(ln_list, list):
            continue
        for ln in ln_list:
            if isinstance(ln, int):
                by_line.setdefault((rel, ln), set()).add(str(ctx_name))
    return by_line


def load_coverage() -> tuple[dict[str, set[int]], dict[tuple[str, int], set[str]]]:
    """Compute load coverage.

    Carry out the load coverage operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Returns
    -------
    tuple[dict[str, set[int]], dict[tuple[str, int], set[str]]]
        Description of return value.

    Examples
    --------
    >>> from tools.docs.build_test_map import load_coverage
    >>> result = load_coverage()
    >>> result  # doctest: +ELLIPSIS
    """
    if not COV_JSON.exists():
        return ({}, {})
    data = _load_json(COV_JSON)
    if not isinstance(data, Mapping):
        return ({}, {})

    files = data.get("files")
    if not isinstance(files, Mapping):
        return ({}, {})

    executed: dict[str, set[int]] = {}
    ctx_by_line: dict[tuple[str, int], set[str]] = {}

    for fpath, info in files.items():
        if not isinstance(fpath, str) or not isinstance(info, Mapping):
            continue

        rel = _normalize_repo_rel(fpath)
        executed[rel] = _executed_lines(info)

        for key, ctx_names in _contexts_for_file(info, rel).items():
            ctx_by_line.setdefault(key, set()).update(ctx_names)
    return (executed, ctx_by_line)


# ---------------------------- builders & policy ------------------------------


def build_test_map(symbols: set[str]) -> dict[str, list[dict[str, object]]]:
    """Compute build test map.

    Carry out the build test map operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Parameters
    ----------
    symbols : set[str]
        Description for ``symbols``.

    Returns
    -------
    dict[str, list[dict[str, object]]]
        Description of return value.

    Examples
    --------
    >>> from tools.docs.build_test_map import build_test_map
    >>> result = build_test_map(...)
    >>> result  # doctest: +ELLIPSIS
    """
    table: dict[str, list[dict[str, object]]] = defaultdict(list)
    if not TESTS.exists():
        return {}

    for test_file in TESTS.rglob("test_*.py"):
        for symbol, rows in scan_test_file(test_file, symbols).items():
            table[symbol].extend(rows)

    # drop empties
    return {sym: rows for sym, rows in table.items() if rows}


def attach_coverage(
    symbol_spans: dict[str, dict[str, Any]],
    executed: dict[str, set[int]],
    ctx_by_line: dict[tuple[str, int], set[str]],
) -> dict[str, dict[str, Any]]:
    """Compute attach coverage.

    Carry out the attach coverage operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Parameters
    ----------
    symbol_spans : dict[str, dict[str, Any]]
        Description for ``symbol_spans``.
    executed : dict[str, set[int]]
        Description for ``executed``.
    ctx_by_line : dict[tuple[str, int], set[str]]
        Description for ``ctx_by_line``.

    Returns
    -------
    dict[str, dict[str, Any]]
        Description of return value.

    Examples
    --------
    >>> from tools.docs.build_test_map import attach_coverage
    >>> result = attach_coverage(..., ..., ...)
    >>> result  # doctest: +ELLIPSIS
    """
    result: dict[str, dict[str, Any]] = {}
    for sym, meta in symbol_spans.items():
        f = meta.get("file")
        ln = int(meta.get("lineno") or 0)
        end_line = meta.get("endlineno")
        if end_line is None:
            candidate = meta.get("end_lineno")
            end_line = candidate if isinstance(candidate, int) else None
        en = int(end_line or ln)
        rel = f if isinstance(f, str) else None
        hits: list[int] = []
        if rel and rel in executed:
            span = set(range(ln, en + 1))
            hits = sorted(executed[rel].intersection(span))
        contexts: set[str] = set()
        if hits and rel:
            for h in hits[:50]:  # limit
                contexts |= ctx_by_line.get((rel, h), set())
        ratio = 0.0
        if en >= ln:
            ratio = round(len(hits) / max(1, (en - ln + 1)), 4)
        result[sym] = {
            "executed": bool(hits),
            "ratio": ratio,
            "hit_lines": hits[:100],  # trim
            "file": rel,
            "span": [ln, en],
            "contexts": sorted(contexts)[:100],
        }
    return result


def summarize(
    public_syms: set[str],
    symbol_spans: dict[str, dict[str, Any]],
    coverage: dict[str, dict[str, Any]],
    budget: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compute summarize.

    Carry out the summarize operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Parameters
    ----------
    public_syms : set[str]
        Description for ``public_syms``.
    symbol_spans : dict[str, dict[str, Any]]
        Description for ``symbol_spans``.
    coverage : dict[str, dict[str, Any]]
        Description for ``coverage``.
    budget : int
        Description for ``budget``.

    Returns
    -------
    tuple[dict[str, Any], list[dict[str, Any]]]
        Description of return value.

    Examples
    --------
    >>> from tools.docs.build_test_map import summarize
    >>> result = summarize(..., ..., ..., ...)
    >>> result  # doctest: +ELLIPSIS
    """
    # group by module
    by_mod: dict[str, list[str]] = defaultdict(list)
    for s in public_syms:
        mod = symbol_spans.get(s, {}).get("module") or ".".join(s.split(".")[:-1])
        by_mod[mod].append(s)

    summary: dict[str, Any] = {}
    lints: list[dict[str, Any]] = []
    untested_total = 0
    for mod, syms in by_mod.items():
        ratios: list[float] = []
        untested: list[str] = []
        for s in syms:
            cov = coverage.get(s, {})
            ratios.append(float(cov.get("ratio") or 0.0))
            if not cov.get("executed"):
                untested.append(s)
        untested_total += len(untested)
        summary[mod] = {
            "untested_top10": untested[:10],
            "coverage_ratio_avg": round(sum(ratios) / max(1, len(ratios)), 4),
            "public_count": len(syms),
            "untested_count": len(untested),
        }

    if untested_total > budget:
        lints.append(
            {
                "severity": "error",
                "symbol": "*",
                "rule": "untested_public_budget",
                "message": f"Untested public symbols {untested_total} exceed budget {budget}",
                "module": "*",
                "file": "*",
            }
        )
    return summary, lints


def main() -> None:
    """Compute main.

    Carry out the main operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Examples
    --------
    >>> from tools.docs.build_test_map import main
    >>> main()  # doctest: +ELLIPSIS
    """
    symbols = load_symbol_candidates()
    spans = load_symbol_spans()
    try:
        public_syms = load_public_symbols()
    except NavMapLoadError:
        LOGGER.exception("[testmap] ERROR loading public symbols")
        sys.exit(1)

    # 1) heuristic test map
    heuristic = build_test_map(symbols)

    # 2) coverage overlay
    executed, ctx_map = load_coverage()
    cov = attach_coverage(spans, executed, ctx_map)

    # 3) policy & summaries
    summary, lints = summarize(public_syms or set(), spans, cov, FAIL_BUDGET)

    # write artifacts
    OUTFILE_MAP.write_text(json.dumps(heuristic, indent=2) + "\n", encoding="utf-8")
    OUTFILE_COV.write_text(json.dumps(cov, indent=2) + "\n", encoding="utf-8")
    OUTFILE_SUM.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    OUTFILE_LINT.write_text(json.dumps(lints, indent=2) + "\n", encoding="utf-8")

    # strict mode
    if FAIL_ON_UNTESTED and any(x["severity"] == "error" for x in lints):
        LOGGER.error(
            "[testmap] FAIL: %d error(s)",
            sum(1 for x in lints if x["severity"] == "error"),
        )
        sys.exit(2)
    LOGGER.info(
        "[testmap] wrote %s, %s, %s, %s",
        OUTFILE_MAP.name,
        OUTFILE_COV.name,
        OUTFILE_SUM.name,
        OUTFILE_LINT.name,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
