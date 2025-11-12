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
- class: `AnswerEnvelope` (line 265)
- class: `SymbolInfo` (line 352)
- class: `GitBlameEntry` (line 383)
- class: `OpenFileResponse` (line 416)
- class: `ListPathsResponse` (line 440)
- class: `BlameRangeResponse` (line 461)
- class: `FileHistoryResponse` (line 476)
- class: `SearchTextResponse` (line 491)

## Dependency Graph

- **fan_in**: 12
- **fan_out**: 1
- **cycle_group**: 12

## Declared Exports (__all__)

AnswerEnvelope, BaseErrorFields, BlameRangeResponse, FileHistoryResponse, Finding, GitBlameEntry, ListPathsResponse, Location, Match, MethodInfo, OpenFileResponse, ScopeIn, SearchTextResponse, SymbolInfo

## Tags

public-api, reexport-hub
