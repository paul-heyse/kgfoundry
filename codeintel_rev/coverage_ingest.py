# SPDX-License-Identifier: MIT
"""Coverage ingestion utilities (Cobertura-style XML)."""

from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover - optional dependency
    from defusedxml import ElementTree  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    from xml.etree import ElementTree  # type: ignore[import-not-found]  # noqa: S405


def collect_coverage(coverage_xml: str | Path) -> dict[str, dict[str, float]]:
    """Collect per-file coverage ratios from ``coverage.xml``.

    Parameters
    ----------
    coverage_xml : str | Path
        Path to coverage XML file (typically ``coverage.xml``).

    Returns
    -------
    dict[str, dict[str, float]]
        Mapping of paths to coverage ratios; empty when file is missing.
    """
    path = Path(coverage_xml)
    if not path.exists():
        return {}
    try:
        root = ElementTree.parse(path).getroot()  # noqa: S314
    except ElementTree.ParseError:
        return {}
    results: dict[str, dict[str, float]] = {}
    for class_elem in root.findall(".//class"):
        filename = class_elem.attrib.get("filename")
        if not filename:
            continue
        statements = _parse_int(class_elem.attrib.get("line-count"))
        covered = _parse_int(class_elem.attrib.get("line-rate"))
        if statements <= 0:
            statements = sum(
                1 for line in class_elem.findall(".//line") if line.attrib.get("hits") is not None
            )
            covered = sum(
                1
                for line in class_elem.findall(".//line")
                if _parse_int(line.attrib.get("hits")) > 0
            )
        ratio = (covered / statements) if statements else 0.0
        results[filename] = {
            "covered_lines_ratio": round(ratio, 4),
            "covered_defs_ratio": round(ratio, 4),
        }
    return results


def _parse_int(value: float | str | None) -> int:
    """Return integer conversion fallback to zero on failure.

    Parameters
    ----------
    value : int | float | str | None
        Value to convert to integer.

    Returns
    -------
    int
        Converted integer value, or 0 if conversion fails.
    """
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
