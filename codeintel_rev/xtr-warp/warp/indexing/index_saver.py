"""Index saving utilities with threaded compression support.

This module provides IndexSaver for saving compressed index chunks to disk
using background threads for compression and I/O operations.
"""

from __future__ import annotations

import pathlib
import queue
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import torch
import ujson
from warp.indexing.codecs.residual import ResidualCodec
from warp.indexing.codecs.residual_embeddings import ResidualEmbeddings
from warp.infra.config.config import ColBERTConfig


class IndexSaver:
    """Saves compressed index chunks to disk using background threads.

    Manages compression and persistence of index chunks with thread-safe
    queue-based background processing. Supports checking for existing chunks
    and loading/saving codec configurations.

    Parameters
    ----------
    config : ColBERTConfig
        Configuration object with index_path_ attribute.

    Attributes
    ----------
    config : ColBERTConfig
        Configuration object.
    codec : ResidualCodec | None
        Loaded codec instance (set during thread context).
    saver_queue : queue.Queue | None
        Queue for passing chunks to background thread (set during thread context).
    """

    def __init__(self, config: ColBERTConfig) -> None:
        """Initialize IndexSaver with configuration.

        Parameters
        ----------
        config
            Configuration object with index_path_ attribute.
        """
        self.config = config

    def save_codec(self, codec: ResidualCodec) -> None:
        """Save codec configuration to index directory.

        Parameters
        ----------
        codec
            Codec instance to save.
        """
        codec.save(index_path=self.config.index_path_)

    def load_codec(self) -> ResidualCodec:
        """Load codec configuration from index directory.

        Returns
        -------
        ResidualCodec
        Loaded codec instance.
        """
        return ResidualCodec.load(index_path=self.config.index_path_)

    def try_load_codec(self) -> bool | None:
        """Attempt to load codec, returning success status.

        Returns
        -------
        bool | None
            True if codec loaded successfully, False if exception occurred.
        """
        try:
            ResidualCodec.load(index_path=self.config.index_path_)
        except (FileNotFoundError, ValueError, OSError):
            return False
        else:
            return True

    def check_chunk_exists(self, chunk_idx: int) -> bool:
        """Check if a chunk with given index already exists on disk.

        Verifies presence of doclens, metadata, codes, and residuals files
        for the specified chunk index.

        Parameters
        ----------
        chunk_idx : int
            Chunk index to check.

        Returns
        -------
        bool
            True if all required files exist, False otherwise.
        """
        # NOTE: Verify that the chunk has the right amount of data?

        doclens_path = pathlib.Path(self.config.index_path_) / f"doclens.{chunk_idx}.json"
        if not doclens_path.exists():
            return False

        index_path_obj = pathlib.Path(self.config.index_path_)
        metadata_path = index_path_obj / f"{chunk_idx}.metadata.json"
        if not metadata_path.exists():
            return False

        path_prefix = index_path_obj / str(chunk_idx)
        codes_path = path_prefix.with_suffix(".codes.pt")
        if not codes_path.exists():
            return False

        residuals_path = path_prefix.with_suffix(".residuals.pt")
        return residuals_path.exists()

    @contextmanager
    def thread(self) -> Iterator[None]:
        """Context manager for threaded index saving.

        Sets up a background thread for compression and I/O operations.
        Loads codec and creates a queue for passing chunks to the saver thread.
        Automatically joins thread and cleans up resources on exit.

        Yields
        ------
        None
            Context manager yields control to caller.

        Examples
        --------
        >>> with index_saver.thread():
        ...     index_saver.save_chunk(0, 0, embs, doclens)
        """
        self.codec = self.load_codec()

        self.saver_queue = queue.Queue(maxsize=3)
        thread = threading.Thread(target=self._saver_thread)
        thread.start()

        try:
            yield

        finally:
            self.saver_queue.put(None)
            thread.join()

            del self.saver_queue
            del self.codec

    def save_chunk(
        self,
        chunk_idx: int,
        offset: int,
        embs: torch.Tensor,
        doclens: list[int],
    ) -> None:
        """Queue a chunk for compression and saving.

        Compresses embeddings using the codec and queues the chunk for
        background thread to write to disk. Must be called within thread()
        context.

        Parameters
        ----------
        chunk_idx : int
            Chunk index identifier.
        offset : int
            Passage offset for this chunk.
        embs : torch.Tensor
            Embeddings tensor to compress and save.
        doclens : list[int]
            Document lengths for passages in this chunk.
        """
        compressed_embs = self.codec.compress(embs)

        self.saver_queue.put((chunk_idx, offset, compressed_embs, doclens))

    def _saver_thread(self) -> None:
        """Background thread function for writing chunks to disk.

        Continuously processes chunks from saver_queue until None is received.
        """
        for args in iter(self.saver_queue.get, None):
            self._write_chunk_to_disk(*args)

    def _write_chunk_to_disk(
        self,
        chunk_idx: int,
        offset: int,
        compressed_embs: ResidualEmbeddings,
        doclens: list[int],
    ) -> None:
        """Write a compressed chunk to disk with metadata.

        Saves compressed embeddings, document lengths, and metadata JSON files
        for a single chunk.

        Parameters
        ----------
        chunk_idx : int
            Chunk index identifier.
        offset : int
            Passage offset for this chunk.
        compressed_embs
            Compressed embeddings object (with save method).
        doclens : list[int]
            Document lengths for passages in this chunk.
        """
        index_path_obj = pathlib.Path(self.config.index_path_)
        path_prefix = str(index_path_obj / str(chunk_idx))
        compressed_embs.save(path_prefix)

        doclens_path = index_path_obj / f"doclens.{chunk_idx}.json"
        with doclens_path.open("w", encoding="utf-8") as output_doclens:
            ujson.dump(doclens, output_doclens)

        metadata_path = index_path_obj / f"{chunk_idx}.metadata.json"
        with metadata_path.open("w", encoding="utf-8") as output_metadata:
            metadata = {
                "passage_offset": offset,
                "num_passages": len(doclens),
                "num_embeddings": len(compressed_embs),
            }
            ujson.dump(metadata, output_metadata)
