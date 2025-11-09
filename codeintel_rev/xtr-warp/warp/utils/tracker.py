"""Performance tracking utilities for WARP operations.

This module provides ExecutionTracker and NOPTracker for timing
and profiling execution steps.
"""

from __future__ import annotations

import time
from typing import Any, Never, Self

import matplotlib.pyplot as plt
import pandas as pd


class ExecutionTrackerIteration:
    """Context manager for tracking a single iteration.

    Parameters
    ----------
    tracker : ExecutionTracker
        Tracker instance to use.
    """

    def __init__(self, tracker: ExecutionTracker) -> None:
        """Initialize ExecutionTrackerIteration.

        Parameters
        ----------
        tracker : ExecutionTracker
            Tracker instance to use.
        """
        self._tracker = tracker

    def __enter__(self) -> Self:
        """Start iteration tracking.

        Returns
        -------
        ExecutionTrackerIteration
            Self for context manager protocol.
        """
        self._tracker.next_iteration()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception_value: BaseException | None,
        exception_traceback: Any | None,
    ) -> None:
        """End iteration tracking."""
        self._tracker.end_iteration()


class ExecutionTracker:
    """Tracks execution time for named steps across iterations.

    Records timing for each step within iterations, computing averages
    and displaying visualizations.

    Parameters
    ----------
    name : str
        Tracker name for display.
    steps : list[str]
        List of step names to track.
    """

    def __init__(self, name: str, steps: list[str]) -> None:
        """Initialize ExecutionTracker.

        Parameters
        ----------
        name : str
            Tracker name for display.
        steps : list[str]
            List of step names to track.
        """
        self._name = name
        self._steps = steps
        self._num_iterations = 0
        self._time = None
        self._time_per_step = {}
        for step in steps:
            self._time_per_step[step] = 0
        self._iter_begin = None
        self._iter_time = 0

    def next_iteration(self) -> None:
        """Start a new iteration."""
        self._num_iterations += 1
        self._iterating = True
        self._current_steps = []
        self._iter_begin = time.time()

    def end_iteration(self) -> None:
        """End current iteration.

        Raises
        ------
        ValueError
            If current steps don't match expected steps.
        """
        tok = time.time()
        if self._steps != self._current_steps:
            msg = f"_steps ({self._steps}) must equal _current_steps ({self._current_steps})"
            raise ValueError(msg)
        self._iterating = False
        self._iter_time += tok - self._iter_begin

    def iteration(self) -> ExecutionTrackerIteration:
        """Get context manager for tracking an iteration.

        Returns
        -------
        ExecutionTrackerIteration
            Context manager for iteration tracking.
        """
        return ExecutionTrackerIteration(self)

    def begin(self, name: str) -> None:
        """Begin timing a step.

        Parameters
        ----------
        name : str
            Step name to begin.

        Raises
        ------
        RuntimeError
            If already timing a step or not in an iteration.
        """
        if self._time is not None:
            msg = f"_time must be None when beginning step {name!r}, got {self._time}"
            raise RuntimeError(msg)
        if not self._iterating:
            msg = "Must be iterating to begin a step"
            raise RuntimeError(msg)
        self._current_steps.append(name)
        self._time = time.time()

    def end(self, name: str) -> None:
        """End timing a step.

        Parameters
        ----------
        name : str
            Step name to end (must match current step).

        Raises
        ------
        ValueError
            If name doesn't match current step.
        """
        tok = time.time()
        if self._current_steps[-1] != name:
            msg = f"Current step ({self._current_steps[-1]!r}) must equal name ({name!r})"
            raise ValueError(msg)
        self._time_per_step[name] += tok - self._time
        self._time = None

    def summary(self, steps: list[str] | None = None) -> tuple[float, list[tuple[str, float]]]:
        """Get timing summary for steps.

        Parameters
        ----------
        steps : list[str] | None
            Steps to include (default: None, uses all steps).

        Returns
        -------
        tuple[float, list[tuple[str, float]]]
            Tuple of (avg_iteration_time, [(step_name, avg_time), ...]).
        """
        if steps is None:
            steps = self._steps
        iteration_time = self._iter_time / self._num_iterations
        breakdown = [(step, self._time_per_step[step] / self._num_iterations) for step in steps]
        return iteration_time, breakdown

    def as_dict(self) -> dict[str, Any]:
        """Convert tracker to dictionary.

        Returns
        -------
        dict[str, Any]
            Dictionary representation of tracker state.
        """
        return {
            "name": self._name,
            "steps": self._steps,
            "time_per_step": self._time_per_step,
            "num_iterations": self._num_iterations,
            "iteration_time": self._iter_time,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ExecutionTracker:
        """Create tracker from dictionary.

        Parameters
        ----------
        data : dict[str, Any]
            Dictionary with tracker state.

        Returns
        -------
        ExecutionTracker
            Reconstructed tracker instance.
        """
        tracker = ExecutionTracker(data["name"], data["steps"])
        tracker._time_per_step = data["time_per_step"]
        tracker._num_iterations = data["num_iterations"]
        tracker._iter_time = data["iteration_time"]
        return tracker

    def __getitem__(self, key: str) -> float:
        """Get average time for a step.

        Parameters
        ----------
        key : str
            Step name.

        Returns
        -------
        float
            Average time per iteration for step.

        Raises
        ------
        KeyError
            If key is not in tracked steps.
        """
        if key not in self._steps:
            msg = f"key ({key!r}) must be in _steps ({self._steps})"
            raise KeyError(msg)
        return self._time_per_step[key] / self._num_iterations

    def display(self, steps: list[str] | None = None, bound: float | None = None) -> None:
        """Display timing visualization.

        Shows horizontal bar chart of step durations.

        Parameters
        ----------
        steps : list[str] | None
            Steps to display (default: None, uses all steps).
        bound : float | None
            Maximum x-axis bound in milliseconds (default: None).
        """
        iteration_time, breakdown = self.summary(steps)
        df = pd.DataFrame(
            {
                "Task": [x[0] for x in breakdown],
                "Duration": [x[1] * 1000 for x in breakdown],
            }
        )
        df["Start"] = df["Duration"].cumsum().shift(fill_value=0)
        _fig, ax = plt.subplots(figsize=(10, 2))

        for i, task in enumerate(df["Task"]):
            start = df["Start"][i]
            duration = df["Duration"][i]
            ax.barh("Tasks", duration, left=start, height=0.5, label=task)

        plt.xlabel("Latency (ms)")
        accumulated = round(sum(x[1] for x in breakdown) * 1000, 1)
        actual = round(iteration_time * 1000, 1)
        plt.title(
            f"{self._name} (iterations={self._num_iterations}, "
            f"accumulated={accumulated}ms, actual={actual}ms)"
        )
        ax.set_yticks([])
        ax.set_ylabel("")

        if bound is not None:
            ax.set_xlim([0, bound])

        plt.legend()
        plt.show()


class NOPTracker:
    """No-op tracker that does nothing.

    Provides same interface as ExecutionTracker but performs no tracking.
    Useful for disabling tracking without changing code.
    """

    def __init__(self) -> None:
        """Initialize NOPTracker (no-op)."""

    def next_iteration(self) -> None:
        """Start iteration (no-op)."""

    def begin(self, name: str) -> None:
        """Begin step (no-op).

        Parameters
        ----------
        name : str
            Step name (ignored).
        """
        # NOP

    def end(self, name: str) -> None:
        """End step (no-op).

        Parameters
        ----------
        name : str
            Step name (ignored).
        """
        # NOP

    def end_iteration(self) -> None:
        """End iteration (no-op)."""

    @staticmethod
    def summary() -> Never:
        """Get summary (always raises).

        Raises
        ------
        AssertionError
            Always raised, as NOPTracker doesn't track anything.
        """
        raise AssertionError

    @staticmethod
    def display() -> Never:
        """Display visualization (always raises).

        Raises
        ------
        AssertionError
            Always raised, as NOPTracker doesn't track anything.
        """
        raise AssertionError


# Type alias for tracker protocol
Tracker = ExecutionTracker | NOPTracker
