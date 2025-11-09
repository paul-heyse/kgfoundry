"""Overview of calibration.

This module bundles calibration logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "isotonic_calibrate",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor isotonic_calibrate]
def isotonic_calibrate(pairs: list[tuple[float, int]]) -> dict[str, object]:
    """Return placeholder isotonic calibration parameters for linking scores.

    This function is a placeholder for future isotonic regression
    calibration functionality. Currently returns a dummy calibration
    dictionary.

    Parameters
    ----------
    pairs : list[tuple[float, int]]
        List of (score, label) pairs for calibration training.

    Returns
    -------
    dict[str, object]
        Dictionary with calibration parameters (currently placeholder).
    """
    # NOTE: fit isotonic regression parameters when calibrator is implemented
    del pairs  # placeholder until calibration logic is wired
    return {"kind": "isotonic", "params": []}
