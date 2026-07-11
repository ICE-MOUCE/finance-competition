# Evidence Layer 设计文档 v1.1

> MinerU输出 → Evidence Builder → Evidence Store 数据模型设计
> 版本：v1.1 | 状态：冻结

---

## 1. 设计背景

### 1.1 MinerU实际输出结构

基于3份样本验证，MinerU输出包含：

```
output/
├── document.md                    # 完整Markdown（仅用于阅读和调试）
├── document_content_list.json     # 结构化内容列表（核心数据输入）
├── document_content_list_v2.json  # v2格式
├── document_middle.json           # 中间结果
├── document_model.json            # 模型信息
├── document_layout.pdf            # 布局标注PDF
└── images/                        # 提取的图片
    ├── hash1.jpg
    └── hash2.jpg
```

**v1.1重要说明**：
- `content_list.json`是Evidence Builder的**核心数据输入**
- `Markdown`仅用于**阅读和调试**，不是核心数据输入
- Evidence Builder直接从`content_list.json`构建Evidence，不依赖Markdown解析

### 1.2 content_list.json 结构

```json
{
  "type": "text|image|table|header|footer|page_number",
  "page_idx": 0,
  "bbox": [x0, y0, x1, y1],
  "text": "文本内容",
  "img_path": "images/hash.jpg"
}
```

**实际数据统计**（S1快手，3页）：

| 类型 | 数量 | 说明 |
|------|------|------|
| text | 63 | 文本块 |
| image | 14 | 图片 |
| table | 1 | 表格 |
| header | 2 | 页眉 |
| footer | 1 | 页脚 |
| page_number | 2 | 页码 |

**关键发现**：
- `bbox`格式为`[x0, y0, x1, y1]`，坐标系为PDF坐标（左下角为原点）
- 表格的`text`字段为空，实际表格HTML在Markdown文件中（需从Markdown提取）
- 图片的`img_path`指向`images/`目录下的文件

---

## 2. 数据模型设计

### 2.1 Document 对象

Document是招股书的整体表示，包含元数据和Evidence列表。

```python
@dataclass
class Document:
    """招股书文档对象"""

    # === 标识 ===
    document_id: str              # 文档唯一ID (如 "2021_01024_快手")

    # === 公司信息 ===
    company: str                  # 公司名称 (如 "快手科技")
    stock_code: str               # 股票代码 (如 "01024.HK")
    listing_date: str             # 上市日期 (如 "2021-01-26")
    industry: str                 # 行业 (如 "科技")

    # === 文件信息 ===
    source_file: str              # 原始PDF路径
    total_pages: int              # 总页数
    file_size_mb: float           # 文件大小(MB)

    # === 解析信息 ===
    parsed_at: datetime           # 解析时间
    parser_version: str           # MinerU版本
    content_list_path: str        # content_list.json路径（核心输入）
    images_dir: str               # 图片目录路径
    markdown_path: str            # Markdown文件路径（仅用于调试）

    # === Evidence列表 ===
    evidences: List['Evidence']   # 所有Evidence对象

    # === 统计信息 ===
    text_count: int = 0           # TextEvidence数量
    table_count: int = 0          # TableEvidence数量
    image_count: int = 0          # ImageEvidence数量
```

**Document vs Evidence关系**：

```
Document (1)
 ├── Evidence (N)
 │   ├── TextEvidence
 │   ├── TableEvidence
 │   └── ImageEvidence
 └── metadata
```

---

### 2.2 Evidence 基类

Evidence是知识的最小单位，所有Evidence必须包含完整溯源信息。

```python
@dataclass
class Evidence:
    """证据基类 - 知识的最小单位"""

    # === 标识（必须）===
    evidence_id: str              # 证据唯一ID
    document_id: str              # 所属文档ID

    # === 来源定位（必须）===
    company: str                  # 公司名称
    page: int                     # 页码（从0开始，与MinerU一致）
    section_path: List[str]       # 章节路径（层级结构）
    bbox: Tuple[float, float, float, float]  # 边界框 (x0, y0, x1, y1)
    source_file: str              # 原始PDF路径

    # === 内容（必须）===
    block_type: str               # 内容类型 (text/table/image)
    text: str                     # 文本内容

    # === 元数据 ===
    metadata: Dict[str, Any]      # 额外元数据

    # === 风险标签（由Risk Agent生成，Evidence Builder不填充）===
    risk_tags: List[str] = field(default_factory=list)

    # === 向量（可选，后续阶段）===
    embedding: Optional[List[float]] = None

    def to_citation(self) -> str:
        """生成Agent可引用的引用格式"""
        section_str = " > ".join(self.section_path) if self.section_path else ""
        return f"[Evidence {self.evidence_id}] p.{self.page} {section_str}"

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "evidence_id": self.evidence_id,
            "document_id": self.document_id,
            "company": self.company,
            "page": self.page,
            "section_path": self.section_path,
            "bbox": list(self.bbox),
            "source_file": self.source_file,
            "block_type": self.block_type,
            "text": self.text,
            "metadata": self.metadata,
            "risk_tags": self.risk_tags,
        }
```

**v1.1变更**：
- `section: str` → `section_path: List[str]`（层级结构）
- `risk_tags`保留字段，但Evidence Builder不填充，由Risk Agent生成

---

### 2.3 TextEvidence

文本证据，对应MinerU的`type=text`。

```python
@dataclass
class TextEvidence(Evidence):
    """文本证据"""

    block_type: str = "text"

    # === 文本特有字段 ===
    is_header: bool = False       # 是否为标题
    header_level: int = 0         # 标题层级 (1=H1, 2=H2, ...)
    context_before: str = ""      # 前文上下文
    context_after: str = ""       # 后文上下文
```

**v1.1变更**：移除`risk_tags`字段（继承自基类，由Risk Agent填充）

**Agent引用场景**：

```python
# Agent检索到TextEvidence
evidence = TextEvidence(
    evidence_id="ev_2021_01024_p45_txt001",
    document_id="2021_01024_快手",
    company="快手科技",
    page=45,
    section_path=["风险因素", "业务风险"],
    bbox=(72.0, 350.5, 540.0, 420.3),
    source_file="data/raw/2021/快手招股书.pdf",
    text="截至2023年12月31日，公司现金及现金等价物为人民币5.2亿元...",
)

# Agent在报告中引用
report += f"根据 {evidence.to_citation()}：{evidence.text}\n"
# 输出: 根据 [Evidence ev_2021_01024_p45_txt001] p.45 风险因素 > 业务风险：截至2023年...

# Risk Agent后续添加风险标签
evidence.risk_tags = ["现金流", "流动性风险"]  # 由Risk Agent填充
```

---

### 2.4 TableEvidence

表格证据，对应MinerU的`type=table`。

```python
@dataclass
class TableEvidence(Evidence):
    """表格证据"""

    block_type: str = "table"

    # === 表格特有字段 ===
    table_html: str               # 原始HTML（从Markdown提取，仅用于调试）
    table_data: Dict[str, Any]    # 结构化表格数据（核心）
    # table_data格式:
    # {
    #     "headers": ["列1", "列2", ...],
    #     "rows": [
    #         ["值1", "值2", ...],
    #         ["值3", "值4", ...],
    #     ],
    #     "row_count": 10,
    #     "col_count": 4,
    # }
    table_description: str        # 表格描述（文本化）
    table_index: int = 0          # 表格在页面中的序号
```

**表格数据提取流程**：

```
content_list.json
    │
    │ type=table, page_idx=3, bbox=[115, 143, 882, 482]
    │ (text为空)
    │
    ▼
Markdown文件（仅用于提取表格HTML）
    │
    │ <table><tr><td>...</td></tr></table>
    │
    ▼
HTML解析
    │
    ▼
table_data = {
    "headers": ["申請認購的香港發售股份數目", "申請時應缴款項"],
    "rows": [["100", "11,615.89"], ["200", "23,231.77"], ...],
    "row_count": 15,
    "col_count": 8
}
```

**Agent引用场景**：

```python
# Agent检索到TableEvidence
evidence = TableEvidence(
    evidence_id="ev_2021_01024_p3_tbl001",
    document_id="2021_01024_快手",
    company="快手科技",
    page=3,
    section_path=["全球发售"],
    bbox=(115.0, 143.0, 882.0, 482.0),
    source_file="data/raw/2021/快手招股书.pdf",
    text="申请认购的香港发售股份数目及应缴款项",
    table_html="<table>...</table>",
    table_data={
        "headers": ["申请认购数目", "应缴款项(港元)"],
        "rows": [["100", "11,615.89"], ...],
    },
    table_description="香港发售股份认购数目及对应应缴款项表",
)

# Agent在报告中引用
report += f"根据 {evidence.to_citation()} [TABLE]：\n"
report += f"表格内容：{evidence.table_description}\n"
# Risk Report展示表格
render_table(evidence.table_data)
```

---

### 2.5 ImageEvidence

图片证据，对应MinerU的`type=image`。

```python
@dataclass
class ImageEvidence(Evidence):
    """图片证据"""

    block_type: str = "image"

    # === 图片特有字段 ===
    image_path: str               # 图片文件路径
    image_hash: str               # 图片文件名（哈希值）
    image_caption: str = ""       # 图片标题（从相邻text块提取）
    image_width: int = 0          # 图片宽度
    image_height: int = 0         # 图片高度
```

**图片Caption提取逻辑**：

```
content_list.json:
  [10] type=image, page=0, bbox=[517, 796, 571, 820], img_path=images/hash.jpg
  [11] type=text,  page=0, bbox=[520, 825, 560, 840], text="Morgan Stanley"

→ ImageEvidence:
  image_path = "images/hash.jpg"
  image_caption = "Morgan Stanley"  # 从相邻text块提取
```

**Agent引用场景**：

```python
# Agent检索到ImageEvidence
evidence = ImageEvidence(
    evidence_id="ev_2021_01024_p0_img001",
    document_id="2021_01024_快手",
    company="快手科技",
    page=0,
    section_path=["封面"],
    bbox=(517.0, 796.0, 571.0, 820.0),
    source_file="data/raw/2021/快手招股书.pdf",
    text="Morgan Stanley",
    image_path="data/cache/mineru_test/S1/images/hash.jpg",
    image_hash="6306557dd36a7334e542faef12e3f8f1248b6922ed65440415593b6366ce7136",
    image_caption="Morgan Stanley Logo",
)

# Risk Report展示图片
render_image(evidence.image_path, caption=evidence.image_caption)
```

---

## 3. Evidence ID 设计

### 3.1 ID格式（v1.1修正）

```
ev_{document_id}_p{page}_{type_prefix}{index:03d}
```

**v1.1变更**：修正type_prefix，消除text/table冲突

| Evidence类型 | type_prefix | ID示例 | 说明 |
|-------------|-------------|--------|------|
| Text | `txt` | `ev_2021_01024_p45_txt001` | 第45页第1个文本块 |
| Table | `tbl` | `ev_2021_01024_p3_tbl001` | 第3页第1个表格 |
| Image | `img` | `ev_2021_01024_p0_img001` | 第0页第1张图片 |

### 3.2 ID生成规则

```python
TYPE_PREFIX_MAP = {
    "text": "txt",
    "table": "tbl",
    "image": "img",
}

def generate_evidence_id(
    document_id: str,
    page: int,
    block_type: str,
    sequence: int
) -> str:
    """
    生成Evidence ID

    Args:
        document_id: 文档ID (如 "2021_01024_快手")
        page: 页码 (从0开始)
        block_type: 类型 (text/table/image)
        sequence: 序号 (从1开始)

    Returns:
        Evidence ID (如 "ev_2021_01024_p45_txt001")

    Example:
        >>> generate_evidence_id("2021_01024_快手", 45, "text", 1)
        'ev_2021_01024_p45_txt001'
        >>> generate_evidence_id("2021_01024_快手", 3, "table", 1)
        'ev_2021_01024_p3_tbl001'
        >>> generate_evidence_id("2021_01024_快手", 0, "image", 1)
        'ev_2021_01024_p0_img001'
    """
    type_prefix = TYPE_PREFIX_MAP[block_type]
    return f"ev_{document_id}_p{page}_{type_prefix}{sequence:03d}"
```

---

## 4. Evidence Builder 设计

### 4.1 数据流（v1.1更新）

```
┌─────────────────────────────────────────────────────────────────┐
│                    Evidence Builder 数据流                        │
└─────────────────────────────────────────────────────────────────┘

MinerU输出目录
    │
    ├── document_content_list.json  ◄── 核心数据输入
    ├── document.md                 ◄── 仅用于提取表格HTML（调试用）
    └── images/                     ◄── 图片文件
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: 解析content_list.json                                    │
│                                                                  │
│ 输入: content_list.json                                          │
│ 输出: List[RawBlock]                                             │
│                                                                  │
│ RawBlock = {                                                     │
│     "type": "text|image|table|header|footer|page_number",       │
│     "page_idx": int,                                             │
│     "bbox": [x0, y0, x1, y1],                                   │
│     "text": str,                                                 │
│     "img_path": str                                              │
│ }                                                                │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: 提取表格HTML（从Markdown，仅表格类型）                    │
│                                                                  │
│ 问题: content_list.json中table的text为空                         │
│ 解决: 从Markdown文件中提取<table>...</table>                     │
│                                                                  │
│ 注意: 这是唯一使用Markdown的地方                                 │
│                                                                  │
│ 输入: document.md + content_list.json中的table条目               │
│ 输出: List[TableBlock] (包含HTML)                                │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: 构建Evidence对象                                         │
│                                                                  │
│ 对每个RawBlock:                                                  │
│   - type=text → TextEvidence                                     │
│   - type=table → TableEvidence                                   │
│   - type=image → ImageEvidence                                   │
│   - type=header/footer/page_number → 跳过或合并                  │
│                                                                  │
│ 附加信息:                                                        │
│   - 生成evidence_id (v1.1格式)                                   │
│   - 关联document_id                                              │
│   - 提取section_path（从标题层级推断，v1.1改为List[str]）        │
│   - 提取image_caption（从相邻text块）                            │
│   - risk_tags留空（由后续Risk Agent生成）                        │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: 繁简转换                                                 │
│                                                                  │
│ OpenCC: 繁体中文 → 简体中文                                      │
│ 保留: 公司名称、英文术语、数字                                    │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: 输出                                                     │
│                                                                  │
│ Document(                                                        │
│     document_id="2021_01024_快手",                                │
│     evidences=[TextEvidence, TableEvidence, ...],                │
│     text_count=63,                                               │
│     table_count=1,                                               │
│     image_count=14                                               │
│ )                                                                │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Section推断策略（v1.1更新）

从标题层级推断当前Evidence的section_path：

```python
def infer_section_path(
    content_list: List[Dict],
    current_idx: int
) -> List[str]:
    """
    推断当前Evidence的section_path

    策略:
    1. 向前搜索最近的header类型条目
    2. 根据header层级构建section路径
    3. 返回List[str]，而非单个string

    Example:
        >>> infer_section_path(content_list, 45)
        ["风险因素", "业务风险", "与业务相关的风险"]
    """
    pass
```

**v1.1变更**：返回`List[str]`而非`str`

### 4.3 Risk Tag策略（v1.1更新）

**Evidence Builder阶段不生成risk_tags。**

`risk_tags`字段在Evidence基类中保留，但由后续Risk Agent填充：

```python
# Evidence Builder构建Evidence时
evidence = TextEvidence(
    ...
    risk_tags=[],  # 留空
)

# Risk Agent分析后填充
evidence.risk_tags = ["现金流", "流动性风险"]  # 由Risk Agent填充
```

**原因**：
- risk_tags需要语义理解和风险判断，不是简单的关键词匹配
- Risk Agent有专门的风险分析能力
- 分离关注点：Evidence Builder负责数据提取，Risk Agent负责风险判断

---

## 5. Evidence Store 设计

### 5.1 存储结构（v1.1 MVP范围）

```
data/evidence/
├── {document_id}/
│   ├── document.json            # Document元数据
│   ├── evidences.json           # 所有Evidence序列化
│   └── images/                  # 图片存储（软链接或复制）
│       ├── hash1.jpg
│       └── hash2.jpg
```

**v1.1 MVP范围**：
- ✅ `document.json`：Document元数据
- ✅ `evidences.json`：所有Evidence序列化
- ✅ `images/`：图片文件
- ❌ `tables/`：后续阶段（表格HTML存储）
- ❌ `index/`：后续阶段（索引文件）
- ❌ `metadata.db`：后续阶段（SQLite）
- ❌ Vector DB：后续阶段（FAISS）
- ❌ Table DB：后续阶段

### 5.2 Evidence Store 接口（v1.1 MVP）

```python
class EvidenceStore:
    """Evidence存储（MVP版本）"""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def save_document(self, document: Document) -> None:
        """
        保存Document及其所有Evidence

        存储:
        - data/evidence/{document_id}/document.json
        - data/evidence/{document_id}/evidences.json
        - data/evidence/{document_id}/images/
        """
        pass

    def get_document(self, document_id: str) -> Document:
        """获取Document"""
        pass

    def get_evidence(self, evidence_id: str) -> Evidence:
        """通过evidence_id获取Evidence"""
        pass

    def list_documents(self) -> List[str]:
        """列出所有document_id"""
        pass
```

**v1.1变更**：移除`search_evidence`方法（需要索引支持，属于后续阶段）

---

## 6. Agent引用设计

### 6.1 引用格式（v1.1更新）

Agent在生成报告时，必须引用Evidence：

```
根据 [Evidence ev_2021_01024_p45_txt001] p.45 风险因素 > 业务风险：
截至2023年12月31日，公司现金及现金等价物为人民币5.2亿元...

根据 [Evidence ev_2021_01024_p46_tbl001] p.46 财务数据 > 现金流量 [TABLE]：
现金流量表显示2023年经营活动现金流为3.2亿元...
```

### 6.2 Agent调用流程

```python
# 1. Agent检索证据
results = retriever.retrieve_evidence(
    query="现金流消耗风险",
    layer="financial",
    top_k=5
)

# 2. Agent引用证据
for evidence in results:
    citation = evidence.to_citation()
    # citation = "[Evidence ev_2021_01024_p45_txt001] p.45 风险因素 > 业务风险"

    # 3. Agent在报告中使用
    report += f"根据 {citation}：\n"
    report += f"{evidence.text}\n\n"

    # 4. 如果是表格，展示表格
    if evidence.block_type == "table":
        report += f"表格数据：\n"
        report += render_table(evidence.table_data)

    # 5. 如果是图片，展示图片
    if evidence.block_type == "image":
        report += f"![{evidence.image_caption}]({evidence.image_path})\n"

# 6. Risk Agent添加风险标签
for evidence in results:
    evidence.risk_tags = risk_agent.analyze_risk(evidence.text)

# 7. Agent审计：通过evidence_id追溯原文
for evidence in results:
    original = evidence_store.get_evidence(evidence.evidence_id)
    assert original.page is not None
    assert original.source_file is not None
    assert original.bbox is not None
```

---

## 7. Risk Report 展示设计

### 7.1 报告结构（v1.1更新）

```
IPO风险穿透预警报告

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
公司: 快手科技 (01024.HK)
上市日期: 2021-01-26
行业: 科技
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 风险摘要
   ...

2. 风险详情
   2.1 现金流风险 [HIGH]
       证据: [Evidence ev_2021_01024_p45_txt001] p.45
       原文: 截至2023年12月31日，公司现金及现金等价物为人民币5.2亿元...

       证据: [Evidence ev_2021_01024_p46_tbl001] p.46 [TABLE]
       表格:
       ┌──────────────┬──────────┬──────────┬──────────┐
       │ 项目          │ 2023年    │ 2022年    │ 2021年    │
       ├──────────────┼──────────┼──────────┼──────────┤
       │ 经营活动现金流 │ 3.2亿    │ 2.8亿    │ 1.5亿    │
       │ 投资活动现金流 │ -1.5亿   │ -2.1亿   │ -3.0亿   │
       └──────────────┴──────────┴──────────┴──────────┘

       图片: [Evidence ev_2021_01024_p0_img001] p.0
       [图片: Morgan Stanley Logo]

3. 证据清单
   | Evidence ID | 页码 | 章节路径 | 类型 | 来源 |
   |-------------|------|----------|------|------|
   | ev_2021_01024_p45_txt001 | p.45 | 风险因素 > 业务风险 | text | 快手招股书.pdf |
   | ev_2021_01024_p46_tbl001 | p.46 | 财务数据 > 现金流量 | table | 快手招股书.pdf |
   | ev_2021_01024_p0_img001 | p.0 | 封面 | image | 快手招股书.pdf |
```

---

## 8. 与现有设计的对齐

### 8.1 与RAG_DESIGN.md的关系

| RAG_DESIGN.md | EVIDENCE_DESIGN v1.1 | 说明 |
|---------------|---------------------|------|
| Evidence Object (2.2节) | Document + Evidence | 细化为Document和三种Evidence子类 |
| Layered Index (2.3节) | 不变 | 后续Stage实现 |
| Evidence模型 (4.1节) | TextEvidence/TableEvidence/ImageEvidence | 细化为三种类型 |

### 8.2 与RAG_ARCHITECTURE.md的关系

| RAG_ARCHITECTURE.md | EVIDENCE_DESIGN v1.1 | 说明 |
|---------------------|---------------------|------|
| Parser Layer | MinerU输出 | 不变 |
| Document Builder | Evidence Builder | 重命名，细化流程 |
| Evidence Layer | Document + Evidence | 细化数据模型 |
| Evidence Store | Evidence Store接口 | 细化存储结构 |

---

## 9. 开发约束

### 9.1 当前阶段只做

- ✅ Evidence数据模型设计
- ✅ Evidence Builder数据流设计
- ✅ Evidence Store MVP接口设计（JSON文件存储）
- ✅ Agent引用格式设计

### 9.2 当前阶段不做

- ❌ Chunk（已废弃）
- ❌ Embedding（后续Stage）
- ❌ Vector DB（后续Stage）
- ❌ SQLite（后续Stage）
- ❌ Table DB（后续Stage）
- ❌ Retriever（后续Stage）
- ❌ API服务（后续Stage）
- ❌ Risk Tags生成（Risk Agent职责）

---

## 10. 附录

### 10.1 MinerU content_list.json 完整字段

```json
{
  "type": "text",           // 内容类型
  "page_idx": 0,            // 页码（从0开始）
  "bbox": [62, 617, 242, 649],  // 边界框 [x0, y0, x1, y1]
  "text": "全球發售",       // 文本内容（table时为空）
  "img_path": ""            // 图片路径（仅image类型）
}
```

### 10.2 bbox坐标系

MinerU的bbox坐标系：
- 原点：PDF页面左下角
- x轴：向右增大
- y轴：向上增大
- 单位：PDF点（1点 = 1/72英寸）

```
(0, height) ─────────── (width, height)
    │                        │
    │      ┌──────────┐      │
    │      │  bbox    │      │
    │      │ [x0,y0]  │      │
    │      │ [x1,y1]  │      │
    │      └──────────┘      │
    │                        │
(0, 0) ───────────────── (width, 0)
```
