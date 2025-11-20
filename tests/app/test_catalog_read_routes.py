# SPDX-License-Identifier: MIT
"""HTTP-level tests for catalog read routes."""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote

from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from fastapi.testclient import TestClient

from tests._helpers import assertions
from tests._helpers.catalog import build_graph_catalog_fixture, make_catalog_app


def _build_client(catalog: DuckDBCatalog) -> TestClient:
    """Build a FastAPI test client with catalog router and context.

    Parameters
    ----------
    catalog : DuckDBCatalog
        DuckDBCatalog instance to inject into app state.

    Returns
    -------
    TestClient
        FastAPI test client configured with catalog read routes.
    """
    return TestClient(make_catalog_app(catalog))


def test_goid_endpoint_returns_crosswalk(tmp_path: Path) -> None:
    """Verify GOID endpoint returns crosswalk rows matching SCIP symbol filter."""
    catalog, goids = build_graph_catalog_fixture(tmp_path)
    client = _build_client(catalog)
    resp = client.get("/v1/catalog/goids", params={"scip_symbol": "pkg.demo.caller"})
    assertions.expect_equal(resp.status_code, HTTPStatus.OK)
    payload = resp.json()
    assertions.expect_true(payload["data"])
    assertions.expect_equal(payload["data"][0]["goid"], goids["caller"].urn)


def test_call_graph_endpoint_supports_ndjson(tmp_path: Path) -> None:
    """Verify call graph endpoint streams NDJSON when Accept header requests it."""
    catalog, goids = build_graph_catalog_fixture(tmp_path)
    client = _build_client(catalog)
    resp = client.get(
        "/v1/graph/call",
        params={"root_goid": goids["caller"].urn, "direction": "out"},
        headers={"Accept": "application/x-ndjson"},
    )
    assertions.expect_equal(resp.status_code, HTTPStatus.OK)
    lines = [line for line in resp.text.splitlines() if line.strip()]
    assertions.expect_true(lines, reason="Streaming response should yield edges")
    first_edge = json.loads(lines[0])
    assertions.expect_equal(first_edge["caller"], goids["caller"].urn)


def test_cfg_and_dfg_endpoints(tmp_path: Path) -> None:
    """Verify CFG and DFG endpoints return graph data and handle missing functions."""
    catalog, goids = build_graph_catalog_fixture(tmp_path)
    client = _build_client(catalog)
    encoded_goid = quote(goids["caller"].urn, safe="")
    cfg_resp = client.get(f"/v1/flow/cfg/{encoded_goid}")
    assertions.expect_equal(cfg_resp.status_code, HTTPStatus.OK)
    cfg = cfg_resp.json()
    assertions.expect_true(cfg["blocks"])
    dfg_resp = client.get(f"/v1/flow/dfg/{encoded_goid}")
    assertions.expect_equal(dfg_resp.status_code, HTTPStatus.OK)
    dfg = dfg_resp.json()
    assertions.expect_true(dfg["nodes"])
    missing_token = quote("goid:missing", safe="")
    missing_cfg = client.get(f"/v1/flow/cfg/{missing_token}")
    assertions.expect_equal(missing_cfg.status_code, HTTPStatus.NOT_FOUND)
    missing_dfg = client.get(f"/v1/flow/dfg/{missing_token}")
    assertions.expect_equal(missing_dfg.status_code, HTTPStatus.NOT_FOUND)
