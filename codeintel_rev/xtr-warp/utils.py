"""Command-line utilities for XTR/WARP index creation and conversion.

This module provides CLI entry points for indexing collections and converting
indexes between formats. It handles argument parsing and configuration
validation for WARP index operations.
"""

from __future__ import annotations

import argparse
import pathlib

from dotenv import load_dotenv
from warp.engine.config import WARPRunConfig
from warp.engine.utils.collection_indexer import index
from warp.engine.utils.index_converter import convert_index

load_dotenv()


def parse_warp_run_config(
    collection: str, dataset: str | None, type_: str | None, split: str | None, nbits: int | None
) -> WARPRunConfig | None:
    """Parse and validate WARP run configuration parameters.

    Validates that all required parameters are present and creates a
    WARPRunConfig object. Returns None if validation fails.

    Parameters
    ----------
    collection : str
        Collection name ("beir" or "lotte").
    dataset : str | None
        Dataset identifier.
    type_ : str | None
        Type identifier (required for "lotte" collection).
    split : str | None
        Data split identifier.
    nbits : int | None
        Number of quantization bits.

    Returns
    -------
    WARPRunConfig | None
        Configured WARP run config, or None if validation fails.
    """
    if collection not in {"lotte", "beir"} or dataset is None or split is None or nbits is None:
        return None
    if collection == "lotte" and type_ is None:
        return None
    return WARPRunConfig(
        nranks=4,
        collection=collection,
        dataset=dataset,
        type_=type_,
        datasplit=split,
        nbits=nbits,
        k=100,
    )


def get_warp_run_config(parser: argparse.ArgumentParser, args: argparse.Namespace) -> WARPRunConfig:
    """Get and validate WARP run configuration from parsed arguments.

    Parses configuration from command-line arguments and validates it.
    Exits with an error message if the configuration is invalid.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Argument parser instance for error reporting.
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    WARPRunConfig
        Validated WARP run configuration.
    """
    config = parse_warp_run_config(
        collection=args.collection,
        dataset=args.dataset,
        type_=args.type,
        split=args.split,
        nbits=args.nbits,
    )
    if config is None:
        parser.error("Invalid warp run config specified.")
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="xtr-warp", description="Utilities for XTR/WARP index creation/evaluation"
    )

    parser.add_argument("mode", choices=["index"], nargs=1)
    parser.add_argument("-c", "--collection", choices=["beir", "lotte"])
    parser.add_argument("-d", "--dataset")
    parser.add_argument("-t", "--type", choices=["search", "forum"])
    parser.add_argument("-s", "--split", choices=["train", "test", "dev"])
    parser.add_argument("-n", "--nbits", type=int, choices=[1, 2, 4, 8])
    args = parser.parse_args()

    if len(args.mode) != 1:
        msg = f"mode must have exactly one element, got {len(args.mode)} elements"
        raise ValueError(msg)
    mode = args.mode[0]

    if mode == "index":
        config = get_warp_run_config(parser, args)
        index(config)
        index_path = pathlib.Path(config.index_root) / config.index_name
        convert_index(index_path)
    else:
        raise AssertionError
