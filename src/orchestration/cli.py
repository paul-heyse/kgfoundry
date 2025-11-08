"""Orchestration CLI integrated with shared tooling metadata and envelopes."""

from __future__ import annotations

import contextlib
import importlib
import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Protocol, cast
from uuid import uuid4

import typer
from tools import (
    CliEnvelope,
    CliEnvelopeBuilder,
    CliErrorStatus,
    CliStatus,
    JsonValue,
    ProblemDetailsDict,
    ProblemDetailsParams,
    build_problem_details,
    get_logger,
    render_cli_envelope,
    with_fields,
)
from tools._shared.logging import LoggerAdapter

from kgfoundry.embeddings_sparse.bm25 import get_bm25
from kgfoundry_common.errors import ConfigurationError, IndexBuildError
from kgfoundry_common.jsonschema_utils import create_draft202012_validator
from kgfoundry_common.schema_helpers import load_schema
from kgfoundry_common.vector_types import VectorBatch, VectorValidationError, coerce_vector_batch
from orchestration import cli_context, safe_pickle
from orchestration.config import IndexCliConfig

if TYPE_CHECKING:
    from kgfoundry_common.jsonschema_utils import (
        Draft202012ValidatorProtocol,
        ValidationErrorProtocol,
    )


class _UvicornRun(Protocol):
    def __call__(
        self, app: str, *, host: str, port: int, reload: bool = False
    ) -> None:  # pragma: no cover - runtime contract
        """Protocol describing the uvicorn ``run`` callable."""


class _BM25Builder(Protocol):
    def build(
        self, docs: Iterable[tuple[str, dict[str, str]]]
    ) -> None:  # pragma: no cover - provided by get_bm25
        """Protocol describing lucene/pure BM25 builders."""


@dataclass(frozen=True)
class BM25BuildConfig:
    """Configuration for BM25 index builds."""

    chunks_path: str
    backend: str
    index_dir: str


@dataclass(slots=True)
class _CommandContext:
    """Structured context shared across a single command invocation."""

    subcommand: str
    operation_id: str
    correlation_id: str
    logger: LoggerAdapter
    start: float

    def extensions(self, extras: Mapping[str, object] | None = None) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {
            "operation_id": self.operation_id,
            "correlation_id": self.correlation_id,
        }
        if extras:
            for key, value in extras.items():
                payload[str(key)] = _coerce_extension_value(value)
        return payload


CLI_COMMAND = cli_context.CLI_COMMAND
CLI_OPERATION_IDS = cli_context.CLI_OPERATION_IDS
CLI_INTERFACE_ID = cli_context.CLI_INTERFACE_ID
CLI_CONFIG = cli_context.get_cli_config()
CLI_SETTINGS = cli_context.get_cli_settings()
CLI_TITLE = cli_context.CLI_TITLE
CLI_ENVELOPE_DIR = cli_context.REPO_ROOT / "site" / "_build" / "cli"

SUBCOMMAND_INDEX_BM25 = "index-bm25"
SUBCOMMAND_INDEX_FAISS = "index-faiss"
SUBCOMMAND_API = "api"
SUBCOMMAND_E2E = "e2e"

CLI_PROBLEM_TYPE_BASE = "https://kgfoundry.dev/problems/orchestration"

STATUS_NOT_FOUND = 404
STATUS_BAD_REQUEST = 400
STATUS_UNPROCESSABLE_ENTITY = 422
STATUS_INTERNAL_ERROR = 500
STATUS_CLIENT_CLOSED = 499
STATUS_MIN_CLIENT_ERROR = 400
STATUS_MAX_CLIENT_ERROR = 499

LOGGER = get_logger(__name__)


_e2e_flow: Callable[[], list[str]] | None = None
with contextlib.suppress(ImportError):
    from orchestration.flows import e2e_flow as _loaded_flow

    _e2e_flow = _loaded_flow


def _resolve_cli_help() -> str:
    title = CLI_CONFIG.title or CLI_TITLE
    return f"{title} ({CLI_SETTINGS.version})"


app = typer.Typer(help=_resolve_cli_help(), no_args_is_help=True, add_completion=False)


def _coerce_extension_value(value: object) -> JsonValue:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(map(_coerce_extension_value, value))
    if isinstance(value, Mapping):
        return {str(key): _coerce_extension_value(val) for key, val in value.items()}
    return str(value)


def _start_command(
    subcommand: str, **log_fields: object
) -> tuple[_CommandContext, CliEnvelopeBuilder]:
    operation_id = CLI_OPERATION_IDS.get(subcommand, subcommand)
    operation_alias = subcommand.replace("-", "_")
    correlation_id = uuid4().hex
    filtered_fields = {key: value for key, value in log_fields.items() if value is not None}
    logger = with_fields(
        LOGGER,
        correlation_id=correlation_id,
        operation_id=operation_id,
        operation=operation_alias,
        command=CLI_COMMAND,
        subcommand=subcommand,
        **filtered_fields,
    )
    logger.info("Command started", extra={"status": "start"})
    builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND, status="success", subcommand=subcommand
    )
    context = _CommandContext(
        subcommand=subcommand,
        operation_id=operation_id,
        correlation_id=correlation_id,
        logger=logger,
        start=time.monotonic(),
    )
    return context, builder


def _run_status_from_error(error_status: CliErrorStatus) -> CliStatus:
    return cast("CliStatus", error_status if error_status in {"config", "violation"} else "error")


def _error_status_from_http(status: int) -> CliErrorStatus:
    if status == STATUS_UNPROCESSABLE_ENTITY:
        return cast("CliErrorStatus", "violation")
    if (
        status in {STATUS_BAD_REQUEST, STATUS_NOT_FOUND, STATUS_CLIENT_CLOSED}
        or STATUS_MIN_CLIENT_ERROR <= status <= STATUS_MAX_CLIENT_ERROR
    ):
        return cast("CliErrorStatus", "config")
    return cast("CliErrorStatus", "error")


def _problem_type_for(subcommand: str) -> str:
    safe = subcommand.replace("/", "-")
    return f"{CLI_PROBLEM_TYPE_BASE}/{safe}"


def _build_cli_problem(
    context: _CommandContext,
    *,
    detail: str,
    status: int,
    extras: Mapping[str, object] | None = None,
    overrides: Mapping[str, str] | None = None,
) -> ProblemDetailsDict:
    override_title = overrides.get("title") if overrides else None
    override_type = overrides.get("type") if overrides else None
    return build_problem_details(
        ProblemDetailsParams(
            type=override_type or _problem_type_for(context.subcommand),
            title=override_title
            or f"{CLI_TITLE} {context.subcommand.replace('-', ' ')} command failed",
            status=status,
            detail=detail,
            instance=f"urn:cli:{CLI_INTERFACE_ID}:{context.subcommand}",
            extensions=context.extensions(extras),
        )
    )


def _envelope_path(subcommand: str) -> Path:
    safe_subcommand = subcommand or "root"
    filename = f"{CLI_SETTINGS.bin_name}-{CLI_COMMAND}-{safe_subcommand.replace('/', '-')}.json"
    return CLI_ENVELOPE_DIR / filename


def _emit_envelope(envelope: CliEnvelope, *, subcommand: str, logger: LoggerAdapter) -> Path:
    path = _envelope_path(subcommand)
    CLI_ENVELOPE_DIR.mkdir(parents=True, exist_ok=True)
    payload = render_cli_envelope(envelope)
    path.write_text(payload + "\n", encoding="utf-8")
    logger.debug(
        "CLI envelope written", extra={"status": envelope.status, "cli_envelope": str(path)}
    )
    return path


def _finish_success(context: _CommandContext, builder: CliEnvelopeBuilder) -> CliEnvelope:
    envelope = builder.finish(duration_seconds=time.monotonic() - context.start)
    path = _emit_envelope(envelope, subcommand=context.subcommand, logger=context.logger)
    context.logger.info(
        "Command completed",
        extra={
            "status": "success",
            "duration_seconds": envelope.duration_seconds,
            "cli_envelope": str(path),
        },
    )
    return envelope


def _handle_failure(
    context: _CommandContext, *, detail: str, status: int, **options: object
) -> None:
    error_status_option = cast("CliErrorStatus | None", options.get("error_status"))
    extras = cast("Mapping[str, object] | None", options.get("extras"))
    overrides = cast("Mapping[str, str] | None", options.get("overrides"))
    exc = cast("BaseException | None", options.get("exc"))

    cli_error_status: CliErrorStatus = error_status_option or _error_status_from_http(status)
    cli_run_status: CliStatus = _run_status_from_error(cli_error_status)
    problem_payload = _build_cli_problem(
        context,
        detail=detail,
        status=status,
        extras=extras,
        overrides=overrides,
    )
    builder = CliEnvelopeBuilder.create(
        command=CLI_COMMAND, status=cli_run_status, subcommand=context.subcommand
    )
    builder.add_error(status=cli_error_status, message=detail, problem=problem_payload)
    builder.set_problem(problem_payload)
    envelope = builder.finish(duration_seconds=time.monotonic() - context.start)
    path = _emit_envelope(envelope, subcommand=context.subcommand, logger=context.logger)
    log_kwargs = {
        "extra": {
            "status": cli_run_status,
            "detail": detail,
            "duration_seconds": envelope.duration_seconds,
            "cli_envelope": str(path),
        }
    }
    context.logger.error("Command failed", exc_info=exc, **log_kwargs)
    typer.echo(json.dumps(problem_payload, sort_keys=True), err=True)
    typer.echo(detail, err=True)


def _extract_bm25_document(record: Mapping[str, object]) -> tuple[str, dict[str, str]] | None:
    chunk_id = record.get("chunk_id")
    if not isinstance(chunk_id, str):
        return None
    title_raw = record.get("title")
    section_raw = record.get("section")
    text_raw = record.get("text")
    title = title_raw if isinstance(title_raw, str) else ""
    section = section_raw if isinstance(section_raw, str) else ""
    text = text_raw if isinstance(text_raw, str) else ""
    return chunk_id, {"title": title, "section": section, "body": text}


def _load_bm25_documents(
    chunks_path: str, *, logger: LoggerAdapter
) -> list[tuple[str, dict[str, str]]]:
    docs: list[tuple[str, dict[str, str]]] = []
    path = Path(chunks_path)
    if chunks_path.endswith(".jsonl"):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload: object = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Skipping invalid JSON line", extra={"status": "warning", "error": str(exc)}
                    )
                    continue
                if isinstance(payload, Mapping) and (document := _extract_bm25_document(payload)):
                    docs.append(document)
    else:
        with path.open("r", encoding="utf-8") as handle:
            payload: object = json.load(handle)
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            msg = "Chunk dataset must be a sequence of mapping objects"
            raise TypeError(msg)
        docs.extend(
            document
            for entry in payload
            if isinstance(entry, Mapping) and (document := _extract_bm25_document(entry))
        )
    return docs


def _get_bm25_index_path(index_dir: Path, backend: str) -> Path:
    return index_dir / "pure_bm25.pkl" if backend == "pure" else index_dir / "bm25_index"


def _instantiate_bm25_builder(
    config: BM25BuildConfig, *, logger: LoggerAdapter
) -> tuple[_BM25Builder, str]:
    requested_backend = config.backend.strip().lower()
    try:
        builder = cast(
            "_BM25Builder",
            get_bm25(requested_backend, config.index_dir, k1=0.9, b=0.4, load_existing=False),
        )
    except RuntimeError as exc:
        if requested_backend != "lucene":
            raise
        logger.warning(
            "Lucene backend unavailable; using pure backend",
            extra={"status": "warning", "backend": requested_backend, "fallback_backend": "pure"},
            exc_info=exc,
        )
        fallback = cast(
            "_BM25Builder", get_bm25("pure", config.index_dir, k1=0.9, b=0.4, load_existing=False)
        )
        return fallback, "pure"
    return builder, requested_backend


def _build_bm25_index(config: BM25BuildConfig, *, logger: LoggerAdapter) -> tuple[str, int]:
    documents = _load_bm25_documents(config.chunks_path, logger=logger)
    builder, backend_used = _instantiate_bm25_builder(config, logger=logger)
    try:
        builder.build(documents)
    except RuntimeError as exc:
        if backend_used != "lucene":
            raise
        logger.warning(
            "Lucene build failed; retrying with pure backend",
            extra={"status": "warning", "backend": backend_used, "fallback_backend": "pure"},
            exc_info=exc,
        )
        fallback_builder = cast(
            "_BM25Builder", get_bm25("pure", config.index_dir, k1=0.9, b=0.4, load_existing=False)
        )
        fallback_builder.build(documents)
        backend_used = "pure"
    except (AttributeError, ValueError, KeyError) as exc:
        msg = f"Failed to build BM25 index: {exc}"
        raise RuntimeError(msg) from exc
    return backend_used, len(documents)


_VECTOR_SCHEMA_PATH = cli_context.REPO_ROOT / "schema/vector-ingestion/vector-batch.v1.schema.json"
_VECTOR_SCHEMA_ID = "https://kgfoundry.dev/schema/vector-ingestion/vector-batch.v1.json"
_VECTOR_PROBLEM_TYPE = "https://kgfoundry.dev/problems/vector-ingestion/invalid-payload"
_VECTOR_SCHEMA_ERROR_LIMIT = 5
_VECTOR_VALIDATOR_CACHE: dict[str, Draft202012ValidatorProtocol] = {}


def _vector_batch_validator() -> Draft202012ValidatorProtocol:
    validator = _VECTOR_VALIDATOR_CACHE.get("validator")
    if validator is None:
        schema = load_schema(_VECTOR_SCHEMA_PATH)
        validator = create_draft202012_validator(cast("dict[str, object]", schema))
        _VECTOR_VALIDATOR_CACHE["validator"] = validator
    return validator


def _error_sort_key(error: ValidationErrorProtocol) -> tuple[str, ...]:
    return tuple(str(part) for part in error.path)


def _validate_vector_payload(payload: object) -> None:
    validator = _vector_batch_validator()
    errors = sorted(validator.iter_errors(payload), key=_error_sort_key)
    if not errors:
        return
    messages: list[str] = []
    for error in errors[:_VECTOR_SCHEMA_ERROR_LIMIT]:
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        messages.append(f"{location}: {error.message}")
    if len(errors) > _VECTOR_SCHEMA_ERROR_LIMIT:
        remaining = len(errors) - _VECTOR_SCHEMA_ERROR_LIMIT
        messages.append(f"... {remaining} additional validation errors")
    raise VectorValidationError(messages[0], errors=messages)


def load_vector_batch_from_json(vectors_path: str) -> VectorBatch:
    vectors_file = Path(vectors_path)
    if not vectors_file.exists():
        msg = f"Vectors file not found: {vectors_path}"
        raise FileNotFoundError(msg)
    with vectors_file.open("r", encoding="utf-8") as handle:
        payload: object = json.load(handle)
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        msg = "Dense vectors payload must be a sequence of mapping objects"
        raise VectorValidationError(msg, errors=[msg])
    _validate_vector_payload(payload)
    records = cast("Iterable[Mapping[str, object]]", payload)
    return coerce_vector_batch(records)


def _prepare_index_directory(index_path: str) -> None:
    Path(index_path).parent.mkdir(parents=True, exist_ok=True)


# Type aliases for CLI parameters to help pydoclint parse Annotated types correctly
_ChunksParquetArg = Annotated[str, typer.Argument(..., help="Path to Parquet/JSONL with chunks")]
_BackendOption = Annotated[str, typer.Option(help="lucene|pure", show_default=True)]
_IndexDirOption = Annotated[str, typer.Option(help="Output index directory", show_default=True)]
_DenseVectorsArg = Annotated[str, typer.Argument(..., help="Path to dense vectors JSON (skeleton)")]
_IndexPathOption = Annotated[str, typer.Option(help="Output FAISS index path", show_default=True)]
_FactoryOption = Annotated[str, typer.Option(help="FAISS factory string", show_default=True)]
_MetricOption = Annotated[
    str, typer.Option(help="Similarity metric ('ip' or 'l2')", show_default=True)
]


@app.command(name=SUBCOMMAND_INDEX_BM25)
def index_bm25(
    chunks_parquet: _ChunksParquetArg,
    backend: _BackendOption = "lucene",
    index_dir: _IndexDirOption = "./_indices/bm25",
) -> None:
    """Build a BM25 index from chunk metadata and emit a CLI envelope.

    Parameters
    ----------
    chunks_parquet : _ChunksParquetArg
        Path to Parquet/JSONL file with chunks. Type alias for
        ``Annotated[str, typer.Argument(...)]`` for CLI argument specification.
    backend : _BackendOption, optional
        Backend to use: 'lucene' or 'pure'. Defaults to 'lucene'. Type alias for
        ``Annotated[str, typer.Option(...)]`` for CLI option specification.
    index_dir : _IndexDirOption, optional
        Output index directory. Defaults to './_indices/bm25'. Type alias for
        ``Annotated[str, typer.Option(...)]`` for CLI option specification.

    Raises
    ------
    typer.Exit
        Raised with a non-zero exit code when index construction fails. The
        generated envelope captures the associated Problem Details payload.
    """
    context, builder = _start_command(
        SUBCOMMAND_INDEX_BM25,
        backend=backend,
        chunks_path=chunks_parquet,
        index_dir=index_dir,
    )
    builder.add_file(path=str(Path(chunks_parquet)), status="success", message="Input dataset")

    config = BM25BuildConfig(chunks_path=chunks_parquet, backend=backend, index_dir=index_dir)
    try:
        _prepare_index_directory(config.index_dir)
        backend_used, doc_count = _build_bm25_index(config, logger=context.logger)
        index_path = _get_bm25_index_path(Path(index_dir), backend_used)
        builder.add_file(
            path=str(index_path),
            status="success",
            message=f"Indexed {doc_count} documents using backend={backend_used}",
        )
        typer.echo(f"BM25 index built at {index_dir} using backend={backend_used}")
        _finish_success(context, builder)
    except FileNotFoundError as exc:
        detail = f"Chunk dataset not found: {exc}"
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_NOT_FOUND,
            error_status="config",
            exc=exc,
        )
        raise typer.Exit(code=1) from exc
    except (TypeError, json.JSONDecodeError) as exc:
        detail = f"Error loading documents: {exc}"
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_UNPROCESSABLE_ENTITY,
            error_status="violation",
            exc=exc,
        )
        raise typer.Exit(code=1) from exc
    except RuntimeError as exc:
        detail = str(exc)
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_INTERNAL_ERROR,
            exc=exc,
        )
        raise typer.Exit(code=1) from exc


def run_index_faiss(*, config: IndexCliConfig) -> dict[str, object]:
    """Build a FAISS index using ``config`` and return build metadata.

    Parameters
    ----------
    config : IndexCliConfig
        Structured configuration describing dense vector input, output index
        path, FAISS factory string, and metric type.

    Returns
    -------
    dict[str, object]
        Summary metadata including ``vector_count`` and ``dimension``.

    Notes
    -----
    Raises ``typer.Exit`` via the surrounding CLI wrapper when any underlying
    helper fails. The wrapper also renders RFC 9457 Problem Details payloads for
    downstream tooling.

    Examples
    --------
    >>> config = IndexCliConfig(
    ...     dense_vectors="vectors.json",
    ...     index_path="./_indices/faiss/shard_000.idx",
    ...     factory="Flat",
    ...     metric="ip",
    ... )
    >>> run_index_faiss(config=config)
    {'vector_count': 0, 'dimension': 0}
    """
    _prepare_index_directory(config.index_path)
    batch = load_vector_batch_from_json(config.dense_vectors)
    matrix_rows = cast("list[list[float]]", batch.matrix.tolist())
    vectors_payload: list[list[float]] = [
        [float(component) for component in row] for row in matrix_rows
    ]
    index_data: dict[str, object] = {
        "keys": [str(vector_id) for vector_id in batch.ids],
        "vectors": vectors_payload,
        "factory": config.factory,
        "metric": config.metric,
    }
    with Path(config.index_path).open("wb") as handle:
        safe_pickle.dump(index_data, handle)
    return {"vector_count": batch.count, "dimension": batch.dimension}


@app.command(name=SUBCOMMAND_INDEX_FAISS)
def index_faiss(
    dense_vectors: _DenseVectorsArg,
    index_path: _IndexPathOption = "./_indices/faiss/shard_000.idx",
    factory: _FactoryOption = "Flat",
    metric: _MetricOption = "ip",
) -> None:
    """Build a FAISS index and emit a structured CLI envelope.

    Parameters
    ----------
    dense_vectors : _DenseVectorsArg
        Path to the dense vector payload (JSON skeleton format). Type alias for
        ``Annotated[str, typer.Argument(...)]`` for CLI argument specification.
    index_path : _IndexPathOption, optional
        Destination path for the serialized FAISS index. Defaults to './_indices/faiss/shard_000.idx'.
        Type alias for ``Annotated[str, typer.Option(...)]`` for CLI option specification.
    factory : _FactoryOption, optional
        FAISS factory string describing index topology. Defaults to 'Flat'. Type alias for
        ``Annotated[str, typer.Option(...)]`` for CLI option specification.
    metric : _MetricOption, optional
        Similarity metric identifier (``"ip"`` or ``"l2"``). Defaults to 'ip'. Type alias for
        ``Annotated[str, typer.Option(...)]`` for CLI option specification.

    Raises
    ------
    typer.Exit
        Raised with a non-zero exit code when the command fails. The envelope
        captures the associated Problem Details payload for downstream tooling.

    Examples
    --------
    >>> orchestration_cli = __import__("orchestration.cli").cli
    >>> orchestration_cli.index_faiss(  # doctest: +SKIP
    ...     "vectors.json",
    ...     "./_indices/faiss/shard_000.idx",
    ...     factory="Flat",
    ...     metric="ip",
    ... )
    """
    context, builder = _start_command(
        SUBCOMMAND_INDEX_FAISS,
        factory=factory,
        metric=metric,
        dense_vectors=dense_vectors,
        index_path=index_path,
    )
    builder.add_file(
        path=str(Path(dense_vectors)), status="success", message="Dense vectors source"
    )

    config = IndexCliConfig(
        dense_vectors=dense_vectors, index_path=index_path, factory=factory, metric=metric
    )
    try:
        metadata = run_index_faiss(config=config)
        context.logger.info(
            "Building FAISS index",
            extra={
                "status": "success",
                "vectors": metadata.get("vector_count"),
                "dimension": metadata.get("dimension"),
            },
        )
        builder.add_file(
            path=str(Path(index_path)),
            status="success",
            message=f"Stored {metadata['vector_count']} vectors (dimension={metadata['dimension']})",
        )
        builder.add_file(
            path="<configuration>",
            status="success",
            message=json.dumps({"factory": factory, "metric": metric}, sort_keys=True),
        )
        typer.echo(f"FAISS index vectors stored at {index_path}")
        _finish_success(context, builder)
    except VectorValidationError as exc:
        detail = str(exc)
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_UNPROCESSABLE_ENTITY,
            error_status="violation",
            extras={
                "vector_path": dense_vectors,
                "schema_id": _VECTOR_SCHEMA_ID,
                "validation_errors": list(exc.errors) if hasattr(exc, "errors") else [],
                "errors": list(exc.errors) if hasattr(exc, "errors") else [],
            },
            overrides={"type": _VECTOR_PROBLEM_TYPE},
            exc=exc,
        )
        raise typer.Exit(code=1) from exc
    except ConfigurationError as exc:
        detail = str(exc)
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_UNPROCESSABLE_ENTITY,
            error_status="config",
            exc=exc,
        )
        raise typer.Exit(code=2) from exc
    except (TypeError, json.JSONDecodeError, FileNotFoundError) as exc:
        detail = f"Error loading vectors: {exc}"
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_BAD_REQUEST,
            error_status="config",
            exc=exc,
        )
        raise typer.Exit(code=1) from exc
    except (OSError, ValueError, RuntimeError, IndexBuildError) as exc:
        detail = f"Error saving index: {exc}"
        _handle_failure(context, detail=detail, status=STATUS_INTERNAL_ERROR, exc=exc)
        raise typer.Exit(code=1) from exc


app.command(name="index_bm25")(index_bm25)
app.command(name="index_faiss")(index_faiss)


@app.command(name=SUBCOMMAND_API)
def api(port: int = typer.Option(8080, help="Port to bind", show_default=True)) -> None:
    """Launch the FastAPI search service using uvicorn.

    Parameters
    ----------
    port : int
        Port to bind the server to. Defaults to 8080.

    Raises
    ------
    typer.Exit
        Raised when the server cannot be started (missing uvicorn entrypoint or
        missing dependency). Envelopes record the failure metadata for
        downstream tooling.
    """
    context, builder = _start_command(SUBCOMMAND_API, port=port)
    builder.add_file(path="<api>", status="success", message=f"Configured port {port}")

    try:
        uvicorn_module = importlib.import_module("uvicorn")
    except ImportError as exc:
        detail = "uvicorn is required to run the API server"
        _handle_failure(context, detail=detail, status=STATUS_INTERNAL_ERROR, exc=exc)
        raise typer.Exit(code=1) from exc

    run_attr = getattr(uvicorn_module, "run", None)
    if not callable(run_attr):
        detail = "uvicorn.run entry point not available"
        _handle_failure(context, detail=detail, status=STATUS_INTERNAL_ERROR)
        raise typer.Exit(code=1)

    typer.echo(f"Starting FastAPI service on port {port}")
    run_server = cast("_UvicornRun", run_attr)
    try:
        run_server("search_api.app:app", host="127.0.0.1", port=port, reload=False)
    except KeyboardInterrupt as exc:  # pragma: no cover - manual interruption
        detail = "API server interrupted by user"
        _handle_failure(
            context,
            detail=detail,
            status=STATUS_CLIENT_CLOSED,
            error_status="config",
            exc=exc,
        )
        raise typer.Exit(code=130) from exc
    else:
        _finish_success(context, builder)


def _run_e2e_flow() -> list[str]:
    if _e2e_flow is None:
        msg = "Prefect is required for the e2e pipeline command. Install it via `pip install -e '.[gpu]'` or add `prefect` manually."
        raise RuntimeError(msg)
    return _e2e_flow()


@app.command(name=SUBCOMMAND_E2E)
def e2e() -> None:
    """Execute the Prefect-powered end-to-end orchestration pipeline.

    Raises
    ------
    typer.Exit
        Raised with a non-zero exit code when the pipeline cannot be executed
        (for example, Prefect is not installed). The envelope captures the
        associated Problem Details payload.
    """
    context, builder = _start_command(SUBCOMMAND_E2E)
    try:
        stages = _run_e2e_flow()
    except RuntimeError as exc:
        _handle_failure(
            context,
            detail=str(exc),
            status=STATUS_INTERNAL_ERROR,
            error_status="config",
            exc=exc,
        )
        raise typer.Exit(code=1) from exc

    for index, stage in enumerate(stages):
        builder.add_file(path=f"<stage:{index}>", status="success", message=stage)
        typer.echo(stage)

    _finish_success(context, builder)


__all__ = ["api", "app", "e2e", "index_bm25", "index_faiss", "run_index_faiss"]


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    app()
