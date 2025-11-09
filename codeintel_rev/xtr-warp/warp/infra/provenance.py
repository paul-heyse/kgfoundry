"""Provenance tracking for debugging and serialization.

This module provides Provenance class for capturing stack traces at
object creation and serialization time.
"""

from __future__ import annotations

import inspect
from typing import Any


class Provenance:
    """Tracks stack traces for object creation and serialization.

    Captures initial stack trace at creation and serialization stack trace
    when converting to dictionary. Useful for debugging object origins.
    """

    def __init__(self) -> None:
        """Initialize Provenance with initial stack trace."""
        self.initial_stacktrace = self.stacktrace()

    @staticmethod
    def stacktrace() -> list[str | None]:
        """Capture current stack trace.

        Extracts stack frames, skipping the first two and last one,
        formatting them as strings.

        Returns
        -------
        list[str | None]
            List of formatted stack frame strings, or None for frames
            that couldn't be formatted.
        """
        trace = inspect.stack()
        output = []

        for frame_info in trace[2:-1]:
            try:
                frame_str = (
                    f"{frame_info.filename}:{frame_info.lineno}:{frame_info.function}:   "
                    f"{frame_info.code_context[0].strip()}"
                )
                output.append(frame_str)
            except (AttributeError, IndexError, TypeError):
                output.append(None)

        return output

    def to_dict(self) -> dict[str, Any]:  # for ujson
        """Convert to dictionary with serialization stack trace.

        Captures current stack trace and returns dictionary representation
        of all attributes.

        Returns
        -------
        dict[str, Any]
            Dictionary containing all instance attributes.
        """
        self.serialization_stacktrace = self.stacktrace()
        return dict(self.__dict__)


if __name__ == "__main__":
    p = Provenance()

    class X:
        """Test class for provenance example."""

        def __init__(self) -> None:
            """Initialize test class."""

        @staticmethod
        def to_dict() -> dict[str, int]:
            """Convert to dictionary.

            Returns
            -------
            dict[str, int]
                Dictionary representation.
            """
            return {"key": 1}
