# IPO-Risk-Agent

IPO-Risk-Agent 是一个面向港股 IPO 招股书风险分析的 RAG 子系统仓库。当前仓库快照聚焦于文档解析、Evidence 构建、Chunk 构建、Embedding、向量检索、Retriever 评估，以及 Benchmark 资产建设。

这个 GitHub 版本是为了和 Agent 开发同学并行协作准备的 RAG 交接包，不包含前端 Demo，也不包含最终的答案生成 Agent。

## 当前能力

- PDF / MinerU 解析流程
- 面向可追溯引用的 Evidence Layer，支持文本、表格、图片
- 面向检索的 Chunk Layer
- BGE Embedding 生成
- FAISS VectorStore
- Layered Retriever MVP
- Gold 集评估
- Benchmark 与 Gold 标注相关评估资产

## 项目结构

```text
src/                  RAG 核心源码
scripts/              构建、解析、评估脚本
tests/                轻量级自检与 smoke tests
docs/                 设计文档、报告与交接说明
evaluation/           Gold 标注、Benchmark 与查询集
data/                 本地原始/生成数据，默认不提交到 Git
```

## 环境准备

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

默认 Embedding 模型为 `BAAI/bge-small-zh-v1.5`，通过 `sentence-transformers` 加载。

## 运行评估

Gold Evidence 召回评估：

```powershell
python scripts/evaluate_gold_rag.py
```

Retriever 查询评估：

```powershell
python scripts/evaluate_retriever.py
```

RAG Benchmark 评估：

```powershell
python scripts/evaluate_rag_benchmark.py --top-k 5
```

## 运行检查

```powershell
python tests/test_gold_report_summary.py
python tests/test_retriever.py
```

其中 `tests/test_retriever.py` 依赖本地 `data/vectors/` 和可用模型环境。

## 数据提交规则

大体量原始招股书 PDF 和本地生成产物不应直接提交到 Git。请将本地原始数据和生成数据保留在 `data/` 下，只提交可以复现实验和评估的小体量标注文件、查询文件与报告。

默认忽略的生成路径包括：

- `data/cache/`
- `data/vectors/`
- `data/processed/`
- `data/chunks/`
- `data/evidence/`
- `evaluation/results/`

## 交接入口文档

- `docs/architecture/AI_CONTEXT.md`
- `docs/architecture/RAG_HANDOFF_SCOPE.md`
- `docs/evidence/EVIDENCE_DESIGN.md`
- `docs/chunk/CHUNK_DESIGN.md`
- `docs/rag/RAG_BENCHMARK_REPORT.md`
- `docs/rag/RAG_GOLD_VALIDATION_REPORT.md`
- `docs/risk/RISK_TAXONOMY.md`
- `PROJECT_PRODUCTION_REVIEW.md`
- `CORPUS_CAPACITY_PLAN.md`
