"""DocFacts reconciliation utilities for the docstring builder."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from tools.docstring_builder.docfacts import (
    DOCFACTS_VERSION,
    build_docfacts_document,
    validate_docfacts_payload,
    write_docfacts,
)
from tools.docstring_builder.models import (
    SchemaViolationError,
    build_docfacts_document_payload,
)
from tools.docstring_builder.paths import DOCFACTS_DIFF_PATH, DOCFACTS_PATH, REPO_ROOT
from tools.docstring_builder.pipeline_types import DocfactsResult
from tools.drift_preview import write_html_diff

if TYPE_CHECKING:
    from collections.abc import Callable

    from tools.docstring_builder.builder_types import LoggerLike
    from tools.docstring_builder.config import BuilderConfig
    from tools.docstring_builder.docfacts import (
        DocFact,
        DocfactsDocument,
        DocfactsProvenance,
    )
    from tools.docstring_builder.models import (
        DocfactsDocumentLike,
        DocfactsDocumentPayload,
    )


def _coerce_provenance_payload(data: object) -> dict[str, str] | None:
    """Return a typed DocFacts provenance payload when ``data`` is valid.

    Parameters
    ----------
    data : object
        Object to coerce to provenance payload.

    Returns
    -------
    dict[str, str] | None
        Provenance payload dictionary if data is valid, None otherwise.
    """
    if not isinstance(data, Mapping):
        return None
    builder_version = data.get("builderVersion")
    config_hash = data.get("configHash")
    commit_hash = data.get("commitHash")
    generated_at = data.get("generatedAt")
    if not all(
        isinstance(value, str)
        for value in (builder_version, config_hash, commit_hash, generated_at)
    ):
        return None
    return {
        "builderVersion": str(builder_version),
        "configHash": str(config_hash),
        "commitHash": str(commit_hash),
        "generatedAt": str(generated_at),
    }


@dataclass(slots=True, frozen=True)
class DocfactsCoordinator:
    """Reconcile DocFacts artifacts for a pipeline run."""

    config: BuilderConfig
    build_provenance: Callable[[BuilderConfig], DocfactsProvenance]
    handle_schema_violation: Callable[[str, SchemaViolationError], None]
    typed_pipeline_enabled: bool
    check_mode: bool = False
    logger: LoggerLike = field(default_factory=lambda: logging.getLogger(__name__))

    def reconcile(self, docfacts: list[DocFact]) -> DocfactsResult:
        """Reconcile DocFacts artifacts for the current run.

        Parameters
        ----------
        docfacts : list[DocFact]
            DocFact entries to reconcile.

        Returns
        -------
        DocfactsResult
            Result indicating success, violation, config error, or general error.
        """
        provenance = self.build_provenance(self.config)
        document = build_docfacts_document(docfacts, provenance, DOCFACTS_VERSION)
        payload = build_docfacts_document_payload(cast("DocfactsDocumentLike", document))
        if self.check_mode:
            return self._check_payload(payload)
        return self._update_payload(document, payload)

    def _check_payload(self, payload: DocfactsDocumentPayload) -> DocfactsResult:
        """Validate DocFacts payload against the stored baseline.

        Parameters
        ----------
        payload : DocfactsDocumentPayload
            Payload to validate against baseline.

        Returns
        -------
        DocfactsResult
            Result indicating success or violation with drift details if applicable.
        """
        if not DOCFACTS_PATH.exists():
            self.logger.error("DocFacts missing at %s", DOCFACTS_PATH)
            return DocfactsResult(status="config", message="docfacts missing")
        try:
            existing_text = DOCFACTS_PATH.read_text(encoding="utf-8")
            existing_raw: object = json.loads(existing_text)
        except json.JSONDecodeError:  # pragma: no cover - defensive guard
            self.logger.exception("DocFacts payload at %s is not valid JSON", DOCFACTS_PATH)
            return DocfactsResult(status="config", message="docfacts invalid json")
        if not isinstance(existing_raw, Mapping):
            self.logger.error("DocFacts payload at %s is not a mapping", DOCFACTS_PATH)
            return DocfactsResult(status="config", message="docfacts invalid structure")
        existing_payload = cast("DocfactsDocumentPayload", existing_raw)
        try:
            validate_docfacts_payload(existing_payload)
        except SchemaViolationError as exc:
            self.handle_schema_violation("DocFacts (check)", exc)
            return DocfactsResult(status="success")

        comparison_payload = cast(
            "DocfactsDocumentPayload",
            json.loads(json.dumps(payload)),
        )
        provenance_existing = _coerce_provenance_payload(existing_payload.get("provenance"))
        comparison_provenance = comparison_payload["provenance"]
        if provenance_existing is not None:
            commit_hash = comparison_provenance.get("commitHash", "")
            generated_at = comparison_provenance.get("generatedAt", "")
            if isinstance(provenance_existing.get("commitHash"), str):
                commit_hash = provenance_existing["commitHash"]
            if isinstance(provenance_existing.get("generatedAt"), str):
                generated_at = provenance_existing["generatedAt"]
            comparison_payload["provenance"] = {
                "builderVersion": str(comparison_provenance.get("builderVersion", "")),
                "configHash": str(comparison_provenance.get("configHash", "")),
                "commitHash": commit_hash,
                "generatedAt": generated_at,
            }
        if existing_payload != comparison_payload:
            before = json.dumps(existing_payload, indent=2, sort_keys=True)
            after = json.dumps(comparison_payload, indent=2, sort_keys=True)
            write_html_diff(before, after, DOCFACTS_DIFF_PATH, "DocFacts drift")
            diff_rel = DOCFACTS_DIFF_PATH.relative_to(REPO_ROOT)
            self.logger.error(
                "DocFacts drift detected; run update mode to refresh (see %s)", diff_rel
            )
            return DocfactsResult(status="violation", message="docfacts drift", diff_path=diff_rel)
        DOCFACTS_DIFF_PATH.unlink(missing_ok=True)
        return DocfactsResult(status="success")

    def _update_payload(
        self,
        document: DocfactsDocument,
        _payload: DocfactsDocumentPayload,
    ) -> DocfactsResult:
        """Write DocFacts payload and validate when required.

        Parameters
        ----------
        document : DocfactsDocument
            Document to write.
        _payload : DocfactsDocumentPayload
            Payload representation (unused, kept for signature compatibility).

        Returns
        -------
        DocfactsResult
            Result indicating success.
        """
        written_payload = write_docfacts(
            DOCFACTS_PATH,
            document,
            validate=self.typed_pipeline_enabled,
        )
        if not self.typed_pipeline_enabled:
            try:
                validate_docfacts_payload(written_payload)
            except SchemaViolationError as exc:
                self.handle_schema_violation("DocFacts (update)", exc)
        DOCFACTS_DIFF_PATH.unlink(missing_ok=True)
        return DocfactsResult(status="success")
