"""Collection extraction utilities for BEIR datasets.

This module provides functions to extract and format collections from BEIR
datasets, converting them into TSV format compatible with XTR/WARP indexing
and evaluation pipelines.
"""

from __future__ import annotations

import argparse
import json
import pathlib

from beir import util
from beir.datasets.data_loader import GenericDataLoader


def _download_collection(dataset: str, input_path: str) -> pathlib.Path:
    """Ensure the BEIR dataset is downloaded and return its path.

    Parameters
    ----------
    dataset : str
        Name of the BEIR dataset.
    input_path : str
        Directory path where datasets are stored.

    Returns
    -------
    pathlib.Path
        Path to the downloaded dataset directory.
    """
    dataset_path = pathlib.Path(input_path) / dataset
    if not dataset_path.exists():
        url = f"https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{dataset}.zip"
        util.download_and_unzip(url, input_path)
    return dataset_path


def _escape_text(value: str) -> str:
    """Escape newline and tab characters for TSV output.

    Parameters
    ----------
    value : str
        Text to escape.

    Returns
    -------
    str
        Escaped text with newlines and tabs replaced with escape sequences.
    """
    return value.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _dump_collection(
    corpus: dict[str, dict[str, str]], path: pathlib.Path
) -> dict[int, str]:
    """Write corpus lines to ``path`` and return the index mapping.

    Parameters
    ----------
    corpus : dict[str, dict[str, str]]
        Corpus dictionary mapping document IDs to document dictionaries
        containing "title" and "text" keys.
    path : pathlib.Path
        Path to the TSV file where collection lines will be written.

    Returns
    -------
    dict[int, str]
        Dictionary mapping line numbers to document IDs.
    """
    mapping: dict[int, str] = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for line_num, (doc_id, document) in enumerate(corpus.items()):
            title = _escape_text(document["title"])
            text = _escape_text(document["text"])
            file.write(f"{line_num}\t{title} {text}\n")
            mapping[line_num] = doc_id
    return mapping


def _write_questions(queries: dict[str, str], path: pathlib.Path) -> None:
    """Write TSV questions to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for query_id, query in queries.items():
            file.write(f"{query_id}\t{query}\n")


def _write_json(path: pathlib.Path, payload: object) -> None:
    """Write JSON payload to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file)


def extract_collection_beir(dataset: str, input_path: str, output_path: str, split: str) -> None:
    """Extract and format a BEIR dataset collection for XTR/WARP processing.

    Downloads the dataset if not present, loads corpus/queries/qrels, and writes
    them in TSV format. Titles and text are escaped to handle special characters.
    Creates collection.tsv, collection_map.json, questions.{split}.tsv, and
    qrels.{split}.json files in the output directory.

    Parameters
    ----------
    dataset : str
        Name of the BEIR dataset to extract (e.g., "nfcorpus", "scifact").
    input_path : str
        Directory path where datasets are stored or will be downloaded.
    output_path : str
        Directory path where extracted files will be written.
    split : str
        Data split to extract (typically "dev" or "test").
    """
    dataset_path = _download_collection(dataset, input_path)
    corpus, queries, qrels = GenericDataLoader(str(dataset_path)).load(split=split)
    output_dir = pathlib.Path(output_path) / dataset
    output_dir.mkdir(parents=True, exist_ok=True)

    collection_path = output_dir / "collection.tsv"
    collection_map = _dump_collection(corpus, collection_path)

    _write_json(output_dir / "collection_map.json", collection_map)
    _write_questions(queries, output_dir / f"questions.{split}.tsv")
    _write_json(output_dir / f"qrels.{split}.json", qrels)


if __name__ == "__main__":
    parser = argparse.ArgumentParser("extract_collection.py")
    parser.add_argument("-d", "--dataset", required=True)
    parser.add_argument("-i", "--input", required=True)
    parser.add_argument("-s", "--split", required=True)
    parser.add_argument("-o", "--output")

    args = parser.parse_args()
    extract_collection_beir(args.dataset, args.input, args.output or args.input, split=args.split)
