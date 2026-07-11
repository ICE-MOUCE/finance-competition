# Chunk Layer 设计文档

> Evidence → Chunk → Embedding → Retriever
> 版本：v1.0 | 状态：设计中

---

## 1. Chunk在系统中的位置

### 1.1 数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                         数据流                                    │
└─────────────────────────────────────────────────────────────────┘

MinerU content_list.json
        │
        ▼
┌───────────────┐
│ Evidence      │  ← 已完成 (MVP验证通过)
│ Builder       │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ Evidence      │  ← TextEvidence / TableEvidence / ImageEvidence
│ Store         │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ Chunk         │  ← 当前设计阶段
│ Builder       │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ Chunk Store   │  ← TextChunk / TableChunk / ImageChunk
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ Embedding     │  ← 后续阶段
│ Engine        │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ Retriever     │  ← 后续阶段
│               │
└───────────────┘
```

### 1.2 Evidence vs Chunk

| 维度 | Evidence | Chunk |
|------|----------|-------|
| 粒度 | 最小知识单位 | 检索单位 |
| 来源 | 直接从MinerU构建 | 从Evidence组合/切分 |
| 用途 | 数据存储、溯源 | Embedding、检索 |
| 关系 | 1个Evidence | 1个Chunk包含1-N个Evidence |

**核心思想**：
- Evidence是**数据层**的最小单位（保留完整溯源）
- Chunk是**检索层**的最小单位（优化Embedding和检索效果）
- 1个Chunk可以包含多个相关Evidence（合并短文本）

---

## 2. Chunk数据模型设计

### 2.1 TextChunk

```python
@dataclass
class TextChunk:
    """文本Chunk"""

    # === 标识 ===
    chunk_id: str                    # Chunk唯一ID
    evidence_ids: List[str]          # 关联的Evidence ID列表

    # === 来源定位 ===
    document_id: str                 # 文档ID
    company: str                     # 公司名称
    pages: List[int]                 # 涉及的页码列表
    section_path: List[str]          # 章节路径

    # === 内容 ===
    block_type: str = "text"         # 内容类型
    text: str = ""                   # 合并后的文本
    token_count: int = 0             # token数量

    # === 上下文 ===
    context_before: str = ""         # 前文上下文
    context_after: str = ""          # 后文上下文

    # === 元数据 ===
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "evidence_ids": self.evidence_ids,
            "document_id": self.document_id,
            "company": self.company,
            "pages": self.pages,
            "section_path": self.section_path,
            "block_type": self.block_type,
            "text": self.text,
            "token_count": self.token_count,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "metadata": self.metadata,
        }
```

### 2.2 TableChunk

```python
@dataclass
class TableChunk:
    """表格Chunk"""

    # === 标识 ===
    chunk_id: str
    evidence_ids: List[str]

    # === 来源定位 ===
    document_id: str
    company: str
    pages: List[int]
    section_path: List[str]

    # === 内容 ===
    block_type: str = "table"
    table_html: str = ""             # 原始HTML（用于展示）
    table_data: Dict[str, Any] = field(default_factory=dict)  # 结构化数据
    table_description: str = ""      # 表格描述（用于Embedding）
    token_count: int = 0

    # === 元数据 ===
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "evidence_ids": self.evidence_ids,
            "document_id": self.document_id,
            "company": self.company,
            "pages": self.pages,
            "section_path": self.section_path,
            "block_type": self.block_type,
            "table_html": self.table_html,
            "table_data": self.table_data,
            "table_description": self.table_description,
            "token_count": self.token_count,
            "metadata": self.metadata,
        }

    def to_text_for_embedding(self) -> str:
        """生成用于Embedding的文本描述"""
        # 例: "表格: 申请认购数目及应缴款项表。包含列: 申请认购数目, 应缴款项(港元)。共15行。"
        return self.table_description
```

### 2.3 ImageChunk

```python
@dataclass
class ImageChunk:
    """图片Chunk"""

    # === 标识 ===
    chunk_id: str
    evidence_ids: List[str]

    # === 来源定位 ===
    document_id: str
    company: str
    pages: List[int]
    section_path: List[str]

    # === 内容 ===
    block_type: str = "image"
    image_path: str = ""             # 图片文件路径
    image_caption: str = ""          # 图片标题
    image_description: str = ""      # 图片描述（用于Embedding）
    token_count: int = 0

    # === 元数据 ===
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "evidence_ids": self.evidence_ids,
            "document_id": self.document_id,
            "company": self.company,
            "pages": self.pages,
            "section_path": self.section_path,
            "block_type": self.block_type,
            "image_path": self.image_path,
            "image_caption": self.image_caption,
            "image_description": self.image_description,
            "token_count": self.token_count,
            "metadata": self.metadata,
        }

    def to_text_for_embedding(self) -> str:
        """生成用于Embedding的文本描述"""
        return self.image_description or self.image_caption or "图片"
```

### 2.4 Chunk ID格式

```
chk_{document_id}_p{page}_{type_prefix}{index:03d}
```

| 类型 | 前缀 | 示例 |
|------|------|------|
| TextChunk | `txt` | `chk_2021_01024_快手_p45_txt001` |
| TableChunk | `tbl` | `chk_2021_01024_快手_p3_tbl001` |
| ImageChunk | `img` | `chk_2021_01024_快手_p0_img001` |

**与Evidence ID的区别**：
- Evidence ID: `ev_2021_01024_快手_p45_txt001`
- Chunk ID: `chk_2021_01024_快手_p45_txt001`

---

## 3. Text Chunk策略

### 3.1 招股书长文本特点

基于实际数据统计：

| 指标 | 值 | 说明 |
|------|-----|------|
| 平均Evidence长度 | 53字符 | 较短 |
| 中位数长度 | 28字符 | 很短 |
| 最大长度 | 352字符 | 适中 |
| 招股书总页数 | 500-800页 | 长文档 |

**特点**：
- MinerU切分后的Evidence大多很短（28-53字符）
- 需要合并多个短Evidence才能形成有意义的Chunk
- 招股书有明确的章节结构

### 3.2 合并策略

**核心思想**：将相邻的短Evidence合并为有意义的Chunk

```python
def merge_text_evidences(
    evidences: List[TextEvidence],
    max_tokens: int = 512,
    min_tokens: int = 50,
) -> List[TextChunk]:
    """
    合并短Evidence为Chunk

    策略:
    1. 按page_idx排序
    2. 同一section_path的Evidence优先合并
    3. 合并直到达到max_tokens
    4. 过短的Chunk向前合并
    """
    pass
```

### 3.3 标题层级处理

**问题**：标题应该作为Chunk的上下文，还是独立Chunk？

**方案**：标题作为上下文附加到后续Chunk

```python
# 原始Evidence序列:
# [标题: "风险因素"] [文本: "本节讨论..."] [文本: "主要包括..."]

# 合并后的Chunk:
# TextChunk(
#     text="本节讨论... 主要包括...",
#     context_before="风险因素",
#     section_path=["风险因素"],
# )
```

### 3.4 页码连续性

**问题**：跨页文本是否应该合并？

**方案**：允许跨页合并，但保留所有页码

```python
# 跨页Evidence合并
chunk = TextChunk(
    text="...第45页内容... 第46页内容...",
    pages=[45, 46],  # 保留所有页码
    section_path=["风险因素", "业务风险"],
)
```

---

## 4. Table Chunk策略

### 4.1 核心原则

**不要简单转文本。保留表格结构。**

### 4.2 双轨存储

```python
class TableChunk:
    # 用于展示（保留原始HTML）
    table_html: str = "<table>...</table>"

    # 用于Embedding（文本描述）
    table_description: str = "表格: 申请认购数目及应缴款项表..."

    # 用于结构化查询（JSON数据）
    table_data: Dict = {
        "headers": ["申请认购数目", "应缴款项"],
        "rows": [["100", "11,615.89"], ...],
    }
```

### 4.3 表格描述生成

**目标**：生成适合Embedding的文本描述

```python
def generate_table_description(table_data: Dict) -> str:
    """
    生成表格描述

    示例输出:
    "表格: 申请认购数目及应缴款项表。
     包含列: 申请认购数目, 应缴款项(港元)。
     共15行数据。
     关键数据: 100股对应11,615.89港元, 200股对应23,231.77港元。"
    """
    pass
```

### 4.4 大表格处理

**问题**：招股书中的财务报表可能很大（如现金流量表50+行）

**方案**：
- 小表格（<20行）：整个表格作为一个Chunk
- 大表格（≥20行）：按逻辑分组拆分

```python
def split_large_table(table_data: Dict, max_rows: int = 20) -> List[Dict]:
    """
    拆分大表格

    策略:
    1. 保留表头
    2. 按行分组
    3. 每组包含表头 + 数据行
    """
    pass
```

---

## 5. Image Chunk策略

### 5.1 哪些图片进入RAG

| 图片类型 | 进入RAG | 原因 |
|----------|---------|------|
| Logo图片 | ❌ 过滤 | 无信息价值 |
| 装饰图片 | ❌ 过滤 | 无信息价值 |
| 股权结构图 | ✅ 保留 | 重要信息 |
| 流程图 | ✅ 保留 | 业务逻辑 |
| 财务图表 | ✅ 保留 | 数据可视化 |
| 组织架构图 | ✅ 保留 | 公司治理 |

### 5.2 图片过滤规则

```python
def should_include_image(evidence: ImageEvidence) -> bool:
    """
    判断图片是否应该进入RAG

    过滤规则:
    1. 图片尺寸太小 (< 50x50 px) → 过滤
    2. 图片在页面边缘 (可能是Logo) → 检查
    3. 图片有caption → 保留
    4. 图片在财务章节 → 保留
    """
    # 规则1: 尺寸过滤
    if evidence.image_width < 50 or evidence.image_height < 50:
        return False

    # 规则2: 有caption的图片保留
    if evidence.image_caption:
        return True

    # 规则3: 财务章节的图片保留
    financial_sections = ["财务", "现金流", "收入", "利润"]
    if any(s in " > ".join(evidence.section_path) for s in financial_sections):
        return True

    # 默认: 保留
    return True
```

### 5.3 图片Embedding策略

**问题**：图片无法直接Embedding

**方案**：使用图片描述进行Embedding

```python
def generate_image_description(evidence: ImageEvidence) -> str:
    """
    生成图片描述用于Embedding

    优先级:
    1. 使用image_caption（如果有）
    2. 使用section_path推断
    3. 使用page上下文推断
    """
    if evidence.image_caption:
        return f"图片: {evidence.image_caption}"

    if evidence.section_path:
        return f"图片: {' > '.join(evidence.section_path)}相关内容"

    return f"图片: 第{evidence.page}页"
```

---

## 6. Chunk大小策略

### 6.1 Token长度选择

| 策略 | Token数 | 适用场景 |
|------|---------|----------|
| 短Chunk | 128-256 | 精确检索，适合FAQ |
| 中Chunk | 256-512 | **推荐**，平衡精度和上下文 |
| 长Chunk | 512-1024 | 上下文丰富，适合长文档 |

**金融文档推荐**：**256-512 tokens**

**原因**：
1. 招股书Evidence平均53字符，需要合并多个
2. 金融问题通常需要一定上下文
3. BGE模型最大支持512 tokens

### 6.2 Overlap策略

| 策略 | Overlap | 适用场景 |
|------|---------|----------|
| 无重叠 | 0% | 独立段落 |
| 轻量重叠 | 10-15% | **推荐**，平衡效率 |
| 重度重叠 | 25-50% | 需要高召回率 |

**金融文档推荐**：**10-15% overlap**

**原因**：
1. 招股书段落相对独立
2. 过度重叠会增加索引大小
3. 10-15%足够保证上下文连续性

### 6.3 金融文档特点

**与通用文档的区别**：

| 特点 | 通用文档 | 金融招股书 |
|------|----------|-----------|
| 文本长度 | 中等 | 很短（Evidence平均53字符） |
| 表格密度 | 低 | 高（财务报表） |
| 章节结构 | 不明显 | 非常明确 |
| 数字密度 | 低 | 高 |
| 专业术语 | 少 | 多 |

**应对策略**：
1. 短Evidence合并：将多个短Evidence合并为一个Chunk
2. 表格独立处理：表格不参与文本合并
3. 章节感知：合并时优先考虑章节边界
4. 数字保留：确保财务数字完整保留

---

## 7. 接口设计

### 7.1 ChunkBuilder接口

```python
class ChunkBuilder:
    """Chunk构建器"""

    def __init__(self, config: ChunkConfig):
        """
        Args:
            config: Chunk配置
                - max_tokens: 最大token数 (默认512)
                - min_tokens: 最小token数 (默认50)
                - overlap_tokens: 重叠token数 (默认50)
        """
        pass

    def build(self, evidences: List[Evidence]) -> List[Chunk]:
        """
        从Evidence构建Chunk列表

        Args:
            evidences: Evidence列表

        Returns:
            List[Chunk]: Chunk列表 (TextChunk/TableChunk/ImageChunk)
        """
        pass

    def build_text_chunks(self, evidences: List[TextEvidence]) -> List[TextChunk]:
        """构建文本Chunk"""
        pass

    def build_table_chunks(self, evidences: List[TableEvidence]) -> List[TableChunk]:
        """构建表格Chunk"""
        pass

    def build_image_chunks(self, evidences: List[ImageEvidence]) -> List[ImageChunk]:
        """构建图片Chunk"""
        pass
```

### 7.2 ChunkConfig

```python
@dataclass
class ChunkConfig:
    """Chunk配置"""
    max_tokens: int = 512           # 最大token数
    min_tokens: int = 50            # 最小token数
    overlap_tokens: int = 50        # 重叠token数
    include_images: bool = True     # 是否包含图片
    image_min_size: int = 50        # 图片最小尺寸
    table_max_rows: int = 20        # 表格最大行数（超过则拆分）
```

### 7.3 ChunkStore接口

```python
class ChunkStore:
    """Chunk存储"""

    def save_chunks(self, chunks: List[Chunk]) -> None:
        """保存Chunk列表"""
        pass

    def get_chunk(self, chunk_id: str) -> Chunk:
        """获取Chunk"""
        pass

    def get_chunks_by_document(self, document_id: str) -> List[Chunk]:
        """获取文档的所有Chunk"""
        pass

    def get_chunks_by_evidence(self, evidence_id: str) -> List[Chunk]:
        """获取Evidence关联的Chunk"""
        pass

    def list_documents(self) -> List[str]:
        """列出所有文档"""
        pass
```

### 7.4 为Embedding提供的接口

```python
# TextChunk → Embedding
text_for_embedding = chunk.text

# TableChunk → Embedding
text_for_embedding = chunk.to_text_for_embedding()

# ImageChunk → Embedding
text_for_embedding = chunk.to_text_for_embedding()
```

### 7.5 为Retriever提供的接口

```python
# 检索时需要的信息
{
    "chunk_id": "chk_2021_01024_快手_p45_txt001",
    "text": "...",
    "document_id": "2021_01024_快手",
    "company": "快手科技",
    "pages": [45, 46],
    "section_path": ["风险因素", "业务风险"],
    "block_type": "text",
    "score": 0.95,
}
```

---

## 8. 输出结构

```
data/chunks/
├── {document_id}/
│   ├── chunks.json              # 所有Chunk序列化
│   └── chunk_index.json         # Chunk ID → Evidence ID映射
└── all_chunks.json              # 全量Chunk（用于批量Embedding）
```

---

## 9. 当前限制

| 限制 | 说明 | 后续方案 |
|------|------|----------|
| 短Evidence合并策略未验证 | 需要实际测试 | 实现后验证 |
| 图片过滤规则简单 | 可能误过滤 | 完善规则 |
| 表格拆分策略未验证 | 需要实际测试 | 实现后验证 |
| token计算依赖分词器 | 需要选择分词器 | 使用tiktoken |

---

## 10. 与现有设计的对齐

| 设计文档 | CHUNK_DESIGN | 说明 |
|----------|--------------|------|
| EVIDENCE_DESIGN_v1.1 | Evidence → Chunk | Chunk基于Evidence构建 |
| RAG_DESIGN.md | Chunk模块 | Chunk是检索层的核心 |
| RAG_API.md | retrieve_evidence | Chunk是检索的最小单位 |

---

## 11. 验收标准

| 检查项 | 标准 |
|--------|------|
| chunk_id格式 | `chk_{doc_id}_p{page}_{type}{seq}` |
| evidence_ids | 非空列表 |
| text Chunk长度 | 50-512 tokens |
| table Chunk保留结构 | table_html + table_data |
| image Chunk过滤 | 过滤小图、Logo |
| 跨页合并 | 支持 |
| 章节感知 | 合并时考虑章节边界 |
