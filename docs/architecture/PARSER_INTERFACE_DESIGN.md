# Parser 模块接口设计

> PDF解析 → Markdown → Document对象

---

## 1. 模块职责

```
┌─────────────────────────────────────────────────────────────────┐
│                     Parser 模块边界                              │
└─────────────────────────────────────────────────────────────────┘

输入：PDF文件路径
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│  Parser                                                         │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │
│  │ PDF解析       │→│ Markdown生成   │→│ Metadata提取  │       │
│  │ (MinerU)      │  │               │  │               │       │
│  └───────────────┘  └───────────────┘  └───────────────┘       │
└─────────────────────────────────────────────────────────────────┘
      │
      ▼
输出：Document对象（Markdown + Metadata）

不包含：Embedding、向量化、检索、LLM调用
```

---

## 2. 核心接口

### 2.1 Parser 接口

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class BaseParser(ABC):
    """Parser基类"""

    @abstractmethod
    def parse(self, pdf_path: Path) -> Document:
        """
        解析PDF文件

        Args:
            pdf_path: PDF文件路径

        Returns:
            Document: 包含Markdown和Metadata的文档对象

        Raises:
            FileNotFoundError: 文件不存在
            ParserError: 解析失败
        """
        pass

    @abstractmethod
    def parse_pages(self, pdf_path: Path, start: int, end: int) -> Document:
        """
        解析PDF指定页面

        Args:
            pdf_path: PDF文件路径
            start: 起始页码（从1开始）
            end: 结束页码

        Returns:
            Document: 包含指定页面的文档对象
        """
        pass
```

### 2.2 Document 数据模型

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any


class DocumentType(str, Enum):
    """文档类型"""
    PROSPECTUS = "prospectus"  # 招股书
    CASE = "case"              # 案例


@dataclass
class TableInfo:
    """表格信息"""
    table_id: str              # 表格唯一ID
    page_number: int           # 所在页码
    caption: str               # 表格标题/描述
    row_count: int             # 行数
    col_count: int             # 列数
    markdown: str              # Markdown格式表格
    bbox: Optional[tuple] = None  # 边界框坐标


@dataclass
class ImageInfo:
    """图片信息"""
    image_id: str              # 图片唯一ID
    page_number: int           # 所在页码
    caption: str               # 图片标题/描述
    ref: str                   # Markdown引用
    bbox: Optional[tuple] = None


@dataclass
class TOCEntry:
    """目录条目"""
    title: str                 # 标题
    level: int                 # 层级（1=一级，2=二级...）
    page_number: int           # 页码
    children: List['TOCEntry'] = field(default_factory=list)


@dataclass
class PageContent:
    """页面内容"""
    page_number: int           # 页码
    markdown: str              # 页面Markdown内容
    tables: List[TableInfo]    # 该页表格
    images: List[ImageInfo]    # 该页图片


@dataclass
class DocumentMetadata:
    """文档元数据"""
    # 基本信息
    doc_id: str                # 文档唯一ID
    file_name: str             # 文件名
    file_size_mb: float        # 文件大小(MB)
    total_pages: int           # 总页数

    # 公司信息（从文件名或内容提取）
    company_name: str = ""     # 公司名称
    stock_code: str = ""       # 股票代码
    listing_date: str = ""     # 上市日期
    industry: str = ""         # 行业
    document_type: DocumentType = DocumentType.PROSPECTUS

    # 解析信息
    parsed_at: datetime = field(default_factory=datetime.now)
    parser_version: str = "1.0.0"
    parse_duration_seconds: float = 0.0

    # 统计信息
    table_count: int = 0       # 表格总数
    image_count: int = 0       # 图片总数
    toc_entries: int = 0       # 目录条目数


@dataclass
class Document:
    """文档对象 - Parser输出"""

    # 元数据
    metadata: DocumentMetadata

    # Markdown内容
    markdown: str              # 完整Markdown（所有页面合并）
    markdown_pages: List[PageContent]  # 按页拆分的Markdown

    # 结构化信息
    toc: List[TOCEntry]        # 目录结构
    tables: List[TableInfo]    # 所有表格
    images: List[ImageInfo]    # 所有图片

    # 文件路径
    source_path: Path          # 原始PDF路径
    markdown_path: Optional[Path] = None  # Markdown文件路径（如果保存）

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "metadata": {
                "doc_id": self.metadata.doc_id,
                "file_name": self.metadata.file_name,
                "total_pages": self.metadata.total_pages,
                "company_name": self.metadata.company_name,
                "stock_code": self.metadata.stock_code,
                "table_count": self.metadata.table_count,
                "image_count": self.metadata.image_count,
            },
            "toc": [
                {"title": e.title, "level": e.level, "page": e.page_number}
                for e in self.toc
            ],
            "tables": [
                {
                    "id": t.table_id,
                    "page": t.page_number,
                    "caption": t.caption,
                    "rows": t.row_count,
                    "cols": t.col_count,
                }
                for t in self.tables
            ],
            "markdown_length": len(self.markdown),
        }

    def get_page(self, page_number: int) -> Optional[PageContent]:
        """获取指定页内容"""
        for page in self.markdown_pages:
            if page.page_number == page_number:
                return page
        return None

    def get_chapter_pages(self, chapter_title: str) -> List[PageContent]:
        """获取指定章节的所有页面"""
        # 根据TOC找到章节页码范围，返回对应页面
        pass
```

---

## 3. MinerU Parser 实现接口

### 3.1 MinerUParser 类

```python
class MinerUParser(BaseParser):
    """MinerU PDF解析器"""

    def __init__(self, config: Optional[MinerUConfig] = None):
        """
        初始化

        Args:
            config: MinerU配置，None使用默认配置
        """
        pass

    def parse(self, pdf_path: Path) -> Document:
        """解析整个PDF"""
        pass

    def parse_pages(self, pdf_path: Path, start: int, end: int) -> Document:
        """解析指定页面"""
        pass


@dataclass
class MinerUConfig:
    """MinerU配置"""
    backend: str = "pipeline"      # 后端：pipeline/vlm-engine/hybrid-engine
    method: str = "auto"           # 方法：auto/txt/ocr
    language: str = "ch"           # 语言：ch/ch_server/en
    enable_table: bool = True      # 启用表格提取
    enable_ocr: bool = True        # 启用OCR
    enable_formula: bool = True    # 启用公式识别
    effort: str = "medium"         # 解析精度：medium/high
```

### 3.2 备选 Parser

```python
class PdfPlumberParser(BaseParser):
    """pdfplumber解析器（轻量备选）"""

    def __init__(self, enable_table: bool = True):
        pass

    def parse(self, pdf_path: Path) -> Document:
        """解析PDF（文本为主，表格有限）"""
        pass


class CamelotParser(BaseParser):
    """camelot解析器（表格专用）"""

    def __init__(self, flavor: str = "stream"):
        """
        Args:
            flavor: 表格检测模式 lattice/stream
        """
        pass

    def parse(self, pdf_path: Path) -> Document:
        """解析PDF（专注表格提取）"""
        pass
```

---

## 4. 使用示例

### 4.1 基本使用

```python
from rag.parser import MinerUParser, Document

# 初始化Parser
parser = MinerUParser()

# 解析PDF
doc = parser.parse(Path("data/raw/2021_88份/01024_26-01-2021_快手－Ｗ_全球發售.pdf"))

# 访问文档信息
print(f"公司: {doc.metadata.company_name}")
print(f"页数: {doc.metadata.total_pages}")
print(f"表格: {doc.metadata.table_count}")
print(f"目录: {len(doc.toc)} 条")

# 访问Markdown
print(doc.markdown[:500])

# 访问指定页面
page_100 = doc.get_page(100)
if page_100:
    print(f"第100页: {len(page_100.markdown)} 字符")
    print(f"表格: {len(page_100.tables)} 个")
```

### 4.2 批量处理

```python
from rag.parser import MinerUParser
from pathlib import Path

parser = MinerUParser()

# 批量解析
pdf_dir = Path("data/raw/2021_88份")
for pdf_file in pdf_dir.glob("*.pdf"):
    doc = parser.parse(pdf_file)
    print(f"{doc.metadata.file_name}: {doc.metadata.total_pages}页, {doc.metadata.table_count}表格")
```

### 4.3 保存Markdown

```python
# 保存到文件
output_dir = Path("data/processed")
markdown_path = output_dir / f"{doc.metadata.doc_id}.md"
markdown_path.write_text(doc.markdown, encoding="utf-8")
doc.markdown_path = markdown_path
```

---

## 5. 输出格式规范

### 5.1 Markdown 格式

```markdown
# {公司名称} {文档类型}

**股票代码**: {股票代码}
**上市日期**: {上市日期}
**总页数**: {页数}

---

## 第 {页码} 页

{页面文本内容}

### 表格 {序号}: {表格标题}

| 列1 | 列2 | 列3 |
|-----|-----|-----|
| 数据 | 数据 | 数据 |

---

## 第 {页码+1} 页

{下一页内容}
```

### 5.2 目录格式

```python
toc = [
    TOCEntry(title="概要", level=1, page_number=1),
    TOCEntry(title="风险因素", level=1, page_number=6),
    TOCEntry(title="与业务相关的风险", level=2, page_number=6),
    TOCEntry(title="与财务相关的风险", level=2, page_number=25),
    TOCEntry(title="财务资料", level=1, page_number=45),
    # ...
]
```

### 5.3 元数据提取

从文件名提取：
```
01024_26-01-2021_快手－Ｗ_全球發售.pdf
      │         │      │
      │         │      └─ 文档类型：全球发售
      │         └─ 公司名称：快手
      └─ 股票代码：01024
      └─ 上市日期：2021-01-26
```

---

## 6. 错误处理

### 6.1 异常定义

```python
class ParserError(Exception):
    """Parser基础异常"""
    pass

class PDFNotFoundError(ParserError):
    """PDF文件不存在"""
    pass

class PDFEncryptedError(ParserError):
    """PDF加密，无法解析"""
    pass

class MinerUError(ParserError):
    """MinerU解析错误"""
    pass

class TableExtractionError(ParserError):
    """表格提取错误"""
    pass
```

### 6.2 错误处理策略

```python
try:
    doc = parser.parse(pdf_path)
except PDFNotFoundError:
    print(f"文件不存在: {pdf_path}")
except PDFEncryptedError:
    print(f"文件加密: {pdf_path}")
except MinerUError as e:
    print(f"MinerU解析失败: {e}")
    # 降级到pdfplumber
    doc = fallback_parser.parse(pdf_path)
except ParserError as e:
    print(f"解析错误: {e}")
```

---

## 7. 日志规范

### 7.1 日志格式

```python
import logging

logger = logging.getLogger("rag.parser")

# 解析开始
logger.info(f"开始解析: {pdf_path.name}, {total_pages}页")

# 进度
logger.info(f"解析进度: {current_page}/{total_pages}")

# 表格提取
logger.info(f"提取表格: 第{page}页, {table_count}个")

# 解析完成
logger.info(f"解析完成: {doc.metadata.file_name}, 耗时{duration:.1f}秒")
```

### 7.2 日志级别

| 级别 | 用途 |
|------|------|
| DEBUG | 详细调试信息 |
| INFO | 解析进度、结果统计 |
| WARNING | 降级处理、非致命错误 |
| ERROR | 解析失败、致命错误 |

---

## 8. 性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 解析速度 | ≥10页/秒 | MinerU pipeline |
| 表格提取率 | ≥80% | 财务表格 |
| 表格精度 | ≥90% | 结构正确 |
| 目录识别率 | ≥90% | 一级标题 |
| 页码保留率 | 100% | 所有页面 |

---

## 9. 依赖清单

```
# requirements-parser.txt

# PDF解析
mineru>=3.4.0           # MinerU（需要torch）

# 备选方案
pdfplumber>=0.10.0      # 文本提取
camelot-py>=0.11.0      # 表格提取
PyPDF2>=3.0.0           # PDF处理
PyMuPDF>=1.23.0         # PDF处理

# 工具
opencc-python-reimplemented>=0.1.7  # 繁简转换
loguru>=0.7.0           # 日志
```

---

## 10. 文件结构

```
rag/
├── parser/
│   ├── __init__.py
│   ├── base.py           # BaseParser抽象类
│   ├── models.py         # Document, TableInfo等数据模型
│   ├── mineru_parser.py  # MinerUParser实现
│   ├── pdfplumber_parser.py  # 备选方案
│   ├── metadata_extractor.py # 元数据提取
│   ├── exceptions.py     # 异常定义
│   └── utils.py          # 工具函数
├── chunk/                # 下一阶段
├── embedding/            # 后续阶段
└── ...
```
