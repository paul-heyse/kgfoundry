# SPLADE-v3 (ONNX, CPU) + BM25 with Pyserini — Makefile

VENV        := .venv
PY          := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip

MODEL_ID    ?= naver/splade-v3
MODEL_DIR   ?= models/splade-v3
ONNX_FILE   ?= onnx/model_qint8.onnx

CORPUS      ?= data/corpus.jsonl
JSON_DIR    ?= data/jsonl
VEC_DIR     ?= data/splade_vectors

BM25_INDEX  ?= indexes/bm25
SPLADE_IDX  ?= indexes/splade_v3_impact

TOPICS      ?= data/topics.tsv
QRELS       ?= data/qrels.txt
RUN         ?= runs/run.trec
TAG         ?= Playbook

Q           ?= solar incentives
K           ?= 10

.PHONY: setup
setup:
	python3 -m venv $(VENV)
	$(PIP) install -U pip wheel
	# CPU Torch (serving is ONNX Runtime)
	$(PIP) install --index-url https://download.pytorch.org/whl/cpu torch torchvision torchaudio
	$(PIP) install "sentence-transformers[onnx]>=5.1.0" onnxruntime "pyserini>=1.3.0" ujson tqdm

.PHONY: export
export:
	$(PY) playbook.py export --model-id "$(MODEL_ID)" --out-dir "$(MODEL_DIR)" --optimize --quantize

.PHONY: prepare-bm25
prepare-bm25:
	$(PY) playbook.py prepare-bm25 --corpus "$(CORPUS)" --out-dir "$(JSON_DIR)"

.PHONY: index-bm25
index-bm25:
	$(PY) playbook.py index-bm25 --json-dir "$(JSON_DIR)" --index-dir "$(BM25_INDEX)"

.PHONY: encode
encode:
	$(PY) playbook.py encode --corpus "$(CORPUS)" --model-dir "$(MODEL_DIR)" --onnx-file "$(ONNX_FILE)" --out-dir "$(VEC_DIR)"

.PHONY: index-splade
index-splade:
	$(PY) playbook.py index-splade --vectors-dir "$(VEC_DIR)" --index-dir "$(SPLADE_IDX)"

.PHONY: search-bm25
search-bm25:
	$(PY) playbook.py search --mode bm25 --query "$(Q)" --k $(K) --bm25-index "$(BM25_INDEX)"

.PHONY: search-splade
search-splade:
	$(PY) playbook.py search --mode splade --query "$(Q)" --k $(K) --splade-index "$(SPLADE_IDX)" --model-dir "$(MODEL_DIR)" --onnx-file "$(ONNX_FILE)"

.PHONY: search-hybrid
search-hybrid:
	$(PY) playbook.py search --mode hybrid --query "$(Q)" --k $(K) --bm25-index "$(BM25_INDEX)" --splade-index "$(SPLADE_IDX)" --model-dir "$(MODEL_DIR)" --onnx-file "$(ONNX_FILE)"

.PHONY: batch-bm25
batch-bm25:
	$(PY) playbook.py search-batch --mode bm25 --topics "$(TOPICS)" --output "$(RUN)" --tag "$(TAG)" --bm25-index "$(BM25_INDEX)"

.PHONY: batch-splade
batch-splade:
	$(PY) playbook.py search-batch --mode splade --topics "$(TOPICS)" --output "$(RUN)" --tag "$(TAG)" --splade-index "$(SPLADE_IDX)" --model-dir "$(MODEL_DIR)" --onnx-file "$(ONNX_FILE)"

.PHONY: batch-hybrid
batch-hybrid:
	$(PY) playbook.py search-batch --mode hybrid --topics "$(TOPICS)" --output "$(RUN)" --tag "$(TAG)" --bm25-index "$(BM25_INDEX)" --splade-index "$(SPLADE_IDX)" --model-dir "$(MODEL_DIR)" --onnx-file "$(ONNX_FILE)"

.PHONY: eval
eval:
	$(PY) playbook.py eval --qrels "$(QRELS)" --run "$(RUN)" --metric ndcg_cut.10 --metric map

.PHONY: tune-bm25
tune-bm25:
	$(PY) playbook.py tune-bm25 --bm25-index "$(BM25_INDEX)" --topics "$(TOPICS)" --qrels "$(QRELS)" --k 1000

.PHONY: train
train:
	$(PY) playbook.py train --train-file data/train.jsonl --base-model "$(MODEL_ID)" --out-dir models/splade-finetuned

.PHONY: clean
clean:
	rm -rf "$(JSON_DIR)" "$(VEC_DIR)" "$(BM25_INDEX)" "$(SPLADE_IDX)" runs
