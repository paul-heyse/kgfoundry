"""WARP experiment configuration for indexing and search.

This module provides WARPRunConfig, a frozen dataclass for configuring
WARP experiments including dataset selection, compression parameters,
runtime backends, and path resolution.
"""

import os
from dataclasses import dataclass
from typing import Literal

from warp.engine.runtime.onnx_model import XTROnnxConfig
from warp.infra import ColBERTConfig
from warp.modeling.xtr import DOC_MAXLEN, QUERY_MAXLEN

USE_CORE_ML = False

if USE_CORE_ML:
    from warp.engine.runtime.coreml_model import XTRCoreMLConfig

    RuntimeConfig = XTROnnxConfig | XTRCoreMLConfig
else:
    RuntimeConfig = XTROnnxConfig


@dataclass(frozen=True)
class WARPRunConfig:
    """Configuration for WARP indexing and search experiments.

    Immutable configuration dataclass that specifies dataset, compression,
    search parameters, and runtime settings. Provides properties for resolving
    paths to collections, queries, and indices based on environment variables.

    Parameters
    ----------
    nbits : int
        Number of quantization bits (typically 2 or 4).
    collection : Literal["beir", "lotte"]
        Dataset collection name.
    dataset : str
        Specific dataset identifier.
    datasplit : Literal["train", "dev", "test"]
        Data split to use.
    type_ : Literal["search", "forum"] | None
        Query type for LOTTE collections (default: None).
    k : int
        Top-k retrieval parameter (default: 100).
    nprobe : int
        Number of IVF centroids to probe (default: 16).
    t_prime : int | None
        T' parameter for search (default: None).
    fused_ext : bool
        Whether to use fused decompression+merge extension (default: True).
        Only applicable when num_threads != 1.
    bound : int
        Bound parameter for search (default: 128).
    nranks : int
        Number of parallel ranks for distributed execution (default: 1).
    runtime : RuntimeConfig | None
        Runtime backend configuration (default: None, uses PyTorch).

    Attributes
    ----------
    index_root : str
        Root directory for indices (from INDEX_ROOT env var).
    index_name : str
        Generated index name based on collection/dataset/split/nbits.
    collection_path : str
        Path to collection TSV file.
    queries_path : str
        Path to queries TSV file.
    experiment_root : str
        Root directory for experiments (from EXPERIMENT_ROOT env var).
    experiment_name : str
        Experiment identifier (collection-dataset).
    """

    nbits: int

    collection: Literal["beir", "lotte"]
    dataset: str
    datasplit: Literal["train", "dev", "test"]
    type_: Literal["search", "forum"] | None = None

    k: int = 100
    nprobe: int = 16
    t_prime: int | None = None

    # Use the fused decompression + merge candidate scores extension.
    # NOTE This option is only applicable with num_threads != 1
    fused_ext: bool = True

    # NOTE To be more efficient, we could also derive this from the dataset.
    #      For now we just set it to a sufficiently high constant value.
    bound: int = 128

    nranks: int = 1

    # runtime == None uses "default" PyTorch for inference.
    runtime: RuntimeConfig | None = None

    @property
    def index_root(self) -> str:
        """Get index root directory from environment.

        Returns
        -------
        str
            INDEX_ROOT environment variable value.
        """
        return os.environ["INDEX_ROOT"]

    @property
    def index_name(self) -> str:
        """Generate index name from configuration.

        Returns
        -------
        str
            Index name in format: "{collection}-{dataset}.split={datasplit}.nbits={nbits}".
        """
        return f"{self.collection}-{self.dataset}.split={self.datasplit}.nbits={self.nbits}"

    @property
    def collection_path(self) -> str:
        """Get collection file path based on configuration.

        Returns
        -------
        str
            Path to collection.tsv file.

        Raises
        ------
        AssertionError
            If collection is not "beir" or "lotte".
        """
        beir_collection_path = os.environ["BEIR_COLLECTION_PATH"]
        lotte_collection_path = os.environ["LOTTE_COLLECTION_PATH"]
        if self.collection == "beir":
            return f"{beir_collection_path}/{self.dataset}/collection.tsv"
        if self.collection == "lotte":
            return f"{lotte_collection_path}/{self.dataset}/{self.datasplit}/collection.tsv"
        raise AssertionError

    @property
    def queries_path(self) -> str:
        """Get queries file path based on configuration.

        Returns
        -------
        str
            Path to questions TSV file.

        Raises
        ------
        AssertionError
            If collection is not "beir" or "lotte".
        """
        beir_collection_path = os.environ["BEIR_COLLECTION_PATH"]
        lotte_collection_path = os.environ["LOTTE_COLLECTION_PATH"]
        if self.collection == "beir":
            return f"{beir_collection_path}/{self.dataset}/questions.{self.datasplit}.tsv"
        if self.collection == "lotte":
            return (
                f"{lotte_collection_path}/{self.dataset}/{self.datasplit}/"
                f"questions.{self.type_}.tsv"
            )
        raise AssertionError

    @property
    def experiment_root(self) -> str:
        """Get experiment root directory from environment.

        Returns
        -------
        str
            EXPERIMENT_ROOT environment variable value.
        """
        return os.environ["EXPERIMENT_ROOT"]

    @property
    def experiment_name(self) -> str:
        """Generate experiment name from configuration.

        Returns
        -------
        str
            Experiment name in format: "{collection}-{dataset}".
        """
        return f"{self.collection}-{self.dataset}"

    def colbert(self) -> ColBERTConfig:
        """Convert to ColBERT configuration.

        Creates a ColBERTConfig instance with parameters derived from
        this WARP configuration.

        Returns
        -------
        ColBERTConfig
            ColBERT configuration object.
        """
        return ColBERTConfig(
            nbits=self.nbits,
            ncells=self.nprobe,
            doc_maxlen=DOC_MAXLEN,
            query_maxlen=QUERY_MAXLEN,
            index_path=f"{self.index_root}/{self.index_name}",
            root="./",
        )
