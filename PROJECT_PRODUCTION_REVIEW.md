# IPO-Risk-Agent 生产就绪度审查

> 审查日期：2026-07-11
>
> 范围：仅做只读审查，覆盖可执行流水线、本地产物、测试和 Streamlit 应用。未修改任何生产代码。

## 总结结论

项目已经具备可运行的 RAG MVP，但**尚未达到**“完整解析 568 份港股 IPO 招股书全部页面”的生产级标准。

目前正式全流程入口默认会调用 MinerU 对整本 PDF 做解析，并不会主动限制页码范围；这一点方向是对的。但仓库里仍然保留着“只跑 200-400 页、只测三个样本”的可执行脚本，而且现有落盘产物也主要证明了小规模验证可行，不能证明全量生产可行：

- `data/raw/` 下有 568 份 PDF。
- `data/processed/` 只有 4 个文档目录；`data/precision_chunks/` 只有 3 个文档目录。
- 最近一次 full pipeline 结果只处理了 3 份 PDF，不是 568 份。
- 当前向量索引只有 2,448 个向量，覆盖 6 个文档。
- 其中 3 个文档的 Evidence JSON 只有 41-74 KB，明显更接近历史“局部页码验证”产物，不能视为整本招股书的完整结果。

当前离生产级最主要的差距在于：

- 缺少整本招股书的端到端验证
- 缺少稳定的断点续跑与版本化产物管理
- 正式全流程里没有真正使用批量 Embedding
- 失败隔离能力不足
- 缺少面向大规模跑数的可观测性

## 审查依据

- `scripts/run_full_pipeline.py`
- `scripts/parse_precision_sections.py`
- `scripts/reparse_for_precision.py`
- `src/evidence/`
- `src/chunk/`
- `src/embedding/`
- `src/vector/`
- `scripts/build_vectors.py`
- `app/app.py`
- `app/rag_console.py`
- 当前本地数据产物、报告和测试

## 1. Parser 与 MinerU 流水线

### 发现

| 分类 | 位置 | 发现 | 生产影响 |
|---|---|---|---|
| 必须修改 | `scripts/parse_precision_sections.py:3,24-48,53-67,85-106` | 这个精细解析脚本写死了三个样本和 `200-400` 页，并显式传入 MinerU 的 `-s` 和 `-e` 参数。 | 它很容易被误运行，并生成“下游接口看起来正常、但实际上不是全书”的不完整数据。必须从生产入口面移除，或者明确隔离为实验脚本。 |
| 必须修改 | `scripts/reparse_for_precision.py:39-58,118-200` | 第二个脚本同样写死了三个样本，并输出单独的 `*_v2` 产物。 | 这会让仓库长期保留一条样本专用流程，增加“哪个结果才是权威结果”的歧义。建议归档或显式隔离。 |
| 必须修改 | `scripts/run_full_pipeline.py:181` | 每次调用 MinerU 都使用固定 `600` 秒超时。 | 整本 IPO PDF 完全可能超过这个时限。当前一旦超时，只记录失败并继续，没有重试、错误分类或足够的诊断信息。 |
| 必须修改 | `scripts/run_full_pipeline.py:40-47,55-78` | PDF 发现逻辑只扫描六个写死的年份目录。 | 这虽然覆盖了当前 568 份 PDF，但对新增年份、目录命名修正或数据布局变化都不稳。生产版应改为数据驱动，并输出“预期数 vs 实际发现数”。 |
| 建议修改 | `scripts/run_full_pipeline.py:319-323` | `--start` 和 `--limit` 是按文档列表切片。 | 这个设计适合控制批次和断点恢复，不是问题本身。但需要把每次跑的 `document_id` 明确写进 manifest，避免局部批次被误认成全量结果。 |
| 无需修改 | `scripts/run_full_pipeline.py:160-176` | 默认 MinerU 命令没有传 `-s` / `-e` 页码参数。 | 这是整本 PDF 解析的正确默认行为。 |
| 无需修改 | `src/evidence/parser.py:104-134` | 遍历 `content_list.json` 时没有页码过滤或样本过滤。 | 只要 MinerU 结果是完整的，这里就能消费整本 PDF 的 block。 |

### 关于 MinerU 默认是否解析整本 PDF

答案是：**是的**。

当前正式入口 `run_full_pipeline.py` 默认请求 MinerU 解析整本 PDF。局部页码行为只存在于 `parse_precision_sections.py` 这类实验脚本里。

但需要强调：只要这些脚本还可执行、产物目录又没有强隔离，它们就仍然是生产风险。

## 2. Evidence Builder

| 分类 | 位置 | 发现 | 生产影响 |
|---|---|---|---|
| 必须修改 | `src/evidence/builder.py:44-92,101-154` 与 `src/evidence/parser.py:104-134` | 会先把完整 `content_list.json`、全部 `RawBlock`、全部 Evidence 对象都加载到内存，再统一保存。 | 当前虽然没有 Evidence 数量上限，这是对完整性的好事；但对于长招股书，没有内存预算也没有流式方案。跑 568 份之前必须先测最坏情况容量。 |
| 必须修改 | `src/evidence/store.py:16-34` | 被访问过的文档都会缓存为内存中的 `evidence_id -> evidence` 映射，且没有缓存上限或失效机制。 | 长时间运行的 Streamlit 进程如果访问很多整本招股书，会无限保留 Evidence 数据，存在明显内存膨胀风险。 |
| 建议修改 | `src/evidence/builder.py` 保存路径 | 目前 Evidence 产物没有输入指纹、解析配置指纹、页数校验或“完整完成标记”。 | `run_full_pipeline.py:357-364` 会把“文件存在”直接当成“可以复用”，这会把历史局部产物误当作完整产物。 |
| 无需修改 | `src/evidence/builder.py:101-154` | Builder 会遍历所有合格 block，没有写死 Evidence 数量限制。 | 核心逻辑本身并不假设只有 200-400 页。 |

## 3. Chunk 流水线

| 分类 | 位置 | 发现 | 生产影响 |
|---|---|---|---|
| 建议修改 | `src/chunk/builder.py:42-144` | 会先把一个文档的全部 Evidence 拆分类别、排序，再统一在内存里构建 Chunk。 | 逻辑上支持整本 PDF，但峰值内存会随文档长度增长。需要对最大招股书做实测。 |
| 建议修改 | `src/chunk/store.py:30-42` | 每个文档的 Chunk 都一次性落成一个 `chunks.json`。 | MVP 阶段这样很简单，但文档变大后，重处理和加载成本会上升。短期比改接口更重要的是增加 manifest 和完成状态。 |
| 无需修改 | `src/chunk/builder.py:75-144,178-282` | 文本按页排序，表格和图片也会遍历完整 Evidence 列表，没有页码上限假设。 | 结构上兼容整本 PDF。 |

## 4. Embedding 流水线

| 分类 | 位置 | 发现 | 生产影响 |
|---|---|---|---|
| 必须修改 | `scripts/run_full_pipeline.py:236-290`，尤其是 `:273` | 正式全流程里是逐 chunk 调用 `engine.embed_text()`。 | 面对几十万 chunk，这个实现会非常慢。仓库里虽然已有 `embed_batch()`，但正式路径并没有复用。 |
| 必须修改 | `scripts/run_full_pipeline.py:241-290` | 会先把一个文档的全部 `VectorDocument` 都留在内存里，再一起写入 FAISS。 | 文档越长，峰值内存越大。生产版应该做成分批嵌入、分批写入、分批记录进度。 |
| 建议修改 | `src/embedding/engine.py:55-75` | `embed_batch()` 虽然支持批处理，但还没有围绕批大小、设备、OOM 重试等做容量验证。 | 基础能力已经有了，缺的是生产级容量参数和失败恢复机制。 |
| 无需修改 | `scripts/build_vectors.py:101-141` | 独立向量构建路径已经使用 `embed_batch()`。 | 这是正式全流程应该复用的正确方向。 |

## 5. Vector Store

| 分类 | 位置 | 发现 | 生产影响 |
|---|---|---|---|
| 必须修改 | `src/vector/store.py:26-29,139-177` | 使用 `faiss.IndexFlatIP`，并在加载时把整个索引和全部 metadata 一次性读入内存。 | 作为 MVP 可以接受，但查询复杂度线性增长，metadata 内存也会持续上升。当前还没有做针对目标规模的容量验证。 |
| 必须修改 | `scripts/run_full_pipeline.py:406-410` 与 `src/vector/store.py:60-88` | 复跑时会对已存在 chunk 重新做 embedding，再依赖 `chunk_id` 去重跳过重复写入。 | 这会浪费 embedding 时间，更关键的是“同一 `chunk_id` 内容变了也不会更新旧向量”，缺乏真正的增量更新语义。 |
| 必须修改 | `src/vector/store.py:121-135` | `faiss.index` 和 `documents.json` 是分别替换的。 | 如果中途崩溃，索引和 metadata 很可能不一致，而加载时又没有完整一致性校验。 |
| 建议修改 | `scripts/build_vectors.py:49-57,73-79` | 默认是全量重建，`--append` 只是简单追加并跳过重复 `chunk_id`。 | 这只能算基础 append 能力，离生产需要的 manifest、删除感知、版本化更新、覆盖率校验还差很远。 |
| 无需修改 | `src/vector/store.py:64-88` | `chunk_id` 去重可以防止重复向量被重复写入。 | 这是一个有用的底线保护，但不等于完整的增量更新方案。 |

## 6. Streamlit

| 分类 | 位置 | 发现 | 生产影响 |
|---|---|---|---|
| 建议修改 | `app/app.py:391-408`，`app/rag_console.py:65-79` | 两个应用都会缓存完整向量索引；`rag_console.py` 还会递归缓存 PDF 列表。 | 当前并没有写死“三个样本”，但在大语料下需要补启动健康检查、索引版本展示、覆盖率展示和 Evidence 缓存上限。 |
| 建议修改 | `app/app.py:466-527`，`app/rag_console.py:82-87,301-353` | Gold 评估依赖的是小规模本地标注集。 | 它适合做 Retriever 回归检查，但不能证明 568 份 PDF 的完整入库和页码可信性。 |
| 无需修改 | `app/rag_console.py:100-111,228-235` | PDF 路径是动态扫描的，不是样本写死。 | 当前 UI 并没有三样本硬编码问题。 |

## 测试与运维缺口

### 必须补齐

1. 增加一份“完整招股书端到端验收跑”，校验 PDF 页数、解析覆盖页、Evidence/Chunk 数量、首页与末页是否存在、引用是否可追溯、向量是否齐全、重启后是否可恢复。
2. 增加 568 文档级别的 manifest，记录每份文档的 `document_id`、源文件校验和、页数、解析版本、阶段状态、尝试次数、耗时、产物计数和失败原因。
3. 增加自动校验，防止局部页码产物在未标记实验状态时混入正式 `data/evidence`、`data/chunks` 和向量索引。
4. 增加最大 PDF 和全语料级容量基准：总耗时、CPU/GPU、峰值 RAM/VRAM、磁盘占用、向量数、索引大小、查询时延。
5. 增加 `faiss.index`、`documents.json`、Chunk 产物和 Evidence 产物之间的一致性检查。

### 建议补齐

1. 进一步把实验数据目录和正式数据目录彻底隔离，不仅靠命名区分。
2. 为 MinerU 失败增加重试、退避和诊断输出，而不是固定一个超时策略。
3. 增加结构化日志和机器可读报表，用于追踪完成率、页覆盖率、失败情况和资源消耗。
4. 在全量解析前明确数据保留和清理策略，因为 MinerU 中间产物、图片、Evidence、Chunk、向量都会明显占盘。
5. 扩展测试范围。目前测试还没有覆盖 MinerU、完整 Evidence/Chunk 路径、568 文档发现、断点恢复和更新一致性。

## 当前距离生产级还差什么

当前架构方向本身没有问题：

- 正式 MinerU 默认是整本 PDF 解析
- Evidence / Chunk 核心逻辑没有 200-400 页假设
- 批量 Embedding 能力已经存在
- VectorStore 也有最基础的去重保护

真正缺的不是“再加几个功能”，而是**面向大语料运行的工程正确性**：

- 至少跑通一份整本招股书的全链路验收
- 再跑通一轮可观察、可恢复、可校验的 568 份批处理
- 在正式全流程中切换到批量 Embedding
- 建立完整的增量更新与产物版本语义
- 证明内存、磁盘、耗时和检索质量都在可控范围内

当前这个“2,448 向量、6 份文档、3 份 full pipeline”的结果，可以证明 MVP 是通的，但还不能当作生产就绪证据。
