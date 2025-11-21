"""Scope configuration plus text and semantic search integration paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from codeintel_rev.mcp_server.adapters import files as files_adapter
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.mcp_server.adapters import text_search as text_search_adapter
from codeintel_rev.mcp_server.schemas import ScopeIn

from tests._helpers import assertions
from tests._helpers.integration import IntegrationHarness
from tests.conftest import HAS_FAISS_SUPPORT

pytestmark = pytest.mark.integration


def _seed_repo_file(harness: IntegrationHarness, relpath: str, contents: str) -> None:
    target = harness.repo_root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_scope_round_trip(integration_harness: IntegrationHarness) -> None:
    """Scope persistence and listing should respect include globs."""
    _seed_repo_file(integration_harness, "src/main.py", "def run():\n    return 1\n")
    _seed_repo_file(integration_harness, "docs/guide.md", "# docs\n")

    context = integration_harness.context
    scope: ScopeIn = cast(
        "ScopeIn", {"include_globs": ["src/**"], "languages": ["python"], "repos": ["test"]}
    )
    result = await files_adapter.set_scope(context, scope)
    assertions.expect_equal(result.get("status"), "ok")

    listing = await files_adapter.list_paths(context, max_results=10)
    paths = {item["path"] for item in listing["items"]}
    assertions.expect_true(all(path.startswith("src/") for path in paths))


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
async def test_text_search_with_custom_runner(integration_harness: IntegrationHarness) -> None:
    """Text search adapter should surface mocked ripgrep results."""
    context = integration_harness.context
    repo_root = integration_harness.repo_root
    _seed_repo_file(integration_harness, "module.py", "def sample():\n    return 1\n")

    def _fake_run_subprocess(
        cmd: list[str],
        *,
        cwd: object,
        timeout: int,
        env: object | None = None,
    ) -> str:
        _ = cmd, timeout, env
        sample_path = (cast("Path", cwd) if cwd else repo_root) / "module.py"
        payload = {
            "type": "match",
            "data": {
                "path": {"text": str(sample_path.resolve())},
                "lines": {"text": "def sample():\n"},
                "line_number": 1,
                "submatches": [{"start": 0}],
            },
        }
        return json.dumps(payload)

    result = await text_search_adapter.search_text(
        context,
        "def",
        max_results=3,
        runner=_fake_run_subprocess,
    )
    assertions.expect_true(isinstance(result.get("matches"), list))


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_session_id")
@pytest.mark.skipif(not HAS_FAISS_SUPPORT, reason="FAISS bindings unavailable")
async def test_semantic_search_runs_with_seeded_index(
    integration_harness: IntegrationHarness,
    faiss_index_seed: None,
) -> None:
    """Semantic search should return well-formed payload with a seeded FAISS index."""
    _ = faiss_index_seed
    context = integration_harness.context
    result = await semantic_adapter.semantic_search(
        context,
        "integration seed",
        limit=2,
    )
    assertions.expect_in("findings", result)
    assertions.expect_in("limits", result)
