"""Scope filtering and merging utilities for CodeIntel MCP.

This module provides helper functions for retrieving session scopes, merging them
with explicit adapter parameters, and applying path/language filters to search results.

Key Functions
-------------
get_effective_scope : Retrieve session scope from registry
merge_scope_filters : Merge session scope with explicit parameters (explicit wins)
apply_path_filters : Filter paths using glob patterns (fnmatch)
apply_language_filter : Filter paths by programming language extension
path_matches_glob : Test if path matches glob pattern

Design Principles
-----------------
- **Explicit Precedence**: Explicit adapter parameters always override session scope
- **Fail-Safe**: Missing scope or empty filters return unfiltered results
- **Cross-Platform**: Normalize path separators for Windows/Unix compatibility
- **Performance**: Early-exit for empty filters to avoid unnecessary iterations

Example Usage
-------------
Retrieve and merge scope in adapter:

>>> from codeintel_rev.mcp_server.scope_utils import get_effective_scope, merge_scope_filters
>>> session_id = get_session_id()
>>> scope = get_effective_scope(context, session_id)
>>> merged = merge_scope_filters(scope, {"include_globs": ["src/**"]})
>>> # merged["include_globs"] is now ["src/**"] (explicit overrides scope)

Filter paths by glob patterns:

>>> from codeintel_rev.mcp_server.scope_utils import apply_path_filters
>>> paths = ["src/main.py", "tests/test_main.py", "docs/README.md"]
>>> filtered = apply_path_filters(paths, include_globs=["**/*.py"], exclude_globs=["**/test_*.py"])
>>> filtered
['src/main.py']

Filter paths by language:

>>> from codeintel_rev.mcp_server.scope_utils import apply_language_filter
>>> paths = ["src/main.py", "src/app.ts", "README.md"]
>>> filtered = apply_language_filter(paths, ["python"])
>>> filtered
['src/main.py']

See Also
--------
codeintel_rev.app.scope_store : ScopeStore for storing session scopes
codeintel_rev.app.middleware : get_session_id for retrieving session ID
"""

from __future__ import annotations

import fnmatch
from time import perf_counter
from typing import TYPE_CHECKING

from kgfoundry_common.logging import get_logger
from kgfoundry_common.prometheus import build_histogram

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext
    from codeintel_rev.mcp_server.schemas import ScopeIn

LOGGER = get_logger(__name__)

# Prometheus metrics for scope filtering
_scope_filter_duration_seconds = build_histogram(
    "codeintel_scope_filter_duration_seconds",
    "Time to apply scope filters",
    ("filter_type",),
)

# Language to file extension mapping
# Exhaustive list of common programming languages
LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
    "python": [".py", ".pyi", ".pyw"],
    "typescript": [".ts", ".tsx", ".mts", ".cts"],
    "javascript": [".js", ".jsx", ".mjs", ".cjs"],
    "rust": [".rs"],
    "go": [".go"],
    "java": [".java"],
    "kotlin": [".kt", ".kts"],
    "scala": [".scala", ".sc"],
    "cpp": [".cpp", ".cc", ".cxx", ".hpp", ".hxx", ".h"],
    "c": [".c", ".h"],
    "csharp": [".cs", ".csx"],
    "ruby": [".rb", ".rake"],
    "php": [".php", ".phtml"],
    "swift": [".swift"],
    "objectivec": [".m", ".mm", ".h"],
    "bash": [".sh", ".bash", ".zsh"],
    "powershell": [".ps1", ".psm1"],
    "yaml": [".yaml", ".yml"],
    "json": [".json", ".jsonc"],
    "toml": [".toml"],
    "xml": [".xml", ".xsd", ".xsl"],
    "html": [".html", ".htm"],
    "css": [".css", ".scss", ".sass", ".less"],
    "markdown": [".md", ".markdown", ".mdown"],
    "sql": [".sql", ".ddl", ".dml"],
    "r": [".r", ".R"],
    "perl": [".pl", ".pm"],
    "lua": [".lua"],
    "haskell": [".hs", ".lhs"],
    "elixir": [".ex", ".exs"],
    "erlang": [".erl", ".hrl"],
    "clojure": [".clj", ".cljs", ".cljc"],
    "dart": [".dart"],
    "vue": [".vue"],
    "svelte": [".svelte"],
}


async def get_effective_scope(
    context: ApplicationContext,
    session_id: str | None,
) -> ScopeIn | None:
    """Retrieve session scope from the scope store.

    Helper function that wraps ScopeStore.get with null-safety for missing session
    IDs. Returns None if session_id is None or scope not found, allowing adapters
    to gracefully fall back to "no scope" behavior.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing scope store.
    session_id : str | None
        Session identifier to look up. If None, returns None immediately
        without registry access.

    Returns
    -------
    ScopeIn | None
        Scope dictionary if session exists and has scope, None otherwise.

    Examples
    --------
    >>> context = ApplicationContext.create()
    >>> session_id = "test-session-123"
    >>> await context.scope_store.set(session_id, {"languages": ["python"]})
    >>> scope = await get_effective_scope(context, session_id)
    >>> scope
    {'languages': ['python']}
    >>> get_effective_scope(context, None)  # No session ID
    >>> get_effective_scope(context, "nonexistent")  # No scope set

    Notes
    -----
    This function is preferred over direct registry access because it handles
    the None case explicitly, making adapter code cleaner.
    """
    if session_id is None:
        return None
    return await context.scope_store.get(session_id)


def merge_scope_filters(
    scope: ScopeIn | None,
    explicit_params: dict,
) -> dict:
    """Merge session scope with explicit adapter parameters.

    Combines scope fields with explicit function parameters, giving precedence
    to explicit parameters. This allows users to override session scope for
    individual queries without clearing the scope.

    Merge Rules:
    - If explicit param is present (not None), use it (override scope).
    - If explicit param is absent (None), use scope value (default).
    - If both absent, field is omitted from result.

    Parameters
    ----------
    scope : ScopeIn | None
        Session scope from registry (may be None if no scope set).
    explicit_params : dict
        Parameters passed directly to adapter (e.g., {"include_globs": [...]}).
        Keys match ScopeIn fields. Values of None are treated as "not provided".

    Returns
    -------
    dict
        Merged dictionary with explicit params overriding scope defaults.

    Examples
    --------
    Explicit parameter overrides scope:

    >>> scope = {"include_globs": ["**/*.py"], "languages": ["python"]}
    >>> explicit = {"include_globs": ["src/**"]}
    >>> merged = merge_scope_filters(scope, explicit)
    >>> merged
    {'include_globs': ['src/**'], 'languages': ['python']}

    Scope provides defaults for unspecified params:

    >>> scope = {"include_globs": ["**/*.py"], "exclude_globs": ["**/test_*"]}
    >>> explicit = {"include_globs": None, "exclude_globs": None}
    >>> merged = merge_scope_filters(scope, explicit)
    >>> merged
    {'include_globs': ['**/*.py'], 'exclude_globs': ['**/test_*']}

    No scope (all from explicit params):

    >>> merged = merge_scope_filters(None, {"include_globs": ["**/*.ts"]})
    >>> merged
    {'include_globs': ['**/*.ts']}

    Empty scope and empty params:

    >>> merged = merge_scope_filters(None, {})
    >>> merged
    {}

    Notes
    -----
    The function does not modify input dicts—it returns a new dict. This
    ensures thread safety (no shared mutable state).
    """
    result: dict = {}

    # Start with scope as defaults (if present)
    if scope:
        result.update(scope)

    # Override with explicit params (filter out None values)
    result.update({key: value for key, value in explicit_params.items() if value is not None})

    return result


def apply_path_filters(
    paths: list[str],
    include_globs: list[str],
    exclude_globs: list[str],
) -> list[str]:
    """Filter paths using glob patterns.

    Applies include and exclude glob patterns to a list of file paths. Paths
    must match at least one include pattern AND no exclude patterns to be kept.

    Matching is done using fnmatch (Unix shell-style globs):
    - `*` matches anything (including `/` in our implementation)
    - `?` matches any single character
    - `[seq]` matches any character in seq
    - `[!seq]` matches any character not in seq

    Parameters
    ----------
    paths : list[str]
        File paths to filter (typically relative to repo root).
    include_globs : list[str]
        Glob patterns to include. Paths must match at least one pattern.
        Empty list means "include all" (no filtering).
    exclude_globs : list[str]
        Glob patterns to exclude. Paths matching any pattern are removed.
        Empty list means "exclude none".

    Returns
    -------
    list[str]
        Filtered paths list (order preserved from input).

    Examples
    --------
    Include only Python files:

    >>> paths = ["src/main.py", "src/app.ts", "README.md"]
    >>> filtered = apply_path_filters(paths, include_globs=["**/*.py"], exclude_globs=[])
    >>> filtered
    ['src/main.py']

    Exclude test files:

    >>> paths = ["src/main.py", "tests/test_main.py", "src/utils.py"]
    >>> filtered = apply_path_filters(paths, include_globs=["**/*.py"], exclude_globs=["**/test_*"])
    >>> filtered
    ['src/main.py', 'src/utils.py']

    Empty include globs (include all):

    >>> filtered = apply_path_filters(paths, include_globs=[], exclude_globs=["**/test_*"])
    >>> # All paths except test files

    Notes
    -----
    Path separators are normalized to forward slashes (/) before matching to
    ensure Windows paths (backslash) match Unix-style glob patterns.

    Performance: O(n * m) where n = len(paths), m = max(len(include), len(exclude)).
    For large path lists, consider pre-filtering during directory traversal
    instead of post-filtering.
    """
    if not include_globs and not exclude_globs:
        return paths  # No filtering needed

    filtered: list[str] = []

    for path in paths:
        # Normalize path separators for cross-platform compatibility
        normalized_path = path.replace("\\", "/")

        # Check include patterns
        if include_globs and not any(
            path_matches_glob(normalized_path, pattern) for pattern in include_globs
        ):
            continue  # Path doesn't match any include pattern

        # Check exclude patterns
        if exclude_globs and any(
            path_matches_glob(normalized_path, pattern) for pattern in exclude_globs
        ):
            continue  # Path matches an exclude pattern

        # Path passed both filters
        filtered.append(path)

    return filtered


def apply_language_filter(
    paths: list[str],
    languages: list[str],
) -> list[str]:
    """Filter paths by programming language.

    Returns only paths whose file extensions match the specified languages.
    Uses LANGUAGE_EXTENSIONS mapping to resolve language names to extensions.

    Parameters
    ----------
    paths : list[str]
        File paths to filter.
    languages : list[str]
        Programming language names (e.g., ["python", "typescript"]).
        Case-insensitive (normalized to lowercase).

    Returns
    -------
    list[str]
        Paths with extensions matching specified languages (order preserved).

    Examples
    --------
    Filter to Python files only:

    >>> paths = ["src/main.py", "src/app.ts", "README.md"]
    >>> filtered = apply_language_filter(paths, ["python"])
    >>> filtered
    ['src/main.py']

    Multiple languages:

    >>> filtered = apply_language_filter(paths, ["python", "typescript"])
    >>> filtered
    ['src/main.py', 'src/app.ts']

    Unknown language (no matches):

    >>> filtered = apply_language_filter(paths, ["cobol"])
    >>> filtered
    []

    Notes
    -----
    Language names are case-insensitive: "Python", "python", "PYTHON" all work.

    If a language is not in LANGUAGE_EXTENSIONS, it's silently ignored (no
    error raised). This allows forward compatibility if new languages are added
    to the mapping later.

    Extension matching is case-sensitive: ".PY" will NOT match Python (use
    lowercase extensions in path normalization if needed).
    """
    if not languages:
        return paths  # No filtering needed

    # Measure filtering duration
    start_time = perf_counter()

    # Normalize language names to lowercase
    normalized_languages = [lang.lower() for lang in languages]

    # Collect all extensions for requested languages
    extensions: set[str] = set()
    for lang in normalized_languages:
        lang_extensions = LANGUAGE_EXTENSIONS.get(lang, [])
        extensions.update(lang_extensions)

    if not extensions:
        # No known extensions for requested languages
        LOGGER.warning(
            "No file extensions found for requested languages",
            extra={"languages": languages},
        )
        return []

    # Filter paths by extension
    filtered: list[str] = []
    for path in paths:
        # Extract extension (include leading dot)
        path_lower = path.lower()  # Case-insensitive extension matching
        for ext in extensions:
            if path_lower.endswith(ext.lower()):
                filtered.append(path)
                break  # Path matches, no need to check other extensions

    # Record filtering duration
    duration = perf_counter() - start_time
    _scope_filter_duration_seconds.labels(filter_type="language").observe(duration)

    return filtered


def path_matches_glob(path: str, pattern: str) -> bool:
    """Test if path matches glob pattern.

    Wrapper around fnmatch.fnmatchcase with path normalization for cross-platform
    compatibility. Handles both simple patterns (*.py) and recursive patterns
    (**/*.py).

    Parameters
    ----------
    path : str
        File path to test (typically relative to repo root).
    pattern : str
        Glob pattern (Unix shell-style).

    Returns
    -------
    bool
        True if path matches pattern, False otherwise.

    Examples
    --------
    Simple suffix match:

    >>> path_matches_glob("test.py", "*.py")
    True
    >>> path_matches_glob("test.ts", "*.py")
    False

    Recursive pattern:

    >>> path_matches_glob("src/utils/helpers.py", "**/*.py")
    True
    >>> path_matches_glob("README.md", "**/*.py")
    False

    Directory prefix:

    >>> path_matches_glob("src/main.py", "src/**")
    True
    >>> path_matches_glob("lib/util.py", "src/**")
    False

    Notes
    -----
    fnmatch treats `*` as matching any characters INCLUDING slashes, unlike
    some glob implementations (e.g., bash) where `*` doesn't match `/`. This
    makes `**/*.py` and `*/*.py` functionally equivalent in our implementation.

    For more complex patterns (e.g., brace expansion {a,b}), consider using
    the `wcmatch` library which supports advanced glob features.
    """
    # Normalize separators
    normalized_path = path.replace("\\", "/")
    normalized_pattern = pattern.replace("\\", "/")

    # fnmatch.fnmatchcase provides consistent case-sensitive matching on all
    # platforms, ensuring behavior matches the documented contract regardless of
    # the underlying filesystem defaults (e.g., Windows being case-insensitive).
    return fnmatch.fnmatchcase(normalized_path, normalized_pattern)


__all__ = [
    "LANGUAGE_EXTENSIONS",
    "apply_language_filter",
    "apply_path_filters",
    "get_effective_scope",
    "merge_scope_filters",
    "path_matches_glob",
]
