"""Launcher for distributed and single-process execution of warp tasks."""

from __future__ import annotations

import contextlib
import os
import random
import time
from collections.abc import Callable
from typing import Any

import numpy as np
import torch
import torch.multiprocessing as mp

with contextlib.suppress(RuntimeError):
    mp.set_start_method("spawn", force=True)

from warp.infra.config import BaseConfig, RunConfig, RunSettings
from warp.infra.run import Run
from warp.utils import distributed
from warp.utils.utils import print_message


class Launcher:
    """Manages launching of warp tasks in distributed or single-process mode."""

    def __init__(
        self,
        callee: Callable[..., Any],
        run_config: RunConfig | None = None,
        *,
        return_all: bool = False,
    ) -> None:
        """Initialize the launcher.

        Parameters
        ----------
        callee : Callable[..., Any]
            Function to execute when launched.
        run_config : RunConfig, optional
            Configuration for the run. If None, uses existing Run configuration.
        return_all : bool, optional
            If True, return results from all ranks. If False, return only rank 0's result.
            Defaults to False.
        """
        self.callee = callee
        self.return_all = return_all

        self.run_config = RunConfig.from_existing(Run().config, run_config)
        self.nranks = self.run_config.nranks

    def launch(self, custom_config: BaseConfig & RunSettings, *args: Any) -> Any:  # noqa: ANN401
        """Launch the callee function in distributed mode across multiple processes.

        Parameters
        ----------
        custom_config : BaseConfig & RunSettings
            Configuration object that must be an instance of both BaseConfig and RunSettings.
        *args : Any
            Additional arguments to pass to the callee function.

        Returns
        -------
        Any
            Return value(s) from the callee function. If return_all is False,
            returns only the first rank's result.

        Raises
        ------
        TypeError
            If custom_config is not an instance of BaseConfig or RunSettings.
        """
        if not isinstance(custom_config, BaseConfig):
            msg = (
                f"custom_config must be an instance of BaseConfig, "
                f"got {type(custom_config).__name__}"
            )
            raise TypeError(msg)
        if not isinstance(custom_config, RunSettings):
            msg = (
                f"custom_config must be an instance of RunSettings, "
                f"got {type(custom_config).__name__}"
            )
            raise TypeError(msg)

        return_value_queue = mp.Queue()
        rng = random.Random(time.time())
        port = str(
            12355 + rng.randint(0, 1000)
        )  # randomize the port to avoid collision on launching several jobs.
        all_procs = []
        for new_rank in range(self.nranks):
            new_config = type(custom_config).from_existing(
                custom_config, self.run_config, RunConfig(rank=new_rank)
            )

            args_ = (self.callee, port, return_value_queue, new_config, *args)
            all_procs.append(mp.Process(target=setup_new_process, args=args_))

        # Clear GPU space (e.g., after a `Searcher` on GPU-0 is deleted)
        # NOTE: Generalize this from GPU-0 only!
        # NOTE: Move this to a function. And call that function from __del__
        # in a class that's inherited by Searcher, Indexer, etc.

        torch.cuda.empty_cache()

        print_memory_stats("MAIN")

        for proc in all_procs:
            proc.start()

        print_memory_stats("MAIN")

        # NOTE: If the processes crash upon join, raise an exception and
        # don't block on .get() below!

        return_values = sorted([return_value_queue.get() for _ in all_procs])
        return_values = [val for rank, val in return_values]

        if not self.return_all:
            return_values = return_values[0]

        for proc in all_procs:
            proc.join()

        print_memory_stats("MAIN")

        return return_values

    def launch_without_fork(self, custom_config: BaseConfig & RunSettings, *args: Any) -> Any:  # noqa: ANN401
        """Launch the callee function in single-process mode without forking.

        Parameters
        ----------
        custom_config : BaseConfig & RunSettings
            Configuration object that must be an instance of both BaseConfig and RunSettings.
        *args : Any
            Additional arguments to pass to the callee function.

        Returns
        -------
        Any
            Return value from the callee function.

        Raises
        ------
        TypeError
            If custom_config is not an instance of BaseConfig or RunSettings.
        ValueError
            If nranks is not 1 or if avoid_fork_if_possible is not True.
        """
        if not isinstance(custom_config, BaseConfig):
            msg = (
                f"custom_config must be an instance of BaseConfig, "
                f"got {type(custom_config).__name__}"
            )
            raise TypeError(msg)
        if not isinstance(custom_config, RunSettings):
            msg = (
                f"custom_config must be an instance of RunSettings, "
                f"got {type(custom_config).__name__}"
            )
            raise TypeError(msg)
        if self.nranks != 1:
            msg = f"nranks must be 1 for launch_without_fork, got {self.nranks}"
            raise ValueError(msg)
        if not (custom_config.avoid_fork_if_possible or self.run_config.avoid_fork_if_possible):
            msg = "avoid_fork_if_possible must be True in either custom_config or run_config"
            raise ValueError(msg)

        new_config = type(custom_config).from_existing(
            custom_config, self.run_config, RunConfig(rank=0)
        )
        return run_process_without_mp(self.callee, new_config, *args)


def set_seed(seed: int) -> None:
    """Set random seeds for reproducibility.

    Parameters
    ----------
    seed : int
        Seed value to use for random number generators.
    """
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def run_process_without_mp(callee: Callable[..., Any], config: RunConfig, *args: Any) -> Any:  # noqa: ANN401
    """Run the callee function in single-process mode without multiprocessing.

    Parameters
    ----------
    callee : Callable[..., Any]
        Function to execute.
    config : RunConfig
        Configuration for the run.
    *args : Any
        Additional arguments to pass to the callee function.

    Returns
    -------
    Any
        Return value from the callee function.
    """
    set_seed(12345)
    os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, config.gpus_[: config.nranks]))

    with Run().context(config, inherit_config=False):
        return_val = callee(config, *args)
        torch.cuda.empty_cache()
        return return_val


def setup_new_process(
    callee: Callable[..., Any],
    port: str,
    return_value_queue: mp.Queue[tuple[int, Any]],
    config: RunConfig,
    *args: Any,  # noqa: ANN401
) -> None:
    """Set up and run a new process for distributed execution.

    Parameters
    ----------
    callee : Callable[..., Any]
        Function to execute in this process.
    port : str
        Port number for distributed communication.
    return_value_queue : mp.Queue[tuple[int, Any]]
        Queue to put the return value with rank information.
    config : RunConfig
        Configuration for this process.
    *args : Any
        Additional arguments to pass to the callee function.

    Raises
    ------
    ValueError
        If the initialized number of ranks doesn't match the expected number.
    """
    print_memory_stats()

    set_seed(12345)

    rank, nranks = config.rank, config.nranks

    os.environ["MASTER_ADDR"] = "localhost"
    os.environ["MASTER_PORT"] = port
    os.environ["WORLD_SIZE"] = str(config.nranks)
    os.environ["RANK"] = str(config.rank)

    # NOTE: Ideally the gpus "getter" handles this max-nranks thing!
    os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, config.gpus_[:nranks]))

    nranks_, _ = distributed.init(rank)
    if nranks_ != nranks:
        msg = f"nranks_ ({nranks_}) must equal nranks ({nranks})"
        raise ValueError(msg)

    with Run().context(config, inherit_config=False):
        return_val = callee(config, *args)

    return_value_queue.put((rank, return_val))


def print_memory_stats(message: str = "") -> None:
    """Print memory statistics for the current process.

    Parameters
    ----------
    message : str, optional
        Optional message prefix for the memory stats output. Defaults to empty string.

    Notes
    -----
    Currently disabled (returns immediately). Re-enable before release if needed.
    """
    return  # NOTE: Add this back before release.

    import psutil  # Remove before releases? Or at least make optional with try/except.

    global_info = psutil.virtual_memory()
    total, available, used, free = (
        global_info.total,
        global_info.available,
        global_info.used,
        global_info.free,
    )

    info = psutil.Process().memory_info()
    rss, vms, shared = info.rss, info.vms, info.shared
    uss = psutil.Process().memory_full_info().uss

    gib = 1024**3

    summary = f"""
    "[PID: {os.getpid()}]
    [{message}]
    Available: {available / gib:,.1f} / {total / gib:,.1f}
    Free: {free / gib:,.1f} / {total / gib:,.1f}
    Usage: {used / gib:,.1f} / {total / gib:,.1f}

    RSS: {rss / gib:,.1f}
    VMS: {vms / gib:,.1f}
    USS: {uss / gib:,.1f}
    SHARED: {shared / gib:,.1f}
    """.strip().replace("\n", "\t")

    print_message(summary, pad=True)
