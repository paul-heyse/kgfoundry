# SPDX-License-Identifier: MIT
"""Writers and helpers that persist CST datasets to disk."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterable, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from hashlib import blake2s
from pathlib import Path
from types import TracebackType
from typing import Self, TextIO

from codeintel_rev.cst_build.cst_resolve import StitchCounters
from codeintel_rev.cst_build.cst_schema import SCHEMA_VERSION, CollectorStats, NodeRecord
from codeintel_rev.enrich.output_writers import write_json


class DatasetWriter:
    """Stream-oriented writer that materializes the dataset artifacts.

    Parameters
    ----------
    out_dir : Path
        Output directory for dataset artifacts.
    sample_size : int, optional
        Number of sample records to retain for debugging (default: 10).
    """

    def __init__(self, out_dir: Path, *, sample_size: int = 10) -> None:
        """Initialize dataset writer instance.

        Parameters are documented in the class docstring.
        """
        self._out_dir = out_dir
        self._sample_size = sample_size
        self._stack: ExitStack | None = None
        self._gz: TextIO | None = None
        self._module_dir = self._out_dir / "module_nodes"
        self._module_handles: dict[str, TextIO] = {}
        self._file_set: set[str] = set()
        self._node_count = 0
        self._samples: list[NodeRecord] = []
        self._stitch_samples = 0

    def __enter__(self) -> Self:
        """Open the gzip stream and module writers.

        Returns
        -------
        Self
            Active writer bound to the destination directory. Returns self
            for use as a context manager.
        """
        self._out_dir.mkdir(parents=True, exist_ok=True)
        stack = ExitStack()
        self._stack = stack
        self._all_path = self._out_dir / "cst_nodes.jsonl.gz"
        self._gz = stack.enter_context(gzip.open(self._all_path, "wt", encoding="utf-8"))
        self._module_dir.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        """Close any open resources when leaving the context manager."""
        self.finalize()

    @property
    def node_count(self) -> int:
        """Return the total number of nodes collected.

        Returns
        -------
        int
            Total count of nodes collected across all files.
        """
        return self._node_count

    @property
    def files_indexed(self) -> int:
        """Return the number of files indexed.

        Returns
        -------
        int
            Count of unique files that have been indexed.
        """
        return len(self._file_set)

    @property
    def samples(self) -> list[NodeRecord]:
        """Return a sample of collected node records.

        Returns
        -------
        list[NodeRecord]
            List of sampled node records, limited by the configured sample size.
        """
        return list(self._samples)

    def observe_file(self, rel_path: str) -> None:
        """Record that a new file is being streamed."""
        self._file_set.add(rel_path)

    def write_nodes(self, nodes: Iterable[NodeRecord]) -> None:
        """Write ``nodes`` to the gzipped dataset and per-module shards."""
        writer = self._ensure_writer()
        for node in nodes:
            payload = json.dumps(node.to_dict(), ensure_ascii=False)
            writer.write(payload)
            writer.write("\n")
            self._write_module_row(node.path, payload)
            self._node_count += 1
            self._maybe_sample(node)

    def finalize(self) -> None:
        """Close open streams."""
        if self._stack is None:
            return
        self._stack.close()
        self._stack = None
        self._gz = None
        self._module_handles.clear()

    def _write_module_row(self, rel_path: str, payload: str) -> None:
        """Write a node row to the per-module JSONL shard.

        Writes a JSON-serialized node record to the appropriate per-module file
        based on the node's path. Module files are created lazily and cached
        in the writer's handle dictionary.

        Parameters
        ----------
        rel_path : str
            Relative file path of the module containing the node. Used to
            determine which module shard file to write to.
        payload : str
            JSON-serialized node record string to write to the module file.

        Raises
        ------
        RuntimeError
            Raised if the writer is not initialized (not used as a context manager).

        Notes
        -----
        This method mutates the writer's state by creating and caching file handles
        for module shards. Each module gets its own JSONL file under the module_nodes
        directory, with the filename derived from the module path slug.
        """
        slug = _module_slug(rel_path)
        handle = self._module_handles.get(slug)
        if handle is None:
            target = self._module_dir / f"{slug}.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            stack = self._stack
            if stack is None:
                message = "DatasetWriter is not initialized; use context manager."
                raise RuntimeError(message)
            handle = stack.enter_context(target.open("w", encoding="utf-8"))
            self._module_handles[slug] = handle
        handle.write(payload)
        handle.write("\n")

    def _maybe_sample(self, node: NodeRecord) -> None:
        """Add a node to the sample collection if it's stitched.

        Maintains a fixed-size sample of stitched nodes (nodes with SCIP symbols)
        using reservoir sampling. The first `sample_size` stitched nodes are added
        directly, then subsequent nodes replace existing samples probabilistically.

        Parameters
        ----------
        node : NodeRecord
            Node record to potentially add to the sample. Only nodes with stitch
            information and a SCIP symbol are sampled.

        Notes
        -----
        This method mutates the writer's `_samples` list. Uses reservoir sampling
        to maintain a representative sample of stitched nodes for quality assurance
        and debugging purposes. The sampling is deterministic based on node_id and
        stitch sample count.
        """
        if not node.stitch or not node.stitch.scip_symbol:
            return
        self._stitch_samples += 1
        if len(self._samples) < self._sample_size:
            self._samples.append(node)
            return
        digest = blake2s(
            f"{node.node_id}:{self._stitch_samples}".encode(),
            digest_size=4,
        ).digest()
        idx = int.from_bytes(digest, "little") % self._sample_size
        self._samples[idx] = node

    def _ensure_writer(self) -> TextIO:
        """Ensure the gzip writer is initialized and return it.

        Returns
        -------
        TextIO
            Open gzip file handle for writing node records.

        Raises
        ------
        RuntimeError
            Raised if the writer is not initialized (not used as a context manager).
        """
        if self._gz is None:
            message = "DatasetWriter is not initialized; use context manager."
            raise RuntimeError(message)
        return self._gz


def write_index(
    out_dir: Path,
    *,
    root: Path,
    collector_stats: CollectorStats,
    stitch_stats: StitchCounters,
    writer: DatasetWriter,
) -> None:
    """Persist index.json summarizing the build."""
    provider_stats = {
        "qname_hits": collector_stats.qname_hits,
        "scope_lookups": collector_stats.scope_resolved,
    }
    payload = {
        "schema": SCHEMA_VERSION,
        "built_at": datetime.now(UTC).isoformat(),
        "root": str(root),
        "files_indexed": collector_stats.files_indexed,
        "node_rows": writer.node_count,
        "stitched": {
            "with_module": stitch_stats.module_matches,
            "with_scip": stitch_stats.scip_matches,
        },
        "provider_stats": provider_stats,
        "parse_errors": collector_stats.parse_errors,
    }
    write_json(out_dir / "index.json", payload)


def write_join_examples(out_dir: Path, samples: Sequence[NodeRecord]) -> None:
    """Write markdown examples linking nodes to SCIP symbols."""
    joins_dir = out_dir / "joins"
    joins_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Stitched CST ⇄ SCIP examples",
        "",
        "Sample joins to help with human QA of the stitching heuristics.",
        "",
    ]
    if not samples:
        lines.append("_No stitched samples were available in this run._")
    for idx, node in enumerate(samples, 1):
        stitch = node.stitch
        symbol = stitch.scip_symbol if stitch else ""
        evidence = ", ".join(stitch.evidence if stitch else [])
        span = node.span.to_dict()
        preview = (node.text_preview or "").strip()
        lines.extend(
            [
                f"{idx}. `{node.path}` — **{node.kind}** `{node.name or ''}`",
                f"   - span: start {span['start']} end {span['end']}",
                f"   - symbol: `{symbol}`",
                f"   - evidence: {evidence or '(none)'}",
                f"   - preview: {preview or '(empty)'}",
                "",
            ]
        )
    (joins_dir / "stitched_examples.md").write_text("\n".join(lines), encoding="utf-8")


def _module_slug(rel_path: str) -> str:
    r"""Convert a file path to a module slug for shard naming.

    Converts a relative file path to a module identifier slug suitable for
    use in filenames. Removes the .py extension, normalizes separators, and
    converts path separators to dots.

    Parameters
    ----------
    rel_path : str
        Relative file path (e.g., "src/pkg/module.py" or "src\\pkg\\module.py").

    Returns
    -------
    str
        Module slug string (e.g., "src.pkg.module") suitable for use in filenames.
        Returns "__root__" if the path normalizes to an empty string.
    """
    normalized = rel_path.replace("\\", "/")
    if normalized.endswith(".py"):
        normalized = normalized[:-3]
    normalized = normalized.strip("/")
    return normalized.replace("/", ".") or "__root__"
