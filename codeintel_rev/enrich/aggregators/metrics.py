"""Metrics aggregation helpers for module analysis."""

from __future__ import annotations

from codeintel_rev.enrich.types import ModuleMetrics


def finalize_annotation_ratio(
    module: str,
    *,
    annotated_defs: int,
    defs_total: int,
) -> ModuleMetrics:
    """Compute annotation ratio and build module metrics.

    Parameters
    ----------
    module : str
        Module name identifier.
    annotated_defs : int
        Number of definitions with type annotations. Must be non-negative.
    defs_total : int
        Total number of definitions. Must be non-negative.

    Returns
    -------
    ModuleMetrics
        Module metrics with computed annotation ratio and side effects flag.
    """
    denominator = max(defs_total, 1)
    ratio = float(annotated_defs) / float(denominator)
    return ModuleMetrics(
        module=module,
        annotated_defs=int(annotated_defs),
        defs_total=int(defs_total),
        annotation_ratio=ratio,
        has_top_level_side_effects=False,
    )


def set_side_effects_flag(metrics: ModuleMetrics, *, has_side_effects: bool) -> ModuleMetrics:
    """Update side effects flag in module metrics.

    Parameters
    ----------
    metrics : ModuleMetrics
        Original module metrics to update.
    has_side_effects : bool
        Whether the module has top-level side effects.

    Returns
    -------
    ModuleMetrics
        New module metrics with updated side effects flag.
    """
    return ModuleMetrics(
        module=metrics.module,
        annotated_defs=metrics.annotated_defs,
        defs_total=metrics.defs_total,
        annotation_ratio=metrics.annotation_ratio,
        has_top_level_side_effects=has_side_effects,
    )
