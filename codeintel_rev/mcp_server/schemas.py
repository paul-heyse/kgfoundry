"""MCP server schemas using TypedDict for FastMCP compatibility.

TypedDict provides automatic JSON Schema generation for FastMCP tools.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from kgfoundry_common.problem_details import ProblemDetailsDict


class BaseErrorFields(TypedDict, total=False):
    """Base fields present in ALL error responses.

    These fields are automatically added by the error handling decorator
    when an exception is caught. Adapters should never construct these
    manually - they only appear on error paths handled by the decorator.

    Attributes
    ----------
    error : str
        Human-readable error message. Present on all error responses.
        Used for display in user interfaces and debugging.
    problem : ProblemDetailsDict
        RFC 9457 Problem Details payload with structured error information.
        Includes type, title, status, detail, instance, code, and optional
        extensions. Present on all error responses.
    """

    error: str
    problem: ProblemDetailsDict


class ScopeIn(TypedDict, total=False):
    """Query scope parameters for filtering search results.

    Defines the scope of a code intelligence query, allowing filtering by
    repository, branch, commit, file patterns, and languages. All fields
    are optional (total=False) - unspecified fields don't filter results.

    This scope is used throughout the MCP server to limit searches to relevant
    parts of the codebase. For example, a query might be scoped to a specific
    repository and Python files only.

    Attributes
    ----------
    repos : list[str]
        List of repository names to include in the search. Repository names
        should match the repository identifier in the index. Empty list or
        omitted means all repositories.
    branches : list[str]
        List of branch names to search. Useful for limiting to specific branches
        (e.g., ["main", "develop"]). Empty list or omitted means all branches.
    commit : str
        Specific commit SHA to search. If provided, results are limited to
        code as it existed at this commit. Useful for historical queries.
    include_globs : list[str]
        File path glob patterns to include (e.g., ["**/*.py", "src/**"]).
        Only files matching these patterns are searched. Empty list or omitted
        means all files.
    exclude_globs : list[str]
        File path glob patterns to exclude (e.g., ["**/test_*.py", "**/__pycache__/**"]).
        Files matching these patterns are excluded from search. Empty list or
        omitted means no exclusions.
    languages : list[str]
        Programming languages to include (e.g., ["python", "typescript"]).
        Only files of these languages are searched. Empty list or omitted means
        all languages.
    kinds : list[str]
        Symbol kinds to include (e.g., ["function", "class", "method"]).
        Results are scoped to these symbol categories when provided.
    symbols : list[str]
        Specific SCIP symbol identifiers to focus on regardless of location.
    """

    repos: list[str]
    branches: list[str]
    commit: str
    include_globs: list[str]
    exclude_globs: list[str]
    languages: list[str]
    kinds: list[str]
    symbols: list[str]


class Match(TypedDict):
    """Search match result from text or semantic search.

    Represents a single match found by a search operation (text search, semantic
    search, etc.). Contains the file location and a code preview for display.

    The score field is optional because some search types (like exact text match)
    may not have a relevance score. When present, scores are typically normalized
    to 0-1 range with higher values indicating better matches.

    Attributes
    ----------
    path : str
        File path where the match was found. Typically a relative path from the
        repository root. Used for navigation and file filtering.
    line : int
        Line number where the match occurs (1-indexed for human readability).
        Used for "go to line" functionality and displaying code context.
    column : int
        Column/character position within the line (0-indexed). Used for precise
        positioning within a line, especially for symbol references.
    preview : str
        Code snippet preview showing the matched code in context. Typically
        1-3 lines around the match. Used for displaying search results without
        opening the full file.
    score : NotRequired[float]
        Relevance score for the match (0.0 to 1.0, higher is better). Present
        for semantic search results, may be omitted for exact text matches.
        Used for ranking and filtering results.
    """

    path: str
    line: int
    column: int
    preview: str
    score: NotRequired[float]


class Location(TypedDict):
    """Source code location with precise line and column positions.

    Represents a contiguous region of source code using line and column
    coordinates. Used for symbol definitions, references, and code ranges.
    Matches the LSP Location format for compatibility with language servers.

    All coordinates are 0-indexed to match programming conventions. The range
    is inclusive at start, exclusive at end (matching LSP/SCIP convention).

    Attributes
    ----------
    uri : str
        File URI or path identifying the source file. Typically a relative path
        from the repository root. Used to locate and open the file.
    start_line : int
        Starting line number (0-indexed). The first line of a file is line 0.
        Together with start_column, defines the start of the range.
    start_column : int
        Starting column/character position (0-indexed) within start_line.
        Character 0 is the first character on the line. Defines the precise
        start position.
    end_line : int
        Ending line number (0-indexed, inclusive). The range spans from start_line
        to end_line (inclusive). For single-line ranges, equals start_line.
    end_column : int
        Ending column/character position (0-indexed, exclusive) within end_line.
        The range includes characters from start_column up to (but not including)
        end_column. This matches LSP/SCIP convention.
    """

    uri: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int


class Finding(TypedDict, total=False):
    """Generic finding result from code intelligence queries.

    Represents a single finding from a search or analysis operation. Findings
    can be symbol definitions, references, documentation, security issues, API
    usages, etc. All fields are optional (total=False) to allow flexible
    result structures.

    Findings are the primary result type returned by MCP tools. They combine
    location information, code snippets, and metadata to provide actionable
    code intelligence.

    Attributes
    ----------
    type : Literal["definition", "reference", "usage", "doc", "security", "api"]
        Type of finding. "definition" = symbol definition, "reference" = symbol
        reference/usage, "usage" = how something is used, "doc" = documentation,
        "security" = security-related finding, "api" = API usage or definition.
    title : str
        Human-readable title for the finding. Should be concise and descriptive
        (e.g., "Function definition: process_data", "Security issue: SQL injection").
        Used for display in search results and tooltips.
    location : Location
        Source code location where this finding occurs. Includes file URI and
        precise line/column positions for navigation.
    snippet : str
        Code snippet showing the relevant code. Typically 3-10 lines of context
        around the finding. Used for preview without opening the full file.
    score : float
        Relevance score (0.0 to 1.0, higher is better). Indicates how well this
        finding matches the query. Used for ranking and filtering results.
    why : str
        Explanation of why this finding matches the query. Provides context and
        reasoning for the match (e.g., "Matches query 'data processing' because
        function name contains 'process' and docstring mentions 'data'").
    chunk_id : int
        Internal chunk identifier used for hydration bookkeeping and hybrid fusion.
        Not all clients need this value; it is primarily used by the server when
        combining multiple retrieval channels.
    """

    type: Literal["definition", "reference", "usage", "doc", "security", "api"]
    title: str
    location: Location
    snippet: str
    score: float
    why: str
    chunk_id: int


class MethodInfo(TypedDict, total=False):
    """Retrieval method metadata for search operations.

    Describes which retrieval methods were used to generate search results and
    provides information about search coverage. Useful for understanding result
    quality and debugging search behavior.

    All fields are optional (total=False) to allow flexible metadata structures.

    Attributes
    ----------
    retrieval : list[str]
        List of retrieval methods used to generate results. Common values:
        "semantic" (FAISS/dense embeddings), "bm25" (keyword/BM25), "splade"
        (learned sparse), "structural" (AST-based). Multiple methods indicate
        hybrid retrieval with RRF fusion.
    coverage : str
        Human-readable description of search coverage. Explains what was searched
        and any limitations (e.g., "Searched 1.2M chunks across Python files",
        "Limited to main branch", "Index incomplete - missing recent commits").
    stages : list[StageInfo]
        Optional stage-level timing data for observability.
    notes : list[str]
        Optional free-form notes about retrieval decisions (e.g., gating reasons).
    explainability : dict[str, list[dict[str, object]]]
        Optional structured explainability payload keyed by channel.
    rerank : dict[str, object]
        Optional metadata describing the reranker decision (provider, reason).
    """

    retrieval: list[str]
    coverage: str
    stages: list[StageInfo]
    notes: list[str]
    explainability: dict[str, list[dict[str, object]]]
    rerank: dict[str, object]


class StageInfo(TypedDict, total=False):
    """Timing metadata for an individual retrieval stage."""

    name: str
    duration_ms: float
    budget_ms: int | None
    exceeded_budget: bool


class AnswerEnvelope(TypedDict, total=False):
    """Standard response envelope for MCP code intelligence tools.

    Comprehensive response structure that wraps all types of code intelligence
    results. This envelope provides a consistent format across all MCP tools,
    making it easy for clients to process results uniformly.

    All fields are optional (total=False) - tools include only relevant fields
    for their specific operation. For example, a semantic search might include
    findings and method, while a symbol lookup might include xrefs and docs.

    Attributes
    ----------
    answer : str
        Human-readable summary answer to the query. Provides a natural language
        explanation of the results (e.g., "Found 15 functions related to data
        processing in src/core/"). Used for display in chat interfaces.
    query_kind : str
        Type of query that was executed (e.g., "semantic_search", "symbol_lookup",
        "text_search", "code_review"). Used for result categorization and routing.
    scope : ScopeIn
        Query scope that was applied to filter results. Shows which repositories,
        branches, files, and languages were searched. Useful for understanding
        result limitations.
    method : MethodInfo
        Retrieval method metadata describing how results were generated. Includes
        which retrieval systems were used and search coverage information.
    findings : list[Finding]
        Primary search results as Finding objects. Each finding represents a
        code location with context. This is the main result field for most queries.
    xrefs : dict
        Cross-reference information (callers, callees, dependencies). Structure
        varies by query type. For symbol queries, might contain "callers" and
        "callees" lists. For dependency queries, might contain dependency graphs.
    history : list[dict]
        Git history entries related to the query. Each entry typically contains
        commit SHA, author, date, message. Used for "who changed this" queries.
    docs : list[dict]
        Documentation entries found. Might include ADRs, API docs, README sections.
        Structure varies by documentation format.
    security : list[dict]
        Security-related findings (vulnerabilities, issues, best practices).
        Each entry describes a security concern with location and severity.
    api : dict
        API catalog information. Contains API definitions, endpoints, schemas
        relevant to the query. Structure depends on API format (OpenAPI, etc.).
    owners : list[dict]
        Code ownership information. Lists who owns or maintains the code in question.
        Each entry might contain name, email, team, ownership percentage.
    related : list[dict]
        Related findings or suggestions. Might include similar code, related
        symbols, or follow-up queries. Structure varies.
    confidence : float
        Overall confidence score for the results (0.0 to 1.0). Indicates how
        confident the system is that results are relevant and complete. Higher
        values indicate high-quality, complete results.
    limits : list[str]
        List of limitations or degraded service notices. Explains any constraints
        on the search (e.g., "Index incomplete", "GPU unavailable - using CPU",
        "Limited to 1000 results"). Used for transparency and debugging.
    next_steps : list[str]
        Suggested follow-up queries or actions. Provides guidance on how to
        refine the search or explore related topics (e.g., "Try searching for
        'data validation'", "See callers of this function").
    problem : ProblemDetailsDict
        RFC 9457 Problem Details payload describing the failure when the request
        could not be fulfilled successfully.
    """

    answer: str
    query_kind: str
    scope: ScopeIn
    method: MethodInfo
    findings: list[Finding]
    xrefs: dict
    history: list[dict]
    docs: list[dict]
    security: list[dict]
    api: dict
    owners: list[dict]
    related: list[dict]
    confidence: float
    limits: list[str]
    next_steps: list[str]
    problem: ProblemDetailsDict


class SymbolInfo(TypedDict):
    """Symbol information with location and documentation.

    Represents a programming language symbol (function, class, variable, etc.)
    with its location and optional documentation. Used for symbol search results
    and "go to definition" functionality.

    Attributes
    ----------
    name : str
        Symbol name as it appears in source code (e.g., "process_data", "DataProcessor").
        Used for display and matching.
    kind : str
        Symbol kind/type (e.g., "function", "class", "variable", "method", "module").
        Language-specific but typically follows LSP symbol kinds. Used for
        filtering and categorization.
    location : Location
        Source code location where the symbol is defined. Includes file URI and
        precise line/column positions for navigation.
    doc : NotRequired[str]
        Documentation string for the symbol (docstring, JSDoc, etc.). May be
        omitted if no documentation is available. Used for displaying symbol
        information without opening the file.
    """

    name: str
    kind: str
    location: Location
    doc: NotRequired[str]


class GitBlameEntry(TypedDict):
    """Git blame entry for a single line of code.

    Represents the git blame information for one line, showing who last modified
    it, when, and why. Used for code ownership queries and understanding code
    history.

    Attributes
    ----------
    line : int
        Line number (1-indexed for human readability). The line this blame entry
        refers to.
    commit : str
        Full commit SHA (40-character hex string) that last modified this line.
        Used for linking to commit details and diffs.
    author : str
        Name of the author who made the commit. Typically in "Name <email>"
        format. Used for identifying code owners.
    date : str
        Commit date in ISO 8601 format (e.g., "2024-01-15T10:30:00Z"). Used for
        temporal analysis and filtering by date.
    message : str
        Commit message explaining why the change was made. First line or full
        message depending on context. Used for understanding the reason for changes.
    """

    line: int
    commit: str
    author: str
    date: str
    message: str


class OpenFileResponse(BaseErrorFields):
    """Response from open_file tool.

    On success: path, content, lines, size are populated.
    On error: all result fields are empty/zero, error and problem are present.

    Attributes
    ----------
    path : str
        File path relative to repository root. Empty string on error.
    content : str
        File content (optionally sliced by line range). Empty string on error.
    lines : int
        Number of lines in the returned content. Zero on error.
    size : int
        Size of the returned content in bytes. Zero on error.
    """

    path: str
    content: str
    lines: int
    size: int


class ListPathsResponse(BaseErrorFields):
    """Response from list_paths tool.

    On success: items list is populated, total > 0.
    On error: items is empty list, total is 0, error and problem are present.

    Attributes
    ----------
    items : list[dict]
        List of file items with path, size, modified timestamp. Empty list on error.
    total : int
        Total number of files found. Zero on error.
    truncated : NotRequired[bool]
        Whether results were truncated due to max_results limit. False on error.
    """

    items: list[dict]
    total: int
    truncated: NotRequired[bool]


class BlameRangeResponse(BaseErrorFields):
    """Response from blame_range tool.

    On success: blame list is populated.
    On error: blame is empty list, error and problem are present.

    Attributes
    ----------
    blame : list[GitBlameEntry]
        List of git blame entries for the requested line range. Empty list on error.
    """

    blame: list[GitBlameEntry]


class FileHistoryResponse(BaseErrorFields):
    """Response from file_history tool.

    On success: commits list is populated.
    On error: commits is empty list, error and problem are present.

    Attributes
    ----------
    commits : list[dict]
        List of commit entries with SHA, author, date, message. Empty list on error.
    """

    commits: list[dict]


class SearchTextResponse(BaseErrorFields):
    """Response from search_text tool.

    On success: matches list is populated, total > 0.
    On error: matches is empty, total is 0, error and problem are present.

    Attributes
    ----------
    matches : list[Match]
        List of search matches. Empty list on error.
    total : int
        Total number of matches found. Zero on error.
    truncated : NotRequired[bool]
        Whether results were truncated due to max_results limit. False on error.
    """

    matches: list[Match]
    total: int
    truncated: NotRequired[bool]


__all__ = [
    "AnswerEnvelope",
    "BaseErrorFields",
    "BlameRangeResponse",
    "FileHistoryResponse",
    "Finding",
    "GitBlameEntry",
    "ListPathsResponse",
    "Location",
    "Match",
    "MethodInfo",
    "OpenFileResponse",
    "ScopeIn",
    "SearchTextResponse",
    "SymbolInfo",
]
