"""Search service endpoints and retrieval adapters.

This package provides typed search APIs with schema validation and
Problem Details error responses. All public APIs are explicitly exported
via `__all__` with full type annotations.

See Also
--------
- `schema/examples/problem_details/search-missing-index.json` - Example error response
- `schema/models/search_request.v1.json` - Request schema
- `schema/models/search_result.v1.json` - Response schema
"""

# [nav:section public-api]

from __future__ import annotations

import sys
from importlib import import_module
from typing import TYPE_CHECKING

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "app",
    "bm25_index",
    "faiss_adapter",
    "fixture_index",
    "fusion",
    "kg_mock",
    "schemas",
    "service",
    "splade_index",
    "types",
]

_ALIASES: dict[str, str] = {name: f"search_api.{name}" for name in __all__}

__navmap__ = load_nav_metadata(__name__, tuple(__all__))


if TYPE_CHECKING:  # pragma: no cover - typing only
    from types import ModuleType

    from search_api import (
        app as _app_module,
    )
    from search_api import (
        bm25_index as _bm25_module,
    )
    from search_api import (
        faiss_adapter as _faiss_module,
    )
    from search_api import (
        fixture_index as _fixture_module,
    )
    from search_api import (
        fusion as _fusion_module,
    )
    from search_api import (
        kg_mock as _kg_mock_module,
    )
    from search_api import (
        schemas as _schemas_module,
    )
    from search_api import (
        service as _service_module,
    )
    from search_api import (
        splade_index as _splade_module,
    )
    from search_api import (
        types as _types_module,
    )

    app = _app_module
    bm25_index = _bm25_module
    faiss_adapter = _faiss_module
    fixture_index = _fixture_module
    fusion = _fusion_module
    kg_mock = _kg_mock_module
    schemas = _schemas_module
    service = _service_module
    splade_index = _splade_module
    types = _types_module


def _load(name: str) -> ModuleType:
    module = import_module(_ALIASES[name])
    sys.modules[f"{__name__}.{name}"] = module
    return module


def __getattr__(name: str) -> ModuleType:
    if name not in _ALIASES:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message)
    return _load(name)


def __dir__() -> list[str]:
    return sorted(set(__all__))
