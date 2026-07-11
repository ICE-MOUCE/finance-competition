# 检索精度优化方案

> 目标：关键风险要素抽取准确率 ≥ 80%，关键证据片段召回率 ≥ 85%

---

## 1. 当前问题诊断

### 1.1 问题清单

| 问题 | 影响 | 严重程度 |
|------|------|----------|
| 只索引前3-4页 | 缺少财务、风险、业务内容 | 🔴 严重 |
| 总向量仅76个 | 检索空间太小 | 🔴 严重 |
| HTML标签残留 | `<sub>` `<sup>` 污染文本 | 🟡 中等 |
| 繁体未转换 | 与查询不匹配 | 🟡 中等 |
| 图片未过滤 | 无关图片混入结果 | 🟢 轻微 |

### 1.2 根本原因

```
当前Pipeline:
PDF → MinerU(前3页) → Evidence → Chunk → Vector
                      ↑
                      只有封面和重要提示，没有财务数据
```

**正确的Pipeline应该是**：
```
PDF → MinerU(全量) → Evidence → 清洗 → Chunk → Vector
                      ↓
                包含：风险因素、财务数据、业务描述、公司治理
```

---

## 2. 优化方案

### 2.1 Phase 1：重新解析（核心）

**目标**：解析完整的招股书，重点是风险相关内容章节

**关键章节**（港股招股书标准结构）：

| 章节 | 页码范围 | 内容 | 风险相关度 |
|------|----------|------|-----------|
| 风险因素 | 30-80页 | 业务风险、财务风险、法律风险 | ⭐⭐⭐⭐⭐ |
| 业务描述 | 80-150页 | 业务模式、客户、供应商 | ⭐⭐⭐⭐ |
| 财务数据 | 150-250页 | 资产负债表、利润表、现金流 | ⭐⭐⭐⭐⭐ |
| 管理层讨论 | 250-350页 | 经营分析、风险展望 | ⭐⭐⭐⭐ |
| 公司治理 | 350-400页 | 董事、高管、关联交易 | ⭐⭐⭐⭐ |

**执行策略**：

```python
# 重新解析策略
REPARSE_CONFIG = {
    "pages": "all",           # 全量解析
    "priority_sections": [    # 优先章节
        "风险因素",
        "财务资料",
        "业务概览",
        "管理层讨论",
    ],
    "output_dir": "data/processed_v2",
}
```

### 2.2 Phase 2：文本清洗

**目标**：清理HTML标签、繁简转换、标准化

**清洗规则**：

```python
CLEANUP_RULES = {
    "remove_html_tags": True,      # 移除 <sub> <sup> 等
    "convert_traditional": True,   # 繁体 → 简体
    "normalize_whitespace": True,  # 标准化空白
    "remove_page_numbers": True,   # 移除页码标记
    "preserve_tables": True,       # 保留表格结构
}
```

**清洗示例**：

```
输入: "本公司以不同投票權控利益未必總與股東整體利"
输出: "本公司以不同投票权控利益未必总与股东整体利"

输入: "截至2023年12月31日，公司<sub>现金</sub>及<sub>现金</sub>等价物"
输出: "截至2023年12月31日，公司现金及现金等价物"
```

### 2.3 Phase 3：优化Chunk策略

**目标**：提高风险相关内容的Chunk质量

**优化点**：

1. **风险章节优先**：风险因素章节的Chunk权重更高
2. **表格独立**：财务表格不参与文本合并
3. **上下文增强**：每个Chunk包含章节路径和页码
4. **Token限制**：控制在256-512 tokens

### 2.4 Phase 4：优化Embedding

**目标**：提高向量质量

**优化点**：

1. **查询增强**：为查询添加上下文前缀
   ```
   查询: "现金流风险"
   增强: "招股书中的现金流风险因素包括：现金流风险"
   ```

2. **文档增强**：为文档添加元数据前缀
   ```
   文档: "截至2023年12月31日，公司现金..."
   增强: "[快手科技 01024.HK 风险因素] 截至2023年12月31日..."
   ```

---

## 3. 执行计划

### 3.1 任务清单

| 任务 | 优先级 | 预计时间 | 状态 |
|------|--------|----------|------|
| 重新解析3份样本（全量） | P0 | 2小时 | 待执行 |
| 文本清洗（HTML、繁简） | P0 | 0.5小时 | 待执行 |
| 优化Chunk策略 | P0 | 1小时 | 待执行 |
| 重新构建向量 | P0 | 0.5小时 | 待执行 |
| 检索测试 | P0 | 0.5小时 | 待执行 |
| 精度评估 | P0 | 1小时 | 待执行 |

### 3.2 本地执行命令

```bash
# 1. 重新解析（全量）
python scripts/run_full_pipeline.py --limit 3

# 2. 检查结果
python -c "
import json
with open('data/evidence/2021_01024_快手/evidences.json') as f:
    data = json.load(f)
print(f'Evidence数: {len(data)}')
sections = set(e.get('section_path', []) for e in data)
print(f'章节数: {len(sections)}')
"

# 3. 重新构建向量
python scripts/build_vectors.py

# 4. 测试检索
python -m streamlit run app/app.py
```

---

## 4. 精度评估标准

### 4.1 测试用例

| 查询 | 预期结果 | 评估标准 |
|------|----------|----------|
| 现金流风险 | 返回财务数据章节 | 包含"现金"关键词 |
| 对赌条款 | 返回风险因素章节 | 包含"对赌"或"赎回" |
| 关联交易 | 返回公司治理章节 | 包含"关联"关键词 |
| 客户集中度 | 返回业务描述章节 | 包含"客户"或"供应商" |

### 4.2 评估指标

```python
# 精度评估
def evaluate_precision(query, expected_keywords):
    results = retriever.search(query, top_k=10)
    relevant = sum(1 for r in results if any(kw in r.text for kw in expected_keywords))
    return relevant / len(results)

# 召回率评估
def evaluate_recall(query, expected_evidence_ids):
    results = retriever.search(query, top_k=20)
    found = sum(1 for eid in expected_evidence_ids if any(r.chunk_id.startswith(eid) for r in results))
    return found / len(expected_evidence_ids)
```

### 4.3 目标

| 指标 | 当前 | 目标 | 差距 |
|------|------|------|------|
| 关键风险要素抽取准确率 | ~30% | ≥80% | +50% |
| 关键证据片段召回率 | ~40% | ≥85% | +45% |

---

## 5. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| MinerU解析失败 | 中 | 高 | 使用pdfplumber备选 |
| 表格提取质量差 | 中 | 中 | 使用camelot补充 |
| 繁简转换错误 | 低 | 低 | 维护术语白名单 |
| 向量质量不佳 | 中 | 高 | 尝试不同Embedding模型 |

---

## 6. 下一步

1. **立即执行**：重新解析3份样本（全量）
2. **验证效果**：对比优化前后的检索精度
3. **迭代优化**：根据结果调整策略
4. **扩展规模**：全量568份招股书
