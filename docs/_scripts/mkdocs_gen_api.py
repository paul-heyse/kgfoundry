"""Generate MkDocs API reference pages from the Griffe symbol graph."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

import mkdocs_gen_files
from tools import get_logger

from docs._scripts import shared

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

ENV = shared.detect_environment()
shared.ensure_sys_paths(ENV)
SETTINGS = shared.load_settings()
LOADER = shared.make_loader(ENV)

ROOT = ENV.root

BASE_LOGGER = get_logger(__name__)
LOG = shared.make_logger("mkdocs_api", logger=BASE_LOGGER, artifact="api")


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """Renderer output for a single MkDocs API page."""

    output_path: Path
    content: str


@runtime_checkable
class DocumentableNode(Protocol):
    """Protocol capturing the Griffe attributes used for MkDocs generation."""

    path: str
    members: Mapping[str, object]
    is_package: bool
    is_module: bool


def iter_packages() -> Sequence[str]:
    """Return the packages that should receive API documentation pages.

    Returns
    -------
    Sequence[str]
        Package names sequence.
    """
    return SETTINGS.packages


def _render_index(destination: Path) -> RenderedPage:
    content = "# API Reference\n"
    return RenderedPage(output_path=destination / "index.md", content=content)


def _render_node(node: DocumentableNode, destination: Path) -> RenderedPage:
    rel = node.path.replace(".", "/")
    page_path = destination / rel / "index.md"
    content = f"# `{node.path}`\n\n::: {node.path}\n"
    return RenderedPage(output_path=page_path, content=content)


def _documentable_members(node: DocumentableNode) -> Iterable[DocumentableNode]:
    members_attr = cast("object", getattr(node, "members", None))
    if not isinstance(members_attr, Mapping):
        return ()
    members = cast("Mapping[str, object]", members_attr)
    filtered: list[DocumentableNode] = []
    for member in members.values():
        member_node = cast("DocumentableNode", member)
        is_package = cast("bool", getattr(member_node, "is_package", False))
        is_module = cast("bool", getattr(member_node, "is_module", False))
        if is_package or is_module:
            filtered.append(member_node)
    return tuple(filtered)


def generate_api_reference(
    loader: shared.GriffeLoader,
    packages: Sequence[str],
    *,
    destination: Path | None = None,
) -> list[RenderedPage]:
    """Generate MkDocs API reference pages for ``packages``.

    Parameters
    ----------
    loader : shared.GriffeLoader
        Griffe loader instance.
    packages : Sequence[str]
        Package names to document.
    destination : Path | None, optional
        Output directory path, defaults to "api".

    Returns
    -------
    list[RenderedPage]
        List of rendered API pages.
    """
    target = destination if destination is not None else Path("api")
    pages: list[RenderedPage] = [_render_index(target)]

    for package in packages:
        module = cast("DocumentableNode", loader.load(package))
        pages.append(_render_node(module, target))
        pages.extend(
            _render_node(member, target) for member in _documentable_members(module)
        )

    return pages


def write_api_page(page: RenderedPage) -> None:
    """Persist a rendered page to disk via mkdocs_gen_files."""
    page.output_path.parent.mkdir(parents=True, exist_ok=True)
    with mkdocs_gen_files.open(page.output_path, "w") as handle:
        handle.write(page.content)


def main(packages: Sequence[str] | None = None) -> int:
    """Generate MkDocs API documentation and return an exit status.

    Parameters
    ----------
    packages : Sequence[str] | None, optional
        Package names to document, defaults to configured packages.

    Returns
    -------
    int
        Exit code: 0 on success.
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)

    resolved_packages = list(packages or iter_packages())
    pages = generate_api_reference(LOADER, resolved_packages)
    for page in pages:
        write_api_page(page)

    LOG.info(
        "Generated MkDocs API reference",
        extra={
            "status": "success",
            "package_count": len(resolved_packages),
            "destination": "api",
            "page_count": len(pages),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
