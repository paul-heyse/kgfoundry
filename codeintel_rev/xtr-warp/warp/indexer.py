"""Indexing interface for creating ColBERT indices.

This module provides the Indexer class for building ColBERT indices from
document collections. Supports distributed indexing, checkpoint management,
and index persistence.
"""

from __future__ import annotations

import pathlib
import time
from typing import Any

import torch.multiprocessing as mp
from warp.data import Collection
from warp.indexing.collection_indexer import encode
from warp.infra.config import ColBERTConfig
from warp.infra.launcher import Launcher
from warp.infra.run import Run
from warp.utils.utils import create_directory, print_message


class Indexer:
    """Indexer for creating and managing ColBERT indices.

    Use Run().context() to choose the run's configuration. They are NOT extracted from `config`.

    Parameters
    ----------
    checkpoint : str
        Path to the ColBERT checkpoint file.
    config : ColBERTConfig | None
        Optional configuration object (default: None). Note that configuration
        is actually extracted from Run().context(), not from this parameter.
    verbose : int
        Verbosity level (default: 3).
    """

    def __init__(
        self, checkpoint: str, config: ColBERTConfig | None = None, verbose: int = 3
    ) -> None:
        self.index_path = None
        self.verbose = verbose
        self.checkpoint = checkpoint
        self.checkpoint_config = ColBERTConfig.load_from_checkpoint(checkpoint)

        self.config = ColBERTConfig.from_existing(self.checkpoint_config, config, Run().config)
        self.configure(checkpoint=checkpoint)

    def configure(self, **kw_args: Any) -> None:  # noqa: ANN401
        """Update indexing configuration parameters.

        Parameters
        ----------
        **kw_args : Any
            Configuration parameters to update.
        """
        self.config.configure(**kw_args)

    def get_index(self) -> str | None:
        """Get the current index path.

        Returns
        -------
        str | None
            Path to the index directory, or None if not yet created.
        """
        return self.index_path

    def erase(self, *, force_silent: bool = False) -> list[str]:
        """Delete existing index files.

        Removes .pt and .json metadata files from the index directory.
        By default, waits 20 seconds before deletion unless force_silent is True.

        Parameters
        ----------
        force_silent : bool
            If True, delete immediately without waiting (default: False).

        Returns
        -------
        list[str]
            List of deleted file paths.

        Raises
        ------
        RuntimeError
            If index_path is not set.
        """
        if self.index_path is None:
            msg = "index_path must be set before calling erase()"
            raise RuntimeError(msg)
        directory = self.index_path
        deleted = []

        directory_obj = pathlib.Path(directory)
        for filename_path in sorted(directory_obj.iterdir()):
            filename = filename_path.name

            delete = filename.endswith(".json")
            delete = delete and (
                "metadata" in filename or "doclen" in filename or "plan" in filename
            )
            delete = delete or filename.endswith(".pt")

            if delete:
                deleted.append(filename)

        if deleted:
            if not force_silent:
                print_message(
                    f"#> Will delete {len(deleted)} files already at {directory} in 20 seconds..."
                )
                time.sleep(20)

            for filename in deleted:
                pathlib.Path(filename).unlink()

        return deleted

    def index(
        self,
        name: str,
        collection: str | Collection,
        *,
        overwrite: bool | str = False,
    ) -> str:
        """Create or update an index from a collection.

        Builds a ColBERT index from the provided collection. Supports various
        overwrite modes for handling existing indices.

        Parameters
        ----------
        name : str
            Index name (used to construct index path).
        collection : str | Collection
            Collection to index (path string or Collection object).
        overwrite : bool | str
            Overwrite mode:
            - False: Skip if index exists
            - True: Delete existing and rebuild (with confirmation delay)
            - "reuse": Use existing index if present
            - "resume": Resume from checkpoint if available
            - "force_silent_overwrite": Delete and rebuild immediately

        Returns
        -------
        str
            Path to the created/updated index directory.

        Raises
        ------
        ValueError
            If overwrite value is not recognized.
        """
        if overwrite not in {True, False, "reuse", "resume", "force_silent_overwrite"}:
            msg = (
                f"overwrite must be one of "
                f"{{True, False, 'reuse', 'resume', 'force_silent_overwrite'}}, "
                f"got {overwrite!r}"
            )
            raise ValueError(msg)

        self.configure(collection=collection, index_name=name, resume=overwrite == "resume")
        # Note: The bsize value set here is ignored internally. Users are
        # encouraged to supply their own batch size for indexing by using the
        # index_bsize parameter in the ColBERTConfig.
        self.configure(bsize=64, partitions=None)

        self.index_path = self.config.index_path_
        index_does_not_exist = not pathlib.Path(self.config.index_path_).exists()

        create_directory(self.config.index_path_)

        if overwrite == "force_silent_overwrite":
            self.erase(force_silent=True)
        elif overwrite is True:
            self.erase()

        if index_does_not_exist or overwrite != "reuse":
            self.__launch(collection)

        return self.index_path

    def __launch(self, collection: str | Collection) -> None:
        launcher = Launcher(encode)
        if self.config.nranks == 1 and self.config.avoid_fork_if_possible:
            shared_queues = []
            shared_lists = []
            launcher.launch_without_fork(
                self.config, collection, shared_lists, shared_queues, self.verbose
            )

            return

        manager = mp.Manager()
        shared_lists = [manager.list() for _ in range(self.config.nranks)]
        shared_queues = [manager.Queue(maxsize=1) for _ in range(self.config.nranks)]

        # Encodes collection into index using the CollectionIndexer class
        launcher.launch(self.config, collection, shared_lists, shared_queues, self.verbose)
