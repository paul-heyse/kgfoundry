"""Shared fixtures for integration contracts using the harness."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from codeintel_rev.app.main import readyz
from codeintel_rev.app.runtime_readiness import ReadinessProbe
from codeintel_rev.io.faiss_manager import FAISSManager
from fastapi.testclient import TestClient

from tests._helpers.http import build_test_app
from tests._helpers.integration import (
    IntegrationHarness,
    IntegrationHarnessOptions,
    build_integration_harness,
)
from tests.conftest import HAS_FAISS_SUPPORT

pytestmark = pytest.mark.integration


@pytest.fixture
def integration_harness(tmp_path: Path) -> Iterator[IntegrationHarness]:
    """Provision an integration harness with real FAISS when available.

    Yields
    ------
    IntegrationHarness
        Harness containing application context and repo root.
    """
    harness = build_integration_harness(
        tmp_path,
        options=IntegrationHarnessOptions(use_real_faiss=HAS_FAISS_SUPPORT),
    )
    try:
        yield harness
    finally:
        harness.close()


@pytest.fixture
def integration_app(
    integration_harness: IntegrationHarness,
) -> Iterator[tuple[TestClient, IntegrationHarness]]:
    """Yield a FastAPI TestClient bound to the harness context.

    Yields
    ------
    tuple[TestClient, IntegrationHarness]
        Tuple containing HTTP client and the backing harness.
    """
    context = integration_harness.context
    readiness = ReadinessProbe(context)
    app = build_test_app(context)
    app.state.readiness = readiness
    app.add_api_route("/readyz", readyz)
    with TestClient(app) as client:
        yield client, integration_harness


@pytest.fixture
def faiss_index_seed(integration_harness: IntegrationHarness) -> None:
    """Seed a tiny FAISS index for semantic search flows when bindings exist."""
    manager = integration_harness.context.faiss_manager
    if not HAS_FAISS_SUPPORT or not isinstance(manager, FAISSManager):
        pytest.skip("FAISS bindings unavailable on this host")
    vec_dim = manager.vec_dim
    rng = np.random.default_rng(7)
    vectors = rng.normal(0.25, 0.05, (3, vec_dim)).astype(np.float32)
    ids = np.arange(vectors.shape[0], dtype=np.int64)
    manager.build_index(vectors)
    manager.add_vectors(vectors, ids)
