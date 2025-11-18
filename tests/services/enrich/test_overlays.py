# SPDX-License-Identifier: MIT
"""Tests for overlay service helpers."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.services.enrich import overlays

from tests._helpers import assertions


def test_load_overlay_options_applies_overrides(tmp_path: Path) -> None:
    """Overlay options honor config file defaults plus CLI overrides."""
    config = tmp_path / "overlay.json"
    config.write_text(
        json.dumps(
            {
                "stubs_root": tmp_path.as_posix(),
                "min_errors": 10,
                "inject_getattr_any": False,
            }
        ),
        encoding="utf-8",
    )
    options = overlays.load_overlay_options(config, ["min_errors=5", "inject_getattr_any=true"])
    expected_min_errors = 5
    assertions.expect_equal(options.stubs_root, tmp_path.resolve())
    assertions.expect_equal(options.min_errors, expected_min_errors)
    assertions.expect_true(options.inject_getattr_any)
