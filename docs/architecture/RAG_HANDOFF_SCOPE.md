# RAG 交接范围说明

这个仓库快照是为 Agent 团队并行开发准备的 RAG 交接版本。

本次上传目标仅限已经相对稳定的 RAG 主链：

- Parser 集成
- Evidence Layer
- Chunk Layer
- Embedding
- FAISS VectorStore
- Layered Retriever
- 评估与 Benchmark 资产
- 生产化审查与容量规划报告

前端 Demo、本地规划笔记、学生协作文档、缓存数据，以及历史 archive 材料，均有意排除在这次 GitHub 交接包之外。

## 纳入的代码

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

## 纳入的评估资产

- `evaluation/benchmark/benchmark_queries.json`
- `evaluation/gold/gold_risk_annotations.json`
- `evaluation/gold/gold_risk_annotations_strict_v2.json`
- `evaluation/queries/queries.json`

`evaluation/results/` 下的结果文件仍然只保留在本地，不作为标准提交内容。

## Markdown 文件分类

### 建议保留并上传

以下文件对交接、实现对齐、评估复现或生产规划直接有用：

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

### 与项目有关，但本次不上传

以下文件虽然与项目有关，但不属于这次清理后的 RAG 交接包：

- `FULL_PIPELINE_REPORT.md`
  原因：与 `docs/reports/FULL_PIPELINE_REPORT.md` 内容重复。
- `PROJECT_CLEANUP_PLAN.md`
  原因：属于内部清理计划，不是运行或交接资产。
- `PROJECT_STRUCTURE_REPORT.md`
  原因：属于阶段性结构审查，已被 `README.md` 和本说明覆盖。
- `findings.md`
  原因：Agent 工作过程笔记。
- `progress.md`
  原因：Agent 工作过程笔记。
- `task_plan.md`
  原因：Agent 工作过程笔记。
- `docs/rag/RAG_CONSOLE.md`
  原因：依赖本地 Streamlit 控制台，而这次不交接前端。
- `docs/experiments/EXPERIMENT_LOG.md`
  原因：属于实验日志，不是稳定交接面。
- `team_work/*.md`
  原因：是学生协作流程文档，不是 Agent 并行开发的必要输入。
- `docs/archive/**/*.md`
  原因：历史/旧版材料，保留在本地即可，上传会增加歧义。

## 非 Markdown 排除项

- `app/`
- `app.py`
- `data/`
- `evaluation/results/`
- `scripts/parse_precision_sections.py`
- `scripts/reparse_for_precision.py`
- Python 缓存目录

## 给 Agent 团队的对接约定

上传后的仓库应被视为“检索与证据归因子系统”，而不是一个终端用户应用。

建议的集成边界如下：

1. Agent 团队调用 Retriever，拿到带 grounding 的 chunk 级结果。
2. 返回结果必须保留 `document_id`、`company`、`pages`、`section_path`、`block_type` 和 `evidence_ids`。
3. Agent 侧的答案生成逻辑不要擅自改 Parser、Evidence、Chunk、VectorStore 的核心接口，如需改动应先同步。
4. Benchmark 与 Gold 评估应继续作为检索改动的验收门槛。
