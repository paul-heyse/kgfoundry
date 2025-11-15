"""Standalone sentence-transformers embedding helper.

Invoke via:

    python -m codeintel_rev.cli.st_embed INPUT.txt \
        --output embeddings.npy \
        --jsonl embeddings.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from codeintel_rev.config.settings import load_settings

LOGGER = logging.getLogger("codeintel.st_embed")


def _resolve_model_name(cli_value: str | None) -> str:
    settings = load_settings()
    if cli_value:
        return cli_value
    if settings.embeddings.model_name:
        return settings.embeddings.model_name
    return settings.vllm.model


def _resolve_device(cli_value: str | None) -> str:
    if cli_value:
        return cli_value
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():  # pragma: no cover - macOS only
        return "mps"
    return "cpu"


def _read_texts(path: Path) -> list[str]:
    texts: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line:
                texts.append(line)
    return texts


def _dump_jsonl(texts: Iterable[str], embeddings: np.ndarray, path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for text, vector in zip(texts, embeddings.tolist()):
            handle.write(json.dumps({"text": text, "embedding": vector}) + "\n")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
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


def embed_file(
    *,
    input_path: Path,
    output_path: Path,
    model_name: str | None,
    batch_size: int,
    device_name: str | None,
    normalize: bool,
    jsonl_path: Path | None,
) -> None:
    """Generate embeddings for text file using SentenceTransformer.

    Parameters
    ----------
    input_path : Path
        Path to input text file. Each line is treated as a separate text
        to embed. Empty lines are skipped.
    output_path : Path
        Path where embeddings will be saved as a NumPy array (.npy format).
        The parent directory is created if it doesn't exist.
    model_name : str | None
        Optional SentenceTransformer model name or path. If None, uses the
        default model from _resolve_model_name().
    batch_size : int
        Batch size for embedding generation. Larger batches improve throughput
        but require more memory.
    device_name : str | None
        Optional device name ("cpu", "cuda", etc.). If None, auto-detected
        based on CUDA availability.
    normalize : bool
        Whether to L2-normalize embeddings. Normalized embeddings are suitable
        for cosine similarity calculations.
    jsonl_path : Path | None
        Optional path to write a JSONL preview file containing text-embedding
        pairs. Useful for inspection and debugging.

    Raises
    ------
    ValueError
        Raised when the input file contains no non-empty lines.
    """
    texts = _read_texts(input_path)
    if not texts:
        msg = f"No non-empty lines found in {input_path}"
        raise ValueError(msg)

    resolved_model = _resolve_model_name(model_name)
    resolved_device = _resolve_device(device_name)
    LOGGER.info("Loading %s on %s", resolved_model, resolved_device)
    st_model = SentenceTransformer(resolved_model, device=resolved_device)

    LOGGER.info("Embedding %s texts (batch=%s)", len(texts), batch_size)
    embeddings = st_model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=normalize,
        show_progress_bar=True,
    ).astype(np.float32, copy=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(output_path, embeddings)
    LOGGER.info("Saved embeddings to %s", output_path)

    if jsonl_path is not None:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        _dump_jsonl(texts, embeddings, jsonl_path)
        LOGGER.info("Wrote JSONL preview to %s", jsonl_path)


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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    try:
        embed_file(
            input_path=args.input_path,
            output_path=args.output,
            model_name=args.model,
            batch_size=args.batch_size,
            device_name=args.device,
            normalize=not args.no_normalize,
            jsonl_path=args.jsonl,
        )
    except Exception as exc:  # pragma: no cover - CLI wrapper
        LOGGER.error("Embedding failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
