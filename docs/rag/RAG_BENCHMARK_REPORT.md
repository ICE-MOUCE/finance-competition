# RAG Benchmark 报告

> 生成时间：2026-07-12T08:07:52.735211

## 评估范围

本 Benchmark 评估的是检索 grounding 能力，而不是最终生成答案的准确率。`gold_seed` 表示来源标签已人工核验；`catalog_document_label` 只校验当前本地样本文档与检索术语，章节与页码仍需后续人工补标。

## 总体结果

| 指标 | 结果 |
|---|---:|
| 问题数量 | 60 |
| 正确文档命中率 | 81.67% (60 labeled) |
| 正确公司命中率 | 81.67% (60 labeled) |
| 预期关键词覆盖率 | 64.44% (60 条有标签) |
| 预期章节命中率 | 76.47% (17 labeled) |
| 预期页码区间命中率 | 47.06% (17 labeled) |
| Evidence 完整率 | 100.00% |
| 页码引用存在率 | 100.00% |
| 无结果占比 | 0.00% |
| 低置信问题数 | 3 |
| 向量文档数 | 10992 |

## 标签覆盖情况

- `catalog_document_label`: 43
- `gold_seed`: 17

## 失败案例分析

### 完全未命中文档

- `seed_fin_001` [financial_risk] doc=False keyword=0.5 section=True page=False
- `seed_fin_004` [financial_risk] doc=False keyword=1.0 section=True page=False
- `seed_bus_001` [business_risk] doc=False keyword=0.6667 section=True page=True
- `seed_bus_002` [business_risk] doc=False keyword=1.0 section=True page=True
- `seed_bus_005` [business_risk] doc=False keyword=0.6667 section=False page=False
- `cat_bus_009` [business_risk] doc=False keyword=0.3333 section=None page=None
- `cat_own_010` [ownership_risk] doc=False keyword=0.5 section=None page=None
- `cat_own_012` [ownership_risk] doc=False keyword=0.5 section=None page=None
- `seed_comp_001` [compliance_risk] doc=False keyword=0.3333 section=True page=True
- `cat_comp_006` [compliance_risk] doc=False keyword=1.0 section=None page=None
- `cat_ipo_005` [ipo_specific_risk] doc=False keyword=0.3333 section=None page=None

### 命中文档但未命中预期关键词

- `cat_ipo_002` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None
- `cat_ipo_004` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None
- `cat_ipo_009` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None

### 命中关键词但章节明显不对

- `seed_fin_005` [financial_risk] doc=True keyword=0.6667 section=False page=False
- `seed_bus_003` [business_risk] doc=True keyword=0.3333 section=False page=False
- `seed_bus_004` [business_risk] doc=True keyword=0.3333 section=False page=False
- `seed_bus_005` [business_risk] doc=False keyword=0.6667 section=False page=False

### 页码缺失或页码不可信

- `seed_fin_001` [financial_risk] doc=False keyword=0.5 section=True page=False
- `seed_fin_004` [financial_risk] doc=False keyword=1.0 section=True page=False
- `seed_fin_005` [financial_risk] doc=True keyword=0.6667 section=False page=False
- `seed_fin_006` [financial_risk] doc=True keyword=0.3333 section=True page=False
- `seed_fin_009` [financial_risk] doc=True keyword=1.0 section=True page=False
- `seed_bus_003` [business_risk] doc=True keyword=0.3333 section=False page=False
- `seed_bus_004` [business_risk] doc=True keyword=0.3333 section=False page=False
- `seed_bus_005` [business_risk] doc=False keyword=0.6667 section=False page=False
- `seed_comp_002` [compliance_risk] doc=True keyword=0.6667 section=True page=False

### 表格类问题

- `seed_fin_003` [financial_risk] doc=True keyword=1.0 section=True page=True
- `seed_fin_004` [financial_risk] doc=False keyword=1.0 section=True page=False
- `seed_fin_005` [financial_risk] doc=True keyword=0.6667 section=False page=False
- `cat_fin_011` [financial_risk] doc=True keyword=1.0 section=None page=None
- `seed_bus_001` [business_risk] doc=False keyword=0.6667 section=True page=True
- `seed_bus_002` [business_risk] doc=False keyword=1.0 section=True page=True
- `cat_bus_006` [business_risk] doc=True keyword=0.3333 section=None page=None
- `cat_own_002` [ownership_risk] doc=True keyword=0.5 section=None page=None
- `cat_own_008` [ownership_risk] doc=True keyword=1.0 section=None page=None
- `cat_ipo_001` [ipo_specific_risk] doc=True keyword=1.0 section=None page=None
- `cat_ipo_003` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_006` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_009` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None
- `cat_ipo_011` [ipo_specific_risk] doc=True keyword=0.6667 section=None page=None

### 治理 / 合规 / IPO 特殊风险中的低覆盖问题

- `cat_own_009` [ownership_risk] doc=True keyword=0.3333 section=None page=None
- `cat_own_011` [ownership_risk] doc=True keyword=0.3333 section=None page=None
- `seed_comp_001` [compliance_risk] doc=False keyword=0.3333 section=True page=True
- `cat_comp_007` [compliance_risk] doc=True keyword=0.3333 section=None page=None
- `cat_comp_012` [compliance_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_002` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None
- `cat_ipo_003` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_004` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None
- `cat_ipo_005` [ipo_specific_risk] doc=False keyword=0.3333 section=None page=None
- `cat_ipo_006` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_007` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_008` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None
- `cat_ipo_009` [ipo_specific_risk] doc=True keyword=0.0 section=None page=None
- `cat_ipo_010` [ipo_specific_risk] doc=True keyword=0.3333 section=None page=None

## 下一步决策建议

- 不建议仅凭这一版结果就直接上 Hybrid Retrieval。先扩充 `gold_seed`，并为 catalog 类问题补齐章节和页码标签。
- 如果扩充后的 Gold 子集显示“文档命中了，但关键词经常漏掉”，优先测试关键词过滤；如果文档和关键词都对但排序靠后，优先测试 rerank，再考虑 BM25。
- 只有在人工核验后的失败案例明确显示“精确词项没有进入向量 TopK”时，BM25 才是高优先级；如果主要问题是命错章节，再考虑章节过滤。
- 不建议仅根据这份 Benchmark 就直接启动 568 份 PDF 全量跑数，也不建议立刻开始做 RAG API；应以前面的生产就绪度审查门槛和整本 PDF 验收跑为准。
- 表格类问题应单独复盘。如果表格覆盖持续偏低，应优先改进 table description 和 table chunk 表达，而不是先改检索架构。