# 架构变更日志

> Evidence-Centric Layered RAG 升级记录

---

## 1. 修改原因

### 1.1 业务需求

基于金融IPO尽调场景，发现普通RAG存在以下问题：

| 问题 | 影响 | 说明 |
|------|------|------|
| 证据丢失 | Agent无法引用原文 | Chunk切分后丢失页码、表格、图片 |
| 不可审计 | 结果不可解释 | Agent无法追溯检索结果来源 |
| 幻觉风险 | LLM生成无依据结论 | 缺少原文支撑 |
| 表格断裂 | 财务分析失效 | 表格被切分后失去结构完整性 |

### 1.2 升级目标

将RAG系统从"Chunk-based RAG"升级为"Evidence-Centric Layered RAG"：

- **Chunk → Evidence**：以Evidence为最小知识单位
- **单层索引 → 分层索引**：Financial/Legal/Governance/Market四层
- **纯文本返回 → EvidenceResult返回**：Agent可引用和审计

---

## 2. 修改前架构

### 2.1 数据流

```
PDF
 ↓
Parser (MinerU)
 ↓
Markdown
 ↓
Chunk（段落/表格/章节）
 ↓
Embedding
 ↓
Vector DB
 ↓
Retriever
 ↓
纯文本结果
```

### 2.2 问题

- Chunk是最终知识单位，丢失溯源信息
- Markdown是最终格式，不是中间格式
- 检索结果是纯文本，Agent无法引用
- 单层索引，无法按领域检索

---

## 3. 修改后架构

### 3.1 数据流

```
PDF
 ↓
MinerU 2.5 Parser
 ↓
Document Builder
 ↓
Evidence Object（最终知识单位）
 ↓
Evidence Store
 ├── Vector Index (FAISS)
 ├── Metadata Index (SQLite)
 ├── Table Store (JSON)
 └── Image Store (本地文件)
 ↓
Layered Retriever
 ├── Financial Layer
 ├── Legal Layer
 ├── Governance Layer
 └── Market Layer
 ↓
EvidenceResult（Agent可引用）
```

### 3.2 核心变化

| 维度 | 修改前 | 修改后 |
|------|--------|--------|
| 知识单位 | Chunk | Evidence |
| 最终格式 | Markdown | Evidence Object |
| 索引结构 | 单层向量索引 | 四层分层索引 |
| 检索结果 | 纯文本 | EvidenceResult |
| Agent引用 | 不支持 | 支持evidence_id |
| 页码溯源 | 可能丢失 | 必须保留 |
| 表格数据 | 可能被切分 | 完整保留 |
| 图片引用 | 通常丢失 | 保留image_path |

---

## 4. 修改的文档

### 4.1 RAG_DESIGN.md

**新增内容**：
- Evidence-Centric RAG设计理念（1.1-1.2节）
- Evidence Object定义（2.2节）
- Layered Index设计（2.3节）
- Evidence模型（4.1节）
- EvidenceResult模型（4.2节）
- EvidenceSearchResponse模型（4.4节）
- 术语表更新（附录A）

**保留内容**：
- 技术指标（更新为Evidence相关指标）
- 设计原则（更新为Evidence为核）
- 性能优化（保留）
- 扩展性设计（保留）

### 4.2 RAG_ARCHITECTURE.md

**新增内容**：
- Parser Layer（解析层）
- Evidence Layer（证据层）
- Index Layer（索引层）
- Retrieval Layer（检索层）
- Evidence-Centric索引流程（3.1节）
- Evidence-Centric查询流程（3.2节）
- Evidence Store存储结构

**修改内容**：
- 系统架构图（升级为Evidence-Centric）
- 核心模块关系（升级为Layer结构）

### 4.3 RAG_API.md

**新增内容**：
- retrieve_evidence接口（3.1节）
- EvidenceResult响应格式
- Agent引用示例

**修改内容**：
- SDK示例（升级为retrieve_evidence）
- 命令行工具（升级为retrieve-evidence）

**删除内容**：
- search_prospectus接口（被retrieve_evidence替代）
- search_cases接口（被retrieve_evidence替代）

### 4.4 RAG_RULES.md

**新增内容**：
- Evidence-Centric开发规则（第10节）
- Evidence必须保留的字段
- Retriever不能直接返回字符串
- Agent调用规范
- 禁止的操作列表

### 4.5 RAG_TASK.md

**新增内容**：
- Stage 0: MinerU验证（已完成）
- Stage 1: Evidence Object设计
- Stage 2: Evidence Store实现
- Stage 3: Layered Index
- Stage 4: Retriever + API
- 新的依赖关系图

**删除内容**：
- Phase 1-4旧任务结构
- Chunk相关任务

### 4.6 PARSER_VALIDATION_PLAN.md

**新增内容**：
- Parser输出要求（Evidence准备）
- 页码映射、标题层级、表格定位、图片引用、bbox信息
- Parser输出示例

**修改内容**：
- Pipeline流程图（升级为Evidence-Centric）

---

## 5. 对后续开发的影响

### 5.1 新增模块

| 模块 | 说明 | 优先级 |
|------|------|--------|
| evidence/models.py | Evidence数据模型 | P0 |
| evidence/builder.py | Document Builder | P0 |
| evidence/store.py | Evidence Store | P0 |
| evidence/vector_index.py | Vector Index | P0 |
| evidence/metadata_index.py | Metadata Index | P0 |
| evidence/table_store.py | Table Store | P0 |
| evidence/image_store.py | Image Store | P1 |
| index/layer_index.py | Layer Index | P0 |
| index/layer_router.py | Layer Router | P0 |
| retriever/layered_retriever.py | Layered Retriever | P0 |

### 5.2 废弃模块

| 模块 | 说明 | 替代方案 |
|------|------|----------|
| chunk/ | Chunk模块 | evidence/builder.py |
| vectordb/ | 向量数据库 | evidence/vector_index.py |
| retriever/hybrid_retriever.py | 混合检索器 | retriever/layered_retriever.py |

### 5.3 接口变化

| 接口 | 修改前 | 修改后 |
|------|--------|--------|
| 检索接口 | retrieve(query) | retrieve_evidence(query, layer) |
| 返回格式 | List[str] | List[EvidenceResult] |
| Agent引用 | 不支持 | evidence_id |

### 5.4 开发顺序

```
Stage 0: MinerU验证 ✅
    ↓
Stage 1: Evidence Object设计（当前）
    ↓
Stage 2: Evidence Store实现
    ↓
Stage 3: Layered Index
    ↓
Stage 4: Retriever + API
```

**注意**：不提前安排Agent开发，RAG模块只负责Evidence检索。

---

## 6. 验收标准

### 6.1 Evidence完整性

- 每个Evidence必须包含：evidence_id, page, section, source_file
- 表格Evidence必须包含：table_data
- 图片Evidence必须包含：image_path

### 6.2 检索结果格式

- 检索结果必须返回EvidenceResult，不能返回纯字符串
- 每个EvidenceResult必须包含：evidence_id, content, page, section, score, source

### 6.3 Agent引用能力

- Agent可通过evidence_id追溯原文
- Agent可定位page和section
- Agent可获取table_data进行财务分析

---

## 7. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Evidence构建复杂 | 开发周期延长 | 先实现基础版本，后续优化 |
| Layer索引构建慢 | 批量索引耗时 | 并行构建，增量更新 |
| 表格数据体积大 | 存储成本高 | 压缩存储，按需加载 |
| MinerU bbox信息不完整 | Evidence定位不精确 | 降级为page级定位 |
