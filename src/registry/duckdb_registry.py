"""Overview of duckdb registry.

This module bundles duckdb registry logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from kgfoundry_common.navmap_loader import load_nav_metadata
from registry import duckdb_helpers
from registry.duckdb_helpers import DuckDBQueryOptions

if TYPE_CHECKING:
    from collections.abc import Mapping

    import duckdb

    from kgfoundry_common.models import Doc, DoctagsAsset

__all__ = [
    "DuckDBRegistry",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor DuckDBRegistry]
class DuckDBRegistry:
    """DuckDB-backed implementation of the registry protocol.

    Minimal registry implementation that stores pipeline artifacts and metadata
    in a DuckDB database. Implements the Registry protocol for managing runs,
    datasets, documents, doctags, and events.

    Parameters
    ----------
    db_path : str
        Path to the DuckDB database file. Database will be created if it
        doesn't exist.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.con = duckdb_helpers.connect(db_path, read_only=False)

    def begin_dataset(self, kind: str, run_id: str) -> str:
        """Insert a dataset placeholder row and return its identifier.

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
        _execute_with_operation(
            self.con,
            (
                "INSERT INTO datasets("
                "dataset_id, kind, parquet_root, run_id, created_at"
                ") VALUES (?, ?, '', ?, now())"
            ),
            [dataset_id, kind, run_id],
            operation="registry.duckdb.begin_dataset",
        )
        return dataset_id

    def commit_dataset(self, dataset_id: str, parquet_root: str, rows: int) -> None:
        """Update dataset metadata once Parquet artifacts are materialized.

        Finalizes a dataset by updating its parquet_root path. The rows
        parameter is currently unused but may be stored in the future.

        Parameters
        ----------
        dataset_id : str
            Dataset ID to commit.
        parquet_root : str
            Root directory path where Parquet files are stored.
        rows : int
            Total number of rows in the dataset (currently unused).
        """
        del rows
        _execute_with_operation(
            self.con,
            "UPDATE datasets SET parquet_root=? WHERE dataset_id=?",
            [parquet_root, dataset_id],
            operation="registry.duckdb.commit_dataset",
        )

    def rollback_dataset(self, dataset_id: str) -> None:
        """Delete a dataset placeholder if the build fails.

        Removes a dataset record when dataset creation fails or needs to
        be abandoned. Use this for cleanup when errors occur.

        Parameters
        ----------
        dataset_id : str
            Dataset ID to rollback.
        """
        _execute_with_operation(
            self.con,
            "DELETE FROM datasets WHERE dataset_id=?",
            [dataset_id],
            operation="registry.duckdb.rollback_dataset",
        )

    def insert_run(
        self,
        purpose: str,
        model_id: str | None,
        revision: str | None,
        config: Mapping[str, object],
    ) -> str:
        """Create a run record and return the generated identifier.

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
        _execute_with_operation(
            self.con,
            (
                "INSERT INTO runs("
                "run_id, purpose, model_id, revision, started_at, config"
                ") VALUES (?, ?, ?, ?, now(), ?)"
            ),
            [run_id, purpose, model_id, revision, json.dumps(config)],
            operation="registry.duckdb.insert_run",
        )
        return run_id

    def close_run(self, run_id: str, *, success: bool, notes: str | None = None) -> None:
        """Mark a run as finished and record the completion timestamp.

        Updates the run's finished_at timestamp. The success and notes
        parameters are currently unused but may be persisted in the future.

        Parameters
        ----------
        run_id : str
            Run ID to close.
        success : bool
            Whether the run completed successfully (currently unused).
        notes : str | None, optional
            Optional notes about the run completion (currently unused).
            Defaults to None.
        """
        _ = success  # placeholder until success flag/notes are persisted
        _ = notes
        _execute_with_operation(
            self.con,
            "UPDATE runs SET finished_at=now() WHERE run_id=?",
            [run_id],
            operation="registry.duckdb.close_run",
        )

    def register_documents(self, docs: list[Doc]) -> None:
        """Insert or update document metadata rows.

        Registers document records in the documents table. Each document's
        metadata (title, authors, publication date, etc.) is stored with
        the document ID. Uses INSERT OR REPLACE to handle duplicates.

        Parameters
        ----------
        docs : list[Doc]
            List of document objects to register. Each document must have
            a unique doc_id.
        """
        for doc in docs:
            _execute_with_operation(
                self.con,
                (
                    "INSERT OR REPLACE INTO documents("
                    "doc_id, openalex_id, doi, arxiv_id, pmcid, title, authors, "
                    "pub_date, license, language, pdf_uri, source, content_hash, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())"
                ),
                [
                    doc.id,
                    doc.openalex_id,
                    doc.doi,
                    doc.arxiv_id,
                    doc.pmcid,
                    doc.title,
                    json.dumps(doc.authors),
                    doc.pub_date,
                    doc.license,
                    doc.language,
                    doc.pdf_uri,
                    doc.source,
                    doc.content_hash,
                ],
                operation="registry.duckdb.register_documents",
            )

    def register_doctags(self, assets: list[DoctagsAsset]) -> None:
        """Insert or update doctags asset records.

        Registers doctags asset records in the doctags table. Doctags
        represent visual document tags generated by vision-language models.
        Uses INSERT OR REPLACE to handle duplicates.

        Parameters
        ----------
        assets : list[DoctagsAsset]
            List of doctags asset objects to register. Each asset must have
            doc_id, doctags_uri, and model information.
        """
        for asset in assets:
            _execute_with_operation(
                self.con,
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
                operation="registry.duckdb.register_doctags",
            )

    def emit_event(self, event_name: str, subject_id: str, payload: Mapping[str, object]) -> None:
        """Persist an arbitrary pipeline event with structured payload.

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
        _execute_with_operation(
            self.con,
            (
                "INSERT INTO pipeline_events("
                "event_id, event_name, subject_id, payload, created_at"
                ") VALUES (gen_random_uuid(), ?, ?, ?, now())"
            ),
            [event_name, subject_id, json.dumps(payload)],
            operation="registry.duckdb.emit_event",
        )

    def incident(self, event: str, subject_id: str, error_class: str, message: str) -> None:
        """Record an incident emitted by registry clients.

        Inserts an incident record into the incidents table for tracking
        errors and failures in pipeline operations.

        Parameters
        ----------
        event : str
            Event name associated with the incident.
        subject_id : str
            ID of the subject the incident relates to (e.g., run_id, dataset_id).
        error_class : str
            Error class or exception type name.
        message : str
            Error message describing the incident.
        """
        _execute_with_operation(
            self.con,
            (
                "INSERT INTO incidents("
                "id, event, subject_id, error_class, message, created_at"
                ") VALUES (gen_random_uuid(), ?, ?, ?, ?, now())"
            ),
            [event, subject_id, error_class, message],
            operation="registry.duckdb.incident",
        )


def _execute_with_operation(
    conn: duckdb.DuckDBPyConnection,
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
