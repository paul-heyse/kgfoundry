"""Generate and optionally validate the import-linter configuration for tooling packages."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from tools._shared.logging import get_logger
from tools._shared.proc import run_tool
from tools.detect_pkg import detect_primary

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

LOGGER = get_logger(__name__)

DOCS_ADAPTERS = (
    "tools.docs.build_artifacts",
    "tools.docs.build_graphs",
    "tools.docs.build_test_map",
    "tools.docs.export_schemas",
    "tools.docs.scan_observability",
)

NAVMAP_ADAPTERS = (
    "tools.navmap.build_navmap",
    "tools.navmap.check_navmap",
    "tools.navmap.migrate_navmaps",
    "tools.navmap.repair_navmaps",
    "tools.navmap.strip_navmap_sections",
)

DOCBUILDER_EXCLUDES = {
    "tools.docstring_builder.cli",
    "tools.docstring_builder.orchestrator",
}


def _iter_module_names(package: str, exclude: Iterable[str]) -> list[str]:
    package_path = Path(__file__).resolve().parents[1] / package.replace(".", "/")
    excluded = set(exclude)
    modules: list[str] = []
    for entry in package_path.iterdir():
        if entry.name.startswith("__pycache__"):
            continue
        if entry.suffix == ".py" and entry.stem != "__init__":
            name = f"{package}.{entry.stem}"
        elif entry.is_dir() and (entry / "__init__.py").exists():
            name = f"{package}.{entry.name}"
        else:
            continue
        if name in excluded:
            continue
        modules.append(name)
    return sorted(modules)


def _format_layers_contract(slug: str, title: str, layers: Sequence[Sequence[str]]) -> str:
    lines = [f"[importlinter:contract:{slug}]", f"name = {title}", "type = layers", "layers ="]
    for layer in layers:
        joined = ", ".join(layer)
        lines.append(f"    {joined}")
    return "\n".join(lines)


def _format_forbid_contract(
    slug: str,
    title: str,
    modules: Sequence[str],
    forbidden: Sequence[str],
) -> str:
    lines = [
        f"[importlinter:contract:{slug}]",
        f"name = {title}",
        "type = forbid",
        "modules =",
    ]
    lines.extend(f"    {module}" for module in modules)
    lines.append("forbidden_modules =")
    lines.extend(f"    {entry}" for entry in forbidden)
    return "\n".join(lines)


def _build_template(root_package: str) -> str:
    """Build the import-linter configuration template.

    Parameters
    ----------
    root_package : str
        Root package name.

    Returns
    -------
    str
        Configuration file content.
    """
    docbuilder_domain = _iter_module_names("tools.docstring_builder", DOCBUILDER_EXCLUDES)
    docs_domain = _iter_module_names("tools.docs", DOCS_ADAPTERS)
    navmap_domain = _iter_module_names("tools.navmap", NAVMAP_ADAPTERS)

    layers_sections = [
        _format_layers_contract(
            "docstring_builder_layers",
            "tools.docstring_builder layering",
            [
                ("tools.docstring_builder.cli",),
                ("tools.docstring_builder.orchestrator",),
                tuple(docbuilder_domain),
                ("tools._shared",),
            ],
        ),
        _format_forbid_contract(
            "docstring_builder_adapters_no_shared",
            "Docstring builder adapters avoid shared internals",
            ("tools.docstring_builder.cli",),
            ("tools._shared",),
        ),
        _format_layers_contract(
            "docs_layers",
            "tools.docs layering",
            [
                DOCS_ADAPTERS,
                tuple(docs_domain),
                ("tools._shared",),
            ],
        ),
        _format_forbid_contract(
            "docs_adapters_no_shared",
            "Docs adapters avoid shared internals",
            DOCS_ADAPTERS,
            ("tools._shared",),
        ),
        _format_layers_contract(
            "navmap_layers",
            "tools.navmap layering",
            [
                NAVMAP_ADAPTERS,
                tuple(navmap_domain),
                ("tools._shared",),
            ],
        ),
        _format_forbid_contract(
            "navmap_adapters_no_shared",
            "Navmap adapters avoid shared internals",
            NAVMAP_ADAPTERS,
            ("tools._shared",),
        ),
    ]
    sections = [f"[importlinter]\nroot_package = {root_package}"]
    sections.extend(layers_sections)
    return "\n\n".join(sections).strip() + "\n"


def _import_detect_primary() -> str:
    """Resolve the primary package name using the detect_pkg helper.

    Returns
    -------
    str
        Primary package name.
    """
    return detect_primary()


def _run_importlinter(config_path: Path, cwd: Path) -> None:
    """Execute import-linter with the generated configuration."""
    command = [sys.executable, "-m", "importlinter", "--config", str(config_path)]
    LOGGER.info("Running import-linter: %s", " ".join(command))
    run_tool(command, cwd=cwd, check=True)


def main(
    *,
    root_package: str | None = None,
    output_path: Path | None = None,
    root_dir: Path | None = None,
    detect: Callable[[], str] | None = None,
    check: bool = False,
) -> Path:
    """Generate the import-linter configuration and optionally run the check.

    Parameters
    ----------
    root_package : str | None
        Root package name (None uses detection).
    output_path : Path | None
        Output file path (None uses default).
    root_dir : Path | None
        Root directory (None uses default).
    detect : Callable[[], str] | None
        Detection function (None uses default).
    check : bool
        Whether to run import-linter after generation.

    Returns
    -------
    Path
        Path to generated configuration file.
    """
    detected_root = root_dir or Path(__file__).resolve().parents[1]
    package = root_package or (detect or _import_detect_primary)()
    destination = Path(output_path) if output_path is not None else detected_root / ".importlinter"
    destination.write_text(_build_template(package), encoding="utf-8")
    LOGGER.info("Wrote import-linter configuration to %s", destination)
    if check:
        _run_importlinter(destination, detected_root)
    return destination


def _build_arg_parser() -> argparse.ArgumentParser:
    """Return the CLI parser for the import-linter generator.

    Returns
    -------
    argparse.ArgumentParser
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(
        description="Generate .importlinter contracts for tooling packages"
    )
    parser.add_argument("--root-package", dest="root_package", default="tools")
    parser.add_argument("--output", dest="output", type=Path)
    parser.add_argument("--root-dir", dest="root_dir", type=Path)
    parser.add_argument(
        "--check", action="store_true", help="Run import-linter after writing the config"
    )
    return parser


@dataclass(slots=True, frozen=True)
class ImportLinterArgs:
    """Typed CLI arguments for the import-linter generator."""

    root_package: str
    output: Path | None
    root_dir: Path | None
    check: bool


class _CLIArguments(argparse.Namespace):
    root_package: str
    output: Path | None
    root_dir: Path | None
    check: bool


def _parse_args(argv: Sequence[str] | None = None) -> ImportLinterArgs:
    """Return typed arguments parsed from ``argv``.

    Parameters
    ----------
    argv : Sequence[str] | None
        Command-line arguments (None uses sys.argv).

    Returns
    -------
    ImportLinterArgs
        Parsed arguments.
    """
    parser = _build_arg_parser()
    namespace = _CLIArguments()
    parser.parse_args(argv, namespace=namespace)
    return ImportLinterArgs(
        root_package=namespace.root_package,
        output=namespace.output,
        root_dir=namespace.root_dir,
        check=namespace.check,
    )


if __name__ == "__main__":
    arguments = _parse_args()
    main(
        root_package=arguments.root_package,
        output_path=arguments.output,
        root_dir=arguments.root_dir,
        check=arguments.check,
    )
