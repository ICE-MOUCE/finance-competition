# IPO-Risk-Agent 语料容量规划

> 规划日期：2026-07-11
>
> 范围：仅做规划分析，不修改源码、流水线配置或数据产物。

## 总体建议

第一轮生产级语料构建，建议按以下量级做容量预估：

- Evidence 约 **230 万条**
- Chunk 约 **47 万条**
- 向量约 **33 万到 47 万条**

磁盘方面，**至少预留 150 GB 可用空间，建议 250 GB**。执行策略上应按年份顺序、按小批次文档推进，并用 manifest 作为断点恢复和状态判断的唯一依据。

在 `PROJECT_PRODUCTION_REVIEW.md` 中列出的阻塞项未解决前，不建议直接启动 568 份 PDF 全量跑数。特别是：

- 页完整性校验
- 正式路径中的批量 Embedding
- 稳定的断点续跑与恢复机制

下面所有估算都采用区间，而不是单点值。原因很简单：当前本地数据同时混杂了“完整文档产物”和“历史 200-400 页局部样本”，如果直接拿来线性外推，会严重误导。

## 1. 基线与估算方法

### 当前已测本地事实

| 项目 | 实测值 | 来源 |
|---|---:|---|
| 原始 PDF 数量 | 568 | `data/raw/` 扫描 |
| 原始 PDF 总容量 | 7.24 GiB | `data/raw/` 扫描 |
| 单份 PDF 平均大小 | 13.06 MiB | `data/raw/` 扫描 |
| 最近一次 full pipeline | 3 份 PDF，12,129 条 Evidence，2,481 条 Chunk，新增 1,761 条向量 | `data/pipeline_results.json` |
| 现有向量索引 | 2,448 个向量，512 维，FAISS 文件 4.78 MiB | `data/pipeline_results.json` |
| 当前 FAISS 存储占用 | 约 2,049 bytes / vector | 4.78 MiB / 2,448；接近 `512 x float32` 加索引开销 |
| 当前 metadata 存储占用 | 需视具体内容而定 | `documents.json` 存储了文本预览和 `evidence_ids`，大小与 Chunk 长度和 fan-out 有关 |
| Parser 规划吞吐 | CPU 约 5 页/秒；GPU 约 20 页/秒 | 历史 MinerU 验证报告；还不是正式语料 benchmark |
| Embedding 配置 | BGE-small-zh-v1.5，512 维，batch size 32，默认 CPU | `src/embedding/config.py` |

### 为什么要分三档场景

本地完整文档跑数显示，平均每份文档大约有：

- 4,043 条 Evidence
- 827 条 Chunk

但仓库里同时存在很多故意只跑 `200-400` 页的局部产物，这些不能参与整库平均估算。另外，目前也没有覆盖 568 份 PDF 的正式页数 manifest。

因此在有代表性的整本 PDF 实测出来之前，先用三档场景做保守规划：

| 场景 | 单份 PDF 平均页数 | 语料总页数 | 每页 Evidence | 每页 Chunk | 解释 |
|---|---:|---:|---:|---:|---|
| 低位 | 350 | 198,800 | 7 | 1.3 | 偏短招股书、版面密度较低 |
| 基准规划 | 500 | 284,000 | 8 | 1.65 | 接近当前完整样本密度，并做保守取整 |
| 高位 | 650 | 369,200 | 9 | 2.0 | 长文档、附录多、表格密、图片多 |

估算公式：

```text
corpus_pages = 568 x average_pages_per_pdf
evidence = corpus_pages x evidence_per_page
chunks = corpus_pages x chunks_per_page
vectors = chunks x vectorization_rate
```

向量数量建议按 `70%-100%` 的区间估算。因为当前正式 full pipeline 会跳过没有可嵌入文本的 chunk，而独立向量构建脚本对 text/table 的覆盖更高，必要时也可以纳入 image chunk。最终向量数取决于图片策略和空表格描述策略。

## 2. 预估的 Evidence / Chunk / Vector 数量

| 场景 | Evidence | Chunks | 向量数（70%） | 向量数（100%） |
|---|---:|---:|---:|---:|
| 低位 | 139 万 | 258,440 | 181,000 | 258,000 |
| 基准规划 | 227 万 | 468,600 | 328,000 | 469,000 |
| 高位 | 332 万 | 738,400 | 517,000 | 738,000 |

**容量预留建议：** 即使基准规划只有约 47 万向量，也建议按 **75 万向量** 去预留 FAISS 和 metadata 空间，以覆盖长文档、表格密度和图片策略波动。

## 3. MinerU 解析时间

`run_full_pipeline.py` 默认每份 PDF 只调用一次 MinerU，且不带 `-s` / `-e` 页码参数，因此这里的估算默认是“整本 PDF 解析”。

目前代码里仍然有每份文件固定 `600` 秒超时，这本身就是生产阻塞项，所以不应把它当作排期上限。

### 纯解析计算耗时估算

| 场景 | 页数 | CPU 按 5 页/秒 | GPU 按 20 页/秒 |
|---|---:|---:|---:|
| 低位 | 198,800 | 11.0 小时 | 2.8 小时 |
| 基准规划 | 284,000 | 15.8 小时 | 3.9 小时 |
| 高位 | 369,200 | 20.5 小时 | 5.1 小时 |

### 真实运维排期估算

需要再额外计入：

- 模型加载
- PDF / 图片 I/O
- 慢文档拖尾
- 重试
- JSON 序列化
- checkpoint 落盘

| 执行模式 | 基准规划估算耗时 | 建议预留 |
|---|---:|---:|
| CPU 串行 | 24-32 小时 | 2 个自然日 |
| GPU 单 worker | 6-10 小时 | 1 个自然日 |
| GPU 双 worker，分离输出目录 | 3-6 小时 | 仅建议在小批量验证通过后尝试 |

这些 CPU/GPU 数值是基于既有验证报告推算出来的，不是 568 份语料上的正式实测。真正排期前，必须先做一个 10 文档 pilot，覆盖短文档、中位文档和最长文档。

## 4. 批量 Embedding 时间

生产路径应该使用批量 Embedding，因为 `EmbeddingEngine.embed_batch()` 已经支持 `batch size = 32`。

当前问题在于：`run_full_pipeline.py` 正式路径还是逐 chunk 调 `embed_text()`。下面这些估算，只在正式路径切换为批量嵌入之后才成立。

本地独立脚本曾在 CPU 上把 649 条向量嵌入完，用时 10.36 秒，约合 `63 vectors/s`。这个结果只能作参考，不能直接拿来乐观外推全语料。

| 场景 | 向量数 | CPU 规划速率 50-80 vectors/s | GPU 规划速率 800-2,000 vectors/s |
|---|---:|---:|---:|
| 低位 | 181k-258k | 0.6-1.4 小时 | 2-6 分钟纯计算 |
| 基准规划 | 328k-469k | 1.1-2.6 小时 | 3-10 分钟纯计算 |
| 高位 | 517k-738k | 1.8-4.1 小时 | 5-16 分钟纯计算 |

如果把 chunk 读取、Python 对象创建、FAISS 写入、JSON 落盘和校验都算进去，建议预留：

- CPU：**4-8 小时**
- GPU：**1-2 小时**

在基准规划下，GPU Embedding 通常不会是全流程瓶颈，真正的主瓶颈仍然是 MinerU 和各类产物 I/O。

## 5. 产物体积与磁盘规划

### 5.1 VectorStore 空间估算

FAISS `IndexFlatIP` 中每条向量占用：

```text
512 x 4 bytes = 2,048 bytes/vector
```

| 场景 | 向量数 | FAISS 索引 | `documents.json` | 向量总占用 |
|---|---:|---:|---:|---:|
| 低位 | 181k-258k | 0.35-0.50 GiB | 0.4-1.0 GiB | 0.8-1.5 GiB |
| 基准规划 | 328k-469k | 0.63-0.90 GiB | 0.7-1.8 GiB | 1.4-2.8 GiB |
| 高位 | 517k-738k | 0.99-1.41 GiB | 1.1-2.9 GiB | 2.1-4.4 GiB |

`documents.json` 的不确定性比 FAISS 更大，因为当前 schema 会为每条向量保存最多 500 字的文本预览和 `evidence_ids` 列表。规划上建议先按 `2-4 KiB / vector` 粗算，并在 10 文档 pilot 后用实测值替换。

### 5.2 Evidence 与 Chunk 产物大小

当前完整 Evidence 文件大约是：

- 每份招股书 `4-6 MiB`

当前完整 Chunk 文件大约是：

- 每份招股书 `1.7-3.6 MiB`

这两个数值比历史局部样本更有参考价值。

| 产物 | 低位 | 基准规划 | 高位 | 规划假设 |
|---|---:|---:|---:|---|
| Evidence JSON | 2.3 GiB | 3.5 GiB | 5.3 GiB | 每 10 万条 Evidence 约 1.0 / 1.6 / 2.4 MiB，表格和图片较多时应上浮 |
| Chunk JSON 与索引 | 1.2 GiB | 2.0 GiB | 3.2 GiB | 每条 Chunk 约 2.5-4.5 KiB，含 `evidence_ids` 和文本/表格载荷 |

这些是保守规划值。按照当前完整文档样本反推，如果很多文档都类似“大页数、重表格”的招股书，那么基准规划下的 Evidence 实际占盘可能更接近 `2.5-3.5 GiB`，甚至更高。

### 5.3 MinerU 输出与总磁盘占用

MinerU 会保留多种中间产物：

- 标注 PDF
- Markdown
- JSON
- 提取图片
- 其他中间结构

目前本地 `data/processed/` 的产物为 4 份文档共 `278 MiB`，`data/precision_chunks/` 的局部页产物为 3 份文档共 `208 MiB`。这些样本还不够干净，不能直接算出单一倍数，因此这里继续用区间做保守预留。

| 区域 | 低位 | 基准规划 | 高位 | 备注 |
|---|---:|---:|---:|---|
| 原始 PDFs | 7.24 GiB | 7.24 GiB | 7.24 GiB | 已存在 |
| MinerU 输出 | 35 GiB | 60 GiB | 100 GiB | 含原始/布局/span PDF、JSON、Markdown、图片 |
| Evidence | 2.3 GiB | 3.5 GiB | 5.3 GiB | JSON 输出 |
| Chunks | 1.2 GiB | 2.0 GiB | 3.2 GiB | JSON 和文档级索引 |
| VectorStore | 0.8 GiB | 2.0 GiB | 4.4 GiB | FAISS、metadata、报告 |
| 日志、manifest、临时文件 | 5 GiB | 10 GiB | 20 GiB | 含临时写入、副本与诊断文件 |
| **保留后的总量** | **52 GiB** | **85 GiB** | **140 GiB** | 包含原始 PDF |
| **建议可用空闲空间** | **100 GiB** | **150 GiB** | **250 GiB** | 预留重试与临时写入安全边际 |

不要被原始 PDF 只有 7.24 GiB 误导。真正占盘不确定性最大的部分，是 MinerU 生成的标注 PDF 和提取图片。

## 6. RAM / VRAM 需求

### 构建机建议

| 资源 | 最低配置 | 建议配置 | 原因 |
|---|---:|---:|---|
| 系统 RAM，CPU-only | 32 GiB | 64 GiB | MinerU、整本文档 Evidence/Chunk 物化、JSON 序列化、FAISS 以及文件缓存都会吃内存 |
| 系统 RAM，GPU 构建 | 32 GiB | 64 GiB | GPU 只减少解析和嵌入计算，不减少 Python / JSON 这部分内存 |
| GPU VRAM，MinerU + Embedding | 12 GiB | 16-24 GiB | 才比较有机会稳妥支撑 MinerU 与保守批大小的 Embedding |
| 仅 Embedding 的 GPU VRAM | 6 GiB | 8 GiB | BGE-small + batch 32 不算高，但不包含与 MinerU 并行占用 |
| 持久化 Streamlit / 检索内存 | 8 GiB | 16 GiB | 需要容纳 FAISS、`documents.json`、受控的 Evidence 缓存、模型与应用本身 |

在实测 VRAM 余量之前，不建议在同一块 GPU 上同时跑 MinerU 和 GPU Embedding。第一轮正式构建最稳妥的方式仍然是分阶段：

1. 先 parse / evidence / chunk
2. 再 batch embed / index

## 7. 主要瓶颈

1. **MinerU 全书解析与产物 I/O**：这是当前最大的时间和磁盘不确定性来源。
2. **正式路径仍是逐条 Embedding**：`run_full_pipeline.py` 还没有切到批量嵌入，这在 30 万到 70 万 Chunk 规模下不可接受。
3. **产物完整性与恢复正确性不足**：当前只要文件存在，就可能被当成“可复用完整产物”，无法区分完整、局部、过期或中断状态。
4. **FAISS 平铺索引的查询增长**：`IndexFlatIP` 在基准规模下未必立刻出问题，但查询成本线性增长，必须在最终规模上做基准。
5. **Streamlit 中无上限 Evidence 缓存**：不是批处理的第一阻塞项，但会给全语料交互使用带来明显内存风险。

## 8. 建议的全语料执行策略

### 按年份分区

建议以**年份**为顶层批次边界，在年份内部再顺序处理文档：

| 年份批次 | PDF 数量 |
|---|---:|
| 2020 | 138 |
| 2021 | 88 |
| 2022 | 87 |
| 2023 | 63 |
| 2024 | 73 |
| 2025 | 116 |

每个年份先做 **10 份 PDF** 的 pilot，通过后再扩大到 **25 份 PDF** 小批次。

同一时间内，一个输出目录只能由一个进程写入。不要让多个进程同时写：

- `data/vectors/`
- Evidence 目录
- Chunk 目录
- MinerU 输出目录

### 分阶段执行

建议顺序：

1. 先做 10 份完整 PDF 的 pilot，覆盖短文档、中位文档、长文档和表格密集文档。
2. 先完成某一年的 MinerU + Evidence + Chunk。
3. 校验页覆盖和 manifest 完整性。
4. 再基于“已完成的 Chunk 产物”批量建向量，写到新一代索引目录。
5. 做完整性检查、检索检查和样本引用检查。
6. 这一年通过后，再推进下一年。

这样做的好处是：

- 故障更容易隔离
- 检索结构调整时不必重做解析
- 第一年的实测数据可以及时反向修正容量估算

## 9. 必须补上的 checkpoint / resume 设计

下面是建议目标，不是当前代码已经实现的内容。

### 文档级 manifest 记录

每份文档都应有一条持久化记录，例如：

```json
{
  "document_id": "2021_01024_company",
  "source_path": "data/raw/...pdf",
  "source_sha256": "...",
  "source_page_count": 0,
  "parser_version": "MinerU version",
  "parser_config": {"full_pdf": true},
  "stages": {
    "mineru": {"status": "complete", "page_min": 0, "page_max": 0, "output_hash": "..."},
    "evidence": {"status": "complete", "count": 0, "output_hash": "..."},
    "chunk": {"status": "complete", "count": 0, "output_hash": "..."},
    "embedding": {"status": "complete", "vector_count": 0, "index_generation": "..."}
  },
  "attempts": 1,
  "last_error": null,
  "updated_at": "ISO-8601"
}
```

### 恢复规则

- 只有前序阶段的源文件指纹、配置指纹和页完整性都匹配时，才允许恢复后续阶段。
- 文件“存在”不等于“完成”，必须 manifest 明确标记完成，且计数与 hash 对得上。
- 失败时要保留 MinerU 的 stdout / stderr、耗时、主机资源快照，以及失败文档 / 页上下文。
- 索引应写入新一代目录；只有在 `faiss.index` 与 `documents.json` 数量一致、且所有文档向量计数核对通过后，才允许提升为当前版本。
- 严禁并发 append 到同一个索引目录。
- 失败文档应进入待重跑队列，在批次结束后统一回补，而不是在原地无限重试。

## 10. 建议的正式执行命令

以下命令是“在补齐上述生产能力后”的目标操作方式，不代表当前脚本已经具备完整 checkpoint 安全性。

```powershell
# 预跑：先做 10 份有代表性的整本 PDF pilot，并检查 manifest。
python scripts/run_full_pipeline.py --start 0 --limit 10 --rebuild-vectors

# 正式阶段 1：在页完整性校验通过后，处理一个受控文档批次。
python scripts/run_full_pipeline.py --start 0 --limit 25 --skip-mineru

# 正式阶段 2：基于已完成 Chunk 产物，用批量 Embedding 重建版本化索引。
python scripts/build_vectors.py --chunk-dir data/chunks --vector-dir data/vectors_generation_YYYY --text-only
```

当前代码里的 `--start` / `--limit` 仍然是按全局扫描顺序切片，不是按年份参数切片。在 manifest、页覆盖门禁、正式路径批量嵌入和事务化索引生成都补齐前，不建议直接无人值守跑满 568 份。

## 通过容量评审的退出标准

1. 10 文档 pilot 已经拿到真实页数、Evidence/Chunk/Vector 密度、磁盘倍率、CPU/GPU 耗时以及峰值 RAM/VRAM。
2. 每份标记完成的文档，都能证明从第 0 页到最后一页都有覆盖，或者明确记录可接受例外。
3. 每个阶段都有可恢复的 manifest 和确定性的输出指纹。
4. 至少有一整年数据可以稳定跑完，并且没有超出预留的 RAM、VRAM、磁盘和时间预算。
5. 最终索引通过向量数 / 文档数一致性校验，以及抽样检索与引用检查。
