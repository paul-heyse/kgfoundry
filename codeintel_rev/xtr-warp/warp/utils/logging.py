"""Logging utilities for WARP experiments.

This module provides Logger class for experiment logging, metrics,
artifacts, and exception tracking.
"""

from __future__ import annotations

import pathlib
import sys
import traceback
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from warp.infra.run import Run

from warp.utils.utils import create_directory, print_message


class Logger:
    """Logger for experiment tracking and artifact management.

    Handles logging metrics, artifacts, warnings, and exceptions for
    distributed training runs. Only rank 0 (main process) logs.

    Parameters
    ----------
    rank : int
        Process rank (-1 or 0 for main process).
    run : Any
        Run manager instance with path and experiment info.
    """

    def __init__(self, rank: int, run: Run) -> None:
        """Initialize Logger with rank and run manager.

        Parameters
        ----------
        rank : int
            Process rank (-1 or 0 for main process).
        run : Any
            Run manager instance with path and experiment info.
        """
        self.rank = rank
        self.is_main = self.rank in {-1, 0}
        self.run = run
        self.logs_path = str(pathlib.Path(self.run.path) / "logs")

        if self.is_main:
            create_directory(self.logs_path)

    def _log_exception(
        self,
        etype: type[BaseException],
        value: BaseException,
        tb: TracebackType | None,
    ) -> None:
        if not self.is_main:
            return

        output_path = str(pathlib.Path(self.logs_path) / "exception.txt")
        trace = "".join(traceback.format_exception(etype, value, tb)) + "\n"
        print_message(trace, "\n\n")

        self.log_new_artifact(output_path, trace)

    def _log_all_artifacts(self) -> None:
        if not self.is_main:
            return

    def _log_args(self, _args: object) -> None:
        if not self.is_main:
            return

        with (pathlib.Path(self.logs_path) / "args.txt").open(
            "w", encoding="utf-8"
        ) as output_metadata:
            output_metadata.write(" ".join(sys.argv) + "\n")

    def log_metric(
        self, _name: str, _value: float, _step: int, *, _log_to_mlflow: bool = True
    ) -> None:
        """Log metric value at given step.

        Parameters
        ----------
        _name : str
            Metric name (unused).
        _value : float
            Metric value (unused).
        _step : int
            Step number (unused).
        _log_to_mlflow : bool
            Whether to log to MLflow (default: True, currently disabled, unused).
        """
        if not self.is_main:
            return

    @staticmethod
    def log_new_artifact(path: str | pathlib.Path, content: str) -> None:
        """Write artifact content to file.

        Parameters
        ----------
        path : str | pathlib.Path
            Path to artifact file.
        content : str
            Content to write.
        """
        with pathlib.Path(path).open("w", encoding="utf-8") as f:
            f.write(content)

    def warn(self, *args: object) -> None:
        """Log warning message.

        Prints warning and appends to warnings.txt file.

        Parameters
        ----------
        *args : Any
            Arguments to print.
        """
        msg = print_message("[WARNING]", "\t", *args)

        with (pathlib.Path(self.logs_path) / "warnings.txt").open(
            "a", encoding="utf-8"
        ) as output_metadata:
            output_metadata.write(msg + "\n\n\n")

    def info_all(self, *args: object) -> None:
        """Log info message from all ranks.

        Parameters
        ----------
        *args : Any
            Arguments to print.
        """
        print_message("[" + str(self.rank) + "]", "\t", *args)

    def info(self, *args: object) -> None:
        """Log info message from main rank only.

        Parameters
        ----------
        *args : Any
            Arguments to print.
        """
        if self.is_main:
            print_message(*args)
