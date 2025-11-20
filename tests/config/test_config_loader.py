"""Tests for the config loader."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.config.api import AppConfig
from codeintel_rev.config.loader import load_app_config

from tests._helpers import assertions


def _assert_splade_overrides(cfg: AppConfig, repo_root: Path) -> None:
    """Assert SPLADE configuration overrides are applied.

    Parameters
    ----------
    cfg : AppConfig
        Configuration to check.
    repo_root : Path
        Repository root for path resolution.
    """
    assertions.expect_equal(cfg.splade.model_id, "custom/splade")
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
    onnx_cfg = cfg.splade.onnx_query
    assertions.expect_true(onnx_cfg is not None, reason="Expected ONNX query config")
    if onnx_cfg is not None:
        assertions.expect_true(onnx_cfg.enabled)
        assertions.expect_equal(
            onnx_cfg.model_path,
            (repo_root / "models" / "custom" / "onnx-query" / "model.onnx").resolve(strict=False),
        )
        assertions.expect_equal(onnx_cfg.tokenizer_name, "custom-tokenizer")
        assertions.expect_equal(onnx_cfg.output_name, "scores")
        assertions.expect_equal(onnx_cfg.input_ids_name, "ids")
        assertions.expect_equal(onnx_cfg.attention_mask_name, "mask")
        assertions.expect_equal(
            onnx_cfg.providers,
            ("CUDAExecutionProvider", "CPUExecutionProvider"),
        )
        assertions.expect_equal(onnx_cfg.topn, 12)
        assertions.expect_equal(onnx_cfg.min_weight, 0.01)
        assertions.expect_true(onnx_cfg.normalize)
        assertions.expect_equal(onnx_cfg.format, "map")


def _assert_bm25_overrides(cfg: AppConfig, repo_root: Path) -> None:
    """Assert BM25 configuration overrides are applied.

    Parameters
    ----------
    cfg : AppConfig
        Configuration to check.
    repo_root : Path
        Repository root for path resolution.
    """
    bm25 = cfg.bm25
    assertions.expect_equal(
        bm25.corpus_json_dir,
        (repo_root / "data" / "custom_bm25_json").resolve(strict=False),
    )
    assertions.expect_equal(
        bm25.index_dir,
        (repo_root / "indexes" / "custom_bm25").resolve(strict=False),
    )
    assertions.expect_equal(bm25.threads, 12)
    assertions.expect_false(bm25.enabled)
    assertions.expect_equal(bm25.k1, 1.1)
    assertions.expect_equal(bm25.b, 0.6)
    assertions.expect_true(bm25.rm3_enabled)
    assertions.expect_equal(bm25.rm3_fb_docs, 14)
    assertions.expect_equal(bm25.rm3_fb_terms, 22)
    assertions.expect_equal(bm25.rm3_original_query_weight, 0.45)
    assertions.expect_equal(bm25.analyzer, "standard")
    assertions.expect_sequence_equal(list(bm25.stopwords), ["foo", "bar"])


def _assert_embeddings_overrides(cfg: AppConfig) -> None:
    """Assert embeddings configuration overrides are applied.

    Parameters
    ----------
    cfg : AppConfig
        Configuration to check.
    """
    embeddings = cfg.embeddings
    assertions.expect_equal(embeddings.provider, "hf")
    assertions.expect_equal(embeddings.model_name, "hf/testing")
    assertions.expect_equal(embeddings.device, "cuda")
    assertions.expect_equal(embeddings.batch_size, 80)
    assertions.expect_equal(embeddings.micro_batch_size, 20)
    assertions.expect_false(embeddings.normalize)
    assertions.expect_equal(embeddings.max_tokens, 8192)
    assertions.expect_equal(embeddings.max_sequence_chars, 16384)
    assertions.expect_equal(embeddings.retry_max_attempts, 5)
    assertions.expect_equal(embeddings.retry_backoff_ms, 500)
    assertions.expect_equal(embeddings.max_pending_batches, 16)
    assertions.expect_equal(embeddings.max_wait_ms, 42)
    assertions.expect_false(embeddings.allow_hf_fallback)


def _assert_vllm_overrides(cfg: AppConfig) -> None:
    """Assert VLLM configuration overrides are applied.

    Parameters
    ----------
    cfg : AppConfig
        Configuration to check.
    """
    vllm = cfg.vllm
    assertions.expect_equal(vllm.base_url, "http://localhost:9999/v1")
    assertions.expect_equal(vllm.model, "hf/testing")
    assertions.expect_equal(vllm.batch_size, 128)
    assertions.expect_equal(vllm.embedding_dim, 1024)
    assertions.expect_equal(vllm.timeout_s, 30.5)
    assertions.expect_equal(vllm.run_mode, "http")
    assertions.expect_equal(vllm.memory_utilization, 0.75)
    assertions.expect_equal(vllm.max_num_batched_tokens, 131072)
    assertions.expect_false(vllm.normalize)
    assertions.expect_equal(vllm.embedding_mode, "MEAN")
    assertions.expect_equal(vllm.max_concurrent_requests, 6)
    assertions.expect_equal(vllm.task, "embed")


def _assert_xtr_overrides(cfg: AppConfig) -> None:
    """Assert XTR configuration overrides are applied.

    Parameters
    ----------
    cfg : AppConfig
        Configuration to check.
    """
    xtr = cfg.xtr
    assertions.expect_equal(xtr.model_id, "hf/coderank")
    assertions.expect_equal(xtr.device, "cpu")
    assertions.expect_equal(xtr.max_query_tokens, 128)
    assertions.expect_equal(xtr.candidate_k, 50)
    assertions.expect_equal(xtr.dim, 1024)
    assertions.expect_equal(xtr.dtype, "float32")
    assertions.expect_true(xtr.enable)
    assertions.expect_equal(xtr.mode, "wide")


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
        "BM25_JSONL_DIR": "data/custom_bm25_json",
        "BM25_INDEX_DIR": "indexes/custom_bm25",
        "BM25_THREADS": "12",
        "HYBRID_ENABLE_BM25": "0",
        "BM25_K1": "1.1",
        "BM25_B": "0.6",
        "BM25_RM3_ENABLED": "1",
        "BM25_RM3_FB_DOCS": "14",
        "BM25_RM3_FB_TERMS": "22",
        "BM25_RM3_ORIG_WEIGHT": "0.45",
        "BM25_ANALYZER": "standard",
        "BM25_STOPWORDS": "foo,bar",
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
        "EMBED_PROVIDER": "hf",
        "EMBED_MODEL": "hf/testing",
        "EMBED_DEVICE": "cuda",
        "EMBED_BATCH_SIZE": "80",
        "EMBED_MICRO_BATCH_SIZE": "20",
        "EMBED_NORMALIZE": "0",
        "EMBED_MAX_TOKENS": "8192",
        "EMBED_MAX_SEQUENCE_CHARS": "16384",
        "EMBED_MAX_RETRIES": "5",
        "EMBED_RETRY_BACKOFF_MS": "500",
        "EMBED_MAX_PENDING_BATCHES": "16",
        "EMBED_MAX_WAIT_MS": "42",
        "EMBED_ALLOW_HF_FALLBACK": "0",
        "VLLM_URL": "http://localhost:9999/v1",
        "VLLM_MODEL": "hf/testing",
        "VLLM_BATCH_SIZE": "128",
        "VLLM_EMBED_DIM": "1024",
        "VLLM_TIMEOUT_S": "30.5",
        "VLLM_RUN_MODE": "http",
        "VLLM_MEMORY_UTILIZATION": "0.75",
        "VLLM_MAX_BATCHED_TOKENS": "131072",
        "VLLM_NORMALIZE": "0",
        "VLLM_POOLING_TYPE": "mean",
        "VLLM_MAX_CONCURRENT_REQUESTS": "6",
        "VLLM_TASK": "embed",
        "XTR_MODEL_ID": "hf/coderank",
        "XTR_DEVICE": "cpu",
        "XTR_MAX_QUERY_TOKENS": "128",
        "XTR_CANDIDATE_K": "50",
        "XTR_DIM": "1024",
        "XTR_DTYPE": "float32",
        "XTR_ENABLE": "1",
        "XTR_MODE": "wide",
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
    _assert_xtr_overrides(cfg)
    _assert_embeddings_overrides(cfg)
    _assert_vllm_overrides(cfg)
    _assert_bm25_overrides(cfg, repo_root)
    _assert_splade_overrides(cfg, repo_root)


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
    assertions.expect_equal(
        cfg.splade.model_dir, (repo_root / "models" / "splade-v3").resolve(strict=False)
    )
    assertions.expect_equal(
        cfg.splade.index_dir, (repo_root / "indexes" / "splade_v3_impact").resolve(strict=False)
    )


def test_bm25_defaults_use_repo_root(tmp_path: Path) -> None:
    """BM25 paths default to repo-root-relative directories."""
    repo_root = tmp_path / "repo"
    cfg = load_app_config(env={"BASE_DIR": str(repo_root)})
    assertions.expect_equal(
        cfg.bm25.corpus_json_dir,
        (repo_root / "data" / "bm25_json").resolve(strict=False),
    )
    assertions.expect_equal(
        cfg.bm25.index_dir,
        (repo_root / "indexes" / "bm25").resolve(strict=False),
    )
