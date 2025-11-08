"""Overview of build graphs.

This module bundles build graphs logic for the kgfoundry stack. It groups related helpers so
downstream packages can import a single cohesive namespace. Refer to the functions and classes below
for implementation specifics.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import warnings
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from kgfoundry_common.logging import setup_logging
from tools import (
    JsonValue,
    ToolExecutionError,
    ToolRunResult,
    ValidationError,
    get_logger,
    resolve_path,
    run_tool,
    with_fields,
)
from tools._shared.cli import (
    CliEnvelope,
    CliEnvelopeBuilder,
    CliErrorStatus,
    CliStatus,
    render_cli_envelope,
)
from tools._shared.logging import LoggerAdapter
from tools._shared.problem_details import (
    ProblemDetailsDict,
    ProblemDetailsParams,
    build_problem_details,
)
from tools.docs import cli_context as docs_cli_context
from tools.docs.errors import GraphBuildError


class GraphPolicyError(GraphBuildError):
    """Raised when dependency graph policy checks fail."""

    def __init__(self, message: str, *, errors: Sequence[str] | None = None) -> None:
        super().__init__(message)
        self.errors = list(errors or [])


if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

    import networkx as nx_mod
    import pydot as pydot_mod

    DiGraph = nx_mod.DiGraph[Any]
    PydotDot = pydot_mod.Dot
else:  # pragma: no cover - runtime fallback when optional deps missing
    DiGraph = Any
    PydotDot = Any

try:  # pragma: no cover - optional dependency
    from yaml import YAMLError as _YamlError
except (ModuleNotFoundError, ImportError):
    _YamlError = Exception


YamlError = _YamlError


def _optional_import(name: str) -> ModuleType | None:
    """Import module if available.

    Parameters
    ----------
    name : str
        Module name to import.

    Returns
    -------
    ModuleType | None
        Imported module | None if import fails.
    """
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


CYCLE_LIMIT_ENV = "GRAPH_CYCLE_LIMIT"
CYCLE_LENGTH_ENV = "GRAPH_CYCLE_LEN"
EDGE_BUDGET_ENV = "GRAPH_EDGE_BUDGET"
DEFAULT_EDGE_BUDGET = 50_000
EDGE_COMPONENTS = 2
SCC_SUMMARY_LIMIT = 10
SCC_MEMBER_PREVIEW = 20
LAYER_PALETTE: dict[str, str] = {
    "domain": "#2f855a",
    "application": "#3182ce",
    "interface": "#805ad5",
    "infra": "#dd6b20",
}
DEFAULT_LAYER_COLOR = "#718096"
DEFAULT_EDGE_COLOR = "#a0aec0"
CYCLE_EDGE_COLOR = "#e53e3e"
EDGE_HIGHLIGHT_WIDTH = "2.5"
EDGE_NORMAL_WIDTH = "1.2"
SUBPROCESS_TIMEOUT_SECONDS = 240.0

LayerConfig = Mapping[str, object]
AnalysisResult = dict[str, object]
CycleList = list[list[str]]


@dataclass(frozen=True)
class CacheContext:
    """Represent the cache state for a single package build."""

    used_cache: bool
    tree_hash: str | None
    bucket: Path | None


@dataclass(frozen=True)
class StagePaths:
    """File system paths used while staging package graph artifacts."""

    staging_dir: Path
    staged_imports: Path
    staged_uml: Path
    final_imports: Path
    final_uml: Path


@dataclass(frozen=True)
class PackageBuildConfig:
    """Configuration values required to render per-package graphs."""

    fmt: str
    excludes: tuple[str, ...]
    max_bacon: int
    cache_dir: Path
    use_cache: bool
    verbose: bool

    def excludes_list(self) -> list[str]:
        """Return a mutable copy of the package exclusion patterns.

        Returns
        -------
        list[str]
            List copy of exclusion patterns.
        """
        return list(self.excludes)


@dataclass(frozen=True)
class CycleConfig:
    """Configuration values governing cycle enumeration bounds."""

    limit: int
    length_bound: int
    edge_budget: int


@dataclass(frozen=True)
class RunInputs:
    """Normalized configuration derived from CLI arguments."""

    packages: tuple[str, ...]
    excludes: tuple[str, ...]
    cache_dir: Path
    use_cache: bool
    verbose: bool
    config: PackageBuildConfig


pydot: ModuleType | None = _optional_import("pydot")
nx: ModuleType | None = _optional_import("networkx")
yaml = _optional_import("yaml")


def _require_pydot() -> ModuleType:
    """Return the imported :mod:`pydot` module, raising if unavailable.

    Returns
    -------
    ModuleType
        Imported pydot module.

    Raises
    ------
    RuntimeError
        If pydot module is not available.
    """
    if pydot is None:
        message = "pydot is required for graph rendering"
        raise RuntimeError(message)
    return pydot


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
OUT = ROOT / "docs" / "_build" / "graphs"
OUT.mkdir(parents=True, exist_ok=True)

# Temporary workspace for graph builds to avoid clobbering finished outputs.
# Render targets supported by both Graphviz and our docs pipeline.
SUPPORTED_FORMATS: tuple[str, ...] = ("svg", "png")

CLI_COMMAND_NAME = "docs-build-graphs"
CLI_DEFINITION = docs_cli_context.get_cli_definition(CLI_COMMAND_NAME)
CLI_SETTINGS = docs_cli_context.get_cli_settings(CLI_COMMAND_NAME)
CLI_OPERATION_IDS = dict(CLI_DEFINITION.operation_ids)
CLI_INTERFACE_ID = CLI_DEFINITION.interface_id
CLI_COMMAND = CLI_DEFINITION.command
CLI_TITLE = CLI_DEFINITION.title
SUBCOMMAND_BUILD_GRAPHS = "build"
CLI_OPERATION_ID = CLI_OPERATION_IDS[SUBCOMMAND_BUILD_GRAPHS]
CLI_PROBLEM_TYPE = "https://kgfoundry.dev/problems/docs/build-graphs"
CLI_ENVELOPE_DIR = docs_cli_context.REPO_ROOT / "site" / "_build" / "cli"


def __getattr__(name: str) -> object:
    if name == "CLI_CONFIG":
        context_module = importlib.import_module("docs._scripts.cli_context")
        return context_module.get_cli_config(CLI_COMMAND_NAME)
    message = f"module 'tools.docs.build_graphs' has no attribute {name!r}"
    raise AttributeError(message)


def _prepare_run_inputs(args: argparse.Namespace) -> RunInputs:
    packages = tuple(_resolve_packages(args))
    excludes = tuple(args.exclude or ["tests/.*", "site/.*"])
    cache_dir, use_cache = _prepare_cache(args)
    _log_configuration(
        verbose=args.verbose,
        packages=packages,
        cache_dir=cache_dir,
        use_cache=use_cache,
    )
    config = PackageBuildConfig(
        fmt=args.format,
        excludes=excludes,
        max_bacon=args.max_bacon,
        cache_dir=cache_dir,
        use_cache=use_cache,
        verbose=args.verbose,
    )
    return RunInputs(
        packages=packages,
        excludes=excludes,
        cache_dir=cache_dir,
        use_cache=use_cache,
        verbose=args.verbose,
        config=config,
    )


warnings.filterwarnings(
    "ignore",
    category=SyntaxWarning,
    module=r"pyserini\.trectools\._base",
)

_PYTHONWARNINGS = "PYTHONWARNINGS"
_PYSERINI_WARNING = "ignore::SyntaxWarning:pyserini.trectools._base"

# Ensure child interpreters (pydeps/pyreverse) inherit the targeted suppression.
if os.environ.get(_PYTHONWARNINGS):
    os.environ[_PYTHONWARNINGS] = ",".join(
        [os.environ[_PYTHONWARNINGS], _PYSERINI_WARNING],
    )
else:
    os.environ[_PYTHONWARNINGS] = _PYSERINI_WARNING


def _coerce_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_coerce_json_value(item) for item in value]
    if isinstance(value, set):
        return [_coerce_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _coerce_json_value(val) for key, val in value.items()}
    return str(value)


def _prepare_extensions(values: Mapping[str, object] | None = None) -> dict[str, JsonValue]:
    if not values:
        return {}
    return {str(key): _coerce_json_value(val) for key, val in values.items()}


@dataclass(slots=True, frozen=True)
class _CommandContext:
    args: argparse.Namespace
    correlation_id: str
    logger: LoggerAdapter
    builder: CliEnvelopeBuilder
    start: float

    def elapsed(self) -> float:
        return time.monotonic() - self.start

    def extensions(self, extras: Mapping[str, object] | None = None) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {
            "operation_id": CLI_OPERATION_ID,
            "correlation_id": self.correlation_id,
        }
        if extras:
            payload.update(_prepare_extensions(extras))
        return payload


def _envelope_path(subcommand: str) -> Path:
    safe_subcommand = subcommand or "root"
    filename = f"{CLI_SETTINGS.bin_name}-{CLI_COMMAND}-{safe_subcommand}.json"
    return CLI_ENVELOPE_DIR / filename


def _emit_envelope(envelope: CliEnvelope, *, logger: LoggerAdapter, subcommand: str) -> Path:
    path = _envelope_path(subcommand)
    CLI_ENVELOPE_DIR.mkdir(parents=True, exist_ok=True)
    rendered = render_cli_envelope(envelope)
    path.write_text(rendered + "\n", encoding="utf-8")
    logger.debug(
        "CLI envelope written",
        extra={"status": envelope.status, "cli_envelope": str(path)},
    )
    return path


def _run_status_from_error(error_status: CliErrorStatus) -> CliStatus:
    return cast("CliStatus", error_status if error_status in {"config", "violation"} else "error")


def _build_problem(
    context: _CommandContext,
    *,
    detail: str,
    status: int,
    extras: Mapping[str, object] | None = None,
) -> ProblemDetailsDict:
    return build_problem_details(
        ProblemDetailsParams(
            type=CLI_PROBLEM_TYPE,
            title=f"{CLI_TITLE} command failed",
            status=status,
            detail=detail,
            instance=f"urn:cli:{CLI_INTERFACE_ID}:{SUBCOMMAND_BUILD_GRAPHS}",
            extensions=context.extensions(extras),
        )
    )


@dataclass(slots=True, frozen=True)
class _FailureOptions:
    extras: Mapping[str, object] | None = None
    exc: BaseException | None = None


def _record_failure(
    context: _CommandContext,
    *,
    detail: str,
    status: int,
    error_status: CliErrorStatus,
    options: _FailureOptions | None = None,
) -> int:
    failure_extras = options.extras if options else None
    exc = options.exc if options else None
    problem = _build_problem(context, detail=detail, status=status, extras=failure_extras)
    builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND,
        status=_run_status_from_error(error_status),
        subcommand=SUBCOMMAND_BUILD_GRAPHS,
    )
    builder.add_error(status=error_status, message=detail, problem=problem)
    builder.set_problem(problem)
    envelope = builder.finish(duration_seconds=context.elapsed())
    path = _emit_envelope(envelope, logger=context.logger, subcommand=SUBCOMMAND_BUILD_GRAPHS)
    log_extra: dict[str, JsonValue] = {
        "status": envelope.status,
        "cli_envelope": str(path),
        "duration_seconds": envelope.duration_seconds,
    }
    if failure_extras:
        log_extra.update(context.extensions(failure_extras))
    context.logger.error("Command failed", extra=log_extra, exc_info=exc)
    sys.stderr.write(detail + "\n")
    return 2 if error_status in {"config", "violation"} else 1


def _finish_success(context: _CommandContext, summary: Mapping[str, object]) -> int:
    builder = context.builder
    builder.add_file(
        path=str(OUT),
        status="success",
        message="Documentation dependency graphs generated",
    )
    builder.add_file(
        path=str(OUT / "graph_meta.json"),
        status="success",
        message="Global graph metadata summary",
    )
    builder.add_file(
        path=str(OUT / f"subsystems.{context.args.format}"),
        status="success",
        message="Subsystem dependency graph",
    )
    envelope = builder.finish(duration_seconds=context.elapsed())
    path = _emit_envelope(envelope, logger=context.logger, subcommand=SUBCOMMAND_BUILD_GRAPHS)
    log_extra: dict[str, JsonValue] = {
        "status": envelope.status,
        "cli_envelope": str(path),
        "duration_seconds": envelope.duration_seconds,
    }
    log_extra.update(_prepare_extensions(summary))
    context.logger.info("Command completed", extra=log_extra)
    return 0


def _start_command(args: argparse.Namespace) -> _CommandContext:
    correlation_id = uuid4().hex
    logger = with_fields(
        LOGGER,
        command=CLI_COMMAND,
        subcommand=SUBCOMMAND_BUILD_GRAPHS,
        correlation_id=correlation_id,
        format=args.format,
        packages=args.packages,
        max_workers=args.max_workers,
    )
    logger.info("Command started", extra={"status": "start"})
    builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND,
        status=cast("CliStatus", "success"),
        subcommand=SUBCOMMAND_BUILD_GRAPHS,
    )
    return _CommandContext(
        args=args,
        correlation_id=correlation_id,
        logger=logger,
        builder=builder,
        start=time.monotonic(),
    )


# Defaults / policy files
LAYER_FILE = ROOT / "docs" / "policies" / "layers.yml"
ALLOW_FILE = ROOT / "docs" / "policies" / "graph_allowlist.json"

# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Compute parse args.

    Carry out the parse args operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Command-line arguments to parse. When ``None``, uses ``sys.argv``.

    Returns
    -------
    argparse.Namespace
        Description of return value.

    Examples
    --------
    >>> from tools.docs.build_graphs import parse_args
    >>> result = parse_args()
    >>> result  # doctest: +ELLIPSIS
    """
    p = argparse.ArgumentParser(
        description="Build per-package and cross-subsystem graphs with policy checks."
    )
    p.add_argument(
        "--packages",
        default=os.getenv("DOCS_PKG", ""),
        help="Comma-separated top-level packages (default: auto-detect under src/)",
    )
    p.add_argument(
        "--format",
        default=os.getenv("GRAPH_FORMAT", "svg"),
        choices=list(SUPPORTED_FORMATS),
        help="Image format for rendered graphs (svg or png)",
    )
    p.add_argument(
        "--max-bacon",
        type=int,
        default=int(os.getenv("GRAPH_MAX_BACON", "4")),
        help="pydeps --max-bacon (default: 4)",
    )
    p.add_argument(
        "--exclude",
        action="append",
        default=None,
        help="Regex/pattern to exclude in pydeps (repeatable)",
    )
    p.add_argument(
        "--layers",
        default=str(LAYER_FILE),
        help="Path to layers.yml (layer names & package mapping)",
    )
    p.add_argument(
        "--allowlist", default=str(ALLOW_FILE), help="Path to graph allowlist (cycles/edges)"
    )
    p.add_argument(
        "--fail-on-cycles",
        action="store_true",
        default=os.getenv("GRAPH_FAIL_ON_CYCLES", "1") == "1",
        help="Fail when new cycles (not allowlisted) are found (default: on)",
    )
    p.add_argument(
        "--fail-on-layer-violations",
        action="store_true",
        default=os.getenv("GRAPH_FAIL_ON_LAYER", "1") == "1",
        help="Fail on forbidden cross-layer edges (default: on)",
    )
    # NEW: parallel + cache knobs
    p.add_argument(
        "--max-workers",
        type=int,
        default=int(os.getenv("GRAPH_MAX_WORKERS", "0")),  # 0 => auto (cpu_count)
        help="Maximum parallel workers for per-package builds (default: CPU count)",
    )
    p.add_argument(
        "--cache-dir",
        default=os.getenv("GRAPH_CACHE_DIR", str(ROOT / ".cache" / "graphs")),
        help="Directory for per-package graph cache",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable cache (always rebuild per-package graphs)",
    )
    p.add_argument("--verbose", action="store_true", help="Verbose logging")
    return p.parse_args(argv)


# --------------------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------------------


LOGGER = get_logger(__name__)


def sh(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    timeout: float = SUBPROCESS_TIMEOUT_SECONDS,
) -> ToolRunResult:
    """Run a subprocess command using secure run_tool wrapper.

    Parameters
    ----------
    cmd : list[str]
        Command to execute.
    cwd : Path | None, optional
        Working directory for the command. Keyword-only argument.
    check : bool, optional
        If True, raise on non-zero exit code. Keyword-only argument.
    timeout : float, optional
        Timeout in seconds (default 30.0 for graphviz commands). Keyword-only argument.

    Returns
    -------
    ToolRunResult
        Completed process result.

    Raises
    ------
    GraphBuildError
        If command fails and check is True.
    """
    log_adapter = with_fields(LOGGER, command=cmd, cwd=str(cwd) if cwd else None)
    try:
        result = run_tool(cmd, timeout=timeout, cwd=cwd)
    except ToolExecutionError as exc:
        if check:
            log_adapter.exception("Subprocess command failed")
            message = f"Command '{cmd[0]}' failed"
            raise GraphBuildError(message) from exc
        # Return a ToolRunResult-like object for non-check mode
        return ToolRunResult(
            command=tuple(cmd),
            returncode=1,
            stdout="",
            stderr=str(exc),
            duration_seconds=0.0,
            timed_out=False,
        )
    if check and result.returncode != 0:
        log_adapter.error("Command returned non-zero exit code: %s", result.returncode)
        message = f"Command '{cmd[0]}' returned exit code {result.returncode}"
        raise GraphBuildError(message)
    return result


def ensure_bin(name: str) -> None:
    """Ensure executable is available on PATH.

    Parameters
    ----------
    name : str
        Executable name to check.

    Raises
    ------
    GraphBuildError
        If executable is not found.
    """
    if not shutil.which(name):
        logger = get_logger(__name__)
        logger.error("Missing required executable on PATH: %s", name)
        message = f"Missing required executable on PATH: {name}"
        raise GraphBuildError(message)


def find_top_packages() -> list[str]:
    """Compute find top packages.

    Carry out the find top packages operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Returns
    -------
    list[str]
        Description of return value.

    Examples
    --------
    >>> from tools.docs.build_graphs import find_top_packages
    >>> result = find_top_packages()
    >>> result  # doctest: +ELLIPSIS
    """
    # Top-level packages are directories under src/ that contain __init__.py
    if not SRC.exists():
        return []
    return sorted(
        child.name for child in SRC.iterdir() if child.is_dir() and (child / "__init__.py").exists()
    )


def _rel(p: Path) -> str:
    """Return ``p`` relative to the repository root when possible.

    Parameters
    ----------
    p : Path
        Path to convert.

    Returns
    -------
    str
        Relative path string, or absolute path if not relative to root.
    """
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


# --------------------------------------------------------------------------------------
# Per-package renderers (pydeps & pyreverse)
# --------------------------------------------------------------------------------------


def build_pydeps_for_package(
    pkg: str, out_svg: Path, excludes: list[str], max_bacon: int, fmt: str
) -> None:
    """Compute build pydeps for package.

    Carry out the build pydeps for package operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Parameters
    ----------
    pkg : str
        Description for ``pkg``.
    out_svg : Path
        Description for ``out_svg``.
    excludes : list[str]
        Description for ``excludes``.
    max_bacon : int
        Description for ``max_bacon``.
    fmt : str
        Description for ``fmt``.

    Examples
    --------
    >>> from tools.docs.build_graphs import build_pydeps_for_package
    >>> build_pydeps_for_package(..., ..., ..., ..., ...)  # doctest: +ELLIPSIS
    """
    with NamedTemporaryFile(suffix=".dot", delete=False) as dot_file:
        dot_target = Path(dot_file.name)
    cmd = [
        sys.executable,
        "-m",
        "pydeps",
        f"src/{pkg}",
        "--noshow",
        "--show-dot",
        "--dot-output",
        str(dot_target),
        "--max-bacon",
        str(max_bacon),
        "-T",
        "dot",
        "--no-output",
    ]
    for pat in excludes:
        cmd += ["-x", pat]
    sh(cmd, cwd=ROOT)
    try:
        fallback_dot = ROOT / f"src_{pkg}.dot"
        if not dot_target.exists() and fallback_dot.exists():
            fallback_dot.replace(dot_target)
        for leftover in ROOT.glob(f"src_{pkg}*.dot"):
            if leftover.exists():
                leftover.unlink()
        # Render to final image via graphviz (dot)
        out_svg.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(suffix=out_svg.suffix, delete=False) as tmp:
            temp_output = Path(tmp.name)
        try:
            sh(["dot", f"-T{fmt}", str(dot_target), "-o", str(temp_output)], cwd=ROOT)
            temp_output.replace(out_svg)
        finally:
            temp_output.unlink(missing_ok=True)
    finally:
        dot_target.unlink(missing_ok=True)


def build_pyreverse_for_package(pkg: str, out_dir: Path, fmt: str) -> None:
    """Compute build pyreverse for package.

    Carry out the build pyreverse for package operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Parameters
    ----------
    pkg : str
        Description for ``pkg``.
    out_dir : Path
        Description for ``out_dir``.
    fmt : str
        Description for ``fmt``.

    Examples
    --------
    >>> from tools.docs.build_graphs import build_pyreverse_for_package
    >>> build_pyreverse_for_package(..., ..., ...)  # doctest: +ELLIPSIS
    """
    # classes_<project>.dot is named by -p <project>; use the package name to get unique names.
    out_dir.mkdir(parents=True, exist_ok=True)
    sh(
        [
            "pyreverse",
            f"src/{pkg}",
            "-o",
            "dot",
            "-p",
            pkg,
            "-d",
            str(out_dir),
        ],
        cwd=ROOT,
    )

    classes_dot = out_dir / f"classes_{pkg}.dot"
    packages_dot = out_dir / f"packages_{pkg}.dot"
    output_path = out_dir / f"{pkg}-uml.{fmt}"
    if classes_dot.exists():
        sh(["dot", f"-T{fmt}", str(classes_dot), "-o", str(output_path)], cwd=ROOT)

    # Cleanup intermediate dot files from both the build directory and repo root
    for dot_path in (classes_dot, packages_dot):
        if dot_path.exists():
            dot_path.unlink()

    for root_dot in (
        ROOT / f"classes_{pkg}.dot",
        ROOT / f"packages_{pkg}.dot",
    ):
        if root_dot.exists():
            root_dot.unlink()


# --------------------------------------------------------------------------------------
# Global graph (collapsed to packages)
# --------------------------------------------------------------------------------------


def _pkg_of(dotted: str) -> str:
    """Return the top-level package segment from a dotted module path.

    Parameters
    ----------
    dotted : str
        Dotted module path.

    Returns
    -------
    str
        Top-level package name.
    """
    head, *_rest = dotted.split(".", 1)
    if head == "src" and "." in dotted:
        return dotted.split(".", 2)[1]
    return head


def _module_label(node: object, data: Mapping[str, object]) -> str:
    """Normalize the label associated with a pydeps node.

    Parameters
    ----------
    node : object
        Graph node.
    data : Mapping[str, object]
        Node data dictionary.

    Returns
    -------
    str
        Normalized label string.
    """
    label = data.get("label")
    if label is None:
        return str(node)
    raw = str(label).strip('"')
    normalized = raw.replace(r"\n", "\n").replace(r"\.", ".").replace(r"\\", "\\")
    return normalized.replace("\n", "")


def _coerce_sequence(value: object) -> list[str]:
    """Coerce sequence.

    Parameters
    ----------
    value : object
        Value to coerce.

    Returns
    -------
    list[str]
        List of string items if value is a sequence, otherwise empty list.
    """
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value]
    return []


def _coerce_mapping(value: object) -> dict[str, str]:
    """Coerce mapping.

    Parameters
    ----------
    value : object
        Value to coerce.

    Returns
    -------
    dict[str, str]
        Dictionary mapping if value is a mapping, otherwise empty dict.
    """
    if isinstance(value, Mapping):
        return {str(key): str(val) for key, val in value.items()}
    return {}


def _allow_outward_rule(layers: LayerConfig) -> bool:
    """Allow outward rule.

    Parameters
    ----------
    layers : LayerConfig
        Layer configuration.

    Returns
    -------
    bool
        True if outward edges are allowed, False otherwise.
    """
    rules = layers.get("rules")
    if not isinstance(rules, Mapping):
        return False
    return bool(rules.get("allow_outward", False))


def _env_int(name: str, default: int) -> int:
    """Env int.

    Parameters
    ----------
    name : str
        Environment variable name.
    default : int
        Default value if variable is missing or invalid.

    Returns
    -------
    int
        Integer value from environment or default.
    """
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _cycle_config() -> CycleConfig:
    """Return cycle enumeration configuration derived from the environment.

    Returns
    -------
    CycleConfig
        Cycle configuration with limits and budget from environment.
    """
    return CycleConfig(
        limit=_env_int(CYCLE_LIMIT_ENV, 0),
        length_bound=_env_int(CYCLE_LENGTH_ENV, 0),
        edge_budget=_env_int(EDGE_BUDGET_ENV, DEFAULT_EDGE_BUDGET),
    )


def _centrality_threshold(centrality: Mapping[str, float], fraction: float) -> float:
    """Return the value at ``fraction`` of the sorted centrality scores.

    Parameters
    ----------
    centrality : Mapping[str, float]
        Centrality scores mapping.
    fraction : float
        Fraction of sorted values (0-1).

    Returns
    -------
    float
        Threshold value at the specified fraction.
    """
    values = sorted(centrality.values())
    if not values:
        return 0.0
    index = min(len(values) - 1, int(fraction * len(values)))
    return values[index]


def _extract_cycle_edges(cycles: CycleList) -> set[tuple[str, str]]:
    """Return directed edges participating in enumerated cycles.

    Parameters
    ----------
    cycles : CycleList
        List of cycle node lists.

    Returns
    -------
    set[tuple[str, str]]
        Set of (source, target) edge tuples.
    """
    edges: set[tuple[str, str]] = set()
    for cycle in cycles:
        for idx, node in enumerate(cycle):
            next_node = cycle[(idx + 1) % len(cycle)]
            edges.add((node, next_node))
    return edges


def _add_graph_nodes(
    dot_graph: PydotDot,
    graph: DiGraph,
    pkg2layer: Mapping[str, str],
    centrality: Mapping[str, float],
    threshold: float,
) -> None:
    """Populate ``dot_graph`` with styled nodes extracted from ``graph``."""
    pydot_module = _require_pydot()
    for node in sorted(graph.nodes()):
        layer = pkg2layer.get(node, "unknown")
        color = LAYER_PALETTE.get(layer, DEFAULT_LAYER_COLOR)
        penwidth = (
            EDGE_HIGHLIGHT_WIDTH if centrality.get(node, 0.0) >= threshold else EDGE_NORMAL_WIDTH
        )
        dot_graph.add_node(
            pydot_module.Node(
                node,
                color=color,
                penwidth=penwidth,
                style="bold",
                fontcolor="#1a202c",
            )
        )


def _add_graph_edges(
    dot_graph: PydotDot,
    graph: DiGraph,
    pkg2layer: Mapping[str, str],
    cycle_edges: set[tuple[str, str]],
) -> None:
    """Populate ``dot_graph`` with styled edges extracted from ``graph``."""
    pydot_module = _require_pydot()
    for src, dst, _ in graph.edges(data=True):
        layer_u = pkg2layer.get(src, "unknown")
        layer_v = pkg2layer.get(dst, "unknown")
        in_cycle = (src, dst) in cycle_edges
        edge_color = CYCLE_EDGE_COLOR if in_cycle else DEFAULT_EDGE_COLOR
        penwidth = EDGE_HIGHLIGHT_WIDTH if in_cycle else EDGE_NORMAL_WIDTH
        label = f"{layer_u}→{layer_v}" if layer_u != layer_v else ""
        dot_graph.add_edge(
            pydot_module.Edge(
                src, dst, color=edge_color, penwidth=penwidth, fontsize="8", label=label
            )
        )


def _rank_map(order: Sequence[str]) -> dict[str, int]:
    """Rank map.

    Parameters
    ----------
    order : Sequence[str]
        Layer names in order.

    Returns
    -------
    dict[str, int]
        Mapping of layer name to rank (0-indexed).
    """
    return {name: idx for idx, name in enumerate(order)}


def _prune_outward_edges(
    graph: DiGraph,
    pkg2layer: Mapping[str, str],
    layer_rank: Mapping[str, int],
    *,
    allow_outward: bool,
) -> DiGraph:
    """Prune outward edges.

    Parameters
    ----------
    graph : DiGraph
        Graph to prune.
    pkg2layer : Mapping[str, str]
        Package to layer mapping.
    layer_rank : Mapping[str, int]
        Layer rank mapping.
    allow_outward : bool
        Whether to allow outward edges.

    Returns
    -------
    DiGraph
        Pruned graph.
    """
    if allow_outward:
        return graph.copy()
    pruned = graph.copy()
    edges_to_remove = []
    for src, dst in graph.edges():
        src_layer = pkg2layer.get(src)
        dst_layer = pkg2layer.get(dst)
        if (
            src_layer is not None
            and dst_layer is not None
            and src_layer in layer_rank
            and dst_layer in layer_rank
            and layer_rank[dst_layer] > layer_rank[src_layer]
        ):
            edges_to_remove.append((src, dst))
    if edges_to_remove:
        pruned.remove_edges_from(edges_to_remove)
    return pruned


def _cycle_generator(graph: DiGraph, length_bound: int) -> Iterator[list[str]]:
    """Cycle generator.

    Parameters
    ----------
    graph : DiGraph
        Graph to enumerate cycles in.
    length_bound : int
        Maximum cycle length (0 for no bound).

    Returns
    -------
    Iterator[list[str]]
        Iterator over cycle node lists.
    """
    if nx is None:
        return iter(())
    if length_bound > 0:
        try:
            return cast("Iterator[list[str]]", nx.simple_cycles(graph, length_bound=length_bound))
        except TypeError:
            pass
    return cast("Iterator[list[str]]", nx.simple_cycles(graph))


def _enumerate_cycles(
    pruned_graph: DiGraph,
    cycle_limit: int,
    length_bound: int,
    edge_budget: int,
    scc_graph: DiGraph,
) -> tuple[CycleList, bool, list[dict[str, object]]]:
    """Enumerate cycles.

    Parameters
    ----------
    pruned_graph : DiGraph
        Pruned graph to enumerate cycles in.
    cycle_limit : int
        Maximum number of cycles to enumerate (0 for unlimited).
    length_bound : int
        Maximum cycle length (0 for no bound).
    edge_budget : int
        Maximum edges before skipping enumeration.
    scc_graph : DiGraph
        Strongly connected components graph.

    Returns
    -------
    tuple[CycleList, bool, list[dict[str, object]]]
        (cycles, skipped, scc_summary) tuple.
    """
    generator = _cycle_generator(pruned_graph, length_bound)
    if cycle_limit > 0:
        cycles: CycleList = []
        for idx, cycle in enumerate(generator, 1):
            cycles.append(cycle)
            if idx >= cycle_limit:
                break
        return cycles, False, []

    if pruned_graph.number_of_edges() > edge_budget:
        if nx is None:
            return (
                [],
                True,
                [
                    {
                        "members": [],
                        "size": 0,
                        "truncated": False,
                        "has_cycle": False,
                    }
                ],
            )
        components = sorted(
            (sorted(component) for component in nx.strongly_connected_components(scc_graph)),
            key=len,
            reverse=True,
        )
        summary: list[dict[str, object]] = []
        for members in components[:SCC_SUMMARY_LIMIT]:
            truncated = len(members) > SCC_MEMBER_PREVIEW
            preview = members if not truncated else [*members[:SCC_MEMBER_PREVIEW], "..."]
            summary.append(
                {
                    "members": preview,
                    "size": len(members),
                    "truncated": truncated,
                    "has_cycle": len(members) > 1,
                }
            )
        if not summary:
            summary.append(
                {
                    "members": [],
                    "size": 0,
                    "truncated": False,
                    "has_cycle": False,
                }
            )
        return [], True, summary

    return list(generator), False, []


def _collect_layer_violations(
    graph: DiGraph,
    layer_rank: Mapping[str, int],
    pkg2layer: Mapping[str, str],
    *,
    allow_outward: bool,
) -> CycleList:
    """Collect layer violations.

    Parameters
    ----------
    graph : DiGraph
        Graph to check.
    layer_rank : Mapping[str, int]
        Layer rank mapping.
    pkg2layer : Mapping[str, str]
        Package to layer mapping.
    allow_outward : bool
        Whether to allow outward edges.

    Returns
    -------
    CycleList
        List of violation records.
    """
    if allow_outward:
        return []
    violations: CycleList = []
    for src, dst in graph.edges():
        src_layer = pkg2layer.get(src)
        dst_layer = pkg2layer.get(dst)
        if (
            src_layer is not None
            and dst_layer is not None
            and src_layer in layer_rank
            and dst_layer in layer_rank
            and layer_rank[dst_layer] > layer_rank[src_layer]
        ):
            violations.append([src_layer, dst_layer, f"edge:{src}->{dst}"])
    return violations


def _degree_centrality(graph: DiGraph) -> dict[str, float]:
    """Degree centrality.

    Parameters
    ----------
    graph : DiGraph
        Graph to compute centrality for.

    Returns
    -------
    dict[str, float]
        Node to centrality score mapping (empty if networkx unavailable or graph empty).
    """
    if nx is None or graph.number_of_nodes() == 0:
        return {}
    return cast("dict[str, float]", nx.degree_centrality(graph))


def _sequence_of_sequences(value: object) -> list[list[str]]:
    """Sequence of sequences.

    Parameters
    ----------
    value : object
        Value to coerce.

    Returns
    -------
    list[list[str]]
        List of string lists (empty if value is not a sequence of sequences).
    """
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [
        [str(item) for item in entry]
        for entry in value
        if isinstance(entry, Sequence) and not isinstance(entry, (str, bytes))
    ]


def _edge_from_violation(record: Sequence[str]) -> tuple[str, str] | None:
    """Edge from violation.

    Parameters
    ----------
    record : Sequence[str]
        Violation record.

    Returns
    -------
    tuple[str, str] | None
        (source, target) edge tuple if parseable, otherwise None.
    """
    if not record:
        return None
    edge_marker = record[-1].split("edge:")[-1]
    parts = edge_marker.split("->")
    if len(parts) != EDGE_COMPONENTS:
        return None
    return parts[0], parts[1]


def build_global_pydeps(dot_out: Path, excludes: list[str], max_bacon: int) -> None:
    """Compute build global pydeps.

    Carry out the build global pydeps operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Parameters
    ----------
    dot_out : Path
        Description for ``dot_out``.
    excludes : list[str]
        Description for ``excludes``.
    max_bacon : int
        Description for ``max_bacon``.

    Examples
    --------
    >>> from tools.docs.build_graphs import build_global_pydeps
    >>> build_global_pydeps(..., ..., ...)  # doctest: +ELLIPSIS
    """
    dot_out.parent.mkdir(parents=True, exist_ok=True)
    dot_target = dot_out if dot_out.is_absolute() else dot_out.resolve()

    cmd = [
        sys.executable,
        "-m",
        "pydeps",
        "src",
        "--noshow",
        "--show-dot",
        "--dot-output",
        str(dot_target),
        "--max-bacon",
        str(max_bacon),
        "-T",
        "dot",
        "--no-output",
    ]
    # optional: limit depth & drop hubs
    noise = os.getenv("GRAPH_NOISE_LEVEL")
    if noise:
        cmd += ["--noise-level", noise]
    mdepth = os.getenv("GRAPH_MAX_MODULE_DEPTH")
    if mdepth:
        cmd += ["--max-module-depth", mdepth]
    for pat in excludes:
        cmd += ["-x", pat]
    sh(cmd, cwd=ROOT)

    # Newer pydeps releases still emit src*.dot files in the repository root; prefer the
    # explicitly requested location and clean up any temporary artifacts.
    fallback_dot = ROOT / "src.dot"
    if not dot_target.exists() and fallback_dot.exists():
        fallback_dot.replace(dot_target)
    for leftover in ROOT.glob("src*.dot"):
        if leftover.exists():
            leftover.unlink()


def collapse_to_packages(dot_path: Path) -> DiGraph:
    """Load a pydeps graph and collapse modules into package-level edges.

    Parameters
    ----------
    dot_path : Path
        Path to DOT file.

    Returns
    -------
    DiGraph
        Collapsed graph with package-level nodes and weighted edges.

    Raises
    ------
    RuntimeError
        If networkx or pydot are not available.
    """
    if nx is None or pydot is None:
        message = "networkx and pydot are required to collapse graphs"
        raise RuntimeError(message)

    graphs = pydot.graph_from_dot_file(str(dot_path))
    pd_obj = graphs[0] if isinstance(graphs, list) else graphs
    pd_graph = cast("PydotDot", pd_obj)
    directed = cast("DiGraph", nx.drawing.nx_pydot.from_pydot(pd_graph).to_directed())
    collapsed: DiGraph = cast("DiGraph", nx.DiGraph())

    module_names = {node: _module_label(node, data) for node, data in directed.nodes(data=True)}

    package_nodes = {_pkg_of(name) for name in module_names.values()}
    collapsed.add_nodes_from(sorted(package_nodes))

    for source, target in directed.edges():
        pkg_src = _pkg_of(module_names.get(source, str(source)))
        pkg_dst = _pkg_of(module_names.get(target, str(target)))
        if pkg_src == pkg_dst:
            continue
        raw_weight = collapsed.get_edge_data(pkg_src, pkg_dst, {}).get("weight", 0)
        existing_weight = int(raw_weight) if isinstance(raw_weight, (int, float)) else 0
        weight = existing_weight + 1
        collapsed.add_edge(pkg_src, pkg_dst, weight=weight)
    return collapsed


def analyze_graph(graph: DiGraph, layers: LayerConfig) -> AnalysisResult:
    """Analyse a collapsed dependency graph and surface policy signals.

    Parameters
    ----------
    graph : DiGraph
        Collapsed package dependency graph.
    layers : LayerConfig
        Layer configuration mapping.

    Returns
    -------
    AnalysisResult
        Dictionary with cycle analysis, SCC summary, and policy signals.

    Raises
    ------
    RuntimeError
        If networkx is not available.
    """
    if nx is None:
        message = "networkx is required for graph analysis"
        raise RuntimeError(message)

    order = _coerce_sequence(layers.get("order"))
    pkg2layer = _coerce_mapping(layers.get("packages"))
    allow_outward = _allow_outward_rule(layers)
    rank = _rank_map(order)

    pruned = _prune_outward_edges(graph, pkg2layer, rank, allow_outward=allow_outward)
    cycle_config = _cycle_config()

    cycles, skipped, scc_summary = _enumerate_cycles(
        pruned,
        cycle_config.limit,
        cycle_config.length_bound,
        cycle_config.edge_budget,
        graph,
    )

    if skipped:
        centrality = _degree_centrality(pruned)
        violations: CycleList = []
    else:
        centrality = _degree_centrality(graph)
        violations = _collect_layer_violations(
            graph,
            rank,
            pkg2layer,
            allow_outward=allow_outward,
        )

    result: AnalysisResult = {
        "cycles": cycles,
        "centrality": centrality,
        "layer_violations": violations,
        "cycle_enumeration_skipped": skipped,
    }
    if scc_summary:
        result["scc_summary"] = scc_summary
    return result


def style_and_render(
    graph: DiGraph,
    layers: LayerConfig,
    analysis: Mapping[str, object],
    out_svg: Path,
    fmt: str = "svg",
) -> None:
    """Render the collapsed graph with styling derived from analysis metadata.

    Parameters
    ----------
    graph : DiGraph
        Directed dependency graph collapsed to packages.
    layers : LayerConfig
        Layer configuration describing allowed dependencies.
    analysis : Mapping[str, object]
        Precomputed metrics produced by :func:`analyze_graph`.
    out_svg : Path
        Destination path for the rendered image.
    fmt : str, optional
        Rendering format (``"svg"`` or ``"png"``) (default: "svg").
    """
    pydot_module = _require_pydot()
    pkg2layer = _coerce_mapping(layers.get("packages"))
    centrality = cast("dict[str, float]", analysis.get("centrality", {}))
    threshold = _centrality_threshold(centrality, 0.80)
    cycle_edges = _extract_cycle_edges(cast("CycleList", analysis.get("cycles", [])))

    dot_graph: PydotDot = pydot_module.Dot(graph_type="digraph", rankdir="LR")
    _add_graph_nodes(dot_graph, graph, pkg2layer, centrality, threshold)
    _add_graph_edges(dot_graph, graph, pkg2layer, cycle_edges)

    renderer = cast("Any", dot_graph)
    payload = renderer.create_svg() if fmt == "svg" else renderer.create_png()
    out_svg.write_bytes(payload)


def write_meta(meta: Mapping[str, object], out_json: Path) -> None:
    """Compute write meta.

    Carry out the write meta operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Parameters
    ----------
    meta : Mapping[str, object]
        Description for ``meta``.
    out_json : Path
        Description for ``out_json``.

    Examples
    --------
    >>> from tools.docs.build_graphs import write_meta
    >>> write_meta(..., ...)  # doctest: +ELLIPSIS
    """
    out_json.write_text(json.dumps(dict(meta), indent=2), encoding="utf-8")


def enforce_policy(
    analysis: Mapping[str, object],
    allow: Mapping[str, object],
    *,
    fail_cycles: bool,
    fail_layers: bool,
) -> None:
    """Compute enforce policy.

    Carry out the enforce policy operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Parameters
    ----------
    analysis : Mapping[str, object]
        Description for ``analysis``.
    allow : Mapping[str, object]
        Description for ``allow``.
    fail_cycles : bool, optional
        Description for ``fail_cycles``. Keyword-only argument.
    fail_layers : bool, optional
        Description for ``fail_layers``. Keyword-only argument.

    Raises
    ------
    GraphPolicyError
        Raised when policy violations are detected.
    """
    allowed_cycle_set = {tuple(cycle) for cycle in _sequence_of_sequences(allow.get("cycles"))}
    allowed_edge_set = {
        tuple(edge)
        for edge in _sequence_of_sequences(allow.get("edges"))
        if len(edge) == EDGE_COMPONENTS
    }

    cycles = cast("CycleList", analysis.get("cycles", []))
    violations = cast("CycleList", analysis.get("layer_violations", []))

    new_cycles = [cycle for cycle in cycles if tuple(cycle) not in allowed_cycle_set]
    new_violations = [
        record
        for record in violations
        if (edge := _edge_from_violation(record)) is not None and edge not in allowed_edge_set
    ]

    errs = []
    if fail_cycles and new_cycles:
        errs.append(f"{len(new_cycles)} cycle(s) not allowlisted")
    if fail_layers and new_violations:
        errs.append(f"{len(new_violations)} layer violation edge(s) not allowlisted")
    if errs:
        message = "Policy violations detected"
        raise GraphPolicyError(message, errors=errs)


# --------------------------------------------------------------------------------------
# NEW: cache helpers + parallel worker
# --------------------------------------------------------------------------------------


def package_snapshot_digest(pkg: str) -> str:
    """Return a deterministic digest representing the package contents.

    Parameters
    ----------
    pkg : str
        Package name relative to ``src/``.

    Returns
    -------
    str
        Hex digest that changes only when tracked sources change.

    Notes
    -----
    The digest intentionally ignores Git metadata, file mtimes, and transient artifacts such as
    ``__pycache__`` or ``*.pyc`` to remain stable across environment rebuilds and history rewrites.
    """
    h = hashlib.sha256()
    path = SRC / pkg
    if not path.exists():
        return "EMPTY"

    skip_names = {"__pycache__", ".DS_Store"}
    skip_suffixes = {".pyc", ".pyo", ".pyd"}

    for entry in sorted(path.rglob("*")):
        name = entry.name
        if name in skip_names or entry.suffix in skip_suffixes:
            continue
        if not entry.is_file():
            continue

        rel = entry.relative_to(ROOT)
        h.update(str(rel).encode("utf-8"))

        try:
            with entry.open("rb") as fh:
                read_chunk = partial(fh.read, 8192)
                for chunk in iter(read_chunk, b""):
                    h.update(chunk)
        except OSError:
            # Skip files we cannot read; treat as unchanged.
            continue
    return h.hexdigest() or "EMPTY"


def last_tree_commit(pkg: str) -> str:
    """Return the content-based cache key for ``pkg``.

    Parameters
    ----------
    pkg : str
        Package name.

    Returns
    -------
    str
        Tree hash for the package.
    """
    return package_snapshot_digest(pkg)


def cache_bucket(cache_dir: Path, pkg: str, tree_hash: str) -> Path:
    """Compute cache bucket.

    Carry out the cache bucket operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Parameters
    ----------
    cache_dir : Path
        Description for ``cache_dir``.
    pkg : str
        Description for ``pkg``.
    tree_hash : str
        Description for ``tree_hash``.

    Returns
    -------
    Path
        Description of return value.

    Examples
    --------
    >>> from tools.docs.build_graphs import cache_bucket
    >>> result = cache_bucket(..., ..., ...)
    >>> result  # doctest: +ELLIPSIS
    """
    return cache_dir / pkg / tree_hash


def _final_output_paths(pkg: str, fmt: str) -> tuple[Path, Path]:
    """Return final output paths.

    Parameters
    ----------
    pkg : str
        Package name.
    fmt : str
        Output format.

    Returns
    -------
    tuple[Path, Path]
        (imports_path, uml_path) tuple.
    """
    return OUT / f"{pkg}-imports.{fmt}", OUT / f"{pkg}-uml.{fmt}"


def _maybe_restore_from_cache(
    pkg: str,
    fmt: str,
    cache_dir: Path,
    *,
    use_cache: bool,
    verbose: bool,
) -> CacheContext:
    """Maybe restore from cache.

    Parameters
    ----------
    pkg : str
        Package name.
    fmt : str
        Output format.
    cache_dir : Path
        Cache directory.
    use_cache : bool
        Whether to use cache.
    verbose : bool
        Verbose logging flag.

    Returns
    -------
    CacheContext
        Cache context with usage status.
    """
    imports_out, uml_out = _final_output_paths(pkg, fmt)
    if not use_cache:
        return CacheContext(used_cache=False, tree_hash=None, bucket=None)

    tree_hash = last_tree_commit(pkg)
    bucket = cache_bucket(cache_dir, pkg, tree_hash)
    cache_imports = bucket / imports_out.name
    cache_uml = bucket / uml_out.name
    if cache_imports.exists() and cache_uml.exists():
        imports_out.parent.mkdir(parents=True, exist_ok=True)
        uml_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache_imports, imports_out)
        shutil.copy2(cache_uml, uml_out)
        if verbose:
            snippet = tree_hash[:7]
            LOGGER.info("Cache hit: %s@%s", pkg, snippet)
        return CacheContext(used_cache=True, tree_hash=tree_hash, bucket=bucket)

    return CacheContext(used_cache=False, tree_hash=tree_hash, bucket=bucket)


def _prepare_staging(pkg: str, fmt: str) -> StagePaths:
    """Prepare staging.

    Parameters
    ----------
    pkg : str
        Package name.
    fmt : str
        Output format.

    Returns
    -------
    StagePaths
        Staging paths configuration.
    """
    imports_out, uml_out = _final_output_paths(pkg, fmt)
    staging_dir = Path(tempfile.mkdtemp(prefix=f"{pkg}-"))
    return StagePaths(
        staging_dir=staging_dir,
        staged_imports=staging_dir / imports_out.name,
        staged_uml=staging_dir / uml_out.name,
        final_imports=imports_out,
        final_uml=uml_out,
    )


def _build_artifacts(
    pkg: str,
    fmt: str,
    excludes: list[str],
    max_bacon: int,
    stage: StagePaths,
) -> tuple[bool, bool]:
    """Build artifacts.

    Parameters
    ----------
    pkg : str
        Package name.
    fmt : str
        Output format.
    excludes : list[str]
        Exclusion patterns.
    max_bacon : int
        Maximum bacon number.
    stage : StagePaths
        Staging paths.

    Returns
    -------
    tuple[bool, bool]
        (pydeps_ok, pyrev_ok) success flags.
    """
    pydeps_ok = True
    try:
        build_pydeps_for_package(pkg, stage.staged_imports, excludes, max_bacon, fmt)
    except (GraphBuildError, RuntimeError, OSError) as exc:
        LOGGER.warning("pydeps build failed for %s: %s", pkg, exc)
        pydeps_ok = False

    pyrev_ok = True
    try:
        build_pyreverse_for_package(pkg, stage.staging_dir, fmt)
    except (GraphBuildError, RuntimeError, OSError) as exc:
        LOGGER.warning("pyreverse build failed for %s: %s", pkg, exc)
        pyrev_ok = False

    return pydeps_ok, pyrev_ok


def _promote_outputs(stage: StagePaths) -> bool:
    """Promote outputs.

    Parameters
    ----------
    stage : StagePaths
        Staging paths.

    Returns
    -------
    bool
        True if promotion succeeded, False otherwise.
    """
    stage.final_imports.parent.mkdir(parents=True, exist_ok=True)
    stage.final_uml.parent.mkdir(parents=True, exist_ok=True)
    try:
        stage.staged_imports.replace(stage.final_imports)
        stage.staged_uml.replace(stage.final_uml)
    except (OSError, shutil.Error) as exc:
        LOGGER.warning("Failed to promote outputs: %s", exc)
        return False
    return True


def _update_cache(
    pkg: str,
    cache_ctx: CacheContext,
    stage: StagePaths,
    *,
    verbose: bool,
) -> None:
    """Update cache.

    Parameters
    ----------
    pkg : str
        Package name.
    cache_ctx : CacheContext
        Cache context.
    stage : StagePaths
        Staging paths.
    verbose : bool
        Verbose logging flag.
    """
    if cache_ctx.bucket is None or cache_ctx.tree_hash is None:
        return
    cache_ctx.bucket.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(stage.final_imports, cache_ctx.bucket / stage.final_imports.name)
        shutil.copy2(stage.final_uml, cache_ctx.bucket / stage.final_uml.name)
    except (OSError, shutil.Error) as exc:
        if verbose:
            snippet = cache_ctx.tree_hash[:7]
            LOGGER.warning("Failed to update cache for %s@%s: %s", pkg, snippet, exc)
        return
    if verbose:
        snippet = cache_ctx.tree_hash[:7]
        LOGGER.info("Cached: %s@%s", pkg, snippet)


def build_one_package(pkg: str, config: PackageBuildConfig) -> tuple[str, bool, bool, bool]:
    """Compute build one package.

    Carry out the build one package operation for the surrounding component. Generated documentation highlights how this helper collaborates with neighbouring utilities. Callers rely on the routine to remain stable across releases.

    Parameters
    ----------
    pkg : str
        Package name to render.
    config : PackageBuildConfig
        Rendering configuration and cache preferences.

    Returns
    -------
    tuple[str, bool, bool, bool]
        ``(pkg, used_cache, pydeps_ok, pyreverse_ok)`` summarising build results.

    Examples
    --------
    >>> from pathlib import Path
    >>> from tools.docs.build_graphs import PackageBuildConfig, build_one_package
    >>> cfg = PackageBuildConfig("svg", tuple(), 4, Path("/tmp/cache"), False, False)
    >>> result = build_one_package("demo_pkg", cfg)
    >>> isinstance(result, tuple)
    True
    """
    cache_ctx = _maybe_restore_from_cache(
        pkg,
        config.fmt,
        config.cache_dir,
        use_cache=config.use_cache,
        verbose=config.verbose,
    )
    if cache_ctx.used_cache:
        return (pkg, True, True, True)

    stage = _prepare_staging(pkg, config.fmt)
    pydeps_ok, pyrev_ok = _build_artifacts(
        pkg,
        config.fmt,
        config.excludes_list(),
        config.max_bacon,
        stage,
    )

    if pydeps_ok and pyrev_ok:
        promoted = _promote_outputs(stage)
        if not promoted:
            pydeps_ok = False
            pyrev_ok = False
    else:
        stage.staged_imports.unlink(missing_ok=True)
        stage.staged_uml.unlink(missing_ok=True)

    shutil.rmtree(stage.staging_dir, ignore_errors=True)

    if config.use_cache and pydeps_ok and pyrev_ok and not cache_ctx.used_cache:
        _update_cache(pkg, cache_ctx, stage, verbose=config.verbose)

    return (pkg, cache_ctx.used_cache, pydeps_ok, pyrev_ok)


def _validate_runtime_dependencies() -> None:
    """Validate runtime dependencies.

    Raises
    ------
    ValidationError
        Raised when required dependencies are missing.
    """
    missing = []
    if pydot is None:
        missing.append("pydot")
    if nx is None:
        missing.append("networkx")
    if yaml is None:
        missing.append("pyyaml")
    if missing:
        message = (
            "Missing Python packages: "
            + ", ".join(missing)
            + ". Install them in the docs environment."
        )
        raise ValidationError(message)

    if not shutil.which("dot"):
        message = "graphviz 'dot' not found on PATH. Install graphviz."
        raise ValidationError(message)

    ensure_bin("pydeps")
    ensure_bin("pyreverse")


def _resolve_packages(args: argparse.Namespace) -> list[str]:
    """Resolve packages.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    list[str]
        List of package names.
    """
    if args.packages:
        return [s.strip() for s in args.packages.split(",") if s.strip()]
    return find_top_packages()


def _prepare_cache(args: argparse.Namespace) -> tuple[Path, bool]:
    """Prepare cache.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    tuple[Path, bool]
        (cache_dir, use_cache) tuple.

    Raises
    ------
    ValidationError
        If cache directory exists but is not a directory.
    """
    cache_dir = resolve_path(args.cache_dir, strict=False)
    if cache_dir.exists() and not cache_dir.is_dir():
        message = f"Cache directory '{cache_dir}' must be a directory"
        raise ValidationError(message)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir, not args.no_cache


def _log_configuration(
    *,
    verbose: bool,
    packages: Sequence[str],
    cache_dir: Path,
    use_cache: bool,
) -> None:
    """Log configuration.

    Parameters
    ----------
    verbose : bool
        Enable verbose logging.
    packages : Sequence[str]
        Package names.
    cache_dir : Path
        Cache directory path.
    use_cache : bool
        Whether to use cache.
    """
    if not verbose:
        return
    LOGGER.info("packages=%s", list(packages))
    LOGGER.info("cache_dir=%s use_cache=%s", cache_dir, use_cache)


def _build_per_package_graphs(
    packages: Sequence[str],
    config: PackageBuildConfig,
    max_workers: int | None,
) -> list[tuple[str, bool, bool, bool]]:
    """Build per package graphs.

    Parameters
    ----------
    packages : Sequence[str]
        Package names to build.
    config : PackageBuildConfig
        Build configuration.
    max_workers : int | None
        Maximum worker processes.

    Returns
    -------
    list[tuple[str, bool, bool, bool]]
        List of (pkg, used_cache, pydeps_ok, pyrev_ok) tuples.
    """
    worker_count = max_workers or os.cpu_count() or 1
    results: list[tuple[str, bool, bool, bool]] = []
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                build_one_package,
                pkg,
                config,
            )
            for pkg in packages
        ]
        for future in as_completed(futures):
            pkg, used_cache, pydeps_ok, pyrev_ok = future.result()
            results.append((pkg, used_cache, pydeps_ok, pyrev_ok))
            if config.verbose:
                source = "cache" if used_cache else "built"
                status = f"pydeps={'ok' if pydeps_ok else 'FAIL'}; pyreverse={'ok' if pyrev_ok else 'FAIL'}"
                LOGGER.info("%s: %s; %s", pkg, source, status)
    return results


def _report_package_failures(results: Sequence[tuple[str, bool, bool, bool]]) -> None:
    """Report package failures.

    Parameters
    ----------
    results : Sequence[tuple[str, bool, bool, bool]]
        Build results tuples.

    Raises
    ------
    GraphPolicyError
        Raised when any per-package build fails.
    """
    failed = [(pkg, ok1, ok2) for pkg, _, ok1, ok2 in results if not (ok1 and ok2)]
    if not failed:
        return
    errors: list[str] = []
    for pkg, pydeps_ok, pyrev_ok in failed:
        parts: list[str] = []
        if not pydeps_ok:
            parts.append("pydeps")
        if not pyrev_ok:
            parts.append("pyreverse")
        errors.append(f"{pkg}: {', '.join(parts)} failed")
    message = "Per-package graph build failures detected"
    raise GraphPolicyError(message, errors=errors)


def _build_global_graph(_fmt: str, excludes: list[str], max_bacon: int) -> DiGraph:
    """Build global graph.

    Parameters
    ----------
    _fmt : str
        Format (unused).
    excludes : list[str]
        Exclusion patterns.
    max_bacon : int
        Maximum bacon number.

    Returns
    -------
    DiGraph
        Collapsed global dependency graph.
    """
    dot_path = OUT / "subsystems.dot"
    build_global_pydeps(dot_path, excludes, max_bacon)
    try:
        return collapse_to_packages(dot_path)
    finally:
        if dot_path.exists():
            dot_path.unlink()


def _load_layers_config(path: str) -> LayerConfig:
    """Load layers config.

    Parameters
    ----------
    path : str
        Config file path.

    Returns
    -------
    LayerConfig
        Layer configuration mapping.

    Raises
    ------
    ValidationError
        If config file is invalid or missing.
    """
    file_path = resolve_path(path, strict=False)
    if yaml is None:
        return {"order": [], "packages": {}, "rules": {}}
    if not file_path.exists():
        message = f"Layers config '{file_path}' does not exist"
        raise ValidationError(message)
    if not file_path.is_file():
        message = f"Layers config '{file_path}' must be a file"
        raise ValidationError(message)
    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except YamlError as exc:
        message = f"Layers config '{file_path}' is not valid YAML"
        raise ValidationError(message) from exc
    if not isinstance(data, Mapping):
        message = f"Layers config '{file_path}' must contain a mapping"
        raise ValidationError(message)
    return cast("LayerConfig", data)


def _load_allowlist(path: str) -> dict[str, object]:
    """Load allowlist.

    Parameters
    ----------
    path : str
        Allowlist file path.

    Returns
    -------
    dict[str, object]
        Allowlist dictionary (empty if file missing).

    Raises
    ------
    ValidationError
        If allowlist file is invalid.
    """
    file_path = resolve_path(path, strict=False)
    if not file_path.exists():
        LOGGER.warning("Allowlist '%s' does not exist; continuing with empty allowlist", file_path)
        return {}
    if not file_path.is_file():
        message = f"Allowlist '{file_path}' must be a file"
        raise ValidationError(message)
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - malformed JSON
        message = f"Allowlist '{file_path}' is not valid JSON"
        raise ValidationError(message) from exc
    if not isinstance(data, dict):
        message = f"Allowlist '{file_path}' must contain a JSON object"
        raise ValidationError(message)
    return data


def _render_summary_markdown(meta: Mapping[str, object]) -> str:
    """Render summary markdown.

    Parameters
    ----------
    meta : Mapping[str, object]
        Analysis metadata.

    Returns
    -------
    str
        Markdown summary string.
    """
    lines = ["# Subsystem Graph Metadata", ""]
    skipped = bool(meta.get("cycle_enumeration_skipped"))
    lines.append(
        "*Cycle enumeration skipped:* Yes" if skipped else "*Cycle enumeration skipped:* No"
    )
    scc_summary = meta.get("scc_summary")
    if isinstance(scc_summary, Sequence) and scc_summary:
        lines.append("")
        lines.append("The fallback strongly connected components are:")
        for entry in scc_summary:
            if not isinstance(entry, Mapping):
                continue
            members = entry.get("members")
            if isinstance(members, Sequence):
                pretty = ", ".join(sorted(str(m) for m in members))
                lines.append(f"- size {entry.get('size', '?')}: {pretty}")
    else:
        lines.append("")
        lines.append("Cycle enumeration completed normally.")
    return "\n".join(lines) + "\n"


def _write_global_artifacts(
    graph: DiGraph,
    layers: LayerConfig,
    fmt: str,
    analysis: AnalysisResult,
) -> None:
    """Write global artifacts.

    Parameters
    ----------
    graph : DiGraph
        Collapsed graph.
    layers : LayerConfig
        Layer configuration.
    fmt : str
        Output format.
    analysis : AnalysisResult
        Analysis results.
    """
    style_and_render(graph, layers, analysis, OUT / f"subsystems.{fmt}", fmt=fmt)
    meta: AnalysisResult = {
        "packages": sorted(str(node) for node in graph.nodes()),
        "cycles": analysis.get("cycles", []),
        "centrality": analysis.get("centrality", {}),
        "layer_violations": analysis.get("layer_violations", []),
        "cycle_enumeration_skipped": analysis.get("cycle_enumeration_skipped", False),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if analysis.get("scc_summary"):
        meta["scc_summary"] = analysis["scc_summary"]
    write_meta(meta, OUT / "graph_meta.json")
    (OUT / "subsystems_meta.md").write_text(_render_summary_markdown(meta), encoding="utf-8")


def _log_run_summary(
    *,
    use_cache: bool,
    cache_dir: Path,
    results: Sequence[tuple[str, bool, bool, bool]],
    duration_s: float,
    verbose: bool,
) -> None:
    built = sum(1 for _, used_cache, _, _ in results if not used_cache)
    cached = sum(1 for _, used_cache, _, _ in results if used_cache)
    if use_cache:
        LOGGER.info(
            "cache summary: per-package built=%d cached=%d; cache_dir=%s", built, cached, cache_dir
        )
    if verbose:
        LOGGER.info("done in %.2fs; outputs in %s", duration_s, OUT)


def _finalize_run(
    inputs: RunInputs,
    results: Sequence[tuple[str, bool, bool, bool]],
    duration_s: float,
    analysis: Mapping[str, object],
) -> dict[str, object]:
    _log_run_summary(
        use_cache=inputs.use_cache,
        cache_dir=inputs.cache_dir,
        results=results,
        duration_s=duration_s,
        verbose=inputs.verbose,
    )

    cached = sum(1 for _, used_cache, _, _ in results if used_cache)
    built = sum(1 for _, used_cache, _, _ in results if not used_cache)

    return {
        "packageCount": len(inputs.packages),
        "cachedPackages": cached,
        "builtPackages": built,
        "useCache": inputs.use_cache,
        "cacheDir": str(inputs.cache_dir),
        "durationSeconds": duration_s,
        "cycleEnumerationSkipped": bool(analysis.get("cycle_enumeration_skipped", False)),
    }


def _execute(context: _CommandContext) -> dict[str, object]:
    """Execute the graph build workflow and return summary metadata.

    Parameters
    ----------
    context : _CommandContext
        CLI command context containing parsed arguments and logging state.

    Returns
    -------
    dict[str, object]
        Summary metadata describing the run (packages processed, cache usage, duration).

    Notes
    -----
    Exceptions raised by dependency validation, graph construction, or policy enforcement
    propagate to the caller.

    Raises
    ------
    GraphBuildError
        Raised when global graph construction fails unexpectedly.
    GraphPolicyError
        Raised when graph policy violations are detected during analysis.
    ValidationError
        Raised when configuration validation fails (layers config, allowlist, etc.).
    """
    args = context.args
    _validate_runtime_dependencies()

    inputs = _prepare_run_inputs(args)
    build_start = time.monotonic()

    try:
        results = _build_per_package_graphs(inputs.packages, inputs.config, args.max_workers)
        _report_package_failures(results)

        try:
            global_graph = _build_global_graph(
                args.format,
                list(inputs.excludes),
                args.max_bacon,
            )
        except (
            GraphBuildError,
            RuntimeError,
            OSError,
        ) as exc:  # pragma: no cover - defensive guard
            message = "Building global graph failed"
            raise GraphBuildError(message) from exc

        layers = _load_layers_config(args.layers)
        allow = _load_allowlist(args.allowlist)

        analysis = analyze_graph(global_graph, layers)
        _write_global_artifacts(global_graph, layers, args.format, analysis)

        enforce_policy(
            analysis,
            allow,
            fail_cycles=args.fail_on_cycles,
            fail_layers=args.fail_on_layer_violations,
        )
    except (GraphPolicyError, ValidationError, GraphBuildError):
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        message = "Unexpected failure while building documentation graphs"
        raise GraphBuildError(message) from exc

    duration = time.monotonic() - build_start

    return _finalize_run(inputs, results, duration, analysis)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the documentation graphs CLI.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Optional command-line arguments to parse instead of ``sys.argv``.

    Returns
    -------
    int
        Exit code compatible with CLI conventions (0 success, non-zero failure).
    """
    args = parse_args(argv)

    if not logging.getLogger().handlers:
        log_level = logging.INFO if args.verbose else logging.WARNING
        setup_logging(level=log_level)

    context = _start_command(args)

    try:
        summary = _execute(context)
    except GraphPolicyError as exc:
        detail = str(exc) or "Graph policy violations detected"
        extras = {"error_count": len(exc.errors), "errors": exc.errors}
        return _record_failure(
            context,
            detail=detail,
            status=422,
            error_status="violation",
            options=_FailureOptions(extras=extras, exc=exc),
        )
    except ValidationError as exc:
        detail = str(exc) or "Invalid configuration"
        extras = {"error": detail}
        return _record_failure(
            context,
            detail=detail,
            status=422,
            error_status="config",
            options=_FailureOptions(extras=extras, exc=exc),
        )
    except GraphBuildError as exc:
        detail = str(exc) or "Graph build failed"
        extras = {"error": detail}
        return _record_failure(
            context,
            detail=detail,
            status=500,
            error_status="error",
            options=_FailureOptions(extras=extras, exc=exc),
        )

    return _finish_success(context, summary)


if __name__ == "__main__":
    sys.exit(main())
