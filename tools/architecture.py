"""Architecture checks for the internal tooling package.

The tooling suite follows a layered structure where reusable domain helpers live
under ``tools._shared``; feature packages such as ``tools.navmap`` and
``tools.codemods`` adapt those helpers; and executable entry points (``tools/*.py``
and ``*.cli`` modules) form the outermost IO/CLI layer. This module provides
pytestarch-based helpers so both the CLI and the automated test suite can enforce
that layering discipline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from tools.types_facade import (
    get_evaluable_architecture,
    new_layered_architecture,
    new_module_name_filter,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from tools.types_facade import (
        EvaluableArchitecture,
        LayeredArchitectureProtocol,
    )

TOOLS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_ROOT.parent

DOMAIN_PATTERNS = (r"^kgfoundry\.tools\._shared(\..+)?$",)
ADAPTER_PATTERNS = (r"^kgfoundry\.tools\.(?:docs|navmap|codemods)(\..+)?$",)
CLI_PATTERNS = (
    r"^kgfoundry\.tools\.(?!(?:_shared|docs|navmap|codemods)$)[^.]+$",
    r"^kgfoundry\.tools\..*\.cli(\..+)?$",
)

ADAPTER_SUPPORT_MODULES = {
    "kgfoundry.tools.drift_preview",
    "kgfoundry.tools.griffe_utils",
    "kgfoundry.tools.stubs.drift_check",
}

ADAPTER_BASE_PACKAGES = {
    "kgfoundry.tools.codemods",
    "kgfoundry.tools.navmap",
}

CLI_SUPPORT_MODULES: set[str] = set()


@dataclass(frozen=True, slots=True)
class ArchitectureResult:
    """Outcome of the tooling architecture evaluation."""

    violations: tuple[str, ...]

    @property
    def is_success(self) -> bool:
        """Return ``True`` when no layering violations were detected."""
        return not self.violations

    def to_json(self) -> str:
        """Return a JSON representation of the architecture check result.

        Returns
        -------
        str
            JSON string representation.
        """
        payload: dict[str, object] = {"violations": list(self.violations)}
        return json.dumps(payload, indent=2)


def _match_modules(modules: Iterable[str], patterns: Sequence[str]) -> set[str]:
    """Return the subset of ``modules`` matching any of the provided regex ``patterns``.

    Parameters
    ----------
    modules : Iterable[str]
        Module names to match.
    patterns : Sequence[str]
        Regex patterns to match against.

    Returns
    -------
    set[str]
        Set of matching module names.
    """
    regexes = [re.compile(pattern) for pattern in patterns]
    return {module for module in modules if any(regex.match(module) for regex in regexes)}


def _build_layered_architecture(
    modules: Sequence[str],
) -> tuple[LayeredArchitectureProtocol, list[str], list[str], list[str]]:
    """Build the layered architecture and return the classified module groups.

    Parameters
    ----------
    modules : Sequence[str]
        Module names to classify.

    Returns
    -------
    tuple[LayeredArchitectureProtocol, list[str], list[str], list[str]]
        (architecture, domain_modules, adapter_modules, io_modules) tuple.
    """
    domain_modules = sorted(_match_modules(modules, DOMAIN_PATTERNS))

    cli_candidates = _match_modules(modules, CLI_PATTERNS)
    cli_candidates.difference_update(ADAPTER_SUPPORT_MODULES)
    cli_candidates.update(module for module in modules if module in CLI_SUPPORT_MODULES)

    adapter_candidates = _match_modules(modules, ADAPTER_PATTERNS)
    adapter_candidates.update(module for module in modules if module in ADAPTER_SUPPORT_MODULES)

    adapter_modules = sorted(adapter_candidates - set(domain_modules) - cli_candidates)
    adapter_modules = [module for module in adapter_modules if module not in ADAPTER_BASE_PACKAGES]
    io_modules = sorted(cli_candidates - set(domain_modules) - set(adapter_modules))

    architecture = new_layered_architecture()
    architecture.layer("domain").containing_modules(domain_modules)
    architecture.layer("adapters").containing_modules(adapter_modules)
    architecture.layer("io_cli").containing_modules(io_modules)
    return architecture, domain_modules, adapter_modules, io_modules


def _load_tooling_architecture(
    root: Path | None = None,
) -> tuple[
    LayeredArchitectureProtocol,
    list[str],
    list[str],
    list[str],
    EvaluableArchitecture,
]:
    project_root = root or REPO_ROOT
    evaluable = get_evaluable_architecture(
        str(project_root),
        str(project_root / "tools"),
    )
    architecture, domain_modules, adapter_modules, io_modules = _build_layered_architecture(
        tuple(evaluable.modules)
    )
    return architecture, domain_modules, adapter_modules, io_modules, evaluable


def _collect_violations(
    evaluable: EvaluableArchitecture,
    sources: Sequence[str],
    targets: Sequence[str],
    message: str,
) -> list[str]:
    if not sources or not targets:
        return []
    dependencies = evaluable.get_dependencies(
        [new_module_name_filter(module) for module in sources],
        [new_module_name_filter(module) for module in targets],
    )
    violations: list[str] = []
    for edges in dependencies.values():
        for importer, importee in edges:
            violations.append(f'{message}: "{importer.identifier}" imports "{importee.identifier}"')
    return violations


def enforce_tooling_layers(root: Path | None = None) -> ArchitectureResult:
    """Validate the domain → adapters → IO layering of the tooling package.

    Parameters
    ----------
    root : Path | None
        Project root path (defaults to REPO_ROOT).

    Returns
    -------
    ArchitectureResult
        Architecture check result with violations.
    """
    _, domain_modules, adapter_modules, io_modules, evaluable = _load_tooling_architecture(
        root=root
    )

    violations: list[str] = []
    violations.extend(
        _collect_violations(
            evaluable,
            domain_modules,
            adapter_modules,
            "domain must not import adapters",
        )
    )
    violations.extend(
        _collect_violations(
            evaluable,
            domain_modules,
            io_modules,
            "domain must not import IO/CLI",
        )
    )
    violations.extend(
        _collect_violations(
            evaluable,
            adapter_modules,
            io_modules,
            "adapters must not import IO/CLI",
        )
    )

    return ArchitectureResult(violations=tuple(sorted(set(violations))))
