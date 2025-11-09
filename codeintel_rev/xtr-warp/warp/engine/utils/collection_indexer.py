"""Collection indexing utilities for WARP.

This module provides functions for indexing document collections using
ColBERT models.
"""

from warp import Indexer
from warp.engine.config import WARPRunConfig
from warp.infra import Run, RunConfig


def index(config: WARPRunConfig) -> None:
    """Index a document collection using ColBERT.

    Creates an indexer with XTR-base-en checkpoint and indexes the collection
    specified in the configuration.

    Parameters
    ----------
    config : WARPRunConfig
        Configuration specifying collection path, index name, and experiment name.
    """
    with Run().context(RunConfig(nranks=config.nranks, experiment=config.experiment_name)):
        indexer = Indexer(checkpoint="google/xtr-base-en", config=config.colbert())
        indexer.index(name=config.index_name, collection=config.collection_path)
