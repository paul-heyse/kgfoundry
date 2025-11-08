# 0) one-time setup (CPU stack + ORT)
make setup

# 1) export SPLADE-v3 to ONNX (optimized + int8)
make export

# 2) prepare corpora for both index types
make prepare-bm25
make encode

# 3) build both indexes
make index-bm25
make index-splade

# 4) interactive searches
make search-bm25  Q="how to claim solar credits"
make search-splade Q="how to claim solar credits"
make search-hybrid Q="how to claim solar credits"

# 5) batch: topics.tsv -> TREC run; evaluate with qrels
# topics.tsv lines: qid<TAB>query
make batch-hybrid TOPICS=data/topics.tsv RUN=runs/hybrid.trec TAG=Hybrid
make eval QRELS=data/qrels.txt RUN=runs/hybrid.trec

# 6) (optional) BM25 tuning
make tune-bm25 TOPICS=data/topics.tsv QRELS=data/qrels.txt

# 7) (optional) finetune SPLADE then re-export & re-index
make train
python playbook.py export --model-id models/splade-finetuned --out-dir models/splade-finetuned --optimize --quantize
python playbook.py encode --corpus data/corpus.jsonl --model-dir models/splade-finetuned --onnx-file onnx/model_qint8.onnx --out-dir data/splade_vectors
make index-splade
