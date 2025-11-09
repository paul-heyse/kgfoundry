"""Tests for OpenAPI operation hyperlink generation utilities."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

operation_links = importlib.import_module(
    "tools.mkdocs_suite.docs._scripts._operation_links"
)
build_operation_href = cast(
    "Callable[[object, str], str | None]",
    operation_links.build_operation_href,
)


@pytest.mark.parametrize(
    ("spec_path", "operation_id", "expected"),
    [
        (
            "docs/api/openapi-cli.yaml",
            "cli.run-command",
            "api/openapi-cli.md#operation/cli.run-command",
        ),
        (
            Path("docs/api/openapi.yaml"),
            "http.get-resource",
            "api/index.md#operation/http.get-resource",
        ),
    ],
)
def test_build_operation_href_known_specs(
    spec_path: str | Path, operation_id: str, expected: str
) -> None:
    """CLI and HTTP specs should resolve to their rendered Markdown pages."""
    href = build_operation_href(spec_path, operation_id)

    assert href == expected


def test_build_operation_href_encodes_operation_id() -> None:
    """Operation identifiers must be percent-encoded within anchors."""
    href = build_operation_href("openapi.yaml", 'operation id/with"chars"?')

    assert href == "api/index.md#operation/operation%20id%2Fwith%22chars%22%3F"


@pytest.mark.parametrize("spec_path", [None, object(), Path("spec/openapi.json")])
def test_build_operation_href_rejects_unknown_specs(spec_path: object) -> None:
    """Unknown specification files should not produce hyperlinks."""
    href = build_operation_href(spec_path, "ignored")

    assert href is None


def test_build_operation_href_requires_operation_identifier() -> None:
    """Empty or missing operation identifiers should return ``None``."""
    assert build_operation_href("openapi.yaml", "") is None
