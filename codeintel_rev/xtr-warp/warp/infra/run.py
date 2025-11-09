"""Runtime context manager for WARP experiments.

This module provides Run singleton for managing experiment configuration,
file paths, and distributed execution context.
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Self

from warp.infra.config import RunConfig
from warp.utils.utils import create_directory, print_message


class Run:
    """Singleton runtime context manager for WARP experiments.

    Manages configuration stack, file paths, and distributed execution.
    Uses singleton pattern to provide global access to runtime state.

    Attributes
    ----------
    stack : list[RunConfig]
        Stack of configuration contexts.
    """

    _instance = None

    os.environ["TOKENIZERS_PARALLELISM"] = "true"  # NOTE: If a deadlock arises, switch to false!!

    def __new__(cls) -> Self:
        """Create or return singleton instance.

        Singleton Pattern. See https://python-patterns.guide/gang-of-four/singleton/.

        Returns
        -------
        Run
            Singleton Run instance.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.stack = []

            # NOTE: Save a timestamp here! And re-use it! And allow the user
            # to override it on calling Run().context a second time.
            run_config = RunConfig()
            run_config.assign_defaults()

            cls._instance.__append(run_config)

        return cls._instance

    @property
    def config(self) -> RunConfig:
        """Get current configuration from stack.

        Returns
        -------
        RunConfig
            Topmost configuration in stack.
        """
        return self.stack[-1]

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        """Delegate attribute access to current config.

        Parameters
        ----------
        name : str
            Attribute name.

        Returns
        -------
        Any
            Attribute value from config, or None if not found.
        """
        if hasattr(self.config, name):
            return getattr(self.config, name)

        super().__getattr__(name)
        return None

    def __append(self, runconfig: RunConfig) -> None:
        """Append configuration to stack.

        Parameters
        ----------
        runconfig : RunConfig
            Configuration to push onto stack.
        """
        self.stack.append(runconfig)

    def __pop(self) -> None:
        """Pop configuration from stack."""
        self.stack.pop()

    @contextmanager
    def context(self, runconfig: RunConfig, *, inherit_config: bool = True) -> Iterator[None]:
        """Context manager for temporary configuration.

        Pushes new configuration onto stack, optionally inheriting from
        current config. Restores previous config on exit.

        Parameters
        ----------
        runconfig : RunConfig
            Configuration to use in context.
        inherit_config : bool
            Whether to merge with current config (default: True).

        Yields
        ------
        None
            Context execution.
        """
        if inherit_config:
            runconfig = RunConfig.from_existing(self.config, runconfig)

        self.__append(runconfig)

        try:
            yield
        finally:
            self.__pop()

    def open(self, path: str, mode: str = "r") -> Any:  # noqa: ANN401
        """Open file relative to experiment path.

        Creates directories as needed. Validates overwrite setting for
        write/append modes.

        Parameters
        ----------
        path : str
            Relative path from experiment directory.
        mode : str
            File open mode (default: "r").

        Returns
        -------
        Any
            Opened file handle.

        Raises
        ------
        FileExistsError
            If file exists and overwrite=False for write/append modes.
        """
        path = str(pathlib.Path(self.path_) / path)

        if not pathlib.Path(self.path_).exists():
            create_directory(self.path_)

        if ("w" in mode or "a" in mode) and not self.overwrite:
            if pathlib.Path(path).exists():
                msg = f"Path already exists and overwrite=False: {path}"
                raise FileExistsError(msg)

            # create directory if it doesn't exist
            pathlib.Path(pathlib.Path(path).parent).mkdir(exist_ok=True, parents=True)

        return pathlib.Path(path).open(mode=mode)

    def print(self, *args: Any) -> None:
        """Print message with rank prefix.

        Parameters
        ----------
        *args : Any
            Arguments to print.
        """
        print_message("[" + str(self.rank) + "]", "\t\t", *args)

    def print_main(self, *args: Any) -> None:
        """Print message only on rank 0.

        Parameters
        ----------
        *args : Any
            Arguments to print.
        """
        if self.rank == 0:
            self.print(*args)


if __name__ == "__main__":
    with (
        Run().context(RunConfig(rank=0, nranks=1)),
        Run().context(RunConfig(experiment="newproject")),
    ):
        pass


# NOTE: Handle logging all prints to a file. There should be a way to
# determine the level of logs that go to stdout.
