# Evidence Builder MVP 构建报告

> 基于 EVIDENCE_DESIGN_v1.1.md + v1.2 Review修正

---

## 1. 构建结果总览

| 样本 | 公司 | 文本 | 表格 | 图片 | 总计 | 状态 |
|------|------|------|------|------|------|------|
| S1 | 快手科技 | 63 | 1 | 14 | 78 | ✅ |
| S2 | KEEP | 40 | 1 | 8 | 49 | ✅ |
| S3 | 京东工业 | 42 | 2 | 2 | 46 | ✅ |
| **合计** | - | **145** | **4** | **24** | **173** | - |

**失败记录**: 无

---

## 2. 实现文件清单

```
src/evidence/
├── __init__.py      # 模块入口
├── models.py        # 数据模型 (BaseEvidence, TextEvidence, TableEvidence, ImageEvidence, Document)
├── parser.py        # MinerU输出解析器 (MineruOutputParser, RawBlock)
└── builder.py       # Evidence Builder (EvidenceBuilder)
```

---

## 3. 数据流验证

```
MinerU content_list.json
    ↓
parser.py: MineruOutputParser.parse()
    ↓
List[RawBlock]
    ↓
builder.py: EvidenceBuilder._build_evidences()
    ↓
List[TextEvidence | TableEvidence | ImageEvidence]
    ↓
builder.py: EvidenceBuilder._save_document()
    ↓
data/evidence/{document_id}/
├── document.json
├── evidences.json
└── images/
```

**验证**: ✅ 完整流程正常

---

## 4. JSON样例

### 4.1 TextEvidence

```json
{
  "evidence_id": "ev_2021_01024_快手_p0_txt001",
  "document_id": "2021_01024_快手",
  "company": "快手科技",
  "page": 0,
  "section_path": [],
  "bbox": [62.0, 617.0, 242.0, 649.0],
  "source_file": "data/raw/2021_88份/01024_26-01-2021_快手－Ｗ_全球發售.pdf",
  "block_type": "text",
  "text": "全球發售",
  "metadata": {},
  "risk_tags": [],
  "is_header": false,
  "header_level": 0,
  "context_before": "",
  "context_after": "Kuaishou Technology 快手科技"
}
```

### 4.2 TableEvidence

```json
{
  "evidence_id": "ev_2021_01024_快手_p3_tbl001",
  "document_id": "2021_01024_快手",
  "company": "快手科技",
  "page": 3,
  "section_path": ["重要通知"],
  "bbox": [115.0, 143.0, 882.0, 482.0],
  "source_file": "data/raw/2021_88份/01024_26-01-2021_快手－Ｗ_全球發售.pdf",
  "block_type": "table",
  "text": "表格（15行）: 申請認購的香港發售股份數目, ...",
  "metadata": {},
  "risk_tags": [],
  "table_html": "<table>...</table>",
  "table_data": {
    "headers": ["申請認購的香港發售股份數目", "申請時應缴款項", ...],
    "rows": [["100", "11,615.89"], ...],
    "row_count": 15,
    "col_count": 8
  },
  "table_description": "表格（15行）: 申請認購的香港發售股份數目, ..."
}
```

### 4.3 ImageEvidence

```json
{
  "evidence_id": "ev_2021_01024_快手_p0_img001",
  "document_id": "2021_01024_快手",
  "company": "快手科技",
  "page": 0,
  "section_path": [],
  "bbox": [652.0, 854.0, 766.0, 875.0],
  "source_file": "data/raw/2021_88份/01024_26-01-2021_快手－Ｗ_全球發售.pdf",
  "block_type": "image",
  "text": "",
  "metadata": {},
  "risk_tags": [],
  "image_path": "data/cache/mineru_test/S1/.../images/064ebd53...jpg",
  "image_hash": "064ebd53e87044ded6aceb39cd36c0cdea3dccc746e18762e6b694e19161c5f5",
  "image_caption": ""
}
```

---

## 5. Evidence ID 验证

| 样本 | 示例ID | 格式 |
|------|--------|------|
| S1 | `ev_2021_01024_快手_p0_txt001` | ✅ |
| S1 | `ev_2021_01024_快手_p3_tbl001` | ✅ |
| S1 | `ev_2021_01024_快手_p0_img001` | ✅ |
| S2 | `ev_2023_03650_KEEP_p0_txt001` | ✅ |
| S3 | `ev_2025_07618_京东工业_p0_txt001` | ✅ |

---

## 6. section_path 验证

**基础版本**：根据MinerU header信息维护当前章节路径

| 样本 | 找到的章节 |
|------|-----------|
| S1 | [] (前3页无header) |
| S2 | [] (前3页无header) |
| S3 | [] (前3页无header) |

**说明**: 测试样本仅3-4页，前几页通常是封面和重要提示，无header类型块。完整招股书会有更多章节信息。

---

## 7. 输出目录结构

```
data/evidence/
├── 2021_01024_快手/
│   ├── document.json      ✅
│   ├── evidences.json     ✅ (78条)
│   └── images/            ✅ (14张)
├── 2023_03650_KEEP/
│   ├── document.json      ✅
│   ├── evidences.json     ✅ (49条)
│   └── images/            ✅ (8张)
├── 2025_07618_京东工业/
│   ├── document.json      ✅
│   ├── evidences.json     ✅ (46条)
│   └── images/            ✅ (2张)
└── build_results.json
```

---

## 8. 当前限制

| 限制 | 说明 | 后续方案 |
|------|------|----------|
| 测试样本仅3-4页 | 无法验证完整招股书 | 全量解析时验证 |
| section_path为空 | 前几页无header | 完整招股书会有章节 |
| image_caption为空 | 前几页图片无相邻text | 完善caption提取 |
| table_html依赖Markdown | content_list.json中table的text为空 | MinerU后续版本可能修复 |
| risk_tags不填充 | v1.1设计：由Risk Agent生成 | Risk Agent阶段实现 |

---

## 9. 验收清单

| 检查项 | 状态 |
|--------|------|
| parser.py读取content_list.json | ✅ |
| parser.py解析block类型 | ✅ |
| parser.py提取page_idx | ✅ |
| parser.py提取bbox | ✅ |
| parser.py提取text | ✅ |
| parser.py提取table HTML | ✅ |
| parser.py提取image路径 | ✅ |
| builder.py创建Document | ✅ |
| builder.py创建TextEvidence | ✅ |
| builder.py创建TableEvidence | ✅ |
| builder.py创建ImageEvidence | ✅ |
| builder.py生成evidence_id | ✅ |
| 输出document.json | ✅ |
| 输出evidences.json | ✅ |
| 输出images/ | ✅ |
| 3份样本全部成功 | ✅ |
| 无失败记录 | ✅ |

---

## 10. 结论

**Evidence Builder MVP 验证通过。**

- 3份样本全部成功构建Evidence（共173条）
- 数据流完整：content_list.json → RawBlock → Evidence → JSON
- Evidence ID格式符合v1.1规范
- 输出结构符合设计要求

**等待Review，不自动进入下一阶段。**
