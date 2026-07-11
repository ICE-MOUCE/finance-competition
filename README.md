# IPO-Risk-Agent

IPO-Risk-Agent is a RAG subsystem for Hong Kong IPO prospectus risk analysis. The current repository snapshot focuses on document parsing, evidence construction, chunking, embedding, vector search, Retriever evaluation, and benchmark assets.

This GitHub snapshot is prepared for parallel development with an Agent team. It does not include the frontend demo or a final answer-generation Agent.

## Current Capabilities

- PDF/MinerU parsing pipeline
- Evidence Layer for source-grounded text, table, and image evidence
- Chunk Layer for retrieval-ready chunks
- BGE embedding generation
- FAISS VectorStore
- Layered Retriever MVP
- Gold-set Retriever evaluation
- Benchmark and gold-set evaluation assets

## Project Structure

```text
src/                  Core RAG source code
scripts/              Build, parsing, and evaluation scripts
tests/                Lightweight smoke/self-check tests
docs/                 Design docs, reports, and handoff notes
evaluation/           Gold annotations and benchmark/query sets
data/                 Local raw/generated data; ignored by Git
```

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

The default embedding model is `BAAI/bge-small-zh-v1.5`, loaded through `sentence-transformers`.

## Run Evaluation

Gold evidence recall:

```powershell
python scripts/evaluate_gold_rag.py
```

Retriever query benchmark:

```powershell
python scripts/evaluate_retriever.py
```

RAG benchmark:

```powershell
python scripts/evaluate_rag_benchmark.py --top-k 5
```

## Run Checks

```powershell
python tests/test_gold_report_summary.py
python tests/test_retriever.py
```

`tests/test_retriever.py` requires local `data/vectors/` and model availability.

## Data Policy

Large raw prospectus PDFs and generated artifacts are not intended for normal Git commits. Keep local/generated data under `data/`, and commit only small gold/query files needed for reproducible evaluation.

Ignored generated paths include `data/cache/`, `data/vectors/`, `data/processed/`, `data/chunks/`, `data/evidence/`, and `evaluation/results/`.

## Handoff Docs

- `docs/architecture/AI_CONTEXT.md`
- `docs/architecture/RAG_HANDOFF_SCOPE.md`
- `docs/evidence/EVIDENCE_DESIGN.md`
- `docs/chunk/CHUNK_DESIGN.md`
- `docs/rag/RAG_BENCHMARK_REPORT.md`
- `docs/rag/RAG_GOLD_VALIDATION_REPORT.md`
- `docs/risk/RISK_TAXONOMY.md`
- `PROJECT_PRODUCTION_REVIEW.md`
- `CORPUS_CAPACITY_PLAN.md`
