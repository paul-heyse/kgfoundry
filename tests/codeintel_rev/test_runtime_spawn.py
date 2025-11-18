"""Sanity checks ensuring multiprocessing uses spawn start method."""

from __future__ import annotations

import multiprocessing as mp

from tests._helpers import assertions


def test_multiprocessing_start_method_is_spawn() -> None:
    """The active multiprocessing start method must be spawn for safety."""
    start_method = mp.get_start_method(allow_none=True)
    assertions.expect_equal(start_method, "spawn")
