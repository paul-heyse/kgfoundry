"""Tests for the XTR runtime ops CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

from codeintel_rev.config.api import (
    CONFIG_API_VERSION,
    AppConfig,
    BM25Settings,
    DuckDBSettings,
    EmbeddingsSettings,
    FAISSSettings,
    IndexSettings,
    LoggingSettings,
    PathsConfig,
    SearchSettings,
    SpladeSettings,
    VLLMSettings,
    XTRSettings,
)
from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.ops.runtime.xtr_open import APP, XtrOpenContext
from typer.testing import CliRunner

from tests._helpers import assertions

RUNNER = CliRunner(mix_stderr=False)


def _prepare_repo(repo_root: Path) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    config_dir = repo_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "app.yml").write_text("tests: true", encoding="utf-8")
    for relative in (
        "data",
        "data/vectors",
        "logs",
        ".cache",
        ".tmp",
        "plugins",
    ):
        (repo_root / relative).mkdir(parents=True, exist_ok=True)


def _app_config_loader(
    repo_root: Path,
    *,
    xtr_enabled: bool,
    data_dir: Path | None = None,
) -> Callable[[], AppConfig]:
    """Return loader for AppConfig referencing repo_root.

    Parameters
    ----------
    repo_root : Path
        Repository root directory path.
    xtr_enabled : bool
        Whether XTR runtime should be enabled.
    data_dir : Path | None, optional
        Optional override for data directory.

    Returns
    -------
    Callable[[], AppConfig]
        Callable that returns an AppConfig instance.
    """
    data_dir = data_dir or (repo_root / "data")
    config = AppConfig(
        version=CONFIG_API_VERSION,
        paths=PathsConfig(
            repo_root=repo_root,
            data_dir=data_dir,
            cache_dir=repo_root / ".cache",
            logs_dir=repo_root / "logs",
        ),
        duckdb=DuckDBSettings(database=data_dir / "catalog.duckdb"),
        faiss=FAISSSettings(index_path=repo_root / "indexes" / "code.ivfpq.faiss"),
        bm25=BM25Settings(
            corpus_json_dir=data_dir / "bm25_json",
            index_dir=repo_root / "indexes" / "bm25",
        ),
        splade=SpladeSettings(
            model_id="naver/splade-v3",
            model_dir=repo_root / "models" / "splade",
            onnx_dir=repo_root / "models" / "splade" / "onnx",
            onnx_file="model.onnx",
            vectors_dir=data_dir / "splade_vectors",
            index_dir=repo_root / "indexes" / "splade",
            provider="CPUExecutionProvider",
            quantization=100,
            max_terms=1000,
            max_clause_count=4096,
            batch_size=16,
            threads=4,
            enabled=False,
            max_query_terms=32,
            prune_below=0.0,
            analyzer="wordpiece",
            static_prune_pct=0.0,
        ),
        xtr=XTRSettings(
            model_id="nomic-ai/CodeRankEmbed",
            device="cuda",
            max_query_tokens=256,
            candidate_k=200,
            dim=768,
            dtype="float16",
            enable=xtr_enabled,
            mode="narrow",
        ),
        embeddings=EmbeddingsSettings(),
        vllm=VLLMSettings(),
        search=SearchSettings(),
        logging=LoggingSettings(),
        index=IndexSettings(),
    )

    def _loader() -> AppConfig:
        return config

    return _loader


class _ReadyIndex:
    def __init__(self, *_: object, **__: object) -> None:
        self.ready = True

    @staticmethod
    def open() -> None:
        """No-op open."""

    @staticmethod
    def metadata() -> dict[str, object]:
        """Return stub metadata for test.

        Returns
        -------
        dict[str, object]
            Dictionary with doc_count, total_tokens, dim, and dtype.
        """
        return {"doc_count": 1, "total_tokens": 4, "dim": 8, "dtype": "float16"}


class _ExplodingIndex:
    def __init__(self, *_: object, **__: object) -> None:
        self.ready = False

    @staticmethod
    def open() -> None:
        """Raise RuntimeError to simulate corruption.

        Raises
        ------
        RuntimeError
            Always raised with message "boom".
        """
        message = "boom"
        raise RuntimeError(message)

    @staticmethod
    def metadata() -> dict[str, object]:
        """Return empty metadata stub.

        Returns
        -------
        dict[str, object]
            Empty dictionary.
        """
        return {}


def test_xtr_open_disabled_feature(
    tmp_path: Path,
    xtr_cli_context_builder: Callable[..., XtrOpenContext],
) -> None:
    """Verify XTR open returns ready=False when feature is disabled."""
    repo_root = tmp_path / "repo"
    _prepare_repo(repo_root)
    context = xtr_cli_context_builder(
        app_config_loader=_app_config_loader(repo_root, xtr_enabled=False),
    )
    result = RUNNER.invoke(
        APP,
        [],
        obj={"xtr_cli_context": context},
    )
    assertions.expect_equal(result.exit_code, 0, reason=result.stderr or result.stdout)
    payload = json.loads(result.stdout.strip())
    assertions.expect_equal(payload, {"ready": False, "limits": ["xtr disabled"]})


def test_xtr_open_missing_artifacts(
    tmp_path: Path,
    xtr_cli_context_builder: Callable[..., XtrOpenContext],
) -> None:
    """Verify XTR open returns 503 when artifacts are missing."""
    repo_root = tmp_path / "repo"
    _prepare_repo(repo_root)
    missing_parent = repo_root / "missing"
    missing_parent.mkdir(parents=True, exist_ok=True)
    context = xtr_cli_context_builder(
        app_config_loader=_app_config_loader(
            repo_root,
            xtr_enabled=True,
            data_dir=missing_parent,
        ),
    )
    result = RUNNER.invoke(
        APP,
        [],
        obj={"xtr_cli_context": context},
    )
    assertions.expect_equal(result.exit_code, 1, reason=result.stderr or result.stdout)
    problem = json.loads(result.stderr.strip())
    assertions.expect_equal(problem["status"], 503)
    assertions.expect_equal(problem["title"], "XTR artifacts unavailable")


def test_xtr_open_success(
    tmp_path: Path,
    xtr_cli_context_builder: Callable[..., XtrOpenContext],
) -> None:
    """Verify XTR open succeeds when artifacts are present."""
    repo_root = tmp_path / "repo"
    _prepare_repo(repo_root)
    root = repo_root / "data" / "xtr"
    root.mkdir(parents=True, exist_ok=True)
    context = xtr_cli_context_builder(
        app_config_loader=_app_config_loader(repo_root, xtr_enabled=True),
        index_factory=lambda *_args, **_kwargs: cast("XTRIndex", _ReadyIndex()),
    )
    result = RUNNER.invoke(
        APP,
        ["--root", str(root)],
        obj={"xtr_cli_context": context},
    )
    assertions.expect_equal(result.exit_code, 0, reason=result.stderr or result.stdout)
    payload = json.loads(result.stdout.strip())
    assertions.expect_true(payload["ready"], reason="ready should be True")
    assertions.expect_equal(payload["limits"], [])
    assertions.expect_equal(payload["metadata"]["chunks"], 1)


def test_xtr_open_reports_corruption(
    tmp_path: Path,
    xtr_cli_context_builder: Callable[..., XtrOpenContext],
) -> None:
    """Verify XTR open reports corruption errors correctly."""
    repo_root = tmp_path / "repo"
    _prepare_repo(repo_root)
    root = repo_root / "data" / "xtr"
    root.mkdir(parents=True, exist_ok=True)
    context = xtr_cli_context_builder(
        app_config_loader=_app_config_loader(repo_root, xtr_enabled=True),
        index_factory=lambda *_args, **_kwargs: cast("XTRIndex", _ExplodingIndex()),
    )
    result = RUNNER.invoke(
        APP,
        [],
        obj={"xtr_cli_context": context},
    )
    assertions.expect_equal(result.exit_code, 1, reason=result.stderr or result.stdout)
    problem = json.loads(result.stderr.strip())
    assertions.expect_equal(problem["title"], "Failed to open XTR artifacts")
