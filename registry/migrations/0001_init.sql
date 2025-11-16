
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
INSERT INTO schema_version VALUES (1);

CREATE TABLE model_registry (
  model_id TEXT,
  repo TEXT,
  revision TEXT,
  tokenizer TEXT,
  embedding_dim INT,
  vocab_size INT,
  framework TEXT,
  framework_version TEXT,
  build_info JSON,
  PRIMARY KEY (model_id, revision)
);

CREATE TABLE runs (
  run_id TEXT PRIMARY KEY,
  purpose TEXT,
  model_id TEXT,
  revision TEXT,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  config JSON
);

CREATE TABLE documents (
  doc_id TEXT PRIMARY KEY,
  openalex_id TEXT, doi TEXT, arxiv_id TEXT, pmcid TEXT,
  title TEXT, authors JSON, pub_date TIMESTAMP,
  license TEXT, language TEXT,
  pdf_uri TEXT, source TEXT,
  content_hash TEXT,
  created_at TIMESTAMP
);

CREATE TABLE doctags (
  doc_id TEXT PRIMARY KEY REFERENCES documents(doc_id),
  doctags_uri TEXT, pages INT,
  vlm_model TEXT, vlm_revision TEXT,
  avg_logprob DOUBLE,
  created_at TIMESTAMP
);

CREATE TABLE datasets (
  dataset_id TEXT PRIMARY KEY,
  kind TEXT,
  parquet_root TEXT,
  run_id TEXT REFERENCES runs(run_id),
  created_at TIMESTAMP
);

CREATE TABLE chunks (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT REFERENCES documents(doc_id),
  section TEXT, start_char INT, end_char INT,
  doctags_span JSON, tokens INT,
  dataset_id TEXT REFERENCES datasets(dataset_id),
  created_at TIMESTAMP
);

CREATE TABLE dense_runs (
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
  model TEXT, dim INT,
  parquet_root TEXT,
  created_at TIMESTAMP
);

CREATE TABLE sparse_runs (
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
  model TEXT, vocab_size INT,
  parquet_root TEXT,
  created_at TIMESTAMP,
  backend TEXT
);

CREATE TABLE faiss_indexes (
  logical_index_id TEXT,
  run_id TEXT REFERENCES dense_runs(run_id),
  shard_id INT,
  index_type TEXT, nlist INT, m INT, opq INT, nprobe INT,
  index_uri TEXT, idmap_uri TEXT,
  created_at TIMESTAMP,
  PRIMARY KEY (logical_index_id, shard_id)
);

CREATE TABLE ontologies (
  ontology_id TEXT PRIMARY KEY,
  format TEXT, src_uri TEXT,
  loaded_at TIMESTAMP, concept_count INT
);

CREATE TABLE concept_embeddings (
  ontology_id TEXT REFERENCES ontologies(ontology_id),
  model TEXT, dim INT,
  parquet_root TEXT,
  created_at TIMESTAMP,
  PRIMARY KEY (ontology_id, model)
);

CREATE TABLE link_assertions (
  id TEXT PRIMARY KEY,
  chunk_id TEXT REFERENCES chunks(chunk_id),
  concept_id TEXT,
  score DOUBLE, decision TEXT,
  evidence_span TEXT,
  features JSON,
  run_id TEXT REFERENCES runs(run_id),
  created_at TIMESTAMP
);

CREATE TABLE pipeline_events (
  event_id TEXT PRIMARY KEY,
  event_name TEXT, subject_id TEXT, payload JSON,
  created_at TIMESTAMP
);

CREATE INDEX idx_chunks_doc ON chunks(doc_id);
CREATE INDEX idx_link_chunk ON link_assertions(chunk_id);
CREATE INDEX idx_link_concept ON link_assertions(concept_id);
