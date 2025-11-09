"""Overview of exceptions.

This module bundles exceptions logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

from kgfoundry_common.errors import DownloadError as _DownloadError
from kgfoundry_common.errors import UnsupportedMIMEError as _UnsupportedMIMEError
from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "DownloadError",
    "UnsupportedMIMEError",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))

# [nav:anchor DownloadError]
DownloadError = _DownloadError
DownloadError.__doc__ = "Compatibility alias for :class:`kgfoundry_common.errors.DownloadError`."


# [nav:anchor UnsupportedMIMEError]
UnsupportedMIMEError = _UnsupportedMIMEError
UnsupportedMIMEError.__doc__ = (
    "Compatibility alias for :class:`kgfoundry_common.errors.UnsupportedMIMEError`."
)
