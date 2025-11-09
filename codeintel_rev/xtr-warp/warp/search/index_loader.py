"""Index loading utilities for WARP search.

This module provides IndexLoader for loading compressed indices, codecs,
IVF structures, document lengths, and embeddings from disk.
"""

from __future__ import annotations

import pathlib
from typing import Never

import torch
import tqdm
import ujson
from warp.indexing.codecs.residual import ResidualCodec
from warp.indexing.utils import optimize_ivf
from warp.search.strided_tensor import StridedTensor
from warp.utils.utils import print_message


class IndexLoader:
    """Loads WARP index components from disk.

    Handles loading of codec, IVF structure, document lengths, and
    compressed embeddings. Supports memory-mapped loading for large indices.

    Parameters
    ----------
    index_path : str | pathlib.Path
        Path to index directory.
    use_gpu : bool
        Whether to use GPU acceleration (default: True).
    load_index_with_mmap : bool
        Whether to load index with memory mapping (default: False).
    """

    def __init__(
        self,
        index_path: str | pathlib.Path,
        *,
        use_gpu: bool = True,
        load_index_with_mmap: bool = False,
    ) -> None:
        self.index_path = index_path
        self.use_gpu = use_gpu
        self.load_index_with_mmap = load_index_with_mmap

        self._load_codec()
        self._load_ivf()

        self._load_doclens()
        self._load_embeddings()

    def _load_codec(self) -> None:
        print_message("#> Loading codec...")
        self.codec = ResidualCodec.load(self.index_path)

    def _load_ivf(self) -> None:
        print_message("#> Loading IVF...")

        index_path_obj = pathlib.Path(self.index_path)
        ivf_pid_path = index_path_obj / "ivf.pid.pt"
        if ivf_pid_path.exists():
            ivf, ivf_lengths = torch.load(str(ivf_pid_path), map_location="cpu")
        else:
            ivf_path = index_path_obj / "ivf.pt"
            if not ivf_path.exists():
                msg = f"ivf.pt file not found at {ivf_path}"
                raise FileNotFoundError(msg)
            ivf, ivf_lengths = torch.load(str(ivf_path), map_location="cpu")
            ivf, ivf_lengths = optimize_ivf(ivf, ivf_lengths, self.index_path)

        ivf = StridedTensor(ivf, ivf_lengths, use_gpu=self.use_gpu)

        self.ivf = ivf

    def _load_doclens(self) -> None:
        doclens = []

        print_message("#> Loading doclens...")

        index_path_obj = pathlib.Path(self.index_path)
        for chunk_idx in tqdm.tqdm(range(self.num_chunks)):
            with (index_path_obj / f"doclens.{chunk_idx}.json").open(encoding="utf-8") as f:
                chunk_doclens = ujson.load(f)
                doclens.extend(chunk_doclens)

        self.doclens = torch.tensor(doclens)

    def _load_embeddings(self) -> None:
        self.embeddings = ResidualCodec.Embeddings.load_chunks(
            self.index_path,
            range(self.num_chunks),
            self.num_embeddings,
            self.load_index_with_mmap,
        )

    @property
    def metadata(self) -> dict[str, object]:
        """Get index metadata dictionary.

        Loads metadata.json from index directory, caching after first access.

        Returns
        -------
        dict[str, object]
            Index metadata dictionary.
        """
        if not hasattr(self, "_metadata"):
            index_path_obj = pathlib.Path(self.index_path)
            with (index_path_obj / "metadata.json").open(encoding="utf-8") as f:
                self._metadata = ujson.load(f)

        return self._metadata

    @property
    def config(self) -> Never:
        """Get configuration from metadata (not implemented).

        Raises
        ------
        NotImplementedError
            Always raised. Should load from metadata['config'].
        """
        raise NotImplementedError  # load from dict at metadata['config']

    @property
    def num_chunks(self) -> int:
        """Get number of index chunks.

        Returns
        -------
        int
            Number of chunks in index.

        Notes
        -----
        EVENTUALLY: If num_chunks doesn't exist (i.e., old index), fall back
        to counting doclens.*.json files.
        """
        return self.metadata["num_chunks"]

    @property
    def num_embeddings(self) -> int:
        """Get total number of embeddings in index.

        Returns
        -------
        int
            Total number of embeddings.

        Notes
        -----
        EVENTUALLY: If num_embeddings doesn't exist (i.e., old index), sum
        the values in doclens.*.json files.
        """
        return self.metadata["num_embeddings"]
