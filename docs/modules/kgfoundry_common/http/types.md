# kgfoundry_common.http.types

Type definitions for HTTP client retry strategies.

[View source on GitHub](https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/http/types.py)

## Hierarchy

- **Parent:** [kgfoundry_common.http](../http.md)

## Sections

- **Public API**

## Contents

### kgfoundry_common.http.types.RetryStrategy

::: kgfoundry_common.http.types.RetryStrategy

*Bases:* Protocol

## Relationships

**Imports:** `__future__.annotations`, `collections.abc.Callable`, `typing.Protocol`, `typing.TypeVar`

## Autorefs Examples

- [kgfoundry_common.http.types.RetryStrategy][]

## Inheritance

```mermaid
classDiagram
    class RetryStrategy
    class Protocol
    Protocol <|-- RetryStrategy
```

## Neighborhood

```d2
direction: right
"kgfoundry_common.http.types": "kgfoundry_common.http.types" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/http/types.py" }
"__future__.annotations": "__future__.annotations"
"kgfoundry_common.http.types" -> "__future__.annotations"
"collections.abc.Callable": "collections.abc.Callable"
"kgfoundry_common.http.types" -> "collections.abc.Callable"
"typing.Protocol": "typing.Protocol"
"kgfoundry_common.http.types" -> "typing.Protocol"
"typing.TypeVar": "typing.TypeVar"
"kgfoundry_common.http.types" -> "typing.TypeVar"
"kgfoundry_common.http": "kgfoundry_common.http" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/http/__init__.py" }
"kgfoundry_common.http" -> "kgfoundry_common.http.types" { style: dashed }
```

