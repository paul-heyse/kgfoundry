# kgfoundry_common.fastapi_helpers

Typed FastAPI helper utilities with structured logging and timeouts.

[View source on GitHub](https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/fastapi_helpers.py)

## Hierarchy

- **Parent:** [kgfoundry_common](../kgfoundry_common.md)

## Sections

- **Public API**

## Contents

### kgfoundry_common.fastapi_helpers._await_with_timeout

::: kgfoundry_common.fastapi_helpers._await_with_timeout

### kgfoundry_common.fastapi_helpers.typed_dependency

::: kgfoundry_common.fastapi_helpers.typed_dependency

### kgfoundry_common.fastapi_helpers.typed_exception_handler

::: kgfoundry_common.fastapi_helpers.typed_exception_handler

### kgfoundry_common.fastapi_helpers.typed_middleware

::: kgfoundry_common.fastapi_helpers.typed_middleware

## Relationships

**Imports:** `__future__.annotations`, `asyncio`, `collections.abc.Callable`, `fastapi.Depends`, `fastapi.FastAPI`, `fastapi.Request`, `fastapi.params.Depends`, `kgfoundry_common.logging.get_correlation_id`, `kgfoundry_common.logging.get_logger`, `kgfoundry_common.logging.with_fields`, `kgfoundry_common.navmap_loader.load_nav_metadata`, `kgfoundry_common.typing.gate_import`, `starlette.middleware.base.BaseHTTPMiddleware`, `starlette.requests.Request`, `starlette.responses.Response`, `starlette.types.ASGIApp`, `time`, `typing`, `typing.TYPE_CHECKING`, `typing.cast`

## Autorefs Examples

- [kgfoundry_common.fastapi_helpers._await_with_timeout][]
- [kgfoundry_common.fastapi_helpers.typed_dependency][]
- [kgfoundry_common.fastapi_helpers.typed_exception_handler][]

## Neighborhood

```d2
direction: right
"kgfoundry_common.fastapi_helpers": "kgfoundry_common.fastapi_helpers" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/fastapi_helpers.py" }
"__future__.annotations": "__future__.annotations"
"kgfoundry_common.fastapi_helpers" -> "__future__.annotations"
"asyncio": "asyncio"
"kgfoundry_common.fastapi_helpers" -> "asyncio"
"collections.abc.Callable": "collections.abc.Callable"
"kgfoundry_common.fastapi_helpers" -> "collections.abc.Callable"
"fastapi.Depends": "fastapi.Depends"
"kgfoundry_common.fastapi_helpers" -> "fastapi.Depends"
"fastapi.FastAPI": "fastapi.FastAPI"
"kgfoundry_common.fastapi_helpers" -> "fastapi.FastAPI"
"fastapi.Request": "fastapi.Request"
"kgfoundry_common.fastapi_helpers" -> "fastapi.Request"
"fastapi.params.Depends": "fastapi.params.Depends"
"kgfoundry_common.fastapi_helpers" -> "fastapi.params.Depends"
"kgfoundry_common.logging.get_correlation_id": "kgfoundry_common.logging.get_correlation_id"
"kgfoundry_common.fastapi_helpers" -> "kgfoundry_common.logging.get_correlation_id"
"kgfoundry_common.logging.get_logger": "kgfoundry_common.logging.get_logger"
"kgfoundry_common.fastapi_helpers" -> "kgfoundry_common.logging.get_logger"
"kgfoundry_common.logging.with_fields": "kgfoundry_common.logging.with_fields"
"kgfoundry_common.fastapi_helpers" -> "kgfoundry_common.logging.with_fields"
"kgfoundry_common.navmap_loader.load_nav_metadata": "kgfoundry_common.navmap_loader.load_nav_metadata"
"kgfoundry_common.fastapi_helpers" -> "kgfoundry_common.navmap_loader.load_nav_metadata"
"kgfoundry_common.typing.gate_import": "kgfoundry_common.typing.gate_import"
"kgfoundry_common.fastapi_helpers" -> "kgfoundry_common.typing.gate_import"
"starlette.middleware.base.BaseHTTPMiddleware": "starlette.middleware.base.BaseHTTPMiddleware"
"kgfoundry_common.fastapi_helpers" -> "starlette.middleware.base.BaseHTTPMiddleware"
"starlette.requests.Request": "starlette.requests.Request"
"kgfoundry_common.fastapi_helpers" -> "starlette.requests.Request"
"starlette.responses.Response": "starlette.responses.Response"
"kgfoundry_common.fastapi_helpers" -> "starlette.responses.Response"
"starlette.types.ASGIApp": "starlette.types.ASGIApp"
"kgfoundry_common.fastapi_helpers" -> "starlette.types.ASGIApp"
"time": "time"
"kgfoundry_common.fastapi_helpers" -> "time"
"typing": "typing"
"kgfoundry_common.fastapi_helpers" -> "typing"
"typing.TYPE_CHECKING": "typing.TYPE_CHECKING"
"kgfoundry_common.fastapi_helpers" -> "typing.TYPE_CHECKING"
"typing.cast": "typing.cast"
"kgfoundry_common.fastapi_helpers" -> "typing.cast"
"kgfoundry_common": "kgfoundry_common" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/__init__.py" }
"kgfoundry_common" -> "kgfoundry_common.fastapi_helpers" { style: dashed }
```

