"""Standalone sentence-transformers embedding helper.

Invoke via:

    python -m codeintel_rev.cli.st_embed INPUT.txt \
        --output embeddings.npy \
        --jsonl embeddings.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from codeintel_rev.config import load_app_config
from codeintel_rev.config.api import AppConfig


@dataclass(slots=True)
class EmbedJob:
    """Configuration bundle for an embedding run.

    Attributes
    ----------
    input_path : Path
        Path to input text file. Each line is treated as a separate text
        sample to embed. Empty lines are skipped.
    output_path : Path
        Destination for the NumPy .npy embeddings array. The parent directory
        is created if it doesn't exist.
    model_name : str | None
        Optional SentenceTransformer identifier. If None, resolved from
        application configuration (embeddings.model_name or vllm.model).
    batch_size : int
        Batch size for encode() calls. Larger batches improve throughput but
        require more memory.
    device_name : str | None
        Optional device override ("cpu", "cuda", "mps"). If None, auto-detected
        based on available hardware.
    normalize : bool
        Whether to L2-normalize embeddings. Normalized embeddings have unit
        length, enabling cosine similarity via dot product.
    jsonl_path : Path | None
        Optional JSONL preview file path. If provided, writes text and embedding
        pairs for inspection. Each line contains a JSON object with "text" and
        "embedding" keys.
    """

    input_path: Path
    output_path: Path
    model_name: str | None
    batch_size: int
    device_name: str | None
    normalize: bool
    jsonl_path: Path | None


def _resolve_model_name(cli_value: str | None) -> str:
    """Resolve the model name from CLI argument or settings.

    Parameters
    ----------
    cli_value : str | None
        Model name provided via CLI argument, or None.

    Returns
    -------
    str
        Model name resolved in priority order: CLI value, embeddings.model_name
        from settings, or vllm.model from settings as fallback.
    """
    app_config = _cached_app_config()
    if cli_value:
        return cli_value
    if app_config.embeddings.model_name:
        return app_config.embeddings.model_name
    return app_config.vllm.model


def _resolve_device(cli_value: str | None) -> str:
    """Resolve the PyTorch device from CLI argument or auto-detect.

    Parameters
    ----------
    cli_value : str | None
        Device name provided via CLI argument (e.g., "cpu", "cuda", "mps"),
        or None to auto-detect.

    Returns
    -------
    str
        Device name resolved in priority order: CLI value, "cuda" if CUDA is
        available, "mps" if MPS is available (macOS), or "cpu" as fallback.
    """
    if cli_value:
        return cli_value
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():  # pragma: no cover - macOS only
        return "mps"
    return "cpu"


def _read_texts(path: Path) -> list[str]:
    """Read non-empty lines from a text file.

    Parameters
    ----------
    path : Path
        Path to the text file to read. Each line is treated as a separate text
        sample. The file must be UTF-8 encoded.

    Returns
    -------
    list[str]
        List of non-empty lines from the file, with leading and trailing
        whitespace stripped.
    """
    texts: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line:
                texts.append(line)
    return texts


def _dump_jsonl(texts: Iterable[str], embeddings: np.ndarray, path: Path) -> None:
    """Write texts and embeddings to a JSONL file.

    Parameters
    ----------
    texts : Iterable[str]
        Iterable of text strings to write. Must match the number of embeddings.
    embeddings : np.ndarray
        NumPy array of embeddings, one per text. Each embedding is converted
        to a list for JSON serialization.
    path : Path
        Output file path for the JSONL file. Each line contains a JSON object
        with "text" and "embedding" keys.
    """
    with path.open("w", encoding="utf-8") as handle:
        for text, vector in zip(texts, embeddings.tolist(), strict=False):
            handle.write(json.dumps({"text": text, "embedding": vector}) + "\n")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments for the embedding CLI.

    Parameters
    ----------
    argv : list[str] | None
        Command-line arguments to parse. If None, argparse will use sys.argv.

    Returns
    -------
    argparse.Namespace
        Parsed arguments containing input_path, output, model, batch_size,
        device, normalize flag, and optional jsonl path.
    """
    parser = argparse.ArgumentParser(
        description="Embed newline-delimited texts using sentence-transformers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input_path", type=Path, help="Text file (one sample per line).")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("embeddings.npy"),
        help="Output .npy file for embeddings.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Sentence-transformers model identifier (defaults to repo settings).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Batch size passed to sentence-transformers encode().",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Torch device to use (cpu/cuda/mps).",
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Disable L2 normalization of embeddings.",
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=None,
        help="Optional JSONL file (text+embedding rows) for inspection.",
    )
    return parser.parse_args(argv)


def embed_file(job: EmbedJob) -> None:
    """Generate embeddings for text file using SentenceTransformer.

    Parameters
    ----------
    job : EmbedJob
        Embedding configuration bundle containing:

        - input_path: Path to input text file. Each line is treated as a separate text
        to embed. Empty lines are skipped.
        - output_path: Destination for the NumPy .npy embeddings array.
        The parent directory is created if it doesn't exist.
        - model_name: Optional SentenceTransformer identifier (defaults to settings).
        - batch_size: Batch size for encode() calls.
        - device_name: Optional device override ("cpu", "cuda", etc.).
        - normalize: Whether to L2-normalize embeddings.
        - jsonl_path: Optional JSONL preview file path.

    Raises
    ------
    ValueError
        Raised when the input file contains no non-empty lines.
    """
    texts = _read_texts(job.input_path)
    if not texts:
        msg = f"No non-empty lines found in {job.input_path}"
        raise ValueError(msg)

    resolved_model = _resolve_model_name(job.model_name)
    resolved_device = _resolve_device(job.device_name)
    st_model = SentenceTransformer(resolved_model, device=resolved_device)

    embeddings = st_model.encode(
        texts,
        batch_size=job.batch_size,
        convert_to_numpy=True,
        normalize_embeddings=job.normalize,
        show_progress_bar=True,
    ).astype(np.float32, copy=False)

    job.output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(job.output_path, embeddings)

    if job.jsonl_path is not None:
        job.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        _dump_jsonl(texts, embeddings, job.jsonl_path)


def main(argv: list[str] | None = None) -> int:
    """Run the SentenceTransformer embedding CLI.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments. If None, uses sys.argv. Defaults to None.

    Returns
    -------
    int
        Exit code: 0 on success, 1 on error.
    """
    args = _parse_args(argv)
    job = EmbedJob(
        input_path=args.input_path,
        output_path=args.output,
        model_name=args.model,
        batch_size=args.batch_size,
        device_name=args.device,
        normalize=not args.no_normalize,
        jsonl_path=args.jsonl,
    )
    try:
        embed_file(job)
    except (OSError, ValueError, RuntimeError):  # pragma: no cover - CLI wrapper
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


@lru_cache(maxsize=1)
def _cached_app_config() -> AppConfig:
    """Load and cache AppConfig for CLI invocations.

    Returns
    -------
    AppConfig
        Cached immutable configuration derived from env/file sources.
    """
    return load_app_config(file=os.environ.get("CODEINTEL_CONFIG_FILE"))
