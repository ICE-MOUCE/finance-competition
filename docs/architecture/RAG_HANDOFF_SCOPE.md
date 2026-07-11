# RAG Handoff Scope

This repository snapshot is prepared for parallel development with an Agent team.

The upload target is the stabilized RAG stack only:

- Parser integration
- Evidence layer
- Chunk layer
- Embedding
- FAISS VectorStore
- Layered Retriever
- Evaluation and benchmark assets
- Production-readiness and corpus planning reports

The frontend demo, local planning notes, student workflow material, cached data, and legacy/archive materials are intentionally excluded from this GitHub snapshot.

## Included Code

- `src/chunk/`
- `src/embedding/`
- `src/evidence/`
- `src/retriever/`
- `src/vector/`
- `scripts/build_vectors.py`
- `scripts/evaluate_gold_rag.py`
- `scripts/evaluate_rag_benchmark.py`
- `scripts/evaluate_retrieval_quality.py`
- `scripts/evaluate_retriever.py`
- `scripts/run_full_pipeline.py`
- `tests/test_gold_report_summary.py`
- `tests/test_gold_risk_extraction_metric.py`
- `tests/test_rag_benchmark.py`
- `tests/test_retriever.py`
- `tests/test_retriever_keyword_boost.py`

## Included Evaluation Assets

- `evaluation/benchmark/benchmark_queries.json`
- `evaluation/gold/gold_risk_annotations.json`
- `evaluation/gold/gold_risk_annotations_strict_v2.json`
- `evaluation/queries/queries.json`

Generated result files under `evaluation/results/` remain local-only.

## Markdown Classification

### Include

These files are directly useful for handoff, implementation alignment, evaluation, or operations:

- `README.md`
- `CONTRIBUTING.md`
- `PROJECT_PRODUCTION_REVIEW.md`
- `CORPUS_CAPACITY_PLAN.md`
- `docs/architecture/AI_CONTEXT.md`
- `docs/architecture/ARCHITECTURE_CHANGELOG.md`
- `docs/architecture/ENVIRONMENT_SETUP.md`
- `docs/architecture/PARSER_INTERFACE_DESIGN.md`
- `docs/architecture/RAG_HANDOFF_SCOPE.md`
- `docs/chunk/CHUNK_BUILD_REPORT.md`
- `docs/chunk/CHUNK_DESIGN.md`
- `docs/evidence/EVIDENCE_BUILD_REPORT.md`
- `docs/evidence/EVIDENCE_DESIGN.md`
- `docs/rag/GOLD_LABELING_REVIEW.md`
- `docs/rag/GOLD_RAG_RESULTS_BASELINE_AFTER_KEYWORD_BOOST_REPORT.md`
- `docs/rag/GOLD_RAG_RESULTS_REPORT.md`
- `docs/rag/GOLD_RAG_RESULTS_STRICT_V2_LIVE_CHECK.md`
- `docs/rag/GOLD_RAG_RESULTS_STRICT_V2_OPTIMIZED_REPORT.md`
- `docs/rag/GOLD_RAG_RESULTS_STRICT_V2_REPORT.md`
- `docs/rag/GOLD_RAG_RESULTS_STRICT_V2_WITH_EXTRACTION_REPORT.md`
- `docs/rag/GOLD_RAG_RESULTS_WITH_EXTRACTION_REPORT.md`
- `docs/rag/RAG_BENCHMARK_REPORT.md`
- `docs/rag/RAG_GOLD_VALIDATION_REPORT.md`
- `docs/rag/RETRIEVAL_OPTIMIZATION_PLAN.md`
- `docs/rag/RETRIEVAL_QUALITY_REPORT.md`
- `docs/rag/RETRIEVER_EVALUATION_REPORT.md`
- `docs/releases/DESIGN_CHANGELOG.md`
- `docs/releases/MODEL_REVIEW_CHANGELOG.md`
- `docs/reports/DATA_ANALYSIS.md`
- `docs/reports/FULL_PIPELINE_REPORT.md`
- `docs/reports/MINERU_VALIDATION_REPORT.md`
- `docs/reports/PARSER_VALIDATION_RESULT.md`
- `docs/reports/RETRIEVER_BUILD_REPORT.md`
- `docs/reports/VECTOR_BUILD_REPORT.md`
- `docs/risk/RISK_TAXONOMY.md`

### Exclude

These files are project-related but are not part of the cleaned RAG handoff snapshot:

- `FULL_PIPELINE_REPORT.md`
  Reason: duplicated by `docs/reports/FULL_PIPELINE_REPORT.md`.
- `PROJECT_CLEANUP_PLAN.md`
  Reason: internal cleanup planning, not a runtime or handoff artifact.
- `PROJECT_STRUCTURE_REPORT.md`
  Reason: temporary structure review; superseded by `README.md` and this scope file.
- `findings.md`
  Reason: agent working notes.
- `progress.md`
  Reason: agent working notes.
- `task_plan.md`
  Reason: agent working notes.
- `docs/rag/RAG_CONSOLE.md`
  Reason: tied to the local Streamlit console, which is intentionally not uploaded now.
- `docs/experiments/EXPERIMENT_LOG.md`
  Reason: experiment journal, not part of the stable handoff surface.
- `team_work/*.md`
  Reason: student workflow and team process docs, not required for Agent-side parallel development.
- `docs/archive/**/*.md`
  Reason: historical/legacy references kept locally, excluded to avoid ambiguity.

## Non-Markdown Exclusions

- `app/`
- `app.py`
- `data/`
- `evaluation/results/`
- `scripts/parse_precision_sections.py`
- `scripts/reparse_for_precision.py`
- Python cache directories

## Handoff Contract For Agent Team

The uploaded snapshot should be treated as a retrieval-and-grounding subsystem, not as an end-user application.

Expected integration boundary:

1. The Agent team calls Retriever and receives chunk-level grounded results.
2. Grounding must preserve `document_id`, `company`, `pages`, `section_path`, `block_type`, and `evidence_ids`.
3. Agent-side answer generation should not modify parser, Evidence, Chunk, or VectorStore interfaces without coordination.
4. Benchmark and gold evaluation should remain the acceptance gate before major retrieval changes.
