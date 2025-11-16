"""Utility assertions that replace bare ``assert`` statements in tests."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import pytest


def expect_true(condition: bool, *, reason: str | None = None) -> None:
    """Fail the current test when ``condition`` evaluates to ``False``."""
    if condition:
        return
    message = "Expected condition to evaluate to True."
    if reason:
        message = f"{message} Reason: {reason}"
    pytest.fail(message, pytrace=False)


def expect_false(condition: bool, *, reason: str | None = None) -> None:
    """Fail the current test when ``condition`` evaluates to ``True``."""
    if not condition:
        return
    message = "Expected condition to evaluate to False."
    if reason:
        message = f"{message} Reason: {reason}"
    pytest.fail(message, pytrace=False)


def expect_equal(actual: Any, expected: Any, *, reason: str | None = None) -> None:
    """Fail when ``actual`` is not equal to ``expected`` according to ``==``."""
    if actual == expected:
        return
    message = f"Expected {actual!r} to equal {expected!r}."
    if reason:
        message = f"{message} Reason: {reason}"
    pytest.fail(message, pytrace=True)


def expect_almost_equal(
    actual: float,
    expected: float,
    *,
    rel_tol: float = 1e-6,
    abs_tol: float = 1e-9,
    reason: str | None = None,
) -> None:
    """Fail when ``actual`` and ``expected`` differ beyond the provided tolerances."""
    if math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol):
        return
    message = (
        f"Expected {actual!r} to be approximately equal to {expected!r} "
        f"(rel_tol={rel_tol}, abs_tol={abs_tol})."
    )
    if reason:
        message = f"{message} Reason: {reason}"
    pytest.fail(message, pytrace=True)


def expect_in(member: Any, container: Iterable[Any], *, reason: str | None = None) -> None:
    """Fail when ``member`` is not present inside ``container``."""
    if member in container:
        return
    message = f"Expected {member!r} to be present in {container!r}."
    if reason:
        message = f"{message} Reason: {reason}"
    pytest.fail(message, pytrace=True)


def expect_sequence_equal(
    actual: Sequence[Any],
    expected: Sequence[Any],
    *,
    reason: str | None = None,
) -> None:
    """Fail when the provided sequences differ."""
    if len(actual) != len(expected):
        expect_equal(len(actual), len(expected), reason="Sequence lengths differ.")
    mismatches = [
        (index, got, want)
        for index, (got, want) in enumerate(zip(actual, expected, strict=True))
        if got != want
    ]
    if not mismatches:
        return
    mismatch_lines = ", ".join(
        f"[{idx}] got={got!r} want={want!r}" for idx, got, want in mismatches
    )
    message = f"Sequence contents differ: {mismatch_lines}."
    if reason:
        message = f"{message} Reason: {reason}"
    pytest.fail(message, pytrace=True)


def expect_mapping_equal(
    actual: Mapping[Any, Any],
    expected: Mapping[Any, Any],
    *,
    reason: str | None = None,
) -> None:
    """Fail when the provided mappings differ."""
    missing = [key for key in expected if key not in actual]
    extra = [key for key in actual if key not in expected]
    value_mismatches = [
        (key, actual[key], expected[key])
        for key in expected
        if key in actual and actual[key] != expected[key]
    ]
    if not missing and not extra and not value_mismatches:
        return
    fragments: list[str] = []
    if missing:
        fragments.append(f"missing keys: {missing}")
    if extra:
        fragments.append(f"extra keys: {extra}")
    if value_mismatches:
        fragments.append(
            "mismatched values: "
            + ", ".join(
                f"{key!r} -> got {got!r}, want {want!r}" for key, got, want in value_mismatches
            ),
        )
    message = "Mapping contents differ: " + "; ".join(fragments) + "."
    if reason:
        message = f"{message} Reason: {reason}"
    pytest.fail(message, pytrace=True)
