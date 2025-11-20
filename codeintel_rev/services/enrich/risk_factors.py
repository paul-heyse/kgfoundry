"""Risk factor computation for function GOIDs.

This module provides functions for computing composite risk scores for functions
based on coverage, complexity, typedness, static errors, hotspot metrics, and
test status. Aggregates multiple analytics artifacts to produce risk factor
rows for each function GOID.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from codeintel_rev.services.enrich.io import write_tabular_records

RISK_HIGH_THRESHOLD = 0.7
RISK_MEDIUM_THRESHOLD = 0.4

# Risk weights
WEIGHT_COV = 0.25
WEIGHT_COMPLEXITY = 0.2
WEIGHT_TYPEDNESS = 0.15
WEIGHT_STATIC = 0.15
WEIGHT_HOTSPOT = 0.15
WEIGHT_TESTS = 0.1
WEIGHT_FAILING = 0.0

# Default risks
RISK_VAL_HIGH = 0.7
RISK_VAL_MEDIUM = 0.4
RISK_VAL_LOW = 0.1
RISK_VAL_DEFAULT = 0.3
RISK_VAL_DEFAULT_TYPE = 0.4
RISK_VAL_UNTESTED = 0.6


@dataclass(slots=True)
class RiskFactorsRow:
    """Composite risk signals for a GOID."""

    function_goid_h128: str
    urn: str
    repo: str
    commit: str
    rel_path: str
    language: str
    kind: str
    qualname: str
    start_line: int
    end_line: int
    loc: int | None
    logical_loc: int | None
    cyclomatic_complexity: int | None
    complexity_bucket: str | None
    typedness_bucket: str | None
    typedness_source: str | None
    hotspot_score: float | None
    commit_count: int | None
    author_count: int | None
    file_typed_ratio: float | None
    static_error_count: int | None
    has_static_errors: bool | None
    executable_lines: int | None
    covered_lines: int | None
    coverage_ratio: float | None
    tested: bool | None
    test_count: int
    failing_test_count: int
    last_test_status: str
    risk_score: float
    risk_level: str
    tags: list[str]
    owners: list[str]
    created_at: str


@dataclass(slots=True)
class RiskScoreInputs:
    """Inputs used to compute a risk score."""

    coverage_ratio: float | None
    complexity_bucket: str | None
    typedness_bucket: str | None
    static_error_count: int | None
    hotspot_score: float | None
    test_count: int
    failing_test_count: int


@dataclass(slots=True)
class RiskInputs:
    """Materialized inputs for building a RiskFactorsRow."""

    goid: str
    cov_row: dict[str, object]
    metric_row: dict[str, object]
    type_row: dict[str, object]
    file_hotspot: dict[str, object]
    file_type: dict[str, object]
    diag: dict[str, object]
    module_meta: dict[str, object]
    test_count: int
    failing_count: int
    status: str
    timestamp: str


@dataclass(slots=True)
class RiskArtifacts:
    """Loaded analytics artifacts used to compute risk rows."""

    cov_functions: dict[str, dict[str, object]]
    metrics: dict[str, dict[str, object]]
    types_rows: dict[str, dict[str, object]]
    hotspots: dict[str, dict[str, object]]
    typedness: dict[str, dict[str, object]]
    static_diag: dict[str, dict[str, object]]
    modules_index: dict[str, dict[str, object]]
    test_counts: dict[str, int]
    failing_counts: dict[str, int]
    last_status: dict[str, str]

    def all_goids(self) -> set[str]:
        """Return union of GOIDs present across loaded artifacts.

        Returns
        -------
        set[str]
            GOID identifiers present in coverage or metrics inputs.
        """
        return set(self.cov_functions.keys()) | set(self.metrics.keys())

    def build_inputs(self, goid: str, timestamp: str) -> RiskInputs | None:
        """Assemble RiskInputs for a GOID or return None when path is missing.

        Parameters
        ----------
        goid : str
            GOID identifier for the function row.
        timestamp : str
            ISO8601 timestamp applied to the row.

        Returns
        -------
        RiskInputs | None
            Materialized inputs or ``None`` if the GOID lacks a path.
        """
        cov_row = self.cov_functions.get(goid, {})
        metric_row = self.metrics.get(goid, {})
        type_row = self.types_rows.get(goid, {})
        rel_path = metric_row.get("rel_path") or cov_row.get("rel_path")
        if rel_path is None:
            return None
        rel_path_str = str(rel_path)
        return RiskInputs(
            goid=goid,
            cov_row=cov_row,
            metric_row=metric_row,
            type_row=type_row,
            file_hotspot=self.hotspots.get(rel_path_str, {}),
            file_type=self.typedness.get(rel_path_str, {}),
            diag=self.static_diag.get(rel_path_str, {}),
            module_meta=self.modules_index.get(rel_path_str, {}),
            test_count=self.test_counts.get(goid, 0),
            failing_count=self.failing_counts.get(goid, 0),
            status=self.last_status.get(
                goid, "untested" if goid not in self.test_counts else "unknown"
            ),
            timestamp=timestamp,
        )


def _as_int(value: object | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_float(value: object | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_str(value: object | None) -> str:
    if value is None:
        return ""
    return str(value)


def _as_str_opt(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_bool_opt(value: object | None) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return bool(value)


def _iter_text_items(value: object | None) -> Iterable[str]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return (str(item) for item in value.values() if item is not None)
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, str)):
        return (str(item) for item in value if item is not None)
    return ()


def _as_str_list(value: object | None) -> list[str]:
    return list(_iter_text_items(value))


def _format_h128(raw: object) -> str:
    try:
        return f"{int(raw)}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(raw)


def _load_jsonl_dict(path: Path, key_field: str) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    records: dict[str, dict[str, object]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            key = _format_h128(row[key_field])
            records[key] = row
    return records


def _load_parquet_dict(path: Path, key_field: str) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    con = duckdb.connect()
    result = con.execute("SELECT * FROM read_parquet(?)", [str(path)])
    columns = [col[0] for col in result.description]
    records: dict[str, dict[str, object]] = {}
    for row in result.fetchall():
        entry = dict(zip(columns, row, strict=True))
        key = _format_h128(entry[key_field])
        records[key] = entry
    con.close()
    return records


def _load_parquet_by_path(path: Path, key_field: str) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    con = duckdb.connect()
    result = con.execute("SELECT * FROM read_parquet(?)", [str(path)])
    columns = [col[0] for col in result.description]
    records: dict[str, dict[str, object]] = {}
    for row in result.fetchall():
        entry = dict(zip(columns, row, strict=True))
        key_raw = entry.get(key_field)
        if key_raw is None:
            continue
        records[str(key_raw)] = entry
    con.close()
    return records


def _bucket_risk(score: float) -> str:
    if score >= RISK_HIGH_THRESHOLD:
        return "high"
    if score >= RISK_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def _compute_risk_score(
    inputs: RiskScoreInputs,
) -> float:
    cov_value = None if inputs.coverage_ratio is None else float(inputs.coverage_ratio)
    cov_risk = 0.7 if cov_value is None else 1.0 - max(0.0, min(1.0, cov_value))
    comp_risk = {
        "low": RISK_VAL_LOW,
        "medium": RISK_VAL_MEDIUM,
        "high": RISK_VAL_HIGH,
        None: RISK_VAL_DEFAULT,
    }.get(inputs.complexity_bucket, RISK_VAL_DEFAULT)
    type_risk = {
        "typed": RISK_VAL_LOW,
        "partial": RISK_VAL_MEDIUM,
        "untyped": RISK_VAL_HIGH,
        None: RISK_VAL_DEFAULT_TYPE,
    }.get(inputs.typedness_bucket, RISK_VAL_DEFAULT_TYPE)
    errors = int(inputs.static_error_count or 0)
    static_risk = min(errors / 10.0, 1.0)
    hotspot_norm = (
        0.0 if inputs.hotspot_score is None else min(float(inputs.hotspot_score) / 10.0, 1.0)
    )
    test_risk = 0.0 if inputs.test_count > 0 else RISK_VAL_UNTESTED
    fail_risk = min(inputs.failing_test_count * 0.2, 0.8)
    score = (
        WEIGHT_COV * cov_risk
        + WEIGHT_COMPLEXITY * comp_risk
        + WEIGHT_TYPEDNESS * type_risk
        + WEIGHT_STATIC * static_risk
        + WEIGHT_HOTSPOT * hotspot_norm
        + WEIGHT_TESTS * test_risk
        + WEIGHT_FAILING * fail_risk
    )
    return max(0.0, min(1.0, score))


def _build_risk_row(
    inputs: RiskInputs,
) -> RiskFactorsRow | None:
    cov_row = inputs.cov_row
    metric_row = inputs.metric_row
    type_row = inputs.type_row
    rel_path = _as_str(metric_row.get("rel_path") or cov_row.get("rel_path"))
    if not rel_path:
        return None

    cov_ratio = _as_float(cov_row.get("coverage_ratio"))
    complexity_bucket = _as_str_opt(metric_row.get("complexity_bucket"))
    typedness_bucket = _as_str_opt(type_row.get("typedness_bucket"))
    total_errors = _as_int(inputs.diag.get("total_errors"))
    hotspot_score = _as_float(inputs.file_hotspot.get("hotspot_score"))

    risk_score = _compute_risk_score(
        inputs=RiskScoreInputs(
            coverage_ratio=cov_ratio,
            complexity_bucket=complexity_bucket,
            typedness_bucket=typedness_bucket,
            static_error_count=total_errors,
            hotspot_score=hotspot_score,
            test_count=inputs.test_count,
            failing_test_count=inputs.failing_count,
        )
    )
    risk_level = _bucket_risk(risk_score)

    annotation_ratio = inputs.file_type.get("annotation_ratio")
    file_typed_ratio = None
    if isinstance(annotation_ratio, Mapping):
        file_typed_ratio = _as_float(annotation_ratio.get("params"))

    return RiskFactorsRow(
        function_goid_h128=inputs.goid,
        urn=_as_str(metric_row.get("urn") or cov_row.get("urn")),
        repo=_as_str(metric_row.get("repo") or cov_row.get("repo")),
        commit=_as_str(metric_row.get("commit") or cov_row.get("commit")),
        rel_path=rel_path,
        language=_as_str(metric_row.get("language") or cov_row.get("language") or "python"),
        kind=_as_str(metric_row.get("kind") or cov_row.get("kind") or "function"),
        qualname=_as_str(metric_row.get("qualname") or cov_row.get("qualname")),
        start_line=_as_int(metric_row.get("start_line") or cov_row.get("start_line")) or 0,
        end_line=_as_int(metric_row.get("end_line") or cov_row.get("end_line")) or 0,
        loc=_as_int(metric_row.get("loc")),
        logical_loc=_as_int(metric_row.get("logical_loc")),
        cyclomatic_complexity=_as_int(metric_row.get("cyclomatic_complexity")),
        complexity_bucket=complexity_bucket,
        typedness_bucket=typedness_bucket,
        typedness_source=_as_str_opt(type_row.get("typedness_source")),
        hotspot_score=hotspot_score,
        commit_count=_as_int(inputs.file_hotspot.get("commit_count")),
        author_count=_as_int(inputs.file_hotspot.get("author_count")),
        file_typed_ratio=file_typed_ratio,
        static_error_count=total_errors,
        has_static_errors=_as_bool_opt(inputs.diag.get("has_errors")),
        executable_lines=_as_int(cov_row.get("executable_lines")),
        covered_lines=_as_int(cov_row.get("covered_lines")),
        coverage_ratio=cov_ratio,
        tested=_as_bool_opt(cov_row.get("tested")),
        test_count=inputs.test_count,
        failing_test_count=inputs.failing_count,
        last_test_status=inputs.status,
        risk_score=risk_score,
        risk_level=risk_level,
        tags=_as_str_list(inputs.module_meta.get("tags")),
        owners=_as_str_list(inputs.module_meta.get("owners")),
        created_at=inputs.timestamp,
    )


def _load_test_statuses(edges_path: Path) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
    test_counts: dict[str, int] = {}
    failing_counts: dict[str, int] = {}
    last_status: dict[str, str] = {}
    if not edges_path.exists():
        return test_counts, failing_counts, last_status
    with edges_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            goid = _format_h128(row["function_goid_h128"])
            status = str(row.get("last_status") or "unknown")
            test_counts[goid] = test_counts.get(goid, 0) + 1
            if status in {"failed", "error", "xfailed"}:
                failing_counts[goid] = failing_counts.get(goid, 0) + 1
            last_status[goid] = status
    return test_counts, failing_counts, last_status


def _load_artifacts(enriched_dir: Path) -> RiskArtifacts:
    analytics_dir = enriched_dir / "analytics"
    coverage_dir = analytics_dir / "coverage"
    tests_dir = analytics_dir / "tests"
    risk_dir = analytics_dir / "risk"
    risk_dir.mkdir(parents=True, exist_ok=True)

    cov_functions = _load_jsonl_dict(
        coverage_dir / "coverage_functions.jsonl", "function_goid_h128"
    )
    metrics = _load_jsonl_dict(analytics_dir / "function_metrics.jsonl", "function_goid_h128")
    types_rows = _load_jsonl_dict(analytics_dir / "function_types.jsonl", "function_goid_h128")
    hotspots = _load_parquet_by_path(analytics_dir / "hotspots.parquet", "path")
    typedness = _load_parquet_by_path(analytics_dir / "typedness.parquet", "path")
    static_diag = _load_parquet_by_path(analytics_dir / "static_diagnostics.parquet", "rel_path")
    modules_index = _load_jsonl_dict(enriched_dir / "modules" / "modules.jsonl", "path")
    test_counts, failing_counts, last_status = _load_test_statuses(
        tests_dir / "test_coverage_edges.jsonl"
    )

    return RiskArtifacts(
        cov_functions=cov_functions,
        metrics=metrics,
        types_rows=types_rows,
        hotspots=hotspots,
        typedness=typedness,
        static_diag=static_diag,
        modules_index=modules_index,
        test_counts=test_counts,
        failing_counts=failing_counts,
        last_status=last_status,
    )


def build_goid_risk_factors(enriched_dir: Path) -> list[RiskFactorsRow]:
    """Join analytics artifacts into a single per-GOID risk table.

    Extended Summary
    ----------------
    Aggregates multiple analytics artifacts (coverage, metrics, typedness,
    hotspots, static diagnostics, test catalog) to compute composite risk
    factors for each function GOID. Computes risk scores based on weighted
    combination of coverage, complexity, typedness, static errors, hotspot
    metrics, and test status. Produces RiskFactorsRow records with risk
    scores, risk levels (high/medium/low), and risk tags.

    Parameters
    ----------
    enriched_dir : Path
        Root directory of enrichment output. Must contain analytics artifacts:
        coverage_functions.jsonl, function_metrics.jsonl, function_types.jsonl,
        hotspots.parquet, typedness.parquet, static_diagnostics.parquet,
        modules.jsonl, and test_catalog.jsonl.

    Returns
    -------
    list[RiskFactorsRow]
        List of risk factor rows, one per function GOID. Each row contains
        function metadata, aggregated metrics (LOC, complexity, coverage),
        risk score (0.0-1.0), risk level (high/medium/low), risk tags, and
        owner information. Rows are ordered by function GOID.

    Notes
    -----
    Time O(n) where n is the number of functions across all artifacts;
    memory O(n) for loading artifacts and computing risk factors. Performs
    file I/O to read multiple analytics artifacts. Thread-safe for separate
    instances. Risk scores are computed via weighted combination: 25% coverage,
    20% complexity, 15% typedness, 15% static errors, 15% hotspot, 10% test
    status. Creates risk output directory if it doesn't exist.
    """
    artifacts = _load_artifacts(enriched_dir)
    timestamp = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    rows: list[RiskFactorsRow] = []
    for goid in sorted(artifacts.all_goids()):
        inputs = artifacts.build_inputs(goid, timestamp)
        if inputs is None:
            continue
        row = _build_risk_row(inputs)
        if row:
            rows.append(row)

    return rows


def write_risk_factors(rows: Iterable[RiskFactorsRow], out_path: Path) -> None:
    """Persist risk factor rows."""
    write_tabular_records(out_path, [asdict(row) for row in rows])
