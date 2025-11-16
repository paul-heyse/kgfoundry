"""Tests for Griffe-powered API symbol extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.repo_scan_griffe import collect_api_symbols_with_griffe

from tests._helpers import assertions


def _write(tmp_path: Path, relative: str, text: str) -> None:
    """Write text to a file at the given relative path."""
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_collect_api_symbols_with_griffe(tmp_path: Path) -> None:
    """Verify Griffe extracts API symbols with docstrings and parameters."""
    pytest.importorskip("griffe")
    pkg_root = tmp_path / "sample_pkg"
    _write(
        pkg_root,
        "__init__.py",
        '"""Sample package."""\nfrom .module import calculate_value, SampleClass\n',
    )
    _write(
        pkg_root,
        "module.py",
        '''"""Doc module."""

class SampleClass:
    """Class with documented init."""

    def __init__(self, value: int) -> None:
        """Initialize the class.

        Args:
            value: Initial value.
        """
        self._value = value

    def compute(self, delta: int) -> int:
        """Compute a new value.

        Args:
            delta: Amount to add.

        Returns:
            int: The updated value.

        Raises:
            ValueError: If ``delta`` is negative.
        """
        if delta < 0:
            raise ValueError("negative delta")
        return self._value + delta


def calculate_value(left: int, right: int) -> int:
    """Add two integers.

    Args:
        left: First operand.
        right: Second operand.

    Returns:
        int: Sum of both numbers.
    """
    return left + right
''',
    )

    symbols = collect_api_symbols_with_griffe(tmp_path, ["sample_pkg"], docstyle="google")
    names = {symbol.short_name: symbol for symbol in symbols}
    assertions.expect_in("SampleClass", names)
    sample = names["SampleClass"]
    assertions.expect_true(
        any(param.name == "value" for param in sample.params), reason="should have value parameter"
    )

    func = names["calculate_value"]
    assertions.expect_true(func.returns is not None, reason="should have returns")
    if func.returns is None:  # pragma: no cover - defensive
        pytest.fail("returns should not be None")
    assertions.expect_true(bool(func.returns.doc), reason="returns should have doc")
    assertions.expect_true(any(param.doc for param in func.params), reason="should have param docs")


def test_collect_api_symbols_with_missing_package(tmp_path: Path) -> None:
    """Verify graceful handling of missing packages."""
    symbols = collect_api_symbols_with_griffe(tmp_path, ["nonexistent_pkg"], docstyle="google")
    assertions.expect_sequence_equal(symbols, [])
