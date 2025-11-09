"""Domain orchestration for the docstring builder pipeline.

This module orchestrates the docstring builder pipeline, coordinating file selection,
processing, and result aggregation. It provides two public APIs:

1. **New Typed API** (recommended): Use :func:`run_build` with :class:`DocstringBuildConfig`
2. **Legacy API**: Use :func:`run_docstring_builder` or :func:`run_legacy` (deprecated)

Examples
--------
**New Typed API (Recommended)**

Use the new API with typed configuration for safer, more maintainable code:

>>> from tools.docstring_builder.orchestrator import run_build
>>> from tools.docstring_builder.config_models import DocstringBuildConfig
>>> from tools.docstring_builder.cache import BuilderCache
>>> from pathlib import Path
>>> import tempfile
>>>
>>> config = DocstringBuildConfig(
...     enable_plugins=True,
...     emit_diff=False,
...     timeout_seconds=600,
... )
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     cache = BuilderCache(Path(tmpdir) / "cache.json")
...     # result = run_build(config=config, cache=cache)  # doctest: +SKIP
...     # print(result.exit_status)  # doctest: +SKIP

**Legacy API (Deprecated)**

The legacy API still works but emits a deprecation warning:

>>> from tools.docstring_builder.orchestrator import run_legacy
>>> import warnings
>>> with warnings.catch_warnings(record=True) as w:  # doctest: +SKIP
...     warnings.simplefilter("always")
...     # result = run_legacy()  # doctest: +SKIP
...     # assert len(w) == 1  # doctest: +SKIP
...     # assert issubclass(w[0].category, DeprecationWarning)  # doctest: +SKIP
"""

from __future__ import annotations

import datetime
import json
import os
import warnings
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FuturesTimeoutError
from dataclasses import dataclass, replace
from importlib import import_module
from typing import TYPE_CHECKING, NoReturn, Protocol, cast

from tools._shared.logging import get_logger, with_fields
from tools._shared.proc import ToolExecutionError, run_tool
from tools.docstring_builder.builder_types import (
    STATUS_LABELS,
    DocstringBuildRequest,
    DocstringBuildResult,
    ExitStatus,
    build_problem_details,
    status_from_exit,
)
from tools.docstring_builder.cache import BuilderCache, DocstringBuilderCache
from tools.docstring_builder.config import load_config_with_selection
from tools.docstring_builder.config_models import CachePolicy, DocstringBuildConfig
from tools.docstring_builder.diff_manager import DiffManager
from tools.docstring_builder.docfacts import (
    DocFact,
    DocfactsProvenance,
)
from tools.docstring_builder.docfacts_coordinator import DocfactsCoordinator
from tools.docstring_builder.file_processor import FileProcessor
from tools.docstring_builder.io import (
    InvalidPathError,
    SelectionCriteria,
    module_to_path,
    select_files,
    should_ignore,
)
from tools.docstring_builder.ir import build_ir, validate_ir
from tools.docstring_builder.metrics import MetricsRecorder
from tools.docstring_builder.models import (
    DocfactsProvenancePayload,
)
from tools.docstring_builder.normalizer import normalize_docstring
from tools.docstring_builder.observability import get_metrics_registry
from tools.docstring_builder.paths import (
    CACHE_PATH,
    DOCFACTS_DIFF_PATH,
    DOCFACTS_PATH,
    DOCSTRINGS_DIFF_PATH,
    OBSERVABILITY_PATH,
    REPO_ROOT,
)
from tools.docstring_builder.pipeline import PipelineConfig, PipelineRunner
from tools.docstring_builder.render import render_docstring
from tools.docstring_builder.schema import DocstringEdit
from tools.docstring_builder.semantics import build_semantic_schemas
from tools.docstring_builder.utils import optional_str, optional_str_list
from tools.docstring_builder.version import BUILDER_VERSION

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from tools.docstring_builder.builder_types import (
        LoggerLike,
        StatusCounts,
    )
    from tools.docstring_builder.config import (
        BuilderConfig,
        ConfigSelection,
    )
    from tools.docstring_builder.config_models import DocstringBuildConfig
    from tools.docstring_builder.harvest import HarvestResult
    from tools.docstring_builder.ir import IRDocstring
    from tools.docstring_builder.models import (
        CliResult,
        ErrorReport,
        RunSummary,
        SchemaViolationError,
    )
    from tools.docstring_builder.models import (
        ProblemDetails as ModelProblemDetails,
    )
    from tools.docstring_builder.orchestration.context_builder import (
        PipelineContextBuilder as PipelineContextBuilderType,
    )
    from tools.docstring_builder.pipeline_types import ProcessingOptions
    from tools.docstring_builder.plugins import PluginManager
    from tools.docstring_builder.semantics import SemanticResult

    class LegacyBuilderSignature(Protocol):
        """Protocol describing the deprecated legacy docstring builder callback signature.

        This protocol documents the variadic argument pattern that the legacy API accepted. The
        actual implementation is deprecated and raises NotImplementedError.
        """

        def __call__(
            self,
            *args: object,
            **kwargs: object,
        ) -> DocstringBuildResult:
            """Legacy callback signature accepting variadic arguments."""
            ...

else:  # pragma: no cover - runtime fallback preserves import laziness
    PipelineContextBuilderType = type[object]
    LegacyBuilderSignature = type[object]


def _load_pipeline_context_builder() -> type[PipelineContextBuilderType]:
    module = import_module("tools.docstring_builder.orchestration.context_builder")
    return cast("type[PipelineContextBuilderType]", module.PipelineContextBuilder)


_LOGGER = get_logger(__name__)
METRICS = get_metrics_registry()

MISSING_MODULE_PATTERNS = ("docs/_build/**",)


def _coerce_provenance_payload(data: object) -> DocfactsProvenancePayload | None:
    """Return a typed DocFacts provenance payload when ``data`` is valid.

    Parameters
    ----------
    data : object
        Object to coerce to provenance payload.

    Returns
    -------
    DocfactsProvenancePayload | None
        Provenance payload if data is valid, None otherwise.
    """
    if not isinstance(data, dict):
        return None
    builder_version = data.get("builderVersion")
    if not isinstance(builder_version, str):
        return None
    config_hash = data.get("configHash")
    if not isinstance(config_hash, str):
        return None
    commit_hash = data.get("commitHash")
    if not isinstance(commit_hash, str):
        return None
    generated_at = data.get("generatedAt")
    if not isinstance(generated_at, str):
        return None
    return DocfactsProvenancePayload(
        builderVersion=builder_version,
        configHash=config_hash,
        commitHash=commit_hash,
        generatedAt=generated_at,
    )


def _typed_pipeline_enabled() -> bool:
    value = os.environ.get("DOCSTRINGS_TYPED_IR", "1").strip().lower()
    return value not in {"", "0", "false", "no", "off"}


TYPED_PIPELINE_ENABLED = _typed_pipeline_enabled()


def _handle_schema_violation(context: str, exc: SchemaViolationError) -> None:
    if TYPED_PIPELINE_ENABLED:
        raise exc
    log_extra = {"problem": exc.problem} if exc.problem else None
    _LOGGER.warning("%s validation failed: %s", context, exc, extra=log_extra)


def _git_output(arguments: Sequence[str]) -> str | None:
    """Return stripped stdout for a git command or ``None`` on failure.

    Parameters
    ----------
    arguments : Sequence[str]
        Git command arguments.

    Returns
    -------
    str | None
        Stripped stdout if command succeeds, None otherwise.
    """
    command_args: list[str] = list(arguments)
    adapter = with_fields(_LOGGER, command=command_args)
    try:
        result = run_tool(arguments, timeout=10.0)
    except ToolExecutionError as exc:  # pragma: no cover - git unavailable
        adapter.debug("git invocation failed: %s", exc)
        return None
    if result.returncode != 0:
        adapter.debug("git returned non-zero exit code: %s", result.returncode)
        return None
    output = result.stdout.strip()
    return output or None


def _resolve_commit_hash() -> str:
    """Resolve the current git commit hash.

    Returns
    -------
    str
        Commit hash string, or "unknown" if git is unavailable.
    """
    command = ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"]
    return _git_output(command) or "unknown"


def _resolve_commit_timestamp(commit_hash: str) -> str:
    """Resolve the commit timestamp for a given hash.

    Parameters
    ----------
    commit_hash : str
        Git commit hash.

    Returns
    -------
    str
        ISO-8601 timestamp string, or default timestamp if unavailable.
    """
    if not commit_hash or commit_hash == "unknown":
        return "1970-01-01T00:00:00Z"
    command = ["git", "-C", str(REPO_ROOT), "show", "-s", "--format=%cI", commit_hash]
    return _git_output(command) or "1970-01-01T00:00:00Z"


def _build_docfacts_provenance(config: BuilderConfig) -> DocfactsProvenance:
    """Build provenance metadata for DocFacts.

    Parameters
    ----------
    config : BuilderConfig
        Builder configuration.

    Returns
    -------
    DocfactsProvenance
        Provenance metadata instance.
    """
    commit_hash = _resolve_commit_hash()
    generated_at = _resolve_commit_timestamp(commit_hash)
    return DocfactsProvenance(
        builder_version=BUILDER_VERSION,
        config_hash=config.config_hash,
        commit_hash=commit_hash,
        generated_at=generated_at,
    )


def _collect_edits(
    result: HarvestResult,
    config: BuilderConfig,
    plugin_manager: PluginManager | None,
    *,
    format_only: bool = False,
) -> tuple[list[DocstringEdit], list[SemanticResult], list[IRDocstring]]:
    semantics = build_semantic_schemas(result, config)
    if plugin_manager is not None:
        semantics = plugin_manager.apply_transformers(result.filepath, semantics)
    edits: list[DocstringEdit] = []
    ir_entries: list[IRDocstring] = []
    for entry in semantics:
        ir_entry = build_ir(entry)
        validate_ir(ir_entry)
        ir_entries.append(ir_entry)
        text: str | None
        if config.normalize_sections:
            normalized = normalize_docstring(entry.symbol, config.ownership_marker)
            if normalized is not None:
                text = normalized
            elif format_only:
                continue
            else:
                text = render_docstring(
                    entry.schema,
                    config.ownership_marker,
                    include_signature=config.render_signature,
                )
        else:
            text = render_docstring(
                entry.schema,
                config.ownership_marker,
                include_signature=config.render_signature,
            )
        edits.append(DocstringEdit(qname=entry.symbol.qname, text=text))
    if plugin_manager is not None:
        edits = plugin_manager.apply_formatters(result.filepath, edits)
    return edits, semantics, ir_entries


def _load_docfacts_from_disk() -> dict[str, DocFact]:
    """Load previously generated DocFacts entries keyed by qualified name.

    Returns
    -------
    dict[str, DocFact]
        Dictionary mapping qualified names to DocFact instances.
    """
    if not DOCFACTS_PATH.exists():
        return {}
    try:
        raw_text = DOCFACTS_PATH.read_text(encoding="utf-8")
        raw: object = json.loads(raw_text)
    except json.JSONDecodeError:
        _LOGGER.warning("DocFacts cache is not valid JSON; ignoring existing data.")
        return {}
    entries: dict[str, DocFact] = {}
    payload_items: Iterable[Mapping[str, object]]
    if isinstance(raw, Mapping):
        entries_field: object = raw.get("entries", [])
        if isinstance(entries_field, Sequence) and not isinstance(
            entries_field, (str, bytes)
        ):
            payload_items = [
                item for item in entries_field if isinstance(item, Mapping)
            ]
        else:
            payload_items = []
    elif isinstance(raw, list):  # pragma: no cover - legacy fallback
        payload_items = [item for item in raw if isinstance(item, Mapping)]
    else:  # pragma: no cover - defensive guard
        return {}
    for item in payload_items:
        fact = DocFact.from_mapping(item)
        if fact is None:
            continue
        entries[fact.qname] = fact
    return entries


def _load_docfact_state() -> tuple[dict[str, DocFact], dict[str, Path]]:
    """Load docfact entries along with best-effort source mapping.

    Returns
    -------
    tuple[dict[str, DocFact], dict[str, Path]]
        Tuple of (entries dictionary, sources dictionary) mapping qualified names
        to DocFact instances and source file paths.
    """
    entries = _load_docfacts_from_disk()
    sources: dict[str, Path] = {}
    for qname, fact in entries.items():
        candidate: Path | None = None
        if fact.filepath:
            candidate_path = (REPO_ROOT / fact.filepath).resolve()
            if candidate_path.exists():
                candidate = candidate_path
        if candidate is None:
            candidate = module_to_path(fact.module)
        if candidate is not None:
            sources[qname] = candidate
    return entries, sources


def _record_docfacts(
    facts: Iterable[DocFact],
    file_path: Path,
    entries: dict[str, DocFact],
    sources: dict[str, Path],
) -> None:
    for fact in facts:
        entries[fact.qname] = fact
        sources[fact.qname] = file_path


def _filter_docfacts_for_output(
    entries: dict[str, DocFact],
    sources: dict[str, Path],
    config: BuilderConfig,
) -> list[DocFact]:
    filtered: list[DocFact] = []
    for qname, fact in entries.items():
        source = sources.get(qname)
        if source is None and fact.filepath:
            candidate = (REPO_ROOT / fact.filepath).resolve()
            if candidate.exists():
                source = candidate
        if source is None:
            source = module_to_path(fact.module)
        if source is not None and should_ignore(source, config):
            _LOGGER.debug("Dropping docfact %s due to ignore rules", qname)
            continue
        filtered.append(fact)
    return filtered


@dataclass(slots=True, frozen=True)
class _DocfactState:
    config: BuilderConfig
    entries: dict[str, DocFact]
    sources: dict[str, Path]

    def record(self, facts: Iterable[DocFact], file_path: Path) -> None:
        """Record docfacts for a file.

        Parameters
        ----------
        facts : Iterable[DocFact]
            Docfacts to record.
        file_path : Path
            Source file path.
        """
        _record_docfacts(facts, file_path, self.entries, self.sources)

    def filtered(self) -> list[DocFact]:
        """Return filtered docfacts for output.

        Returns
        -------
        list[DocFact]
            Filtered docfacts list.
        """
        return _filter_docfacts_for_output(self.entries, self.sources, self.config)


@dataclass(slots=True, frozen=True)
class _PipelineDependencies:
    config: BuilderConfig
    logger: LoggerLike
    cache: DocstringBuilderCache
    diff_manager: DiffManager
    metrics: MetricsRecorder
    file_processor: FileProcessor
    docfact_state: _DocfactState

    def record_docfacts(self, facts: Iterable[DocFact], file_path: Path) -> None:
        """Record docfacts for a file.

        Parameters
        ----------
        facts : Iterable[DocFact]
            Docfacts to record.
        file_path : Path
            Source file path.
        """
        self.docfact_state.record(facts, file_path)

    def filter_docfacts(self) -> list[DocFact]:
        """Return filtered docfacts for output.

        Returns
        -------
        list[DocFact]
            Filtered docfacts list.
        """
        return self.docfact_state.filtered()

    def docfacts_coordinator_factory(self, *, check_mode: bool) -> DocfactsCoordinator:
        """Create docfacts coordinator factory.

        Parameters
        ----------
        check_mode : bool
            Whether to run in check mode.

        Returns
        -------
        DocfactsCoordinator
            Coordinator instance.
        """
        return DocfactsCoordinator(
            config=self.config,
            build_provenance=_build_docfacts_provenance,
            handle_schema_violation=_handle_schema_violation,
            typed_pipeline_enabled=TYPED_PIPELINE_ENABLED,
            check_mode=check_mode,
            logger=self.logger,
        )


def _build_pipeline_dependencies(
    config: BuilderConfig,
    options: ProcessingOptions,
    plugin_manager: PluginManager | None,
    logger: LoggerLike,
    *,
    cache: DocstringBuilderCache | None = None,
) -> _PipelineDependencies:
    cache_instance: DocstringBuilderCache = cache or BuilderCache(CACHE_PATH)
    docfact_entries, docfact_sources = _load_docfact_state()
    diff_manager = DiffManager(options)
    metrics = MetricsRecorder(
        cli_duration_seconds=METRICS.cli_duration_seconds,
        runs_total=METRICS.runs_total,
    )
    file_processor = FileProcessor(
        config=config,
        cache=cache_instance,
        options=options,
        collect_edits=_collect_edits,
        plugin_manager=plugin_manager,
        logger=logger,
    )
    docfact_state = _DocfactState(
        config=config,
        entries=docfact_entries,
        sources=docfact_sources,
    )
    return _PipelineDependencies(
        config=config,
        logger=logger,
        cache=cache_instance,
        diff_manager=diff_manager,
        metrics=metrics,
        file_processor=file_processor,
        docfact_state=docfact_state,
    )


class _CachePolicyAdapter(DocstringBuilderCache):
    """Apply cache policy semantics over a delegate cache implementation."""

    def __init__(self, delegate: DocstringBuilderCache, policy: CachePolicy) -> None:
        self._delegate = delegate
        self._policy = policy

    @property
    def path(self) -> Path:
        return self._delegate.path

    def needs_update(self, file_path: Path, config_hash: str) -> bool:
        if self._policy is CachePolicy.WRITE_ONLY:
            return True
        if self._policy is CachePolicy.DISABLED:
            return True
        return self._delegate.needs_update(file_path, config_hash)

    def update(self, file_path: Path, config_hash: str) -> None:
        if self._policy in {CachePolicy.DISABLED, CachePolicy.READ_ONLY}:
            return
        self._delegate.update(file_path, config_hash)

    def write(self) -> None:
        if self._policy in {CachePolicy.DISABLED, CachePolicy.READ_ONLY}:
            return
        self._delegate.write()

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


def _adapt_cache_policy(
    cache: DocstringBuilderCache,
    policy: CachePolicy,
) -> DocstringBuilderCache:
    if policy is CachePolicy.READ_WRITE:
        return cache
    return _CachePolicyAdapter(cache, policy)


def render_cli_result(result: DocstringBuildResult) -> CliResult | None:
    """Return the CLI payload for JSON output when available.

    Parameters
    ----------
    result : DocstringBuildResult
        Build result containing CLI payload.

    Returns
    -------
    CliResult | None
        CLI result dictionary if available, None otherwise.
    """
    return result.cli_payload


def render_failure_summary(result: DocstringBuildResult) -> None:
    """Log a structured failure summary for non-successful runs."""
    if result.exit_status is ExitStatus.SUCCESS:
        return

    summary_obj = result.observability_payload.get("summary", {})
    if isinstance(summary_obj, Mapping):
        considered = int(summary_obj.get("considered", 0))
        processed = int(summary_obj.get("processed", 0))
        changed = int(summary_obj.get("changed", 0))
        status_counts: object = summary_obj.get("status_counts", {})
    else:
        considered = processed = changed = 0
        status_counts = {}

    _LOGGER.error("[SUMMARY] Docstring builder reported issues.")
    _LOGGER.error("  Considered files: %s", considered)
    _LOGGER.error("  Processed files: %s", processed)
    _LOGGER.error("  Changed files: %s", changed)
    _LOGGER.error("  Status counts: %s", status_counts)
    _LOGGER.error("  Observability log: %s", OBSERVABILITY_PATH)

    if result.errors:
        _LOGGER.error("  Top errors:")
        for entry in result.errors[:5]:
            file_name = entry.get("file", "<unknown>")
            status_label = entry.get("status", "unknown")
            message = entry.get("message", "no additional details")
            _LOGGER.error("    - %s: %s (%s)", file_name, status_label, message)


def load_builder_config(
    override: str | None = None,
) -> tuple[BuilderConfig, ConfigSelection]:
    """Load builder configuration honouring CLI/environment precedence.

    Parameters
    ----------
    override : str | None, optional
        Explicit config path override.

    Returns
    -------
    tuple[BuilderConfig, ConfigSelection]
        Loaded configuration and selection metadata.
    """
    config, selection = load_config_with_selection(override)
    return config, selection


def _build_error_result(
    status: ExitStatus,
    request: DocstringBuildRequest,
    detail: str,
    *,
    selection: ConfigSelection | None,
) -> DocstringBuildResult:
    command = request.command or "unknown"
    subcommand = request.invoked_subcommand or request.subcommand or command
    errors: list[ErrorReport] = [
        {"file": "<command>", "status": status_from_exit(status), "message": detail}
    ]
    status_counts_dict: dict[str, int] = {
        "success": 0,
        "violation": 0,
        "config": 0,
        "error": 0,
    }
    status_counts_dict[STATUS_LABELS[status]] += 1
    summary: RunSummary = {
        "considered": 0,
        "processed": 0,
        "skipped": 0,
        "changed": 0,
        "duration_seconds": 0.0,
        "status_counts": cast("StatusCounts", status_counts_dict),
        "cache_hits": 0,
        "cache_misses": 0,
        "subcommand": subcommand,
        "docfacts_checked": False,
    }

    observability_payload: dict[str, object] = {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "status": STATUS_LABELS[status],
        "summary": summary,
        "errors": errors,
        "cache": {
            "path": str(CACHE_PATH),
            "exists": CACHE_PATH.exists(),
            "hits": 0,
            "misses": 0,
        },
    }
    if selection is not None:
        observability_payload["config"] = {
            "path": str(selection.path),
            "source": selection.source,
        }

    problem = build_problem_details(status, request, detail, errors=errors)

    return DocstringBuildResult(
        exit_status=status,
        errors=errors,
        file_reports=[],
        observability_payload=observability_payload,
        cli_payload=None,
        manifest_path=None,
        problem_details=problem,
        config_selection=selection,
    )


@dataclass(slots=True, frozen=True)
class _PipelineInvocation:
    """Aggregate inputs required to execute the docstring builder pipeline."""

    files: Iterable[Path]
    request: DocstringBuildRequest
    config: BuilderConfig
    selection: ConfigSelection | None
    cache: DocstringBuilderCache | None = None
    plugins_enabled: bool = True


def _run_pipeline(invocation: _PipelineInvocation) -> DocstringBuildResult:
    files_list = list(invocation.files)

    context_builder_cls = _load_pipeline_context_builder()
    context_builder = context_builder_cls(
        invocation.request,
        invocation.config,
        invocation.selection,
        files_list,
    )
    build_result = context_builder.build()
    if isinstance(build_result, DocstringBuildResult):
        return build_result
    logger, plugin_manager, policy_engine, options = build_result
    if not invocation.plugins_enabled:
        plugin_manager = None

    dependencies = _build_pipeline_dependencies(
        invocation.config,
        options,
        plugin_manager,
        logger,
        cache=invocation.cache,
    )

    def build_problem_details_wrapper(
        status: ExitStatus,
        request: DocstringBuildRequest,
        detail: str,
        *,
        instance: str | None = None,
        errors: Sequence[ErrorReport] | None = None,
    ) -> ModelProblemDetails:
        """Build problem details wrapper for pipeline errors.

        Parameters
        ----------
        status : ExitStatus
            Exit status code.
        request : DocstringBuildRequest
            Build request.
        detail : str
            Error detail message.
        instance : str | None, optional
            Problem instance URI.
        errors : Sequence[ErrorReport] | None, optional
            Error reports.

        Returns
        -------
        ModelProblemDetails
            Problem details model.
        """
        return build_problem_details(
            status,
            request,
            detail,
            instance=instance,
            errors=errors,
        )

    pipeline_config = PipelineConfig(
        request=invocation.request,
        config=invocation.config,
        selection=invocation.selection,
        options=options,
        cache=dependencies.cache,
        file_processor=dependencies.file_processor,
        record_docfacts=dependencies.record_docfacts,
        filter_docfacts=dependencies.filter_docfacts,
        docfacts_coordinator_factory=dependencies.docfacts_coordinator_factory,
        plugin_manager=plugin_manager,
        policy_engine=policy_engine,
        metrics=dependencies.metrics,
        diff_manager=dependencies.diff_manager,
        logger=logger,
        status_from_exit=status_from_exit,
        status_labels=STATUS_LABELS,
        build_problem_details=build_problem_details_wrapper,
        success_status=ExitStatus.SUCCESS,
        violation_status=ExitStatus.VIOLATION,
        config_status=ExitStatus.CONFIG,
        error_status=ExitStatus.ERROR,
    )

    runner = PipelineRunner(pipeline_config)
    result = runner.run(files_list)

    if invocation.request.command == "update":
        dependencies.cache.write()

    if (
        not files_list
        and invocation.request.command == "check"
        and invocation.request.diff
    ):
        DOCSTRINGS_DIFF_PATH.unlink(missing_ok=True)
        DOCFACTS_DIFF_PATH.unlink(missing_ok=True)

    return result


def run_docstring_builder(
    request: DocstringBuildRequest,
    *,
    config_override: str | None = None,
) -> DocstringBuildResult:
    """Execute the docstring builder for ``request`` and return a structured result.

    Parameters
    ----------
    request : DocstringBuildRequest
        Build request containing command, options, and selection criteria.
    config_override : str | None, optional
        Explicit configuration file path override.

    Returns
    -------
    DocstringBuildResult
        Build result containing exit status, metrics, and CLI payload.
    """
    config, config_selection = load_builder_config(config_override)
    if request.llm_summary:
        config = replace(config, llm_summary_mode="apply")
    elif request.llm_dry_run:
        config = replace(config, llm_summary_mode="dry-run")
    if request.normalize_sections:
        config = replace(config, normalize_sections=True)
    try:
        selection = SelectionCriteria(
            module=optional_str(request.module),
            since=optional_str(request.since),
            changed_only=request.changed_only,
            explicit_paths=optional_str_list(request.explicit_paths or None),
        )
        files = select_files(config, selection)
    except InvalidPathError:
        _LOGGER.exception("Invalid path supplied to docstring builder")
        return _build_error_result(
            ExitStatus.CONFIG,
            request,
            "Invalid path supplied to docstring builder",
            selection=config_selection,
        )
    invocation = _PipelineInvocation(
        files=files,
        request=request,
        config=config,
        selection=config_selection,
    )
    return _run_pipeline(invocation)


def run_build(
    *,
    config: DocstringBuildConfig,
    cache: DocstringBuilderCache,
) -> DocstringBuildResult:
    """Execute docstring builder pipeline using typed configuration.

    Parameters
    ----------
    config : DocstringBuildConfig
        Typed configuration controlling plugin usage, diff emission, cache policy,
        and execution timeout.
    cache : DocstringBuilderCache
        Cache interface used to determine stale files and persist run metadata.

    Returns
    -------
    DocstringBuildResult
        Build result containing exit status, metrics, and generated artifacts.

    Raises
    ------
    TimeoutError
        Raised when the build exceeds ``config.timeout_seconds``.
    """
    builder_config, config_selection = load_builder_config(None)
    builder_config = replace(builder_config, dynamic_probes=config.dynamic_probes)
    if config.normalize_sections:
        builder_config = replace(builder_config, normalize_sections=True)

    command = "check" if config.emit_diff else "update"
    request = DocstringBuildRequest(
        command=command,
        subcommand=command,
        diff=config.emit_diff,
        normalize_sections=config.normalize_sections,
        invoked_subcommand=command,
    )

    selection = SelectionCriteria(
        module=None,
        since=None,
        changed_only=False,
        explicit_paths=None,
    )

    try:
        files = select_files(builder_config, selection)
    except InvalidPathError:
        _LOGGER.exception("Invalid path supplied to docstring builder")
        return _build_error_result(
            ExitStatus.CONFIG,
            request,
            "Invalid path supplied to docstring builder",
            selection=config_selection,
        )

    adapted_cache = _adapt_cache_policy(cache, config.cache_policy)

    def _execute() -> DocstringBuildResult:
        invocation = _PipelineInvocation(
            files=files,
            request=request,
            config=builder_config,
            selection=config_selection,
            cache=adapted_cache,
            plugins_enabled=config.enable_plugins,
        )
        return _run_pipeline(invocation)

    timeout_seconds = float(config.timeout_seconds)
    if timeout_seconds > 0:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_execute)
            try:
                return future.result(timeout=timeout_seconds)
            except _FuturesTimeoutError as exc:  # pragma: no cover - defensive guard
                future.cancel()
                message = f"Docstring build exceeded timeout of {config.timeout_seconds} seconds"
                raise TimeoutError(message) from exc
    return _execute()


def run_legacy(
    *args: object,
    **kwargs: object,
) -> NoReturn:
    """Deprecate legacy API for docstring builder in favor of typed config.

    .. deprecated::
        Use :func:`run_build` instead with typed configuration objects.

    This function accepts the old positional argument style and emits a
    deprecation warning. It will be removed in a future release.

    Parameters
    ----------
    *args : object
        Positional arguments (deprecated, accepted for backward compatibility only).
    **kwargs : object
        Keyword arguments (deprecated, accepted for backward compatibility only).

    Raises
    ------
    NotImplementedError
        Always raised as this function is a placeholder and not yet implemented.

    Notes
    -----
    This function never returns normally; it always raises :exc:`NotImplementedError`.
    The return type annotation ``NoReturn`` indicates that this function never
    returns a value.
    """
    msg = (
        "run_legacy() is deprecated and will be removed in a future release. "
        "Use run_build(config=..., cache=...) instead with typed "
        "DocstringBuildConfig objects."
    )
    warnings.warn(msg, DeprecationWarning, stacklevel=2)

    # Log arguments for debugging/diagnostic purposes (structural use of variadic args)
    if args:
        _LOGGER.debug(
            "Legacy API called with %d positional argument(s)",
            len(args),
            extra={"legacy_args_count": len(args)},
        )
    if kwargs:
        _LOGGER.debug(
            "Legacy API called with %d keyword argument(s)",
            len(kwargs),
            extra={
                "legacy_kwargs_count": len(kwargs),
                "legacy_kwargs_keys": list(kwargs.keys()),
            },
        )

    # This is a placeholder that would delegate to run_docstring_builder
    # or other legacy behavior
    msg_impl = "run_legacy is not yet fully implemented"
    raise NotImplementedError(msg_impl)


__all__ = [
    "DocstringBuildRequest",
    "DocstringBuildResult",
    "ExitStatus",
    "InvalidPathError",
    "build_problem_details",
    "load_builder_config",
    "render_cli_result",
    "render_failure_summary",
    "run_build",
    "run_docstring_builder",
    "run_legacy",
]
