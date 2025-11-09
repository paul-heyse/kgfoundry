"""Overview of kgfoundry common.

This module bundles kgfoundry common logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

# [nav:anchor config]
# [nav:anchor errors]
# [nav:anchor exceptions]
# [nav:anchor fs]
# [nav:anchor ids]
# [nav:anchor logging]
# [nav:anchor models]
# [nav:anchor navmap_types]
# [nav:anchor parquet_io]
# [nav:anchor safe_pickle_v2]
# [nav:anchor subprocess_utils]
from kgfoundry_common import (
    config,
    errors,
    exceptions,
    fs,
    ids,
    logging,
    models,
    navmap_types,
    observability,
    parquet_io,
    safe_pickle_v2,
    schema_helpers,
    sequence_guards,
    serialization,
    settings,
    subprocess_utils,
    vector_types,
)
from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "config",
    "errors",
    "exceptions",
    "fs",
    "ids",
    "logging",
    "models",
    "navmap_types",
    "observability",
    "parquet_io",
    "safe_pickle_v2",
    "schema_helpers",
    "sequence_guards",
    "serialization",
    "settings",
    "subprocess_utils",
    "vector_types",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
