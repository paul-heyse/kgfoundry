"""Admin endpoints for staging, publishing, and rolling back index versions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.errors import RuntimeLifecycleError
from codeintel_rev.indexing.index_lifecycle import IndexAssets
from codeintel_rev.runtime.factory_adjustment import DefaultFactoryAdjuster
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
router = APIRouter(prefix="/admin/index", tags=["admin:index"])

_ADMIN_FLAG = {"1", "true", "yes", "on"}


def _require_admin() -> None:
    flag = os.getenv("CODEINTEL_ADMIN", "")
    if flag.strip().lower() not in _ADMIN_FLAG:
        raise HTTPException(status_code=403, detail="admin-disabled")


def _context(request: Request) -> ApplicationContext:
    context = getattr(request.app.state, "context", None)
    if context is None:
        raise HTTPException(status_code=503, detail="context-unavailable")
    return context


@router.get("/status")
async def status_endpoint(
    request: Request,
    _: None = Depends(_require_admin),
) -> JSONResponse:
    """Return the current index version and health.

    Returns
    -------
    JSONResponse
        Snapshot containing version info and availability flags.

    """
    ctx = _context(request)
    mgr = ctx.index_manager
    version = mgr.current_version()
    assets_ok = False
    try:
        assets_ok = mgr.read_assets() is not None
    except RuntimeLifecycleError as exc:  # pragma: no cover - logged + returned
        LOGGER.warning("index.status.assets_unavailable", exc_info=exc)
    payload = {
        "current": version,
        "dir": str(mgr.current_dir()) if version else None,
        "assets_ok": assets_ok,
        "versions": mgr.list_versions(),
    }
    return JSONResponse(payload)


class PublishBody(TypedDict):
    version: str
    faiss_index: str
    duckdb_path: str
    scip_index: str
    bm25_dir: str | None
    splade_dir: str | None
    xtr_dir: str | None


class TuningBody(TypedDict, total=False):
    faiss_nprobe: int
    faiss_gpu_preference: bool
    hybrid_rrf_k: int
    hybrid_bm25_weight: float
    hybrid_splade_weight: float


@router.post("/publish")
async def publish_endpoint(
    body: PublishBody,
    request: Request,
    _: None = Depends(_require_admin),
) -> JSONResponse:
    """Stage and publish a new index version, then reload runtimes.

    Returns
    -------
    JSONResponse
        Confirmation payload with staging and final directories.

    Raises
    ------
    HTTPException
        If validation fails or publishing encounters runtime errors.
    """
    ctx = _context(request)
    mgr = ctx.index_manager
    try:
        bm25_raw = body.get("bm25_dir")
        splade_raw = body.get("splade_dir")
        xtr_raw = body.get("xtr_dir")
        assets = IndexAssets(
            faiss_index=Path(body["faiss_index"]),
            duckdb_path=Path(body["duckdb_path"]),
            scip_index=Path(body["scip_index"]),
            bm25_dir=Path(bm25_raw) if bm25_raw else None,
            splade_dir=Path(splade_raw) if splade_raw else None,
            xtr_dir=Path(xtr_raw) if xtr_raw else None,
        )
        staging = mgr.prepare(body["version"], assets)
        final = mgr.publish(body["version"])
        ctx.reload_indices()
    except KeyError as exc:  # pragma: no cover - body validation
        raise HTTPException(status_code=400, detail=f"missing field: {exc.args[0]}") from exc
    except RuntimeLifecycleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.exception("index.publish.unexpected", exc_info=exc)
        raise HTTPException(status_code=500, detail="publish-failed") from exc
    return JSONResponse(
        {
            "ok": True,
            "version": body["version"],
            "staging": str(staging),
            "final": str(final),
        }
    )


@router.post("/rollback/{version}")
async def rollback_endpoint(
    version: str,
    request: Request,
    _: None = Depends(_require_admin),
) -> JSONResponse:
    """Flip ``CURRENT`` to a previously published version.

    Returns
    -------
    JSONResponse
        Confirmation payload noting the active version.

    Raises
    ------
    HTTPException
        If the requested version cannot be located.

    """
    ctx = _context(request)
    try:
        ctx.index_manager.rollback(version)
        ctx.reload_indices()
    except RuntimeLifecycleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "version": version})


@router.post("/tuning")
async def tuning_endpoint(
    body: TuningBody,
    request: Request,
    _: None = Depends(_require_admin),
) -> JSONResponse:
    """Update runtime tuning knobs (nprobe, fusion weights, etc.).

    Returns
    -------
    JSONResponse
        Summary of the tuning fields that were applied.

    """
    ctx = _context(request)
    adjuster = DefaultFactoryAdjuster(
        faiss_nprobe=body.get("faiss_nprobe"),
        faiss_gpu_preference=body.get("faiss_gpu_preference"),
        hybrid_rrf_k=body.get("hybrid_rrf_k"),
        hybrid_bm25_weight=body.get("hybrid_bm25_weight"),
        hybrid_splade_weight=body.get("hybrid_splade_weight"),
    )
    ctx.apply_factory_adjuster(adjuster)
    return JSONResponse({"ok": True, "tuning": {k: v for k, v in body.items() if v is not None}})


__all__ = ["router"]
