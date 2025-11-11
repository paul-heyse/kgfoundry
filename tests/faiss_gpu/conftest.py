from collections.abc import Callable

import numpy as np
import pytest

SEED = 1234


def pytest_addoption(parser):
    parser.addoption(
        "--gpu-strict", action="store_true", help="Fail instead of skip if GPU module is missing."
    )


@pytest.fixture(scope="session")
def rng():
    return np.random.RandomState(SEED)


@pytest.fixture(scope="session")
def dims():
    return 64


@pytest.fixture(scope="session")
def train_db(rng, dims):
    xb = rng.random_sample((5000, dims)).astype("float32")
    xb[:, 0] += np.arange(xb.shape[0]) / 1000.0
    return xb


@pytest.fixture(scope="session")
def query_db(rng, dims):
    nq = 200
    xq = rng.random_sample((nq, dims)).astype("float32")
    xq[:, 0] += np.arange(nq) / 1000.0
    return xq


@pytest.fixture(scope="session")
def k():
    return 10


@pytest.fixture(scope="session")
def gpu_require(pytestconfig) -> Callable[[object, str], None]:
    """Return helper that skips or fails when GPU requirements are unmet.

    Returns
    -------
    Callable[[object, str], None]
        Callback that accepts a truthy condition and a failure reason.
    """

    def _check(condition: object, reason: str) -> None:
        if condition:
            return
            if pytestconfig.getoption("gpu_strict", default=False):
                pytest.fail(reason)
            pytest.skip(reason)

    return _check
