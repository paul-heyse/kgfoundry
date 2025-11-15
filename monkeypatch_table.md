| File (first patch) | Env var edits | Attribute/Item patches | Notes |
|---|---|---|---|
| tests/app/test_admin_index.py:28 | CODEINTEL_ADMIN@28, CODEINTEL_ADMIN@44, CODEINTEL_ADMIN@63, CODEINTEL_ADMIN@81 | ctx.__class__."get_coderank_faiss_manager"@52 | - |
| tests/app/test_capz.py:43 | - | capabilities_module."_import_optional"@43, capabilities_module.Capabilities."from_context"@80 | - |
| tests/app/test_lifespan_runtime_cleanup.py:86 | XTR_PRELOAD@93, HYBRID_PRELOAD@94 | ApplicationContext."create"@86, "codeintel_rev.app.main.warmup_gpu"._fake_warmup@91, "codeintel_rev.app.main.ReadinessProbe"._probe_factory@92, "codeintel_rev.app.config_context.HybridSearchEngine"._factory@126 | - |
| tests/app/test_runtime_gates.py:35 | - | config_module."gate_import"@35, config_module."gate_import"@63 | - |
| tests/cli/test_indexctl_embeddings.py:187 | - | "codeintel_rev.cli.indexctl.get_embedding_provider"._provider_factory@187 | - |
| tests/cli/test_indexctl_health.py:90 | - | "codeintel_rev.cli.indexctl._get_settings".lambda: _Settings(tmp_path)@90, "codeintel_rev.cli.indexctl._faiss_manager".lambda *_: manager@91, "codeintel_rev.cli.indexctl._duckdb_catalog".lambda *_: catalog@92, "codeintel_rev.cli.indexctl._duckdb_embedding_dim".lambda _c: 4@93, "codeintel_rev.cli.indexctl._count_idmap_rows".lambda _p: 4@94 | - |
| tests/codeintel_rev/io/test_coderank_embedder.py:29 | - | "codeintel_rev.io.coderank_embedder.gate_import"._gate_import@29 | - |
| tests/codeintel_rev/io/test_rerank_coderankllm.py:64 | - | rerank_module."gate_import"@64 | - |
| tests/codeintel_rev/io/test_vllm_engine.py:53 | - | engine_module."transformers"@62, engine_module."vllm_inputs"@68, engine_module."vllm_config"@74, engine_module."vllm"@80 | sys.modules["vllm"]@53, sys.modules["vllm.config"]@54, sys.modules["vllm.inputs"]@55 |
| tests/codeintel_rev/io/test_xtr_manager.py:70 | - | XTRIndex."encode_query_tokens"@70 | - |
| tests/codeintel_rev/mcp_server/test_semantic_pro_adapter.py:209 | - | semantic_pro."observe_duration"@209, semantic_pro."get_session_id"@210, semantic_pro."get_effective_scope"@211 | - |
| tests/codeintel_rev/retrieval/test_telemetry.py:39 | - | telemetry_module."_STAGE_DECISION_COUNTER"@39 | - |
| tests/codeintel_rev/test_app_lifespan.py:47 | REPO_ROOT@47, VLLM_URL@48, REPO_ROOT@95, VLLM_URL@96, REPO_ROOT@115, VLLM_URL@116, FAISS_PRELOAD@151 | - | - |
| tests/codeintel_rev/test_bm25_cli.py:86 | - | Paths."discover"@86, bm25_cli."_create_bm25_manager"@93, bm25_cli."_create_bm25_manager"@111 | - |
| tests/codeintel_rev/test_bm25_manager.py:46 | REPO_ROOT@46, DATA_DIR@47, FAISS_INDEX@48, DUCKDB_PATH@49, SCIP_INDEX@50, BM25_JSONL_DIR@51, BM25_INDEX_DIR@52, VLLM_URL@53, BM25_THREADS@137 | "codeintel_rev.io.bm25_manager._run_pyserini_index".fake_run@138, codeintel_rev.io.bm25_manager._detect_pyserini_version".lambda: "test@139 | - |
| tests/codeintel_rev/test_config_context.py:96 | REPO_ROOT@96, VLLM_URL@97, REPO_ROOT@118, VLLM_URL@119, REPO_ROOT@140, VLLM_URL@141, REPO_ROOT@172, VLLM_URL@173, REPO_ROOT@206, VLLM_URL@207, REPO_ROOT@234 | context.faiss_manager."load_cpu_index"@101, context.faiss_manager."clone_to_gpu"@102, context.faiss_manager."load_cpu_index"@144, context.faiss_manager."clone_to_gpu"@145, context.faiss_manager."load_cpu_index"@176, context.faiss_manager."clone_to_gpu"@177 | - |
| tests/codeintel_rev/test_duckdb_catalog.py:621 | - | test_catalog."_query_builder"@621 | - |
| tests/codeintel_rev/test_duckdb_manager.py:134 | - | "codeintel_rev.io.duckdb_manager.duckdb.connect"._instrumented_connect@134 | - |
| tests/codeintel_rev/test_faiss_dual_index.py:206 | - | faiss_module."index_cpu_to_gpu"@216 | sys.modules["torch"]@206 |
| tests/codeintel_rev/test_faiss_manager.py:38 | - | faiss_module."GpuClonerOptions"@38, faiss_module."StandardGpuResources"@47, faiss_module."index_cpu_to_gpu"@58, faiss_module."StandardGpuResources"@77 | - |
| tests/codeintel_rev/test_hybrid_explainability.py:16 | HYBRID_ENABLE_BM25@16, HYBRID_ENABLE_SPLADE@17, BM25_INDEX_DIR@18, SPLADE_INDEX_DIR@19, SPLADE_MODEL_DIR@20, SPLADE_ONNX_DIR@21 | - | - |
| tests/codeintel_rev/test_integration_full.py:53 | REPO_ROOT@53, VLLM_URL@54, FAISS_PRELOAD@55, REPO_ROOT@101, VLLM_URL@102, FAISS_PRELOAD@118, FAISS_PRELOAD@137 | - | - |
| tests/codeintel_rev/test_integration_smoke.py:97 | - | text_search_adapter."run_subprocess"@97 | - |
| tests/codeintel_rev/test_mcp_server.py:50 | REPO_ROOT@50, VLLM_URL@51 | - | - |
| tests/codeintel_rev/test_observability_common.py:168 | - | "codeintel_rev.mcp_server.common.observability._base_observe_duration"._raise_value_error@168 | - |
| tests/codeintel_rev/test_observability_runpack.py:104 | - | runpack_module."build_timeline_run_report"@104, runpack_module."latest_run_report"@105, runpack_module."build_report"@110, runpack_module."resolve_timeline_dir"@111 | - |
| tests/codeintel_rev/test_polars_writers.py:93 | - | graph_builder."gate_import"@93, uses_builder."gate_import"@115 | - |
| tests/codeintel_rev/test_semantic_adapter.py:67 | - | "codeintel_rev.mcp_server.adapters.semantic.observe_duration"._fake_observe@67 | - |
| tests/codeintel_rev/test_service_context_paths.py:96 | REPO_ROOT@96, FAISS_INDEX@97, DUCKDB_PATH@98, VECTORS_DIR@99 | config_context."_import_faiss_manager_cls"@109, config_context."DuckDBCatalog"@110, config_context."VLLMClient"@111 | - |
| tests/codeintel_rev/test_splade_cli.py:139 | - | Paths."discover"@139, splade_cli."_create_artifacts_manager"@146, splade_cli."_create_encoder_service"@172, splade_cli."_create_index_manager"@202, splade_cli."_create_encoder_service"@237 | - |
| tests/codeintel_rev/test_splade_manager.py:61 | REPO_ROOT@61, DATA_DIR@62, FAISS_INDEX@63, DUCKDB_PATH@64, SCIP_INDEX@65, BM25_JSONL_DIR@66, BM25_INDEX_DIR@67, VLLM_URL@68, SPLADE_MODEL_ID@70, SPLADE_MODEL_DIR@71, SPLADE_ONNX_DIR@72, SPLADE_ONNX_FILE@73, SPLADE_VECTORS_DIR@74, SPLADE_INDEX_DIR@75, SPLADE_PROVIDER@76, SPLADE_QUANTIZATION@77, SPLADE_MAX_TERMS@78, SPLADE_MAX_CLAUSE@79, SPLADE_BATCH_SIZE@80, SPLADE_THREADS@81 | "codeintel_rev.io.splade_manager._require_sparse_encoder".lambda: _StubEncoder@130, "codeintel_rev.io.splade_manager._require_export_helpers".fake_export_helpers@145, "codeintel_rev.io.splade_manager._require_sparse_encoder".lambda: _StubEncoder@191, "codeintel_rev.io.splade_manager._require_sparse_encoder".lambda: _StubEncoder@222, "codeintel_rev.io.splade_manager.perf_counter".lambda: next(timings)@227, "codeintel_rev.io.splade_manager.run_subprocess".fake_run@280, codeintel_rev.io.splade_manager._detect_pyserini_version".lambda: "test@281, "codeintel_rev.io.splade_manager.run_subprocess".fake_run@315 | - |
| tests/codeintel_rev/test_telemetry_reporter.py:34 | - | reporter_module."RUN_REPORT_STORE"@34, reporter_module.Capabilities."from_context"@40 | - |
| tests/codeintel_rev/test_text_search.py:54 | - | text_search."run_subprocess"@54, text_search."run_subprocess"@93, text_search."run_subprocess"@121, text_search."run_subprocess"@157 | - |
| tests/codeintel_rev/test_typing_gate_import.py:31 | - | "builtins.__import__".fake_import@31 | - |
| tests/codeintel_rev/test_vllm_client.py:44 | - | client."embed_batch"@44, httpx."AsyncClient"@67, "codeintel_rev.io.vllm_engine.InprocessVLLMEmbedder".MagicMock(return_value=fake_engine)@88 | - |
| tests/conftest.py:259 | - | Capabilities."from_context"@259 | - |
| tests/dist/test_extras_minimal_import.py:22 | - | importlib."import_module"@22 | - |
| tests/download/test_cli.py:15 | - | cli."CLI_ENVELOPE_DIR"@15 | - |
| tests/enrich/test_duckdb_ingest.py:16 | - | "codeintel_rev.enrich.duckdb_store._USE_NATIVE_JSON".True@16 | - |
| tests/enrich/test_tree_sitter_outline.py:22 | - | tsb."_USE_TS_QUERY"@22, tsb."_USE_TS_QUERY"@29 | - |
| tests/io/test_duckdb_manager.py:26 | - | "codeintel_rev.io.duckdb_manager.duckdb".duckdb_stub@26 | - |
| tests/io/test_hybrid_search_paths.py:59 | HOME@59 | - | - |
| tests/io/test_output_writers.py:12 | ENRICH_JSONL_WRITER@12 | - | - |
| tests/mcp/test_semantic_observability.py:18 | DATA_DIR@18, DATA_DIR@35 | semantic."current_trace_id"@19, semantic."current_span_id"@20, semantic_pro."current_timeline"@36, semantic_pro."current_trace_id"@37, semantic_pro."current_span_id"@38, semantic_pro."current_run_id"@39 | - |
| tests/observability/test_flight_recorder.py:10 | DATA_DIR@10 | - | - |
| tests/observability/test_run_report_writer.py:11 | CODEINTEL_DIAG_DIR@11 | - | - |
| tests/observability/test_timeline.py:21 | CODEINTEL_DIAG_DIR@21, CODEINTEL_DIAG_DIR@33, CODEINTEL_DIAG_DIR@50, CODEINTEL_DIAG_MAX_FIELD_LEN@51 | - | - |
| tests/ops/test_xtr_open.py:25 | - | "codeintel_rev.ops.runtime.xtr_open.load_settings".lambda: _settings(enabled=False)@25, "codeintel_rev.ops.runtime.xtr_open.resolve_application_paths".lambda _settings: _paths(tmp_path)@29, "codeintel_rev.ops.runtime.xtr_open.load_settings".lambda: _settings(enabled=True)@41, "codeintel_rev.ops.runtime.xtr_open.resolve_application_paths".lambda _settings: _paths(missing_root)@45, "codeintel_rev.ops.runtime.xtr_open.load_settings".lambda: _settings(enabled=True)@59, "codeintel_rev.ops.runtime.xtr_open.resolve_application_paths".lambda _settings: _paths(root)@63, "codeintel_rev.ops.runtime.xtr_open.XTRIndex"._StubIndex@78, "codeintel_rev.ops.runtime.xtr_open.load_settings".lambda: _settings(enabled=True)@90, "codeintel_rev.ops.runtime.xtr_open.resolve_application_paths".lambda _settings: _paths(root)@94, "codeintel_rev.ops.runtime.xtr_open.XTRIndex"._ExplodingIndex@110 | - |
| tests/orchestration/test_cli_envelopes.py:29 | - | orchestration_cli."CLI_ENVELOPE_DIR"@29, orchestration_cli."_build_bm25_index"@40, orchestration_cli."CLI_ENVELOPE_DIR"@68, orchestration_cli."run_index_faiss"@76 | - |
| tests/orchestration/test_index_cli_idempotency.py:212 | - | typer."echo"@212 | - |
| tests/plugins/test_registry.py:45 | - | registry_module."entry_points"@45 | - |
| tests/runtime/test_runtime_cell.py:164 | KGFOUNDRY_ALLOW_RUNTIME_SEED@164, PYTEST_CURRENT_TEST@178, KGFOUNDRY_ALLOW_RUNTIME_SEED@185, KGFOUNDRY_ALLOW_RUNTIME_SEED@221, KGFOUNDRY_ALLOW_RUNTIME_SEED@245, del KGFOUNDRY_ALLOW_RUNTIME_SEED@177 | - | - |
| tests/test_cli_runtime.py:18 | - | Paths."discover"@18, Paths."discover"@34 | - |
| tests/test_minimal_profile.py:33 | - | importlib.util."find_spec"@33 | - |
| tests/test_networking_mounts.py:95 | - | app_main."_initialize_context"@95, app_main."_shutdown_context"@96, Capabilities."from_context"@97, app_main."build_http_app"@98 | - |
| tests/test_streaming_through_proxy_headers.py:13 | SSE_MAX_KEEPALIVES@13 | - | - |
| tests/test_typing_facade.py:54 | - | typing_module."gate_import"@54 | - |
| tests/tools/test_cli_context_registry.py:88 | - | shared_registry."load_cli_tooling_context"@88, registry_module.REGISTRY."augment_for"@152 | undo@95 |
| tests/tools/test_repo_scan.py:58 | - | sys."argv"@58 | - |
| tests/vector_ingestion/test_vector_cli.py:132 | - | "orchestration.cli.uuid4".deterministic_uuid_factory@132 | - |