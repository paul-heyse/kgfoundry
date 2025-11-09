"""Load and validate Sphinx gallery manifest metadata."""

from __future__ import annotations

import json
import typing
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

MANIFEST_VERSION: Final[int] = 1


@dataclass(frozen=True, slots=True)
class GalleryExample:
    """Structured metadata describing a single gallery example."""

    slug: str
    filename: str
    title: str
    tooltip: str


class GalleryManifestError(RuntimeError):
    """Raised when the gallery manifest is missing or invalid."""


def _read_manifest(path: Path) -> Mapping[str, object]:
    """Return the raw manifest mapping loaded from ``path``.

    Parameters
    ----------
    path : Path
        Path to the gallery manifest JSON file.

    Returns
    -------
    Mapping[str, object]
        Parsed manifest mapping.

    Raises
    ------
    GalleryManifestError
        If the manifest file is missing, invalid JSON, or not an object.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - validated in CI
        message = f"Gallery manifest missing at {path}"
        raise GalleryManifestError(message) from exc

    try:
        parsed: object = json.loads(raw_text)
    except json.JSONDecodeError as exc:  # pragma: no cover - validated in CI
        message = f"Gallery manifest at {path} is not valid JSON"
        raise GalleryManifestError(message) from exc

    if not isinstance(parsed, Mapping):
        message = "Gallery manifest root must be an object"
        raise GalleryManifestError(message)

    return typing.cast("Mapping[str, object]", parsed)


def _ensure_supported_version(manifest: Mapping[str, object]) -> None:
    version = manifest.get("version")
    if version != MANIFEST_VERSION:
        message = (
            f"Gallery manifest version {version!r} is unsupported; expected {MANIFEST_VERSION}"
        )
        raise GalleryManifestError(message)


def _example_entries(manifest: Mapping[str, object]) -> list[object]:
    entries_obj: object = manifest.get("examples")
    if not isinstance(entries_obj, list):
        message = "Gallery manifest must define an 'examples' list"
        raise GalleryManifestError(message)
    return typing.cast("list[object]", entries_obj)


def _expect_mapping(index: int, item: object) -> Mapping[str, object]:
    if not isinstance(item, Mapping):
        message = f"Gallery manifest entry #{index} must be an object, received {type(item)!r}"
        raise GalleryManifestError(message)
    return item


def _require_nonempty_string(
    entry: Mapping[str, object],
    field: str,
    *,
    index: int,
    slug: str | None = None,
) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        if slug is None:
            message = f"Gallery manifest entry #{index} is missing {field}"
        else:
            message = f"Gallery manifest entry '{slug}' is missing {field}"
        raise GalleryManifestError(message)
    return value.strip()


def _validate_filename(
    *,
    filename: str,
    slug: str,
    seen_filenames: set[str],
) -> None:
    if not filename.endswith(".py"):
        message = f"Gallery manifest entry '{slug}' must specify a '.py' filename"
        raise GalleryManifestError(message)
    if Path(filename).name != filename:
        message = f"Gallery manifest entry '{slug}' filename must be a basename"
        raise GalleryManifestError(message)
    if filename in seen_filenames:
        message = f"Gallery manifest filename '{filename}' is referenced multiple times"
        raise GalleryManifestError(message)


def _parse_example(
    index: int,
    entry: Mapping[str, object],
    *,
    seen_slugs: set[str],
    seen_filenames: set[str],
) -> GalleryExample:
    slug = _require_nonempty_string(entry, "slug", index=index)
    if slug in seen_slugs:
        message = f"Gallery manifest slug '{slug}' is duplicated"
        raise GalleryManifestError(message)

    filename = _require_nonempty_string(entry, "filename", index=index, slug=slug)
    _validate_filename(filename=filename, slug=slug, seen_filenames=seen_filenames)

    title = _require_nonempty_string(entry, "title", index=index, slug=slug)
    tooltip = _require_nonempty_string(entry, "tooltip", index=index, slug=slug)

    seen_slugs.add(slug)
    seen_filenames.add(filename)

    return GalleryExample(slug=slug, filename=filename, title=title, tooltip=tooltip)


def load_gallery_manifest(path: Path) -> list[GalleryExample]:
    """Return gallery metadata loaded from ``path``.

    Parameters
    ----------
    path : Path
        Path to the gallery manifest JSON file.

    Returns
    -------
    list[GalleryExample]
        List of parsed gallery examples.
    """
    manifest = _read_manifest(path)
    _ensure_supported_version(manifest)
    entries = _example_entries(manifest)

    examples: list[GalleryExample] = []
    seen_slugs: set[str] = set()
    seen_filenames: set[str] = set()

    for index, raw_entry in enumerate(entries):
        mapping = _expect_mapping(index, raw_entry)
        examples.append(
            _parse_example(
                index,
                mapping,
                seen_slugs=seen_slugs,
                seen_filenames=seen_filenames,
            )
        )

    return examples


def explicit_order(manifest: typing.Iterable[GalleryExample]) -> list[str]:
    """Return filenames for use with ``sphinx_gallery.sorting.ExplicitOrder``.

    Parameters
    ----------
    manifest : typing.Iterable[GalleryExample]
        Gallery examples to extract filenames from.

    Returns
    -------
    list[str]
        List of filenames in manifest order.
    """
    return [entry.filename for entry in manifest]
