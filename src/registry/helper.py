"""Overview of helper.

This module bundles helper logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import json
import uuid
from contextlib import closing
from typing import TYPE_CHECKING

from kgfoundry_common.navmap_loader import load_nav_metadata
from registry import duckdb_helpers
from registry.duckdb_helpers import DuckDBQueryOptions

if TYPE_CHECKING:
    from collections.abc import Mapping

    from duckdb import DuckDBPyConnection

    from kgfoundry_common.models import Doc, DoctagsAsset

__all__ = [
    "DuckDBRegistryHelper",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


def _execute_with_operation(
    conn: DuckDBPyConnection,
    sql: str,
    params: duckdb_helpers.Params,
    operation: str,
) -> None:
    duckdb_helpers.execute(
        conn,
        sql,
        params,
        options=DuckDBQueryOptions(operation=operation),
    )


# [nav:anchor DuckDBRegistryHelper]
class DuckDBRegistryHelper:
    """Helper class for writing records into the DuckDB registry.

    Provides convenient methods for managing runs, datasets, documents, and
    doctags in the DuckDB registry. All operations use parameterized queries
    for safety and structured logging for observability.

    Initializes the registry helper with database path. Sets up the helper
    with the path to the DuckDB database file. The database will be created
    if it doesn't exist.

    Parameters
    ----------
    db_path : str
        Path to the DuckDB database file.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _connect(self) -> DuckDBPyConnection:
        """Create a DuckDB connection for registry operations.

        Opens a connection to the DuckDB database using the configured path.
        Uses the standard connection helper with default pragmas.

        Returns
        -------
        DuckDBPyConnection
            Configured DuckDB connection ready for registry operations.
        """
        return duckdb_helpers.connect(self.db_path)

    def new_run(
        self,
        purpose: str,
        model_id: str | None,
        revision: str | None,
        config: Mapping[str, object],
    ) -> str:
        """Create a new pipeline run record.

        Inserts a new run record into the registry with the specified purpose,
        model information, and configuration. Returns a unique run ID.

        Parameters
        ----------
        purpose : str
            Purpose description for the run (e.g., "embedding", "indexing").
        model_id : str | None
            Model identifier used in this run, or None if not applicable.
        revision : str | None
            Model revision or version, or None if not applicable.
        config : Mapping[str, object]
            Run configuration dictionary (serialized as JSON).

        Returns
        -------
        str
            Unique run ID (UUID) for the newly created run.
        """
        run_id = str(uuid.uuid4())
        with closing(self._connect()) as con:
            _execute_with_operation(
                con,
                (
                    "INSERT INTO runs "
                    "(run_id,purpose,model_id,revision,started_at,config) "
                    "VALUES (?,?,?,?,CURRENT_TIMESTAMP,?)"
                ),
                [run_id, purpose, model_id, revision, json.dumps(config)],
                operation="registry.helper.new_run",
            )
        return run_id

    def close_run(
        self, run_id: str, *, success: bool, notes: str | None = None
    ) -> None:
        """Close a pipeline run and record completion status.

        Updates the run's finished_at timestamp and emits a RunClosed event
        with success status and optional notes.

        Parameters
        ----------
        run_id : str
            Run ID to close.
        success : bool
            Whether the run completed successfully.
        notes : str | None, optional
            Optional notes about the run completion. Defaults to None.
        """
        with closing(self._connect()) as con:
            _execute_with_operation(
                con,
                "UPDATE runs SET finished_at=CURRENT_TIMESTAMP WHERE run_id=?",
                [run_id],
                operation="registry.helper.close_run.finish",
            )
            payload: dict[str, object] = {"success": success, "notes": notes or ""}
            _execute_with_operation(
                con,
                "INSERT INTO pipeline_events VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                [
                    str(uuid.uuid4()),
                    "RunClosed",
                    run_id,
                    json.dumps(payload),
                ],
                operation="registry.helper.close_run.event",
            )

    def begin_dataset(self, kind: str, run_id: str) -> str:
        """Begin a new dataset within a run.

        Creates a new dataset record associated with the specified run.
        The dataset is initially created with an empty parquet_root; use
        commit_dataset() to finalize it with data.

        Parameters
        ----------
        kind : str
            Dataset kind (e.g., "embeddings", "chunks", "metadata").
        run_id : str
            Run ID that this dataset belongs to.

        Returns
        -------
        str
            Unique dataset ID (UUID) for the newly created dataset.
        """
        dataset_id = str(uuid.uuid4())
        with closing(self._connect()) as con:
            _execute_with_operation(
                con,
                (
                    "INSERT INTO datasets "
                    "(dataset_id,kind,parquet_root,run_id,created_at) "
                    "VALUES (?,?,?,?,CURRENT_TIMESTAMP)"
                ),
                [dataset_id, kind, "", run_id],
                operation="registry.helper.begin_dataset",
            )
        return dataset_id

    def commit_dataset(self, dataset_id: str, parquet_root: str, rows: int) -> None:
        """Commit a dataset with Parquet data location.

        Finalizes a dataset by updating its parquet_root path and row count,
        then emits a DatasetCommitted event.

        Parameters
        ----------
        dataset_id : str
            Dataset ID to commit.
        parquet_root : str
            Root directory path where Parquet files are stored.
        rows : int
            Total number of rows in the dataset.
        """
        with closing(self._connect()) as con:
            _execute_with_operation(
                con,
                "UPDATE datasets SET parquet_root=? WHERE dataset_id=?",
                [parquet_root, dataset_id],
                operation="registry.helper.commit_dataset.update",
            )
            payload: dict[str, object] = {"rows": rows, "root": parquet_root}
            _execute_with_operation(
                con,
                "INSERT INTO pipeline_events VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                [
                    str(uuid.uuid4()),
                    "DatasetCommitted",
                    dataset_id,
                    json.dumps(payload),
                ],
                operation="registry.helper.commit_dataset.event",
            )

    def rollback_dataset(self, dataset_id: str) -> None:
        """Rollback a dataset by deleting it.

        Deletes a dataset record and emits a DatasetRolledBack event.
        Use this when a dataset creation fails or needs to be abandoned.

        Parameters
        ----------
        dataset_id : str
            Dataset ID to rollback.
        """
        with closing(self._connect()) as con:
            _execute_with_operation(
                con,
                "DELETE FROM datasets WHERE dataset_id=?",
                [dataset_id],
                operation="registry.helper.rollback_dataset.delete",
            )
            _execute_with_operation(
                con,
                "INSERT INTO pipeline_events VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                [str(uuid.uuid4()), "DatasetRolledBack", dataset_id, "{}"],
                operation="registry.helper.rollback_dataset.event",
            )

    def register_documents(self, docs: list[Doc]) -> None:
        """Register document records in the registry.

        Inserts or replaces document records in the documents table. Each
        document's metadata (title, authors, publication date, etc.) is
        stored with the document ID.

        Parameters
        ----------
        docs : list[Doc]
            List of document objects to register. Each document must have
            a unique doc_id.
        """
        with closing(self._connect()) as con:
            for doc in docs:
                authors_list = list(doc.authors) if doc.authors is not None else []
                authors_json = json.dumps(authors_list)
                _execute_with_operation(
                    con,
                    """INSERT OR REPLACE INTO documents
                (doc_id, openalex_id, doi, arxiv_id, pmcid, title, authors,
                 pub_date, license, language, pdf_uri, source, content_hash, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    [
                        doc.id,
                        doc.openalex_id,
                        doc.doi,
                        doc.arxiv_id,
                        doc.pmcid,
                        doc.title,
                        authors_json,
                        doc.pub_date,
                        doc.license,
                        doc.language,
                        doc.pdf_uri,
                        doc.source,
                        doc.content_hash or "",
                    ],
                    operation="registry.helper.register_documents",
                )

    def register_doctags(self, assets: list[DoctagsAsset]) -> None:
        """Register doctags asset records in the registry.

        Inserts or replaces doctags asset records in the doctags table.
        Doctags represent visual document tags generated by vision-language
        models.

        Parameters
        ----------
        assets : list[DoctagsAsset]
            List of doctags asset objects to register. Each asset must have
            doc_id, doctags_uri, and model information.
        """
        with closing(self._connect()) as con:
            for asset in assets:
                _execute_with_operation(
                    con,
                    (
                        "INSERT OR REPLACE INTO doctags("
                        "doc_id, doctags_uri, pages, vlm_model, vlm_revision, avg_logprob, created_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, now())"
                    ),
                    [
                        asset.doc_id,
                        asset.doctags_uri,
                        asset.pages,
                        asset.vlm_model,
                        asset.vlm_revision,
                        asset.avg_logprob,
                    ],
                    operation="registry.helper.register_doctags",
                )

    def emit_event(
        self, event_name: str, subject_id: str, payload: Mapping[str, object]
    ) -> None:
        """Emit a pipeline event to the registry.

        Records an event in the pipeline_events table with a unique event ID,
        event name, subject ID, and JSON payload. Used for tracking pipeline
        operations and state changes.

        Parameters
        ----------
        event_name : str
            Name of the event (e.g., "RunClosed", "DatasetCommitted").
        subject_id : str
            ID of the subject the event relates to (e.g., run_id, dataset_id).
        payload : Mapping[str, object]
            Event payload dictionary (serialized as JSON).
        """
        with closing(self._connect()) as con:
            payload_dict: dict[str, object] = dict(payload)
            _execute_with_operation(
                con,
                "INSERT INTO pipeline_events VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                [str(uuid.uuid4()), event_name, subject_id, json.dumps(payload_dict)],
                operation="registry.helper.emit_event",
            )
