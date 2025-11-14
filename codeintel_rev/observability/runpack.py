"""Helpers for building per-run diagnostic artifacts ("runpacks")."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path
from time import time
from typing import Any

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.observability.otel import telemetry_enabled
from codeintel_rev.observability.reporting import (
    build_timeline_run_report,
    latest_run_report,
    resolve_timeline_dir,
)
from codeintel_rev.telemetry.reporter import build_report, report_to_json
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)

__all__ = ["make_runpack"]


def _json_bytes(payload: Mapping[str, Any] | list[Any]) -> bytes:
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def _write_bytes(archive: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    info = zipfile.ZipInfo(arcname)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data)


def _sanitize_dataclass(obj: object | None) -> dict[str, Any]:
    if not is_dataclass(obj):
        return {}
    snapshot: dict[str, Any] = {}
    for field in fields(obj):
        value = getattr(obj, field.name)
        if isinstance(value, Path):
            snapshot[field.name] = str(value)
        else:
            snapshot[field.name] = value
    return snapshot


def _settings_summary(context: ApplicationContext) -> dict[str, Any]:
    try:
        index = context.settings.index
        bm25 = context.settings.bm25
        splade = context.settings.splade
    except AttributeError:
        return {}
    summary: dict[str, Any] = {
        "index": {
            "vec_dim": index.vec_dim,
            "rrf_k": index.rrf_k,
            "enable_bm25_channel": index.enable_bm25_channel,
            "enable_splade_channel": index.enable_splade_channel,
            "use_gpu": index.use_gpu,
            "hybrid_top_k_per_channel": index.hybrid_top_k_per_channel,
        },
        "bm25": {"enabled": bm25.enabled, "rm3_enabled": bm25.rm3_enabled},
        "splade": {"enabled": splade.enabled},
    }
    return summary


def _runtime_facts(context: ApplicationContext) -> dict[str, Any]:
    facts: dict[str, Any] = {"telemetry_enabled": telemetry_enabled()}
    vllm = getattr(context, "vllm_client", None)
    if vllm is not None:
        config = getattr(vllm, "config", None)
        facts["vllm"] = {
            "model": getattr(config, "model", None),
            "base_url": getattr(config, "base_url", None),
            "embedding_dim": getattr(config, "embedding_dim", None),
            "mode": getattr(vllm, "_mode", None),
        }
    faiss = getattr(context, "faiss_manager", None)
    if faiss is not None:
        facts["faiss"] = {
            "index_path": str(getattr(faiss, "index_path", "")),
            "vec_dim": getattr(faiss, "vec_dim", None),
            "use_cuvs": getattr(faiss, "use_cuvs", None),
            "has_gpu_clone": bool(getattr(faiss, "gpu_index", None)),
        }
    duckdb = getattr(context, "duckdb_manager", None)
    if duckdb is not None:
        facts["duckdb"] = {"path": str(getattr(duckdb, "_db_path", ""))}
    return facts


def _context_snapshot(context: ApplicationContext) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "paths": _sanitize_dataclass(getattr(context, "paths", None)),
        "settings": _settings_summary(context),
    }
    snapshot["runtime"] = _runtime_facts(context)
    return snapshot


def _extract_budget(report: Mapping[str, Any]) -> Mapping[str, Any] | None:
    events = report.get("events")
    if not isinstance(events, list):
        return None
    for payload in reversed(events):
        attrs = payload.get("attrs")
        if (
            isinstance(attrs, Mapping)
            and attrs
            and (payload.get("name") == "gate.budget" or payload.get("type") == "decision")
        ):
            return dict(attrs)
    return None


def _structured_report(
    context: ApplicationContext,
    session_id: str,
    run_id: str | None,
) -> Mapping[str, Any] | None:
    try:
        report = build_report(context, session_id, run_id)
    except (RuntimeError, ValueError, OSError):  # pragma: no cover - diagnostics are best-effort
        LOGGER.debug("runpack.build_report_failed", exc_info=True)
        return None
    if report is None:
        return None
    return report_to_json(report)


def make_runpack(
    *,
    context: ApplicationContext,
    session_id: str,
    run_id: str | None,
    trace_id: str | None,
    reason: str | None = None,
) -> Path:
    """Build a zipped telemetry artifact for ``session_id``/``run_id``.

    This function creates a zip archive containing telemetry artifacts including
    timeline events, run reports, configuration snapshots, and metadata. It is
    called by CLI commands and diagnostic tools to package telemetry data for
    offline analysis and debugging.

    Parameters
    ----------
    context : ApplicationContext
        Application context providing settings and runtime configuration.
    session_id : str
        Session identifier to package artifacts for.
    run_id : str | None
        Optional run identifier when multiple runs share a session. If None,
        packages the latest run for the session.
    trace_id : str | None
        Optional trace identifier to record in metadata.
    reason : str | None
        Optional reason stored in metadata explaining why the runpack was created.
        Defaults to None.

    Returns
    -------
    Path
        Filesystem path to the generated zip archive.
    """
    timeline_dir = resolve_timeline_dir(None)
    out_dir = timeline_dir / "runpacks" / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time())
    inferred_run = run_id or "latest"
    archive_path = out_dir / f"runpack_{session_id}_{inferred_run}_{timestamp}.zip"

    try:
        timeline_report = build_timeline_run_report(
            session_id=session_id,
            run_id=run_id,
            timeline_dir=timeline_dir,
        ).to_dict()
    except (RuntimeError, ValueError, OSError):  # pragma: no cover - diagnostics fallback
        LOGGER.debug("runpack.timeline_failed", exc_info=True)
        timeline_report = {
            "session_id": session_id,
            "run_id": run_id,
            "error": "timeline_unavailable",
        }

    structured_report = _structured_report(context, session_id, run_id)
    budgets = None
    if structured_report is not None:
        budgets = structured_report.get("budgets") or structured_report.get("gating")
    if budgets is None:
        budgets = _extract_budget(timeline_report)

    context_payload = _context_snapshot(context)
    latest = latest_run_report()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        _write_bytes(
            archive,
            "meta.json",
            _json_bytes(
                {
                    "schema": "codeintel/runpack@v1",
                    "session_id": session_id,
                    "run_id": run_id,
                    "trace_id": trace_id,
                    "reason": reason,
                    "generated_at": timestamp,
                }
            ),
        )
        _write_bytes(archive, "timeline_report.json", _json_bytes(timeline_report))
        events = timeline_report.get("events") or []
        if isinstance(events, list) and events:
            timeline_lines = b"\n".join(
                json.dumps(event, ensure_ascii=False).encode("utf-8") for event in events
            )
            _write_bytes(archive, "timeline_events.jsonl", timeline_lines)
        if structured_report is not None:
            _write_bytes(archive, "run_report.json", _json_bytes(structured_report))
        if budgets:
            _write_bytes(archive, "budgets.json", _json_bytes(budgets))
        _write_bytes(archive, "context.json", _json_bytes(context_payload))
        if latest:
            _write_bytes(archive, "latest_report_pointer.json", _json_bytes(latest))
    buffer.seek(0)
    archive_path.write_bytes(buffer.getvalue())
    return archive_path
