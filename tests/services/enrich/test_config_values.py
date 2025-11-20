# SPDX-License-Identifier: MIT
"""Tests for config value normalization."""

from __future__ import annotations

from typing import cast

from codeintel_rev.enrich.models import ModuleRecord
from codeintel_rev.services.enrich.analytics import prepare_config_state
from codeintel_rev.services.enrich.config_values import build_config_value_rows

from tests._helpers import assertions


def test_build_config_value_rows_normalizes_references() -> None:
    """Config value rows should include formats, references, and modules."""
    module_rows = [
        ModuleRecord(path="src/app.py", repo_path="src/app.py", module_name="pkg.app"),
        ModuleRecord(path="src/util.py", repo_path="src/util.py", module_name="pkg.util"),
    ]
    records = [
        {
            "path": "config/settings.yaml",
            "keys": ["service.host", "service.port"],
            "references": ["src/app.py", "src/util.py"],
        },
        {
            "path": "config/feature.toml",
            "keys": ["feature.enabled"],
            "references": [],
        },
    ]

    state = prepare_config_state(records)
    rows = build_config_value_rows(state, module_rows)

    assertions.expect_equal(len(rows), 3)
    host_row = next(row for row in rows if row["key"] == "service.host")
    port_row = next(row for row in rows if row["key"] == "service.port")
    feature_row = next(row for row in rows if row["key"] == "feature.enabled")

    expected_refs = ["src/app.py", "src/util.py"]
    expected_modules = ["pkg.app", "pkg.util"]
    assertions.expect_sequence_equal(
        cast("list[str]", host_row["reference_paths"]),
        expected_refs,
    )
    assertions.expect_sequence_equal(
        cast("list[str]", port_row["reference_modules"]),
        expected_modules,
    )
    assertions.expect_equal(host_row["reference_count"], 2)
    assertions.expect_equal(host_row["format"], "yaml")
    assertions.expect_equal(feature_row["format"], "toml")
