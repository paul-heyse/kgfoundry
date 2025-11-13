"""Admin endpoints for staging, publishing, and rolling back index versions."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.scope_store import ScopeIn
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


async def _persist_session_tuning(
    ctx: ApplicationContext, session_id: str, overrides: dict[str, float | int]
) -> dict[str, float]:
    scope = await ctx.scope_store.get(session_id)
    scope_dict = cast("ScopeIn", dict(scope or {}))
    existing_tuning = scope_dict.get("faiss_tuning")
    typed_existing = cast("Mapping[str, float] | None", existing_tuning)
    current_tuning: dict[str, float] = dict(typed_existing or {})
    normalized_overrides: dict[str, float] = {key: float(value) for key, value in overrides.items()}
    current_tuning.update(normalized_overrides)
    scope_dict["faiss_tuning"] = current_tuning
    await ctx.scope_store.set(session_id, scope_dict)
    return dict(normalized_overrides)


@router.get("/status")
async def status_endpoint(
    request: Request,
    _: None = Depends(_require_admin),
) -> JSONResponse:
    """Return the current index version and health.

    Extended Summary
    ----------------
    This endpoint provides visibility into the index lifecycle state for
    administrative monitoring and debugging. It reports the currently active
    version, available versions, asset availability, and directory locations.
    Used by operators to verify index deployment status and troubleshoot
    version management issues.

    Parameters
    ----------
    request : Request
        FastAPI request object containing application state with context.

    Returns
    -------
    JSONResponse
        Snapshot containing:
        - "current": str | None, active version identifier
        - "dir": str | None, path to current version directory
        - "assets_ok": bool, whether index assets are readable
        - "versions": list[str], all available version identifiers

    Notes
    -----
    This endpoint requires admin privileges (CODEINTEL_ADMIN=1). It performs
    non-blocking checks on index assets and gracefully handles missing or
    corrupted versions. Time complexity: O(1) for version lookup, O(n) for
    listing versions where n is the number of published versions.
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
    """Request body schema for index publication endpoint.

    Extended Summary
    ----------------
    This TypedDict defines the structure for publishing a new index version via
    the /admin/index/publish endpoint. It specifies all required and optional
    index asset paths (FAISS, DuckDB, SCIP, BM25, SPLADE, XTR) that must be
    staged before publication. The publication process validates these paths,
    stages them in a versioned directory, and updates the CURRENT symlink to
    activate the new version.

    Attributes
    ----------
    version : str
        Version identifier for the new index (e.g., "v1.2.3"). Must be unique
        and follow semantic versioning conventions. Used to create the versioned
        directory structure.
    faiss_index : str
        Path to the FAISS vector index directory. Required. Must exist and be
        readable. Contains the vector index files for dense retrieval.
    duckdb_path : str
        Path to the DuckDB catalog database file. Required. Must exist and be
        readable. Contains symbol metadata and chunk catalog for hybrid search.
    scip_index : str
        Path to the SCIP index file (JSON or protobuf). Required. Must exist and
        be readable. Contains symbol definitions and cross-references for code
        intelligence.
    bm25_dir : str | None
        Optional path to the BM25 sparse index directory. If None, BM25 retrieval
        is unavailable for this version. Used for keyword-based sparse retrieval.
    splade_dir : str | None
        Optional path to the SPLADE sparse index directory. If None, SPLADE
        retrieval is unavailable for this version. Used for learned sparse retrieval.
    xtr_dir : str | None
        Optional path to the XTR token index directory. If None, XTR reranking
        is unavailable for this version. Used for late-interaction reranking.
    faiss_idmap : str | None
        Optional path to the FAISS ID map sidecar. If provided, the lifecycle
        manager copies the parquet file into the version directory.
    tuning_profile : str | None
        Optional path to a tuning.json profile. When present, the profile is
        staged next to the index assets and applied at runtime.

    Notes
    -----
    All paths are resolved relative to the repository root. Required paths (faiss_index,
    duckdb_path, scip_index) are validated during staging. Optional paths are validated
    only if provided. The publication process is atomic: if any required asset fails
    validation, the entire operation is rolled back.
    """

    version: str
    faiss_index: str
    duckdb_path: str
    scip_index: str
    bm25_dir: str | None
    splade_dir: str | None
    xtr_dir: str | None
    faiss_idmap: str | None
    tuning_profile: str | None


class TuningBody(TypedDict, total=False):
    """Request body schema for runtime tuning endpoint.

    Extended Summary
    ----------------
    This TypedDict defines optional runtime tuning parameters that can be applied
    to the application context's factory adjuster. All fields are optional (total=False),
    allowing partial updates to specific tuning knobs. Tuning parameters affect how
    runtime cells (FAISS manager, hybrid search engine) are created and configured.
    Changes take effect immediately for new runtime cell instances.

    Attributes
    ----------
    faiss_nprobe : int, optional
        FAISS IVF nprobe parameter override. Controls the number of IVF clusters
        probed during search. Higher values improve recall but increase latency.
        Applied to FAISS manager factory configuration.
    faiss_gpu_preference : bool, optional
        GPU preference flag for FAISS operations. If True, prefers GPU execution
        when CUDA is available. If False, forces CPU execution. Applied to FAISS
        manager factory configuration.
    hybrid_rrf_k : int, optional
        Reciprocal Rank Fusion k parameter for hybrid search. Controls the
        fusion algorithm's rank aggregation behavior. Higher k values give more
        weight to top-ranked results. Applied to hybrid search engine configuration.
    hybrid_bm25_weight : float, optional
        BM25 weight in hybrid search fusion. Must be non-negative. Controls the
        contribution of BM25 scores to the final hybrid ranking. Applied to hybrid
        search engine configuration.
    hybrid_splade_weight : float, optional
        SPLADE weight in hybrid search fusion. Must be non-negative. Controls the
        contribution of SPLADE scores to the final hybrid ranking. Applied to hybrid
        search engine configuration.

    Notes
    -----
    All fields are optional. Only non-None values are applied to the factory adjuster.
    Tuning changes affect future runtime cell creation but do not modify existing cells.
    For immediate effect, combine with index reload operations. Weight parameters should
    be normalized appropriately for the fusion algorithm.
    """

    faiss_nprobe: int
    faiss_gpu_preference: bool
    hybrid_rrf_k: int
    hybrid_bm25_weight: float
    hybrid_splade_weight: float


class FaissRuntimeTuningBody(TypedDict, total=False):
    """Request body schema for FAISS runtime tuning endpoint.

    Extended Summary
    ----------------
    This TypedDict defines optional FAISS runtime tuning parameters that can be
    applied either globally (affecting all searches) or session-specifically (stored
    in scope metadata for a particular session). All fields are optional (total=False),
    allowing partial updates to specific tuning knobs. Runtime tuning overrides take
    precedence over factory defaults and autotune profiles.

    Attributes
    ----------
    nprobe : int, optional
        IVF nprobe override for FAISS search. Controls the number of IVF clusters
        probed during approximate nearest neighbor search. Higher values improve recall
        but increase latency. Applied as a runtime override to the FAISS manager.
    ef_search : int, optional
        HNSW ef_search parameter override. Controls the size of the candidate set
        during HNSW graph traversal. Higher values improve recall but increase latency.
        Only applicable to HNSW indexes. Applied as a runtime override.
    quantizer_ef_search : int, optional
        IVF quantizer ef_search parameter override. Controls the quantizer search
        depth for IVF indexes with HNSW quantizers. Higher values improve quantizer
        accuracy but increase latency. Applied as a runtime override.
    k_factor : float, optional
        Search k factor multiplier. Multiplies the requested k value before performing
        search, then returns the top-k results. Used to improve recall by searching
        more candidates than requested. Must be >= 1.0. Applied as a runtime override.
    session_id : str, optional
        Optional session identifier for session-scoped tuning. If provided, tuning
        parameters are persisted in the scope store and applied to searches for that
        session. If None, parameters are applied globally to the FAISS manager runtime
        overrides. Session-scoped tuning takes precedence over global tuning.

    Notes
    -----
    All fields are optional. Only non-None values are applied. When session_id is
    provided, tuning is stored in scope metadata and persists across requests for
    that session. Global tuning affects all searches immediately. Runtime overrides
    take precedence over factory defaults and autotune profiles. The k_factor must
    be >= 1.0 or validation will fail.
    """

    nprobe: int
    ef_search: int
    quantizer_ef_search: int
    k_factor: float
    session_id: str


@router.post("/publish")
async def publish_endpoint(
    body: PublishBody,
    request: Request,
    _: None = Depends(_require_admin),
) -> JSONResponse:
    """Stage and publish a new index version, then reload runtimes.

    Extended Summary
    ----------------
    This endpoint orchestrates the index publication workflow: staging assets
    (FAISS, DuckDB, SCIP, BM25, SPLADE, XTR), validating completeness, publishing
    to the versioned directory structure, updating the CURRENT symlink, and
    reloading runtime cells to pick up the new index. This is the primary
    mechanism for deploying new index versions in production.

    Parameters
    ----------
    body : PublishBody
        Request body containing:
        - "version": str, version identifier (e.g., "v1.2.3")
        - "faiss_dir": str, path to FAISS index directory
        - "duckdb_dir": str, path to DuckDB catalog directory
        - "scip_dir": str | None, optional path to SCIP index directory
        - "bm25_dir": str | None, optional path to BM25 index directory
        - "splade_dir": str | None, optional path to SPLADE index directory
        - "xtr_dir": str | None, optional path to XTR index directory
        - "faiss_idmap": str | None, optional path to faiss_idmap.parquet sidecar
        - "tuning_profile": str | None, optional path to tuning.json profile
    request : Request
        FastAPI request object containing application state with context.

    Returns
    -------
    JSONResponse
        Confirmation payload with:
        - "version": str, published version identifier
        - "staging": str, staging directory path
        - "final": str, final published directory path

    Raises
    ------
    HTTPException
        If validation fails (missing required assets), publishing encounters
        runtime errors (filesystem I/O, symlink creation), or index manager
        operations fail (status code 400 or 500).

    Notes
    -----
    This endpoint requires admin privileges (CODEINTEL_ADMIN=1). The publication
    process is atomic: if any step fails, the operation is rolled back. After
    successful publication, runtime cells are reloaded to ensure all components
    use the new index version. Time complexity: O(asset_count) for validation
    and staging, plus I/O time for directory operations.
    """
    ctx = _context(request)
    mgr = ctx.index_manager
    try:
        bm25_raw = body.get("bm25_dir")
        splade_raw = body.get("splade_dir")
        xtr_raw = body.get("xtr_dir")
        idmap_raw = body.get("faiss_idmap")
        tuning_raw = body.get("tuning_profile")
        assets = IndexAssets(
            faiss_index=Path(body["faiss_index"]),
            duckdb_path=Path(body["duckdb_path"]),
            scip_index=Path(body["scip_index"]),
            bm25_dir=Path(bm25_raw) if bm25_raw else None,
            splade_dir=Path(splade_raw) if splade_raw else None,
            xtr_dir=Path(xtr_raw) if xtr_raw else None,
            faiss_idmap=Path(idmap_raw) if idmap_raw else None,
            tuning_profile=Path(tuning_raw) if tuning_raw else None,
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

    Extended Summary
    ----------------
    This endpoint performs a rollback operation by updating the CURRENT symlink
    to point to a previously published version. After updating the symlink, it
    reloads runtime cells to ensure all components use the rolled-back index.
    Used for rapid recovery from problematic index deployments without requiring
    full re-publication.

    Parameters
    ----------
    version : str
        Version identifier to rollback to (e.g., "v1.2.0"). Must exist in
        the published versions list.
    request : Request
        FastAPI request object containing application state with context.

    Returns
    -------
    JSONResponse
        Confirmation payload with:
        - "ok": bool, True if rollback succeeded
        - "version": str, the version that is now active

    Raises
    ------
    HTTPException
        If the requested version cannot be located (status code 400) or if
        rollback operations fail (filesystem errors, symlink creation failures).

    Notes
    -----
    This endpoint requires admin privileges (CODEINTEL_ADMIN=1). Rollback is
    a fast operation (O(1) symlink update) but triggers full runtime cell
    reload. The operation is atomic: if reload fails, the symlink change is
    reverted. Use this for emergency rollbacks when a new version causes issues.
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

    Extended Summary
    ----------------
    This endpoint applies runtime tuning parameters to the application context's
    factory adjuster, affecting how runtime cells (FAISS manager, hybrid search
    engine) are created and configured. Tuning parameters include FAISS search
    knobs (nprobe, GPU preference) and hybrid search fusion weights (BM25, SPLADE).
    Changes take effect immediately for new runtime cell instances.

    Parameters
    ----------
    body : TuningBody
        Request body containing optional tuning parameters:
        - "faiss_nprobe": int | None, FAISS IVF nprobe override
        - "faiss_gpu_preference": str | None, GPU preference ("gpu", "cpu", "auto")
        - "hybrid_rrf_k": int | None, Reciprocal Rank Fusion k parameter
        - "hybrid_bm25_weight": float | None, BM25 weight in hybrid fusion
        - "hybrid_splade_weight": float | None, SPLADE weight in hybrid fusion
    request : Request
        FastAPI request object containing application state with context.

    Returns
    -------
    JSONResponse
        Summary payload with:
        - "ok": bool, True if tuning was applied
        - "tuning": dict[str, object], dictionary of applied tuning parameters
          (only includes non-None values from the request)

    Notes
    -----
    This endpoint requires admin privileges (CODEINTEL_ADMIN=1). Tuning changes
    are applied to the factory adjuster and affect future runtime cell creation.
    Existing cells are not modified; they continue using their current configuration
    until reloaded. For immediate effect, combine with index reload operations.
    Time complexity: O(1) for factory adjuster update.
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


@router.get("/tuning/faiss")
async def faiss_runtime_status(
    request: Request,
    _: None = Depends(_require_admin),
) -> JSONResponse:
    """Return the active FAISS runtime tuning profile.

    Extended Summary
    ----------------
    This endpoint provides visibility into the current FAISS runtime tuning
    state, including active parameters (nprobe, ef_search, quantizer_ef_search,
    k_factor), runtime overrides, and persisted autotune profiles. Used for
    monitoring and debugging FAISS search performance tuning.

    Parameters
    ----------
    request : Request
        FastAPI request object containing application state with context.

    Returns
    -------
    JSONResponse
        JSON document with keys:
        - "active": dict[str, object], current effective parameters
        - "overrides": dict[str, object], runtime override parameters
        - "autotune_profile": dict[str, object], persisted autotune profile

    Notes
    -----
    This endpoint requires admin privileges (CODEINTEL_ADMIN=1). The response
    reflects the tuning state of the FAISS manager for the coderank index.
    Time complexity: O(1) for tuning state retrieval.
    """
    ctx = _context(request)
    manager = ctx.get_coderank_faiss_manager(ctx.settings.index.vec_dim)
    return JSONResponse(manager.get_runtime_tuning())


@router.post("/tuning/faiss")
async def faiss_runtime_tuning_endpoint(
    body: FaissRuntimeTuningBody,
    request: Request,
    _: None = Depends(_require_admin),
) -> JSONResponse:
    """Apply FAISS runtime tuning overrides or persist them for a specific session.

    Extended Summary
    ----------------
    This endpoint applies FAISS runtime tuning parameters either globally (affecting
    all searches) or session-specifically (stored in scope metadata). When a
    session_id is provided, tuning parameters are persisted in the scope store
    and applied to searches for that session. Without a session_id, parameters
    are applied globally to the FAISS manager runtime overrides.

    Parameters
    ----------
    body : FaissRuntimeTuningBody
        Request body containing optional tuning parameters:
        - "nprobe": int | None, IVF nprobe override
        - "ef_search": int | None, HNSW ef_search override
        - "quantizer_ef_search": int | None, IVF quantizer ef_search override
        - "k_factor": float | None, search k factor multiplier
        - "session_id": str | None, optional session identifier for session-scoped tuning
    request : Request
        FastAPI request object containing application state with context.

    Returns
    -------
    JSONResponse
        Payload describing the applied overrides (same format as GET /tuning/faiss).

    Raises
    ------
    HTTPException
        If the request body contains no tunable fields (all parameters are None)
        or fails validation (status code 400).

    Notes
    -----
    This endpoint requires admin privileges (CODEINTEL_ADMIN=1). Session-scoped
    tuning takes precedence over global tuning for searches within that session.
    Global tuning affects all searches immediately. Time complexity: O(1) for
    global tuning, O(1) for session-scoped tuning (scope store update).
    """
    ctx = _context(request)
    session_id = body.get("session_id")
    # Extract non-null overrides
    payload = {
        key: value
        for key, value in (
            ("nprobe", body.get("nprobe")),
            ("ef_search", body.get("ef_search")),
            ("quantizer_ef_search", body.get("quantizer_ef_search")),
            ("k_factor", body.get("k_factor")),
        )
        if value is not None
    }
    if not payload:
        raise HTTPException(status_code=400, detail="no overrides provided")

    if session_id:
        tuning = await _persist_session_tuning(ctx, session_id, payload)
        return JSONResponse({"session_id": session_id, "faiss_tuning": tuning})

    manager = ctx.get_coderank_faiss_manager(ctx.settings.index.vec_dim)
    try:
        result = manager.apply_runtime_tuning(
            nprobe=body.get("nprobe"),
            ef_search=body.get("ef_search"),
            quantizer_ef_search=body.get("quantizer_ef_search"),
            k_factor=body.get("k_factor"),
        )
    except ValueError as exc:  # pragma: no cover - validation surface
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)


@router.delete("/tuning/faiss")
async def faiss_runtime_reset_endpoint(
    request: Request,
    session_id: str | None = Query(default=None),
    _: None = Depends(_require_admin),
) -> JSONResponse:
    """Reset FAISS runtime tuning overrides globally or for a session.

    Extended Summary
    ----------------
    This endpoint clears FAISS runtime tuning overrides, reverting to default
    (or autotuned) parameters. When a session_id is provided, clears session-scoped
    tuning from the scope store. Without a session_id, clears global runtime
    overrides from the FAISS manager. Used to reset tuning experiments or
    recover from misconfigured parameters.

    Parameters
    ----------
    request : Request
        FastAPI request object containing application state with context.
    session_id : str | None, optional
        Optional session identifier. If provided, clears session-scoped tuning
        for that session. If None, clears global runtime overrides.

    Returns
    -------
    JSONResponse
        Confirmation payload:
        - If session_id provided: {"session_id": str, "faiss_tuning": None}
        - If global reset: same format as GET /tuning/faiss with cleared overrides

    Notes
    -----
    This endpoint requires admin privileges (CODEINTEL_ADMIN=1). Resetting
    global overrides immediately affects all searches. Resetting session-scoped
    tuning only affects searches for that session. Time complexity: O(1) for
    both global and session-scoped resets.
    """
    ctx = _context(request)
    if session_id:
        scope = await ctx.scope_store.get(session_id)
        if scope:
            updated = cast("ScopeIn", dict(scope))
            updated.pop("faiss_tuning", None)
            await ctx.scope_store.set(session_id, updated)
        return JSONResponse({"session_id": session_id, "faiss_tuning": None})
    manager = ctx.get_coderank_faiss_manager(ctx.settings.index.vec_dim)
    return JSONResponse(manager.reset_runtime_tuning())


__all__ = ["router"]
