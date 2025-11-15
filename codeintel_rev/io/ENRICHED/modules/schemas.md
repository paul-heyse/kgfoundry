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
- class: `ExplanationPayload` (line 168)
- class: `Finding` (line 176)
- class: `MethodInfo` (line 230)
- class: `StageInfo` (line 268)
- class: `SearchFilterPayload` (line 280)
- class: `SearchToolArgs` (line 302)
- class: `SearchExplainability` (line 311)
- class: `SearchResultMetadata` (line 320)
- class: `SearchResultItem` (line 333)
- class: `SearchStructuredContent` (line 345)
- class: `FetchToolArgs` (line 354)
- class: `FetchObjectMetadata` (line 361)
- class: `FetchObject` (line 372)
- class: `FetchStructuredContent` (line 382)
- class: `AnswerEnvelope` (line 388)
- class: `SymbolInfo` (line 492)
- class: `GitBlameEntry` (line 523)
- class: `OpenFileResponse` (line 556)
- class: `ListPathsResponse` (line 580)
- class: `BlameRangeResponse` (line 601)
- class: `FileHistoryResponse` (line 616)
- class: `SearchTextResponse` (line 631)

## Graph Metrics

- **fan_in**: 13
- **fan_out**: 1
- **cycle_group**: 31

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
- loc: 678

## Doc Coverage

- `BaseErrorFields` (class): summary=yes, examples=no — Base fields present in ALL error responses.
- `ScopeIn` (class): summary=yes, examples=no — Query scope parameters for filtering search results.
- `Match` (class): summary=yes, examples=no — Search match result from text or semantic search.
- `Location` (class): summary=yes, examples=no — Source code location with precise line and column positions.
- `ExplanationPayload` (class): summary=yes, examples=no — Structure-aware explanation metadata attached to findings.
- `Finding` (class): summary=yes, examples=no — Generic finding result from code intelligence queries.
- `MethodInfo` (class): summary=yes, examples=no — Retrieval method metadata for search operations.
- `StageInfo` (class): summary=yes, examples=no — Timing metadata for an individual retrieval stage.
- `SearchFilterPayload` (class): summary=yes, examples=no — Structured filter payload for Deep Research search requests.
- `SearchToolArgs` (class): summary=yes, examples=no — Input schema for the MCP ``search`` tool.

## Tags

low-coverage, public-api, reexport-hub
