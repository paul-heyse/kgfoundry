"""Run management for WARP experiments.

This module provides _RunManager singleton for managing experiment
lifecycle, paths, and logging context.
"""

from __future__ import annotations

import pathlib
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager

from warp.utils import distributed
from warp.utils.logging import Logger
from warp.utils.utils import create_directory, print_message, timestamp

import __main__


class _RunManager:
    def __init__(self) -> None:
        self.experiments_root = None
        self.experiment = None
        self.path = None
        self.script = self._get_script_name()
        self.name = self._generate_default_run_name()
        self.original_name = self.name
        self.exit_status = "FINISHED"

        self._logger = None
        self.start_time = time.time()

    def init(self, rank: int, root: str | pathlib.Path, experiment: str, name: str) -> None:
        if "/" in experiment:
            msg = f"experiment must not contain '/', got {experiment!r}"
            raise ValueError(msg)
        if "/" in name:
            msg = f"name must not contain '/', got {name!r}"
            raise ValueError(msg)

        self.experiments_root = pathlib.Path(root).resolve()
        self.experiment = experiment
        self.name = name
        self.path = str(
            pathlib.Path(self.experiments_root) / self.experiment / self.script / self.name
        )

        if rank < 1:
            if pathlib.Path(self.path).exists():
                print_message("It seems that ", self.path, " already exists.")
                print_message("Do you want to overwrite it? \t yes/no \n")

                # NOTE: This should timeout and exit (i.e., fail) given no response for 60 seconds.

                response = input()
                if response.strip() != "yes" and pathlib.Path(self.path).exists():
                    msg = f"Path already exists: {self.path}"
                    raise FileExistsError(msg)
            else:
                create_directory(self.path)

        distributed.barrier(rank)

        self._logger = Logger(rank, self)
        self._log_args = self._logger.log_args
        self.warn = self._logger.warn
        self.info = self._logger.info
        self.info_all = self._logger.info_all
        self.log_metric = self._logger.log_metric
        self.log_new_artifact = self._logger.log_new_artifact

    @staticmethod
    def _generate_default_run_name() -> str:
        return timestamp()

    @staticmethod
    def _get_script_name() -> str:
        return pathlib.Path(__main__.__file__).name if "__file__" in dir(__main__) else "none"

    @contextmanager
    def context(self, *, consider_failed_if_interrupted: bool = True) -> Iterator[None]:
        try:
            yield

        except KeyboardInterrupt as ex:
            self._logger.log_exception(ex.__class__, ex, ex.__traceback__)
            self._logger.log_all_artifacts()

            if consider_failed_if_interrupted:
                self.exit_status = "KILLED"  # mlflow.entities.RunStatus.KILLED

            sys.exit(128 + 2)

        except Exception as ex:
            self._logger.log_exception(ex.__class__, ex, ex.__traceback__)
            self._logger.log_all_artifacts()

            self.exit_status = "FAILED"  # mlflow.entities.RunStatus.FAILED

            raise

        finally:
            total_seconds = str(time.time() - self.start_time) + "\n"
            original_name = str(self.original_name)
            name = str(self.name)

            logs_path_obj = pathlib.Path(self._logger.logs_path)
            self.log_new_artifact(str(logs_path_obj / "elapsed.txt"), total_seconds)
            self.log_new_artifact(str(logs_path_obj / "name.original.txt"), original_name)
            self.log_new_artifact(str(logs_path_obj / "name.txt"), name)

            self._logger.log_all_artifacts()


Run = _RunManager()
