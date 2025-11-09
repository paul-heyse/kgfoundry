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
    input_dataset_path = pathlib.Path(input_path) / dataset
    if not input_dataset_path.exists():
        url = f"https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{dataset}.zip"
        util.download_and_unzip(url, input_path)

    input_path = str(input_dataset_path)
    output_path = str(pathlib.Path(output_path) / dataset)

    corpus, queries, qrels = GenericDataLoader(input_path).load(split=split)

    collection, collection_map = [], {}
    for line_num, (id_, document) in enumerate(corpus.items()):
        title, text = document["title"], document["text"]

        # Escape newline characters in the title/text
        title = title.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        text = text.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")

        # NOTE We are using the "XTR way" of concatenating title and text
        # https://colab.research.google.com/github/google-deepmind/xtr/blob/main/xtr_evaluation_on_beir_miracl.ipynb
        collection.append(f"{line_num}\t{title} {text}\n")
        collection_map[line_num] = id_

    output_path_obj = pathlib.Path(output_path)
    collection_path = output_path_obj / "collection.tsv"
    with collection_path.open("w", encoding="utf-8") as file:
        file.writelines(collection)

    collection_map_path = output_path_obj / "collection_map.json"
    with collection_map_path.open("w", encoding="utf-8") as file:
        file.write(json.dumps(collection_map))

    questions = []
    for id_, query in queries.items():
        questions.append(f"{id_}\t{query}\n")

    questions_file = output_path_obj / f"questions.{split}.tsv"
    with questions_file.open("w", encoding="utf-8") as file:
        file.writelines(questions)

    qrels_file = output_path_obj / f"qrels.{split}.json"
    with qrels_file.open("w", encoding="utf-8") as file:
        json.dump(qrels, file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser("extract_collection.py")
    parser.add_argument("-d", "--dataset", required=True)
    parser.add_argument("-i", "--input", required=True)
    parser.add_argument("-s", "--split", required=True)
    parser.add_argument("-o", "--output")

    args = parser.parse_args()
    extract_collection_beir(args.dataset, args.input, args.output or args.input, split=args.split)
