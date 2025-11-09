"""Collection indexing pipeline for creating WARP indices.

This module provides CollectionIndexer and the encode entry point for
building WARP-compressed indices from document collections. Handles
encoding, compression, training, and index persistence.
"""

from __future__ import annotations

import contextlib
import random
from typing import Any

import torch
import tqdm
import ujson

with contextlib.suppress(ImportError):
    import faiss

import pathlib

import numpy as np
import torch.multiprocessing as mp
from warp.data.collection import Collection
from warp.indexing.codecs.residual import ResidualCodec
from warp.indexing.collection_encoder import CollectionEncoder
from warp.indexing.index_saver import IndexSaver
from warp.indexing.utils import optimize_ivf
from warp.infra.config.config import ColBERTConfig
from warp.infra.launcher import print_memory_stats
from warp.infra.run import Run
from warp.modeling.checkpoint import Checkpoint
from warp.utils import distributed
from warp.utils.utils import print_message

# Verbose logging threshold
VERBOSE_DEBUG_LEVEL = 2


def encode(
    config: ColBERTConfig,
    collection: str | Collection,
    shared_lists: list[mp.managers.SyncManager.list[Any]],
    _shared_queues: list[mp.Queue[Any]],
    verbose: int = 3,
) -> None:
    """Entry point for distributed collection indexing.

    Creates a CollectionIndexer and runs the indexing pipeline with
    distributed synchronization support.

    Parameters
    ----------
    config : ColBERTConfig
        Configuration for indexing.
    collection : str | Collection
        Collection to index (path string or Collection object).
    shared_lists : list[mp.managers.SyncManager.list[Any]]
        Shared lists for inter-process communication.
    _shared_queues : list[mp.Queue[Any]]
        Shared queues for inter-process communication (unused).
    verbose : int
        Verbosity level (default: 3).
    """
    encoder = CollectionIndexer(config=config, collection=collection, verbose=verbose)
    encoder.run(shared_lists)


class CollectionIndexer:
    """Indexes a collection into a WARP-compressed index stored in chunks.

    Given a collection and config, encodes the collection into a compressed
    index and stores it on disk in chunks. Handles encoding, compression,
    training, and index persistence with distributed execution support.

    Parameters
    ----------
    config : ColBERTConfig
        Configuration for indexing (checkpoint, paths, compression settings).
    collection : str | Collection
        Collection to index (path string or Collection object).
    verbose : int
        Verbosity level (default: 2).

    Attributes
    ----------
    config : ColBERTConfig
        Indexing configuration.
    collection : Collection
        Collection being indexed.
    checkpoint : Checkpoint
        ColBERT checkpoint for encoding.
    encoder : CollectionEncoder
        Encoder for converting passages to embeddings.
    saver : IndexSaver
        Saver for persisting compressed chunks.
    rank : int
        Process rank for distributed execution.
    nranks : int
        Total number of processes.
    use_gpu : bool
        Whether GPU is available.
    verbose : int
        Verbosity level.
    """

    def __init__(
        self, config: ColBERTConfig, collection: str | Collection, verbose: int = 2
    ) -> None:
        self.verbose = verbose
        self.config = config
        self.rank, self.nranks = self.config.rank, self.config.nranks

        self.use_gpu = self.config.total_visible_gpus > 0

        if self.config.rank == 0 and self.verbose > 1:
            self.config.help()

        self.collection = Collection.cast(collection)
        self.checkpoint = Checkpoint(self.config.checkpoint, colbert_config=self.config)
        if self.use_gpu:
            self.checkpoint = self.checkpoint.cuda()

        self.encoder = CollectionEncoder(config, self.checkpoint)
        self.saver = IndexSaver(config)

        print_memory_stats(f"RANK:{self.rank}")

    def run(self, shared_lists: list[mp.managers.SyncManager.list[Any]]) -> None:
        """Execute the complete indexing pipeline.

        Runs setup, training, indexing, and finalization phases with
        distributed synchronization barriers between phases.

        Parameters
        ----------
        shared_lists : list[mp.managers.SyncManager.list[Any]]
            Shared lists for inter-process communication during training.
        """
        with torch.inference_mode():
            self.setup()  # Computes and saves plan for whole collection
            distributed.barrier(self.rank)
            print_memory_stats(f"RANK:{self.rank}")

            if not self.config.resume or not self.saver.try_load_codec():
                self.train(shared_lists)  # Trains centroids from selected passages
            distributed.barrier(self.rank)
            print_memory_stats(f"RANK:{self.rank}")

            self.index()  # Encodes and saves all tokens into residuals
            distributed.barrier(self.rank)
            print_memory_stats(f"RANK:{self.rank}")

            self.finalize()  # Builds metadata and centroid to passage mapping
            distributed.barrier(self.rank)
            print_memory_stats(f"RANK:{self.rank}")

    def setup(self) -> None:
        """Calculate and save plan.json for the whole collection.

        Computes indexing plan including number of chunks, partitions (centroids),
        estimated embeddings count, and average document length. Saves plan.json
        to index directory for use in subsequent phases.

        plan.json contains: config, num_chunks, num_partitions,
        num_embeddings_est, avg_doclen_est.
        num_partitions is the number of centroids to be generated.
        """
        if self.config.resume and self._try_load_plan():
            if self.verbose > 1:
                Run().print_main(f"#> Loaded plan from {self.plan_path}:")
                Run().print_main(f"#> num_chunks = {self.num_chunks}")
                Run().print_main(f"#> num_partitions = {self.num_chunks}")
                Run().print_main(f"#> num_embeddings_est = {self.num_embeddings_est}")
                Run().print_main(f"#> avg_doclen_est = {self.avg_doclen_est}")
            return

        self.num_chunks = int(np.ceil(len(self.collection) / self.collection.get_chunksize()))

        # Saves sampled passages and embeddings for training k-means centroids later
        sampled_pids = self._sample_pids()
        avg_doclen_est = self._sample_embeddings(sampled_pids)

        # Select the number of partitions
        num_passages = len(self.collection)
        self.num_embeddings_est = num_passages * avg_doclen_est
        self.num_partitions = int(2 ** np.floor(np.log2(16 * np.sqrt(self.num_embeddings_est))))

        if self.verbose > 0:
            Run().print_main(f"Creating {self.num_partitions:,} partitions.")
            Run().print_main(f"*Estimated* {int(self.num_embeddings_est):,} embeddings.")

        self._save_plan()

    def _sample_pids(self) -> set[int]:
        num_passages = len(self.collection)

        # Simple alternative: < 100k: 100%, < 1M: 15%, < 10M: 7%, < 100M: 3%, > 100M: 1%
        # Keep in mind that, say, 15% still means at least 100k.
        # So the formula is max(100% * min(total, 100k), 15% * min(total, 1M), ...)
        # Then we subsample the vectors to 100 * num_partitions

        typical_doclen = 120  # let's keep sampling independent of the actual doc_maxlen
        sampled_pids = 16 * np.sqrt(typical_doclen * num_passages)
        sampled_pids = min(1 + int(sampled_pids), num_passages)

        sampled_pids = random.sample(range(num_passages), sampled_pids)
        if self.verbose > 1:
            Run().print_main(
                f"# of sampled PIDs = {len(sampled_pids)} \t sampled_pids[:3] = {sampled_pids[:3]}"
            )

        return set(sampled_pids)

    def _sample_embeddings(self, sampled_pids: set[int]) -> float:
        local_pids = self.collection.enumerate(rank=self.rank)
        local_sample = [passage for pid, passage in local_pids if pid in sampled_pids]

        local_sample_embs, doclens = self.encoder.encode_passages(local_sample)

        if torch.cuda.is_available():
            if torch.distributed.is_available() and torch.distributed.is_initialized():
                self.num_sample_embs = torch.tensor([local_sample_embs.size(0)]).cuda()
                torch.distributed.all_reduce(self.num_sample_embs)

                avg_doclen_est = sum(doclens) / len(doclens) if doclens else 0
                avg_doclen_est = torch.tensor([avg_doclen_est]).cuda()
                torch.distributed.all_reduce(avg_doclen_est)

                nonzero_ranks = torch.tensor([float(len(local_sample) > 0)]).cuda()
                torch.distributed.all_reduce(nonzero_ranks)
            else:
                self.num_sample_embs = torch.tensor([local_sample_embs.size(0)]).cuda()

                avg_doclen_est = sum(doclens) / len(doclens) if doclens else 0
                avg_doclen_est = torch.tensor([avg_doclen_est]).cuda()

                nonzero_ranks = torch.tensor([float(len(local_sample) > 0)]).cuda()
        elif torch.distributed.is_available() and torch.distributed.is_initialized():
            self.num_sample_embs = torch.tensor([local_sample_embs.size(0)]).cpu()
            torch.distributed.all_reduce(self.num_sample_embs)

            avg_doclen_est = sum(doclens) / len(doclens) if doclens else 0
            avg_doclen_est = torch.tensor([avg_doclen_est]).cpu()
            torch.distributed.all_reduce(avg_doclen_est)

            nonzero_ranks = torch.tensor([float(len(local_sample) > 0)]).cpu()
            torch.distributed.all_reduce(nonzero_ranks)
        else:
            self.num_sample_embs = torch.tensor([local_sample_embs.size(0)]).cpu()

            avg_doclen_est = sum(doclens) / len(doclens) if doclens else 0
            avg_doclen_est = torch.tensor([avg_doclen_est]).cpu()

            nonzero_ranks = torch.tensor([float(len(local_sample) > 0)]).cpu()

        avg_doclen_est = avg_doclen_est.item() / nonzero_ranks.item()
        self.avg_doclen_est = avg_doclen_est

        Run().print(
            f"avg_doclen_est = {avg_doclen_est} \t len(local_sample) = {len(local_sample):,}"
        )

        torch.save(
            local_sample_embs,
            pathlib.Path(self.config.index_path_) / f"sample.{self.rank}.pt",
        )

        return avg_doclen_est

    def _try_load_plan(self) -> bool:
        config = self.config
        self.plan_path = pathlib.Path(config.index_path_) / "plan.json"
        if self.plan_path.exists():
            with pathlib.Path(self.plan_path).open(encoding="utf-8") as f:
                try:
                    plan = ujson.load(f)
                except ValueError:
                    return False
                if not (
                    "num_chunks" in plan
                    and "num_partitions" in plan
                    and "num_embeddings_est" in plan
                    and "avg_doclen_est" in plan
                ):
                    return False

                # NOTE: Verify config matches
                self.num_chunks = plan["num_chunks"]
                self.num_partitions = plan["num_partitions"]
                self.num_embeddings_est = plan["num_embeddings_est"]
                self.avg_doclen_est = plan["avg_doclen_est"]

            return True
        return False

    def _save_plan(self) -> None:
        if self.rank < 1:
            config = self.config
            self.plan_path = pathlib.Path(config.index_path_) / "plan.json"
            Run().print("#> Saving the indexing plan to", self.plan_path, "..")

            with self.plan_path.open("w", encoding="utf-8") as f:
                d = {"config": config.export()}
                d["num_chunks"] = self.num_chunks
                d["num_partitions"] = self.num_partitions
                d["num_embeddings_est"] = self.num_embeddings_est
                d["avg_doclen_est"] = self.avg_doclen_est

                f.write(ujson.dumps(d, indent=4) + "\n")

    def train(self, shared_lists: list[mp.managers.SyncManager.list[Any]]) -> None:
        """Train compression codec from sampled embeddings.

        Trains K-means centroids from sampled passages and computes average
        residual statistics. Only rank 0 performs training; other ranks skip.
        Saves codec configuration to index directory.

        Parameters
        ----------
        shared_lists : list[mp.managers.SyncManager.list[Any]]
            Shared lists for inter-process communication during K-means training.
        """
        if self.rank > 0:
            return

        sample, heldout = self._concatenate_and_split_sample()

        centroids = self._train_kmeans(sample, shared_lists)

        print_memory_stats(f"RANK:{self.rank}")
        del sample

        bucket_cutoffs, bucket_weights, avg_residual = self._compute_avg_residual(
            centroids, heldout
        )

        if self.verbose > 1:
            print_message(f"avg_residual = {avg_residual}")

        # Compute and save codec into avg_residual.pt, buckets.pt and centroids.pt
        codec = ResidualCodec(
            config=self.config,
            centroids=centroids,
            avg_residual=avg_residual,
            bucket_cutoffs=bucket_cutoffs,
            bucket_weights=bucket_weights,
        )
        self.saver.save_codec(codec)

    def _concatenate_and_split_sample(self) -> tuple[torch.Tensor, torch.Tensor]:
        print_memory_stats(f"***1*** \t RANK:{self.rank}")

        # NOTE: Allocate a float16 array. Load the samples from disk, copy to array.
        sample = torch.empty(self.num_sample_embs, self.config.dim, dtype=torch.float32)

        offset = 0
        index_path_obj = pathlib.Path(self.config.index_path_)
        for r in range(self.nranks):
            sub_sample_path = index_path_obj / f"sample.{r}.pt"
            sub_sample = torch.load(sub_sample_path)
            sub_sample_path.unlink()

            endpos = offset + sub_sample.size(0)
            sample[offset:endpos] = sub_sample
            offset = endpos

        if endpos != sample.size(0):
            msg = f"endpos ({endpos}) must equal sample.size(0) ({sample.size(0)})"
            raise ValueError(msg)

        print_memory_stats(f"***2*** \t RANK:{self.rank}")

        # Shuffle and split out a 5% "heldout" sub-sample [up to 50k elements]
        sample = sample[torch.randperm(sample.size(0))]

        print_memory_stats(f"***3*** \t RANK:{self.rank}")

        heldout_fraction = 0.05
        heldout_size = int(min(heldout_fraction * sample.size(0), 50_000))
        sample, sample_heldout = sample.split([sample.size(0) - heldout_size, heldout_size], dim=0)

        print_memory_stats(f"***4*** \t RANK:{self.rank}")

        return sample, sample_heldout

    def _train_kmeans(
        self, sample: torch.Tensor, shared_lists: list[mp.managers.SyncManager.list[Any]]
    ) -> torch.Tensor:
        if self.use_gpu:
            torch.cuda.empty_cache()

        # set to True to free faiss GPU-0 memory at the cost of one more copy
        do_fork_for_faiss = False  # of `sample`.

        args_ = [self.config.dim, self.num_partitions, self.config.kmeans_niters]

        if do_fork_for_faiss:
            # For this to work reliably, write the sample to disk. Pickle may
            # not handle >4GB of data.
            # Delete the sample file after work is done.

            shared_lists[0][0] = sample
            return_value_queue = mp.Queue()

            args_ += [shared_lists, return_value_queue]
            proc = mp.Process(target=compute_faiss_kmeans, args=args_)

            proc.start()
            centroids = return_value_queue.get()
            proc.join()

        else:
            args_ += [[[sample]]]
            centroids = compute_faiss_kmeans(*args_)

        centroids = torch.nn.functional.normalize(centroids, dim=-1)
        return centroids.float()

    def _compute_avg_residual(
        self, centroids: torch.Tensor, heldout: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, float]:
        compressor = ResidualCodec(config=self.config, centroids=centroids, avg_residual=None)

        heldout_reconstruct = compressor.compress_into_codes(
            heldout, out_device="cuda" if self.use_gpu else "cpu"
        )
        heldout_reconstruct = compressor.lookup_centroids(
            heldout_reconstruct, out_device="cuda" if self.use_gpu else "cpu"
        )
        if self.use_gpu:
            heldout_avg_residual = heldout.cuda() - heldout_reconstruct
        else:
            heldout_avg_residual = heldout - heldout_reconstruct

        avg_residual = torch.abs(heldout_avg_residual).mean(dim=0).cpu()

        num_options = 2**self.config.nbits
        quantiles = torch.arange(0, num_options, device=heldout_avg_residual.device) * (
            1 / num_options
        )
        bucket_cutoffs_quantiles, bucket_weights_quantiles = (
            quantiles[1:],
            quantiles + (0.5 / num_options),
        )

        bucket_cutoffs = heldout_avg_residual.float().quantile(bucket_cutoffs_quantiles)
        bucket_weights = heldout_avg_residual.float().quantile(bucket_weights_quantiles)

        if self.verbose > VERBOSE_DEBUG_LEVEL:
            print_message(
                f"#> Got bucket_cutoffs_quantiles = {bucket_cutoffs_quantiles} "
                f"and bucket_weights_quantiles = {bucket_weights_quantiles}"
            )
            print_message(
                f"#> Got bucket_cutoffs = {bucket_cutoffs} and bucket_weights = {bucket_weights}"
            )

        return bucket_cutoffs, bucket_weights, avg_residual.mean()

    def index(self) -> None:
        """Encode embeddings for all passages in collection.

        Each embedding is converted to code (centroid id) and residual.
        Embeddings stored according to passage order in contiguous chunks of memory.

        Saved data files described below:
            {CHUNK#}.codes.pt:      centroid id for each embedding in chunk
            {CHUNK#}.residuals.pt:  16-bits residual for each embedding in chunk
            doclens.{CHUNK#}.pt:    number of embeddings within each passage in chunk

        Raises
        ------
        ValueError
            If embeddings dtype is not torch.float32.
        """
        with self.saver.thread():
            batches = self.collection.enumerate_batches(rank=self.rank)
            for chunk_idx, offset, passages in tqdm.tqdm(batches, disable=self.rank > 0):
                if self.config.resume and self.saver.check_chunk_exists(chunk_idx):
                    if self.verbose > VERBOSE_DEBUG_LEVEL:
                        Run().print_main(
                            f"#> Found chunk {chunk_idx} in the index already, skipping encoding..."
                        )
                    continue
                # Encode passages into embeddings with the checkpoint model
                embs, doclens = self.encoder.encode_passages(passages)
                if embs.dtype != torch.float32:
                    msg = f"embs.dtype must be torch.float32, got {embs.dtype}"
                    raise ValueError(msg)
                if self.verbose > 1:
                    Run().print_main(
                        f"#> Saving chunk {chunk_idx}: \t {len(passages):,} passages "
                        f"and {embs.size(0):,} embeddings. From #{offset:,} onward."
                    )

                self.saver.save_chunk(
                    chunk_idx, offset, embs, doclens
                )  # offset = first passage index in chunk
                del embs, doclens

    def finalize(self) -> None:
        """Aggregate and store metadata for each chunk and the whole index.

        Builds and saves inverse mapping from centroids to passage IDs.
        Only rank 0 performs finalization; other ranks skip.

        Saved data files:
            {CHUNK#}.metadata.json: [ passage_offset, num_passages,
            num_embeddings, embedding_offset ]
            metadata.json: [ num_chunks, num_partitions, num_embeddings, avg_doclen ]
            ivf.pid.pt: [ ivf, ivf_lengths ]
                ivf is an array of passage IDs for centroids 0, 1, ...
                ivf_length contains the number of passage IDs for each centroid
        """
        if self.rank > 0:
            return

        self._check_all_files_are_saved()
        self._collect_embedding_id_offset()

        self._build_ivf()
        self._update_metadata()

    def _check_all_files_are_saved(self) -> None:
        if self.verbose > 1:
            Run().print_main("#> Checking all files were saved...")
        success = True
        for chunk_idx in range(self.num_chunks):
            if not self.saver.check_chunk_exists(chunk_idx):
                success = False
                Run().print_main(f"#> ERROR: Could not find chunk {chunk_idx}!")
                # NOTE: Fail here?
        if success and self.verbose > 1:
            Run().print_main("Found all files!")

    def _collect_embedding_id_offset(self) -> None:
        passage_offset = 0
        embedding_offset = 0

        self.embedding_offsets = []

        index_path_obj = pathlib.Path(self.config.index_path_)
        for chunk_idx in range(self.num_chunks):
            metadata_path = index_path_obj / f"{chunk_idx}.metadata.json"

            with metadata_path.open(encoding="utf-8") as f:
                chunk_metadata = ujson.load(f)

                chunk_metadata["embedding_offset"] = embedding_offset
                self.embedding_offsets.append(embedding_offset)

                if chunk_metadata["passage_offset"] != passage_offset:
                    msg = (
                        f"chunk_metadata['passage_offset'] "
                        f"({chunk_metadata['passage_offset']}) must equal "
                        f"passage_offset ({passage_offset}) for chunk_idx={chunk_idx}"
                    )
                    raise ValueError(msg)

                passage_offset += chunk_metadata["num_passages"]
                embedding_offset += chunk_metadata["num_embeddings"]

            with pathlib.Path(metadata_path).open("w", encoding="utf-8") as f:
                f.write(ujson.dumps(chunk_metadata, indent=4) + "\n")

        self.num_embeddings = embedding_offset
        if len(self.embedding_offsets) != self.num_chunks:
            msg = (
                f"len(embedding_offsets) ({len(self.embedding_offsets)}) "
                f"must equal num_chunks ({self.num_chunks})"
            )
            raise ValueError(msg)

    def _build_ivf(self) -> None:
        # Maybe we should several small IVFs? Every 250M embeddings, so that's every 1 GB.
        # It would save *memory* here and *disk space* regarding the int64.
        # But we'd have to decide how many IVFs to use during retrieval: many (loop) or one?
        # A loop seems nice if we can find a size that's large enough for
        # speed yet small enough to fit on GPU!
        # Then it would help nicely for batching later: 1GB.

        if self.verbose > 1:
            Run().print_main("#> Building IVF...")

        codes = torch.zeros(
            self.num_embeddings,
        ).long()
        if self.verbose > 1:
            print_memory_stats(f"RANK:{self.rank}")

        if self.verbose > 1:
            Run().print_main("#> Loading codes...")

        for chunk_idx in tqdm.tqdm(range(self.num_chunks)):
            offset = self.embedding_offsets[chunk_idx]
            chunk_codes = ResidualCodec.Embeddings.load_codes(self.config.index_path_, chunk_idx)

            codes[offset : offset + chunk_codes.size(0)] = chunk_codes

        if offset + chunk_codes.size(0) != codes.size(0):
            msg = (
                f"offset + chunk_codes.size(0) ({offset + chunk_codes.size(0)}) "
                f"must equal codes.size(0) ({codes.size(0)})"
            )
            raise ValueError(msg)
        if self.verbose > 1:
            Run().print_main("Sorting codes...")

            print_memory_stats(f"RANK:{self.rank}")

        codes = codes.sort()
        ivf, values = codes.indices, codes.values

        if self.verbose > 1:
            print_memory_stats(f"RANK:{self.rank}")

            Run().print_main("Getting unique codes...")

        ivf_lengths = torch.bincount(values, minlength=self.num_partitions)
        if ivf_lengths.size(0) != self.num_partitions:
            msg = (
                f"ivf_lengths.size(0) ({ivf_lengths.size(0)}) must equal "
                f"num_partitions ({self.num_partitions})"
            )
            raise ValueError(msg)

        if self.verbose > 1:
            print_memory_stats(f"RANK:{self.rank}")

        # Transforms centroid->embedding ivf to centroid->passage ivf
        _, _ = optimize_ivf(ivf, ivf_lengths, self.config.index_path_)

    def _update_metadata(self) -> None:
        config = self.config
        self.metadata_path = pathlib.Path(config.index_path_) / "metadata.json"
        if self.verbose > 1:
            Run().print("#> Saving the indexing metadata to", self.metadata_path, "..")

        with pathlib.Path(self.metadata_path).open("w", encoding="utf-8") as f:
            d = {"config": config.export()}
            d["num_chunks"] = self.num_chunks
            d["num_partitions"] = self.num_partitions
            d["num_embeddings"] = self.num_embeddings
            d["avg_doclen"] = self.num_embeddings / len(self.collection)

            f.write(ujson.dumps(d, indent=4) + "\n")


def compute_faiss_kmeans(
    dim: int,
    num_partitions: int,
    kmeans_niters: int,
    shared_lists: list[mp.managers.SyncManager.list[Any]],
    return_value_queue: mp.Queue[torch.Tensor] | None = None,
) -> torch.Tensor:
    """Compute K-means centroids using FAISS.

    Trains spherical K-means clustering on sampled embeddings to generate
    centroids for residual compression. Supports GPU acceleration and
    multiprocessing communication via shared lists.

    Parameters
    ----------
    dim : int
        Embedding dimension.
    num_partitions : int
        Number of centroids (K) to generate.
    kmeans_niters : int
        Number of K-means iterations.
    shared_lists : list[mp.managers.SyncManager.list[Any]]
        Shared lists containing sample embeddings at index [0][0].
    return_value_queue : mp.Queue[torch.Tensor] | None
        Optional queue for returning centroids in subprocess mode.

    Returns
    -------
    torch.Tensor
        Trained centroids tensor (normalized).
    """
    use_gpu = torch.cuda.is_available()
    Run().print_main("#> use_gpu =", use_gpu)
    kmeans = faiss.Kmeans(
        dim,
        num_partitions,
        niter=kmeans_niters,
        spherical=True,
        gpu=use_gpu,
        verbose=True,
        seed=123,
    )

    sample = shared_lists[0][0]
    sample = sample.float().numpy()

    kmeans.train(sample)

    centroids = torch.from_numpy(kmeans.centroids)

    print_memory_stats("RANK:0*")

    if return_value_queue is not None:
        return_value_queue.put(centroids)

    return centroids


"""
TODOs:

1. Consider saving/using heldout_avg_residual as a vector --- that is, using 128 averages!

2. Consider the operations with .cuda() tensors. Are all of them good for OOM?
"""
