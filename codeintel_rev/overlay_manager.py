# SPDX-License-Identifier: MIT
"""Targeted overlay manager for opt-in stub generation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from codeintel_rev.module_utils import normalize_module_name


@dataclass(slots=True, frozen=True)
class OverlayPlan:
    """Plan describing overlays to generate."""

    module_path: str
    exports: dict[str, dict[str, str]]


def select_overlay_candidates(
    rows: Iterable[Mapping[str, object]],
    *,
    max_candidates: int = 50,
) -> list[OverlayPlan]:
    """Return overlay candidates based on re-exports and typedness.

    Parameters
    ----------
    rows : Iterable[Mapping[str, object]]
        Module metadata rows to evaluate for overlay generation.
    max_candidates : int, optional
        Maximum number of overlay plans to return (defaults to 50).

    Returns
    -------
    list[OverlayPlan]
        Overlay plans limited to ``max_candidates`` items.
    """
    plans: list[OverlayPlan] = []
    for row in rows:
        path = row.get("path")
        if not isinstance(path, str):
            continue
        reexports = row.get("reexports")
        if not isinstance(reexports, Mapping) or not reexports:
            continue
        type_errors = _safe_int(row.get("type_errors"))
        if type_errors == 0:
            continue
        plans.append(
            OverlayPlan(
                module_path=path,
                exports={str(k): dict(v) for k, v in reexports.items()},
            )
        )
        if len(plans) >= max_candidates:
            break
    return plans


def generate_overlay_stub(plan: OverlayPlan, overlays_root: Path) -> Path:
    """Write a re-export-only stub for ``plan``.

    Parameters
    ----------
    plan : OverlayPlan
        Overlay plan describing which exports to generate.
    overlays_root : Path
        Root directory for generated overlay stubs.

    Returns
    -------
    Path
        Path to the generated stub file.
    """
    module_name = normalize_module_name(plan.module_path)
    destination = overlays_root / Path(plan.module_path).with_suffix(".pyi")
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "from __future__ import annotations",
        "",
        f"# Auto-generated overlay for {module_name}.",
        "",
    ]
    for export, meta in sorted(plan.exports.items()):
        origin = meta.get("from")
        if not origin:
            continue
        lines.append(f"from {origin} import {export} as {export}")
    lines.append("")
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


def activate_generated_overlays(
    plans: Iterable[OverlayPlan],
    *,
    overlays_root: Path,
    stubs_root: Path,
) -> int:
    """Symlink generated overlays into the primary stub path.

    Parameters
    ----------
    plans : Iterable[OverlayPlan]
        Overlay plans to activate by creating symlinks.
    overlays_root : Path
        Root directory containing generated overlay stubs.
    stubs_root : Path
        Target directory where symlinks will be created.

    Returns
    -------
    int
        Number of overlays that were activated.
    """
    activated = 0
    for plan in plans:
        stub_path = generate_overlay_stub(plan, overlays_root)
        target = stubs_root / stub_path.relative_to(overlays_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(stub_path)
        activated += 1
    return activated


def _safe_int(value: object | None) -> int:
    """Return a best-effort integer conversion.

    Parameters
    ----------
    value : object | None
        Value to convert to integer. Supports int, float, str, bool, or None.

    Returns
    -------
    int
        Normalized integer representation; 0 when conversion fails or value is None.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0
