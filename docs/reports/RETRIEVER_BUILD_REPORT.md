# Layered Retriever 构建报告

> 状态：⚠️ 需在本地环境运行测试

---

## 1. 实现清单

| 文件 | 状态 | 说明 |
|------|------|------|
| `src/retriever/config.py` | ✅ | RetrieverConfig + Layer关键词 |
| `src/retriever/models.py` | ✅ | SearchResult数据类 |
| `src/retriever/layered_retriever.py` | ✅ | LayeredRetriever类 |
| `tests/test_retriever.py` | ✅ | 测试脚本 |

---

## 2. LayeredRetriever 设计

### 2.1 检索流程

```
查询文本
    ↓
EmbeddingEngine.embed_text(query)
    ↓
VectorStore.search(query_embedding, top_k * 3)
    ↓
Layer过滤（section_path关键词匹配）
    ↓
分数过滤（min_score=0.3）
    ↓
截断（top_k）
    ↓
List[SearchResult]
```

### 2.2 Layer过滤逻辑

| Layer | 关键词 |
|-------|--------|
| financial | 财务, 现金流, 收入, 利润, 资产负债, 资产, 负债, 现金, 盈利, 亏损 |
| legal | 法律, 合规, 监管, 诉讼, 仲裁, 法规, 处罚, 罚款, 纠纷 |
| governance | 股权, 董事, 管理层, 薪酬, 关联交易, 高管, 股东, 投票权 |
| market | 市场, 竞争, 客户, 供应商, 行业, 份额, 增长, 需求 |

**过滤策略**：
1. 检查section_path是否包含关键词
2. 检查文本是否包含关键词
3. 如果过滤后结果<3个，放宽条件返回原始结果

---

## 3. 本地运行命令

```bash
conda activate ipo311
cd E:\IPO-Risk-Agent

# 确保向量已构建（如未运行）
python scripts/build_vectors.py

# 运行Retriever测试
python tests/test_retriever.py
```

---

## 4. 测试用例

| 用例 | 查询 | Layer | 预期 |
|------|------|-------|------|
| 1 | "现金流风险" | financial | 返回财务相关Chunk |
| 2 | "监管合规" | legal | 返回法律相关Chunk |
| 3 | "股权稀释" | governance | 返回治理相关Chunk |

---

## 5. 预期输出格式

```
查询: 现金流风险
Layer: financial
耗时: 0.050秒
结果数: 5

  1. chunk_id: chk_2021_01024_快手_p45_txt001
     score: 0.8234
     block_type: text
     pages: [45]
     section_path: [风险因素, 业务风险]
     preview: 截至2023年12月31日，公司现金及现金等价物为人民币5.2亿元...
```

---

## 6. 验收标准

| 检查项 | 标准 |
|--------|------|
| 3个用例均返回结果 | ✅ |
| financial查询返回财务Chunk | ✅ |
| legal查询返回法律Chunk | ✅ |
| governance查询返回治理Chunk | ✅ |
| 检索耗时 < 1秒 | ✅ |
| score >= min_score (0.3) | ✅ |

---

## 7. 代码结构

```
src/retriever/
├── __init__.py
├── config.py              # RetrieverConfig + LAYER_KEYWORDS
├── models.py              # SearchResult
└── layered_retriever.py   # LayeredRetriever
```

---

## 8. 硬性约束（已遵守）

- ✅ 未实现Agent或LLM调用
- ✅ 未修改src/embedding/或src/vector/
- ✅ 未引入新依赖
