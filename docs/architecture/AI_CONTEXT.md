# IPO-Risk-Agent Project AI Context

## 0. AI Assistant Role

你现在作为本项目的技术决策辅助者。

不要直接大规模修改代码。

执行原则：

1. 先理解已有架构
2. 优先阅读 docs/*.md
3. 修改前提出计划
4. 小步迭代
5. 保持模块边界
6. 不提前开发未规划模块


项目当前处于：

样本级 RAG Pipeline MVP 已打通
Retriever Review + Pipeline 稳定化阶段


---

# 1. Project Overview

项目名称：

IPO-Risk-Agent


目标：

构建一个面向港股IPO招股书风险分析的AI Agent系统。

输入：

- IPO招股书PDF
- 公司信息CSV
- 股票行情CSV


输出：

用户可以通过系统：

- 查询公司风险
- 分析财务风险
- 获取可信引用证据
- 查看原始招股书页码


核心竞争点：

不是简单RAG问答。

而是：

Evidence-Centric Financial RAG。


---

# 2. Team Background

团队：

- 工商管理学生
- 金融学生
- 计算机学生


计算机负责：

- PDF解析
- Evidence Layer
- RAG Pipeline
- Embedding
- Retriever
- Agent
- Streamlit产品


金融负责：

- 风险指标定义
- 财务分析逻辑
- IPO业务规则


工商管理负责：

- 商业分析
- 产品设计
- 竞品分析
- 展示材料


---

# 3. Core Design Philosophy

禁止：

普通RAG：

PDF
↓
Text Chunk
↓
Embedding
↓
Vector Search


原因：

金融招股书具有：

- 长文档
- 表格多
- 页面引用要求高
- 审计可信需求


采用：

Evidence First Architecture


核心链路：

PDF

↓

MinerU

↓

Evidence Builder

↓

Evidence Store

↓

Evidence-aware Chunk

↓

Embedding

↓

Retriever

↓

Risk Agent


---

# 4. Current Completed Modules


## 4.1 MinerU Parser

状态：

DONE


工具：

MinerU 2.5


原因：

招股书：

- 表格复杂
- 财务数据重要
- 需要页码定位


验证：

3份样本：

- 快手
- KEEP
- 京东工业


结果：

成功率100%


---

# 4.2 Evidence Layer

状态：

DONE


设计文件：

EVIDENCE_DESIGN_v1.1.md


核心思想：

Evidence 是系统最小可信单元。


Evidence必须保存：

- 原文
- 页码
- bbox
- 来源文件
- 类型


类型：

TextEvidence

TableEvidence

ImageEvidence


---

# 5. Evidence Data Model


Evidence字段：


evidence_id

document_id

company

page

section_path

bbox

source_file

block_type

text

metadata

risk_tags



注意：

risk_tags：

不是Evidence Builder生成。

由未来Risk Agent生成。


---

# 6. Evidence ID Rule


必须保持：


ev_{document_id}p{page}{type}{index}



type:

text:

txt


table:

tbl


image:

img


例如：


ev_2021_01024_p45_txt001

ev_2021_01024_p210_tbl003



---

# 7. Current Folder Structure


当前：


src/

└── evidence/

├── models.py

├── parser.py

├── builder.py

└── __init__.py


---

# 8. Evidence Builder Status


状态：

MVP完成


输入：

MinerU:

content_list.json


输出：

data/evidence/


包含：

document.json

evidences.json


已经验证：

快手

KEEP

京东工业


生成：

173 Evidence


---

# 9. Important Engineering Decisions


## Markdown不是核心数据源

错误：

PDF

↓

Markdown

↓

Chunk


正确：

MinerU content_list.json

↓

Evidence


Markdown:

只用于：

- 阅读
- Debug


---

## Table不能简单文本化


金融表格：

不能：


收入 100
利润 20


直接Embedding。


需要保留：

结构。


---

## Image暂不重点处理


当前：

保留Image Evidence。


未来：

过滤：

- logo
- 页眉
- 装饰图片


保留：

- 财务图表
- 架构图


---

# 10. Current Development Stage


当前：

Stage 8


目标：

稳定：

Evidence

↓

Chunk

↓

Embedding

↓

VectorStore

↓

Layered Retriever


已开发：

Chunk Builder MVP

Embedding Engine MVP

FAISS VectorStore MVP

Layered Retriever MVP

Streamlit Demo MVP


还未完成：

全量 Pipeline 稳定运行

Retriever 质量评估

Evidence 原文级引用展示

Agent


---

# 11. Next Task


下一步：

优先稳定检索链路：

1. 重建去重后的 VectorStore
2. Retriever 回查完整 Chunk 与 evidence_ids
3. 非 all 检索层默认过滤 Image Chunk
4. 修复全量 Pipeline 对已有 MinerU/Evidence/Chunk 的复用
5. 对真实风险查询做人工 Review


Chunk必须继承：


chunk_id

evidence_ids

document_id

company

page

section_path

block_type



---

# 12. Chunk Design Requirements


## Text Chunk

考虑：

- 招股书长文本
- 标题层级
- 页码连续性


不要简单：

固定500 token切割。


---

## Table Chunk

必须：

保留表结构。


不能：

普通文本chunk。


---

## Image Chunk

设计：

是否进入RAG。

如何过滤。


---

# 13. Development Rules


AI开发规则：


不要：

一次开发全部系统。


必须：

设计

↓

Review

↓

冻结

↓

编码


---

当前不要开发：

❌ Agent

❌ 大规模重构

❌ 新增复杂框架


当前允许小步修复：

✅ VectorStore 去重与重建

✅ Retriever 返回完整 Chunk/Evidence 引用

✅ Pipeline 断点续跑与已有产物复用

✅ Streamlit Demo 性能与展示修复


---

# 18. Latest Working State

更新时间：

2026-07-10


当前索引：

- VectorStore: data/vectors
- 向量数：2448
- 维度：512
- 重复 chunk_id：0
- 已索引文档：
  - 2020_00368_德合集團
  - 2020_00589_建中建設
  - 2020_00873_世茂服務
  - 2021_01024_快手
  - 2023_03650_KEEP
  - 2025_07618_京东工业


当前验证：

- tests/test_retriever.py 通过
- scripts/evaluate_retrieval_quality.py 通过
- RETRIEVAL_QUALITY_REPORT.md 已生成
- 评估结果：
  - 6个测试查询
  - 平均关键词命中率：96.67%
  - Evidence覆盖率：100%
  - Image结果：0


当前Demo：

- Streamlit: app.py
- 本地地址：http://localhost:8501
- 支持展示：
  - chunk文本
  - evidence_ids
  - Evidence页码
  - bbox
  - source_file


下一步建议：

1. 做人工标注版检索评估集
2. 为financial层增加子类过滤或rerank
3. 批量扩展更多已解析/可解析PDF
4. 改进Table解析，保留rowspan/colspan
5. 再进入Agent回答生成


---

# 14. Future Architecture


最终目标：


User

↓

Streamlit

↓

Risk Agent

↓

Retriever

↓

Evidence Store

↓

Vector DB

↓

Evidence-aware Chunk

↓

MinerU Parsed Data

↓

IPO PDF



---

# 15. Innovation Points


比赛创新点：


## 1. Evidence-Centric RAG

回答带：

- 页码
- 原文
- 定位


解决金融可信问题。


## 2. Multi-modal Evidence

同时支持：

- Text
- Table
- Image


## 3. Financial Domain Agent

未来：

Risk Agent

Financial Agent

Legal Agent


---

# 16. Coding Style


要求：

- 简洁
- 模块化
- 不过度抽象
- 不提前引入复杂框架


优先：

Python


---

# 17. Before Any Modification


执行：

1.

阅读：

AI_CONTEXT.md


2.

阅读：

相关设计文档


3.

说明：

准备修改哪些文件


4.

等待确认
