"""Typed helpers for working with FAISS GPU bindings.

This module hides optional GPU initialisation and cloning logic behind a small typed surface so the
rest of the search stack can import a single, well-typed facade. The helpers are resilient to
missing GPU extras and fall back to CPU behaviour automatically.
"""

# [nav:section public-api]

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.sequence_guards import (
    first_or_error,
    first_or_error_multi_device,
)
from search_api.types import (
    FaissIndexProtocol,
    FaissModuleProtocol,
    GpuClonerOptionsProtocol,
    GpuResourcesProtocol,
)

logger = logging.getLogger(__name__)

__all__ = [
    "GpuContext",
    "clone_index_to_gpu",
    "configure_search_parameters",
    "detect_gpu_context",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


@dataclass(frozen=True)
# [nav:anchor GpuContext]
class GpuContext:
    """Container describing GPU resources associated with a FAISS module."""

    module: FaissModuleProtocol
    resources: GpuResourcesProtocol
    options: GpuClonerOptionsProtocol | None
    device_ids: tuple[int, ...]


# [nav:anchor detect_gpu_context]
def detect_gpu_context(
    module: FaissModuleProtocol,
    *,
    use_cuvs: bool = True,
    device_ids: Sequence[int] | None = None,
) -> GpuContext | None:
    """Return a :class:`GpuContext` when GPU helpers are available.

    Parameters
    ----------
    module : FaissModuleProtocol
        FAISS module previously imported (may be CPU-only).
    use_cuvs : bool, optional
        Whether to request cuVS acceleration when the module exposes the
        ``GpuClonerOptions`` flag. Defaults to ``True``.
    device_ids : Sequence[int] | None, optional
        Specific GPU device IDs to target. Defaults to ``(0,)`` when omitted.

    Returns
    -------
    GpuContext | None
        GPU context if GPU helpers are available, None otherwise.
    """
    standard_gpu_resources_raw = cast(
        "object | None", getattr(module, "StandardGpuResources", None)
    )
    if standard_gpu_resources_raw is None:
        return None

    resources_ctor = cast("Callable[[], GpuResourcesProtocol]", standard_gpu_resources_raw)
    resources = resources_ctor()

    options_ctor_raw = cast("object | None", getattr(module, "GpuClonerOptions", None))
    options: GpuClonerOptionsProtocol | None = None
    if options_ctor_raw is not None:
        options_ctor = cast("Callable[[], GpuClonerOptionsProtocol]", options_ctor_raw)
        options = options_ctor()
        if hasattr(options, "use_cuvs"):
            options.use_cuvs = bool(use_cuvs)

    devices = tuple(int(device) for device in device_ids) if device_ids else (0,)

    return GpuContext(module=module, resources=resources, options=options, device_ids=devices)


# [nav:anchor clone_index_to_gpu]
def clone_index_to_gpu(index: FaissIndexProtocol, context: GpuContext) -> FaissIndexProtocol:
    """Clone ``index`` onto GPU hardware described by ``context``.

    If GPU helpers are unavailable or cloning fails, the original CPU index is returned. All
    exceptions are caught and logged at debug level so callers can emit typed Problem Details
    without leaking driver internals to clients.

    Parameters
    ----------
    index : FaissIndexProtocol
        CPU index to clone.
    context : GpuContext
        GPU context for cloning.

    Returns
    -------
    FaissIndexProtocol
        GPU index if cloning succeeds, otherwise the original CPU index.
    """
    module = context.module
    devices = context.device_ids
    options = context.options

    try:
        if len(devices) > 1:
            multi_clone_raw = cast(
                "object | None", getattr(module, "index_cpu_to_gpu_multiple", None)
            )
            if multi_clone_raw is not None:
                multi_clone = cast(
                    "Callable[[GpuResourcesProtocol, Sequence[int], FaissIndexProtocol, GpuClonerOptionsProtocol | None], list[FaissIndexProtocol]]",
                    multi_clone_raw,
                )
                gpu_indices = multi_clone(context.resources, list(devices), index, options)
                if gpu_indices:
                    return first_or_error_multi_device(
                        gpu_indices, context="gpu_indices_from_multi_clone"
                    )

        clone_raw = cast("object | None", getattr(module, "index_cpu_to_gpu", None))
        if clone_raw is None:
            return index

        if options is not None:
            clone = cast(
                "Callable[[GpuResourcesProtocol, int, FaissIndexProtocol, GpuClonerOptionsProtocol], FaissIndexProtocol]",
                clone_raw,
            )
            return clone(
                context.resources,
                first_or_error(devices, context="device_ids_single_clone"),
                index,
                options,
            )

        clone_without_options = cast(
            "Callable[[GpuResourcesProtocol, int, FaissIndexProtocol], FaissIndexProtocol]",
            clone_raw,
        )
        return clone_without_options(
            context.resources,
            first_or_error(devices, context="device_ids_no_options"),
            index,
        )
    except (
        RuntimeError,
        OSError,
        ValueError,
    ) as exc:  # pragma: no cover - defensive fallback
        logger.debug("FAISS GPU cloning failed: %s", exc, exc_info=True)
        return index


# [nav:anchor configure_search_parameters]
def configure_search_parameters(
    module: FaissModuleProtocol,
    index: FaissIndexProtocol,
    *,
    nprobe: int,
    gpu_enabled: bool,
) -> None:
    """Apply FAISS search parameters (such as ``nprobe``) to ``index``.

    Parameters
    ----------
    module : FaissModuleProtocol
        FAISS module to query for parameter space helpers.
    index : FaissIndexProtocol
        Index to configure.
    nprobe : int
        Number of inverted lists to probe during search.
    gpu_enabled : bool
        Whether the index runs on GPU (selects GPU or CPU parameter space).
    """
    params_name = "GpuParameterSpace" if gpu_enabled else "ParameterSpace"
    params_ctor_raw = cast("object | None", getattr(module, params_name, None))
    if params_ctor_raw is None:
        return

    params_ctor = cast("Callable[[], object]", params_ctor_raw)
    params = params_ctor()
    setter_raw = cast("object | None", getattr(params, "set_index_parameter", None))
    if setter_raw is None:
        return

    setter = cast("Callable[[FaissIndexProtocol, str, object], None]", setter_raw)
    try:
        setter(index, "nprobe", nprobe)
    except (
        RuntimeError,
        AttributeError,
        ValueError,
    ) as exc:  # pragma: no cover - defensive fallback
        logger.debug("Unable to configure FAISS parameter 'nprobe': %s", exc, exc_info=True)
