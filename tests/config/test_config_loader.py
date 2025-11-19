"""Tests for the config loader."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.config.loader import load_app_config

from tests._helpers import assertions


def test_env_values_override_defaults(tmp_path: Path) -> None:
    """Environment-provided values should take precedence over defaults."""
    repo_root = tmp_path / "env_repo"
    env = {
        "BASE_DIR": str(repo_root),
        "DUCKDB_THREADS": "8",
        "DUCKDB_OBJECT_CACHE": "0",
        "DUCKDB_TEMP_DIR": str(tmp_path / "tmp"),
        "DUCKDB_POOL_SIZE": "16",
        "FAISS_INDEX_PATH": str(tmp_path / "env_index.faiss"),
        "FAISS_DEFAULT_K": "42",
        "FAISS_DEFAULT_NPROBE": "128",
        "FAISS_REFINE_K_FACTOR": "2.5",
        "SEARCH_BM25_WEIGHT": "0.1",
        "SEARCH_SPLADE_WEIGHT": "0.4",
        "SEARCH_FAISS_WEIGHT": "0.5",
        "SEARCH_MAX_RESULTS": "25",
        "LOG_LEVEL": "DEBUG",
        "LOG_JSON": "1",
        "SPLADE_MODEL_ID": "custom/splade",
        "SPLADE_MODEL_DIR": "models/custom",
        "SPLADE_ONNX_DIR": "models/custom/onnx-rt",
        "SPLADE_ONNX_FILE": "custom.onnx",
        "SPLADE_VECTORS_DIR": "data/splade_vectors_custom",
        "SPLADE_INDEX_DIR": "indexes/custom_splade",
        "SPLADE_PROVIDER": "CUDAExecutionProvider",
        "SPLADE_QUANTIZATION": "200",
        "SPLADE_MAX_TERMS": "1234",
        "SPLADE_MAX_CLAUSE": "2222",
        "SPLADE_BATCH_SIZE": "64",
        "SPLADE_THREADS": "16",
        "HYBRID_ENABLE_SPLADE": "0",
        "SPLADE_MAX_QUERY_TERMS": "32",
        "SPLADE_PRUNE_BELOW": "0.5",
        "SPLADE_ANALYZER": "code",
        "SPLADE_STATIC_PRUNE_PCT": "0.1",
        "SPLADE_USE_ONNX_QUERY_ENCODER": "1",
        "SPLADE_ONNX_QUERY_MODEL": "models/custom/onnx-query/model.onnx",
        "SPLADE_ONNX_QUERY_TOKENIZER": "custom-tokenizer",
        "SPLADE_ONNX_QUERY_OUTPUT": "scores",
        "SPLADE_ONNX_QUERY_INPUT_IDS": "ids",
        "SPLADE_ONNX_QUERY_ATTENTION_MASK": "mask",
        "SPLADE_ONNX_QUERY_PROVIDERS": "CUDAExecutionProvider,CPUExecutionProvider",
        "SPLADE_ONNX_QUERY_TOPN": "12",
        "SPLADE_ONNX_QUERY_MIN_WEIGHT": "0.01",
        "SPLADE_ONNX_QUERY_NORMALIZE": "1",
        "SPLADE_ONNX_QUERY_FORMAT": "map",
    }
    cfg = load_app_config(env=env)
    assertions.expect_equal(cfg.paths.repo_root, repo_root.resolve(strict=False))
    assertions.expect_equal(cfg.duckdb.threads, 8)
    assertions.expect_false(cfg.duckdb.object_cache)
    assertions.expect_equal(
        cfg.duckdb.temp_directory, Path(env["DUCKDB_TEMP_DIR"]).resolve(strict=False)
    )
    assertions.expect_equal(cfg.duckdb.pool_size, 16)
    assertions.expect_equal(
        cfg.faiss.index_path, Path(env["FAISS_INDEX_PATH"]).resolve(strict=False)
    )
    assertions.expect_equal(cfg.faiss.default_k, 42)
    assertions.expect_equal(cfg.faiss.default_nprobe, 128)
    assertions.expect_equal(cfg.faiss.refine_k_factor, 2.5)
    assertions.expect_equal(cfg.search.max_results, 25)
    assertions.expect_equal(cfg.logging.level, "DEBUG")
    assertions.expect_true(cfg.logging.json)
    assert cfg.splade.model_id == "custom/splade"
    assertions.expect_equal(
        cfg.splade.model_dir, (repo_root / "models" / "custom").resolve(strict=False)
    )
    assertions.expect_equal(
        cfg.splade.onnx_dir, (repo_root / "models" / "custom" / "onnx-rt").resolve(strict=False)
    )
    assertions.expect_equal(cfg.splade.onnx_file, "custom.onnx")
    assertions.expect_equal(
        cfg.splade.vectors_dir,
        (repo_root / "data" / "splade_vectors_custom").resolve(strict=False),
    )
    assertions.expect_equal(
        cfg.splade.index_dir, (repo_root / "indexes" / "custom_splade").resolve(strict=False)
    )
    assertions.expect_equal(cfg.splade.provider, "CUDAExecutionProvider")
    assertions.expect_equal(cfg.splade.quantization, 200)
    assertions.expect_equal(cfg.splade.max_terms, 1234)
    assertions.expect_equal(cfg.splade.max_clause_count, 2222)
    assertions.expect_equal(cfg.splade.batch_size, 64)
    assertions.expect_equal(cfg.splade.threads, 16)
    assertions.expect_false(cfg.splade.enabled)
    assertions.expect_equal(cfg.splade.max_query_terms, 32)
    assertions.expect_equal(cfg.splade.prune_below, 0.5)
    assertions.expect_equal(cfg.splade.analyzer, "code")
    assertions.expect_equal(cfg.splade.static_prune_pct, 0.1)
    assert cfg.splade.onnx_query is not None
    assertions.expect_true(cfg.splade.onnx_query.enabled)
    assertions.expect_equal(
        cfg.splade.onnx_query.model_path,
        (repo_root / "models" / "custom" / "onnx-query" / "model.onnx").resolve(strict=False),
    )
    assertions.expect_equal(cfg.splade.onnx_query.tokenizer_name, "custom-tokenizer")
    assertions.expect_equal(cfg.splade.onnx_query.output_name, "scores")
    assertions.expect_equal(cfg.splade.onnx_query.input_ids_name, "ids")
    assertions.expect_equal(cfg.splade.onnx_query.attention_mask_name, "mask")
    assertions.expect_equal(
        cfg.splade.onnx_query.providers,
        ("CUDAExecutionProvider", "CPUExecutionProvider"),
    )
    assertions.expect_equal(cfg.splade.onnx_query.topn, 12)
    assertions.expect_equal(cfg.splade.onnx_query.min_weight, 0.01)
    assertions.expect_true(cfg.splade.onnx_query.normalize)
    assertions.expect_equal(cfg.splade.onnx_query.format, "map")


def test_loader_reads_file_and_env_precedence(tmp_path: Path) -> None:
    """File-provided settings should load, with env overrides taking precedence."""
    cfg_file = tmp_path / "config.json"
    base_dir = str(tmp_path / "file_repo")
    file_values = {
        "BASE_DIR": base_dir,
        "FAISS_DEFAULT_K": 60,
        "SEARCH_MAX_RESULTS": 9,
    }
    cfg_file.write_text(json.dumps(file_values), encoding="utf-8")
    cfg = load_app_config(file=cfg_file)
    assertions.expect_equal(cfg.paths.repo_root, Path(base_dir).resolve(strict=False))
    assertions.expect_equal(cfg.faiss.default_k, 60)
    assertions.expect_equal(cfg.search.max_results, 9)

    cfg = load_app_config(file=cfg_file, env={"FAISS_DEFAULT_K": "99"})
    assertions.expect_equal(cfg.faiss.default_k, 99)


def test_splade_defaults_use_repo_root(tmp_path: Path) -> None:
    """SPLADE paths default to repo-root-relative directories."""
    repo_root = tmp_path / "repo"
    env = {"BASE_DIR": str(repo_root)}
    cfg = load_app_config(env=env)
    assertions.expect_equal(cfg.splade.model_dir, (repo_root / "models" / "splade-v3").resolve(strict=False))
    assertions.expect_equal(cfg.splade.index_dir, (repo_root / "indexes" / "splade_v3_impact").resolve(strict=False))
