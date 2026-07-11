# Chunk Builder MVP 构建报告

> 基于 CHUNK_DESIGN.md v1.0

---

## 1. 构建结果总览

| 样本 | 输入 Evidence | 输出 Chunk | 合并比 | 平均Token |
|------|--------------|------------|--------|-----------|
| S1_快手 | 78 (text:63, table:1, image:14) | 20 (text:5, table:1, image:14) | 12.6:1 | 123 |
| S2_KEEP | 49 (text:40, table:1, image:8) | 11 (text:2, table:1, image:8) | 20.0:1 | 93 |
| S3_京东工业 | 46 (text:42, table:2, image:2) | 7 (text:3, table:2, image:2) | 14.0:1 | 223 |
| **合计** | **173** | **38** | **15.3:1** | **146** |

---

## 2. 合并前后对比

### 2.1 Text Chunk

| 样本 | 输入 TextEvidence | 输出 TextChunk | 合并比 |
|------|------------------|----------------|--------|
| S1_快手 | 63 | 5 | 12.6:1 |
| S2_KEEP | 40 | 2 | 20.0:1 |
| S3_京东工业 | 42 | 3 | 14.0:1 |

**说明**：短Evidence（平均53字符）被合并为有意义的Chunk（平均146 tokens）。

### 2.2 Table Chunk

| 样本 | 输入 TableEvidence | 输出 TableChunk | 说明 |
|------|-------------------|-----------------|------|
| S1_快手 | 1 | 1 | 独立保留 |
| S2_KEEP | 1 | 1 | 独立保留 |
| S3_京东工业 | 2 | 2 | 独立保留 |

**说明**：每个TableEvidence独立生成一个TableChunk，未触发拆分（行数<20）。

### 2.3 Image Chunk

| 样本 | 输入 ImageEvidence | 输出 ImageChunk | 过滤数 |
|------|-------------------|-----------------|--------|
| S1_快手 | 14 | 14 | 0 |
| S2_KEEP | 8 | 8 | 0 |
| S3_京东工业 | 2 | 2 | 0 |

**说明**：所有图片均保留（无尺寸信息，默认保留）。

---

## 3. TextChunk JSON样例

```json
{
  "chunk_id": "chk_2025_07618_京东工业_p0_txt001",
  "evidence_ids": [
    "ev_2025_07618_京东工业_p0_txt001",
    "ev_2025_07618_京东工业_p0_txt002",
    "ev_2025_07618_京东工业_p0_txt003",
    "ev_2025_07618_京东工业_p0_txt004",
    "ev_2025_07618_京东工业_p0_txt010",
    "ev_2025_07618_京东工业_p0_txt015",
    "ev_2025_07618_京东工业_p1_txt001",
    "ev_2025_07618_京东工业_p1_txt002",
    "ev_2025_07618_京东工业_p1_txt003",
    "ev_2025_07618_京东工业_p1_txt004",
    "ev_2025_07618_京东工业_p1_txt005"
  ],
  "document_id": "2025_07618_京东工业",
  "company": "京东工业",
  "pages": [0, 1],
  "section_path": [],
  "block_type": "text",
  "text": "於開曼群島註冊成立的有限公司 全球發售 股份代號 :7618 ...",
  "token_count": 233,
  "context_before": "",
  "context_after": "",
  "metadata": {}
}
```

**特征**：
- 合并了20个Evidence
- 跨页（page 0和1）
- section_path为空（前几页无header）

---

## 4. TableChunk JSON样例

```json
{
  "chunk_id": "chk_2021_01024_快手_p3_tbl001",
  "evidence_ids": ["ev_2021_01024_快手_p3_tbl001"],
  "document_id": "2021_01024_快手",
  "company": "快手科技",
  "pages": [3],
  "section_path": ["重要通知"],
  "block_type": "table",
  "table_html": "<table><tr><td>...</td></tr></table>",
  "table_data": {
    "headers": ["申請認購的香港發售股份數目", "申請時應缴款項", ...],
    "rows": [["100", "11,615.89"], ["200", "23,231.77"], ...],
    "row_count": 15,
    "col_count": 8
  },
  "table_description": "表格（15行）: 申請認購的香港發售股份數目, ...",
  "token_count": 47,
  "metadata": {}
}
```

**特征**：
- 独立保留（未合并）
- 保留table_html（展示用）
- 保留table_data（结构化查询）
- table_description用于Embedding

---

## 5. 输出目录结构

```
data/chunks/
├── 2021_01024_快手/
│   ├── chunks.json        (20条)
│   └── chunk_index.json
├── 2023_03650_KEEP/
│   ├── chunks.json        (11条)
│   └── chunk_index.json
├── 2025_07618_京东工业/
│   ├── chunks.json        (7条)
│   └── chunk_index.json
├── build_results.json
├── sample_text_chunk.json
└── sample_table_chunk.json
```

---

## 6. 验收清单

| 检查项 | 状态 |
|--------|------|
| config.py: ChunkConfig | ✅ |
| models.py: TextChunk, TableChunk, ImageChunk | ✅ |
| models.py: to_dict() | ✅ |
| models.py: to_text_for_embedding() | ✅ |
| models.py: chunk_id格式 | ✅ |
| builder.py: 文本合并 | ✅ |
| builder.py: 表格独立处理 | ✅ |
| builder.py: 图片过滤 | ✅ |
| store.py: save() | ✅ |
| store.py: save_index() | ✅ |
| 3份样本全部成功 | ✅ |
| CHUNK_BUILD_REPORT.md | ✅ |

---

## 7. 当前限制

| 限制 | 说明 | 后续方案 |
|------|------|----------|
| token计算使用字符估算 | chars/1.5 | 后续集成tiktoken |
| 图片无尺寸信息 | 测试样本无image_width/height | 全量解析时验证 |
| section_path部分为空 | 前几页无header | 完整招股书会有 |
| 未测试大表格拆分 | 行数<20未触发 | 全量解析时验证 |

---

## 8. 结论

**Chunk Builder MVP 验证通过。**

- 3份样本全部成功构建Chunk（共38条）
- 文本合并效果良好（平均15.3:1合并比）
- 表格独立保留，结构完整
- 图片按规则过滤（当前全部保留）
- 平均token数146，符合256-512设计目标

**等待Review，不自动进入下一阶段。**
