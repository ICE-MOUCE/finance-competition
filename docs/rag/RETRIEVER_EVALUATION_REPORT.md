# Retriever 评估报告

> 生成时间：2026-07-11T17:43:22.364479

## 评估摘要

| 指标 | 数值 |
|---|---:|
| 测试问题数 | 22 |
| TopK 命中率 | 100.00% |
| 平均关键词覆盖率 | 31.61% |
| 平均 Evidence 完整率 | 100.00% |
| 平均页码引用率 | 100.00% |
| 失败案例数 | 0 |
| 向量数量 | 10992 |

## 当前效果

当前 Retriever 可以为完整风险测试集返回带 Evidence 和页码引用的 chunks。本报告只评估检索质量，不评估未来 Risk Agent 的最终回答质量。

## 失败案例

- 本次没有 TopK 关键词命中失败案例。

## 分问题指标

| ID | 分类 | 检索层 | TopK 命中 | 关键词覆盖率 | Evidence 完整率 | 页码引用率 |
|---|---|---|---:|---:|---:|---:|
| `financial_001` | financial_risk | financial | True | 11.11% | 100.00% | 100.00% |
| `financial_002` | financial_risk | financial | True | 50.00% | 100.00% | 100.00% |
| `financial_003` | financial_risk | financial | True | 42.86% | 100.00% | 100.00% |
| `financial_004` | financial_risk | financial | True | 33.33% | 100.00% | 100.00% |
| `financial_005` | financial_risk | financial | True | 50.00% | 100.00% | 100.00% |
| `business_001` | business_risk | market | True | 44.44% | 100.00% | 100.00% |
| `business_002` | business_risk | market | True | 40.00% | 100.00% | 100.00% |
| `business_003` | business_risk | market | True | 14.29% | 100.00% | 100.00% |
| `business_004` | business_risk | market | True | 50.00% | 100.00% | 100.00% |
| `business_005` | business_risk | market | True | 62.50% | 100.00% | 100.00% |
| `ownership_001` | ownership_risk | governance | True | 20.00% | 100.00% | 100.00% |
| `ownership_002` | ownership_risk | governance | True | 11.11% | 100.00% | 100.00% |
| `ownership_003` | ownership_risk | governance | True | 30.00% | 100.00% | 100.00% |
| `ownership_004` | ownership_risk | governance | True | 10.00% | 100.00% | 100.00% |
| `compliance_001` | compliance_risk | legal | True | 22.22% | 100.00% | 100.00% |
| `compliance_002` | compliance_risk | legal | True | 37.50% | 100.00% | 100.00% |
| `compliance_003` | compliance_risk | legal | True | 37.50% | 100.00% | 100.00% |
| `compliance_004` | compliance_risk | legal | True | 10.00% | 100.00% | 100.00% |
| `ipo_001` | ipo_specific_risk | all | True | 30.00% | 100.00% | 100.00% |
| `ipo_002` | ipo_specific_risk | all | True | 40.00% | 100.00% | 100.00% |
| `ipo_003` | ipo_specific_risk | all | True | 28.57% | 100.00% | 100.00% |
| `ipo_004` | ipo_specific_risk | all | True | 20.00% | 100.00% | 100.00% |

## 后续优化建议

- 为每个问题补充人工标注的预期文档和页码，再用标注集评估 recall。
- 对关键词覆盖率低的宽泛风险问题拆分子问题。
- 优先改进财务比率、现金流、负债相关表格 chunk 的描述质量。
- 只有当人工标注显示稳定失败模式后，再考虑加入轻量 rerank。