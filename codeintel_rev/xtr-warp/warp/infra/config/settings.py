"""Settings classes for WARP configuration.

This module provides dataclass mixins for different configuration aspects:
runtime execution, resources, document/query processing, training, indexing,
search, and tokenization.
"""

import os
import pathlib
from dataclasses import dataclass

import torch
from warp.infra.config.core_config import DefaultVal
from warp.utils.utils import timestamp

import __main__


@dataclass(frozen=True)
class RunSettings:
    """Runtime execution settings for WARP experiments.

    The defaults here have a special status in Run(), which initially calls
    assign_defaults(), so these aren't soft defaults in that specific context.

    Attributes
    ----------
    overwrite : bool
        Whether to overwrite existing outputs (default: False).
    root : str
        Root directory for experiments (default: ./experiments).
    experiment : str
        Experiment name (default: "default").
    index_root : str
        Root directory for indices (default: None, uses root/experiment/indexes/).
    name : str
        Run name, typically timestamp-based (default: timestamp).
    rank : int
        Process rank for distributed execution (default: 0).
    nranks : int
        Number of ranks (default: 1).
    amp : bool
        Whether to use automatic mixed precision (default: True).
    gpus : int
        Number of GPUs or GPU list (default: total_visible_gpus).
    avoid_fork_if_possible : bool
        Whether to avoid forking if possible (default: False).
    """

    overwrite: bool = DefaultVal(val=False)

    root: str = DefaultVal(str(pathlib.Path.cwd() / "experiments"))
    experiment: str = DefaultVal("default")

    index_root: str = DefaultVal(None)
    name: str = DefaultVal(val=timestamp(daydir=True))

    rank: int = DefaultVal(0)
    nranks: int = DefaultVal(1)
    amp: bool = DefaultVal(val=True)

    total_visible_gpus: int = torch.cuda.device_count()
    gpus: int = DefaultVal(total_visible_gpus)

    avoid_fork_if_possible: bool = DefaultVal(val=False)

    @property
    def gpus_(self) -> list[int]:
        """Get normalized GPU device list.

        Converts GPU specification (int, str, or list) to sorted list of
        device indices, validating against available GPUs.

        Returns
        -------
        list[int]
            Sorted list of GPU device indices.

        Raises
        ------
        ValueError
            If any device index is out of range.
        """
        value = self.gpus

        if isinstance(value, int):
            value = list(range(value))

        if isinstance(value, str):
            value = value.split(",")

        value = list(map(int, value))
        value = sorted(set(value))

        if not all(
            device_idx in range(self.total_visible_gpus) for device_idx in value
        ):
            msg = f"All device indices must be in range(0, {self.total_visible_gpus}), got {value}"
            raise ValueError(msg)

        return value

    @property
    def index_root_(self) -> str:
        """Get index root directory path.

        Returns index_root if set, otherwise constructs path from root
        and experiment.

        Returns
        -------
        str
            Index root directory path.
        """
        return self.index_root or str(
            pathlib.Path(self.root) / self.experiment / "indexes"
        )

    @property
    def script_name_(self) -> str:
        """Get normalized script name from __main__ module.

        Extracts script name from __main__.__file__, normalizing relative
        to current working directory or experiment root.

        Returns
        -------
        str
            Normalized script name (e.g., "module.submodule.script"),
            or "none" if __file__ is not available.

        Raises
        ------
        ValueError
            If script_path doesn't end with .py or script_name is empty.
        """
        if "__file__" in dir(__main__):
            cwd = pathlib.Path(pathlib.Path.cwd()).resolve()
            script_path = pathlib.Path(__main__.__file__).resolve()
            root_path = pathlib.Path(self.root).resolve()

            if script_path.startswith(cwd):
                script_path = script_path[len(cwd) :]

            else:
                try:
                    commonpath = os.path.commonpath([script_path, root_path])
                    script_path = script_path[len(commonpath) :]
                except ValueError:
                    pass

            if not script_path.endswith(".py"):
                msg = f"script_path must end with .py, got {script_path}"
                raise ValueError(msg)
            script_name = script_path.replace("/", ".").strip(".")[:-3]

            if len(script_name) == 0:
                msg = (
                    "script_name must be non-empty, got "
                    f"script_name={script_name!r}, script_path={script_path!r}, "
                    f"cwd={cwd!r}"
                )
                raise ValueError(msg)

            return script_name

        return "none"

    @property
    def path_(self) -> str:
        """Get experiment output path.

        Constructs path from root, experiment, script_name_, and name.

        Returns
        -------
        str
            Experiment output directory path.
        """
        return str(
            pathlib.Path(self.root) / self.experiment / self.script_name_ / self.name
        )

    @property
    def device_(self) -> torch.device:
        """Get device index for current rank.

        Returns GPU device index assigned to current process rank.

        Returns
        -------
        int
            GPU device index.
        """
        return self.gpus_[self.rank % self.nranks]


@dataclass(frozen=True)
class TokenizerSettings:
    """Tokenizer configuration settings.

    Attributes
    ----------
    query_token_id : str
        Token ID for query special token (default: "[unused0]").
    doc_token_id : str
        Token ID for document special token (default: "[unused1]").
    query_token : str
        Query special token string (default: "[Q]").
    doc_token : str
        Document special token string (default: "[D]").
    """

    query_token_id: str = DefaultVal("[unused0]")
    doc_token_id: str = DefaultVal("[unused1]")
    query_token: str = DefaultVal("[Q]")
    doc_token: str = DefaultVal("[D]")


@dataclass(frozen=True)
class ResourceSettings:
    """Resource path settings for data and models.

    Attributes
    ----------
    checkpoint : str
        Path to model checkpoint (default: None).
    triples : str
        Path to training triples file (default: None).
    collection : str
        Path to document collection (default: None).
    queries : str
        Path to queries file (default: None).
    index_name : str
        Name of index to use (default: None).
    """

    checkpoint: str = DefaultVal(None)
    triples: str = DefaultVal(None)
    collection: str = DefaultVal(None)
    queries: str = DefaultVal(None)
    index_name: str = DefaultVal(None)


@dataclass(frozen=True)
class DocSettings:
    """Document processing settings.

    Attributes
    ----------
    dim : int
        Embedding dimension (default: 128).
    doc_maxlen : int
        Maximum document sequence length (default: 220).
    mask_punctuation : bool
        Whether to mask punctuation tokens (default: True).
    """

    dim: int = DefaultVal(128)
    doc_maxlen: int = DefaultVal(220)
    mask_punctuation: bool = DefaultVal(val=True)


@dataclass(frozen=True)
class QuerySettings:
    """Query processing settings.

    Attributes
    ----------
    query_maxlen : int
        Maximum query sequence length (default: 32).
    attend_to_mask_tokens : bool
        Whether to attend to mask tokens (default: False).
    interaction : str
        Interaction mode: "colbert" or "flipr" (default: "colbert").
    """

    query_maxlen: int = DefaultVal(32)
    attend_to_mask_tokens: bool = DefaultVal(val=False)
    interaction: str = DefaultVal("colbert")


@dataclass(frozen=True)
class TrainingSettings:
    """Training configuration settings.

    Attributes
    ----------
    similarity : str
        Similarity metric: "cosine" or "l2" (default: "cosine").
    bsize : int
        Batch size (default: 32).
    accumsteps : int
        Gradient accumulation steps (default: 1).
    lr : float
        Learning rate (default: 3e-06).
    maxsteps : int
        Maximum training steps (default: 500_000).
    save_every : int
        Save checkpoint every N steps (default: None).
    resume : bool
        Whether to resume from checkpoint (default: False).
    warmup : int
        Warmup steps (default: None).
    warmup_bert : int
        BERT warmup steps (default: None).
    relu : bool
        Whether to use ReLU activation (default: False).
    nway : int
        Number of negative examples per positive (default: 2).
    use_ib_negatives : bool
        Whether to use in-batch negatives (default: False).
    reranker : bool
        Whether model is a reranker (default: False).
    distillation_alpha : float
        Distillation loss weight (default: 1.0).
    ignore_scores : bool
        Whether to ignore scores during training (default: False).
    model_name : str
        Base model name (default: None).
    """

    similarity: str = DefaultVal("cosine")

    bsize: int = DefaultVal(32)

    accumsteps: int = DefaultVal(1)

    lr: float = DefaultVal(3e-06)

    maxsteps: int = DefaultVal(500_000)

    save_every: int = DefaultVal(None)

    resume: bool = DefaultVal(val=False)

    # NEW:
    warmup: int = DefaultVal(None)

    warmup_bert: int = DefaultVal(None)

    relu: bool = DefaultVal(val=False)

    nway: int = DefaultVal(2)

    use_ib_negatives: bool = DefaultVal(val=False)

    reranker: bool = DefaultVal(val=False)

    distillation_alpha: float = DefaultVal(1.0)

    ignore_scores: bool = DefaultVal(val=False)

    model_name: str = DefaultVal(None)  # DefaultVal('bert-base-uncased')


@dataclass(frozen=True)
class IndexingSettings:
    """Indexing configuration settings.

    Attributes
    ----------
    index_path : str
        Path to index directory (default: None).
    index_bsize : int
        Batch size for indexing (default: 64).
    nbits : int
        Number of bits for quantization (default: 1).
    kmeans_niters : int
        K-means iterations for codec training (default: 4).
    resume : bool
        Whether to resume indexing (default: False).
    """

    index_path: str = DefaultVal(None)

    index_bsize: int = DefaultVal(64)

    nbits: int = DefaultVal(1)

    kmeans_niters: int = DefaultVal(4)

    resume: bool = DefaultVal(val=False)

    @property
    def index_path_(self) -> str:
        """Get index path, constructing from index_root_ and index_name if needed.

        Returns
        -------
        str
            Index directory path.
        """
        return self.index_path or str(pathlib.Path(self.index_root_) / self.index_name)


@dataclass(frozen=True)
class SearchSettings:
    """Search configuration settings.

    Attributes
    ----------
    ncells : int
        Number of cells for IVF search (default: None).
    centroid_score_threshold : float
        Minimum centroid score threshold (default: None).
    ndocs : int
        Number of documents to retrieve (default: None).
    load_index_with_mmap : bool
        Whether to load index with memory mapping (default: False).
    """

    ncells: int = DefaultVal(None)
    centroid_score_threshold: float = DefaultVal(None)
    ndocs: int = DefaultVal(None)
    load_index_with_mmap: bool = DefaultVal(val=False)
