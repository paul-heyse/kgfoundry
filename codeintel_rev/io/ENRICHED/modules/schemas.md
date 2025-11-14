# mcp_server/schemas.py

## Docstring

```
MCP server schemas using TypedDict for FastMCP compatibility.

TypedDict provides automatic JSON Schema generation for FastMCP tools.
```

## Imports

- from **__future__** import annotations
- from **typing** import Literal, NotRequired, TypedDict
- from **kgfoundry_common.problem_details** import ProblemDetailsDict

## Definitions

- class: `BaseErrorFields` (line 13)
- class: `ScopeIn` (line 35)
- class: `Match` (line 92)
- class: `Location` (line 130)
- class: `Finding` (line 168)
- class: `MethodInfo` (line 218)
- class: `StageInfo` (line 256)
- class: `SearchFilterPayload` (line 268)
- class: `SearchToolArgs` (line 290)
- class: `SearchExplainability` (line 299)
- class: `SearchResultMetadata` (line 308)
- class: `SearchResultItem` (line 321)
- class: `SearchStructuredContent` (line 333)
- class: `FetchToolArgs` (line 342)
- class: `FetchObjectMetadata` (line 349)
- class: `FetchObject` (line 360)
- class: `FetchStructuredContent` (line 370)
- class: `AnswerEnvelope` (line 376)
- class: `SymbolInfo` (line 480)
- class: `GitBlameEntry` (line 511)
- class: `OpenFileResponse` (line 544)
- class: `ListPathsResponse` (line 568)
- class: `BlameRangeResponse` (line 589)
- class: `FileHistoryResponse` (line 604)
- class: `SearchTextResponse` (line 619)

## Graph Metrics

- **fan_in**: 13
- **fan_out**: 1
- **cycle_group**: 10

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 12
- recent churn 90: 12

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

AnswerEnvelope, BaseErrorFields, BlameRangeResponse, FetchObject, FetchObjectMetadata, FetchStructuredContent, FetchToolArgs, FileHistoryResponse, Finding, GitBlameEntry, ListPathsResponse, Location, Match, MethodInfo, OpenFileResponse, ScopeIn, SearchExplainability, SearchFilterPayload, SearchResultItem, SearchResultMetadata, SearchStructuredContent, SearchTextResponse, SearchToolArgs, SymbolInfo

## Doc Health

- **summary**: MCP server schemas using TypedDict for FastMCP compatibility.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 1.84

## Side Effects

- network

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 666

## Doc Coverage

- `BaseErrorFields` (class): summary=yes, examples=no — Base fields present in ALL error responses.
- `ScopeIn` (class): summary=yes, examples=no — Query scope parameters for filtering search results.
- `Match` (class): summary=yes, examples=no — Search match result from text or semantic search.
- `Location` (class): summary=yes, examples=no — Source code location with precise line and column positions.
- `Finding` (class): summary=yes, examples=no — Generic finding result from code intelligence queries.
- `MethodInfo` (class): summary=yes, examples=no — Retrieval method metadata for search operations.
- `StageInfo` (class): summary=yes, examples=no — Timing metadata for an individual retrieval stage.
- `SearchFilterPayload` (class): summary=yes, examples=no — Structured filter payload for Deep Research search requests.
- `SearchToolArgs` (class): summary=yes, examples=no — Input schema for the MCP ``search`` tool.
- `SearchExplainability` (class): summary=yes, examples=no — Explainability payload attached to each search result.

## Tags

low-coverage, public-api, reexport-hub
