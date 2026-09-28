"""
Evidence Layer - 数据模型 (v1.2 Review修正)

严格遵循 EVIDENCE_DESIGN_v1.1.md 定义
Review修正: 增加BaseEvidence基类、Optional bbox、section_path默认值
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union


# ============================================================================
# Evidence ID 生成
# ============================================================================

TYPE_PREFIX_MAP = {
    "text": "txt",
    "table": "tbl",
    "image": "img",
}


def generate_evidence_id(document_id, page, block_type, sequence):
    """
    生成Evidence ID

    格式: ev_{document_id}_p{page}_{type_prefix}{index:03d}

    Example:
        >>> generate_evidence_id("2021_01024_快手", 45, "text", 1)
        'ev_2021_01024_快手_p45_txt001'
        >>> generate_evidence_id("2021_01024_快手", 3, "table", 1)
        'ev_2021_01024_快手_p3_tbl001'
    """
    type_prefix = TYPE_PREFIX_MAP[block_type]
    return f"ev_{document_id}_p{page}_{type_prefix}{sequence:03d}"


# ============================================================================
# BaseEvidence 抽象基类
# ============================================================================


class BaseEvidence(ABC):
    """
    Evidence抽象基类

    所有Evidence类型共享的字段和方法。
    TextEvidence、TableEvidence、ImageEvidence继承此类。
    """

    @property
    @abstractmethod
    def block_type(self) -> str:
        """内容类型 (text/table/image)"""
        pass

    @abstractmethod
    def to_citation(self) -> str:
        """生成Agent可引用的引用格式"""
        pass

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        pass


# ============================================================================
# TextEvidence
# ============================================================================


@dataclass
class TextEvidence(BaseEvidence):
    """文本证据"""

    # === 标识（必须）===
    evidence_id: str
    document_id: str

    # === 来源定位（必须）===
    company: str
    page: int
    section_path: List[str] = field(default_factory=list)
    bbox: Optional[Tuple[float, float, float, float]] = None
    source_file: str = ""

    # === 内容（必须）===
    text: str = ""
    _block_type: str = field(default="text", init=False, repr=False)

    # === 元数据 ===
    metadata: Dict[str, Any] = field(default_factory=dict)

    # === 风险标签 ===
    # NOTE: Evidence Builder不生成risk_tags
    # risk_tags由后续Risk Agent阶段生成
    risk_tags: List[str] = field(default_factory=list)

    # === 文本特有字段 ===
    is_header: bool = False
    header_level: int = 0
    context_before: str = ""
    context_after: str = ""

    @property
    def block_type(self) -> str:
        return self._block_type

    def to_citation(self) -> str:
        section_str = " > ".join(self.section_path) if self.section_path else ""
        return f"[Evidence {self.evidence_id}] p.{self.page} {section_str}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "document_id": self.document_id,
            "company": self.company,
            "page": self.page,
            "section_path": self.section_path,
            "bbox": list(self.bbox) if self.bbox else None,
            "source_file": self.source_file,
            "block_type": self.block_type,
            "text": self.text,
            "metadata": self.metadata,
            "risk_tags": self.risk_tags,
            "is_header": self.is_header,
            "header_level": self.header_level,
            "context_before": self.context_before,
            "context_after": self.context_after,
        }


# ============================================================================
# TableEvidence
# ============================================================================


@dataclass
class TableEvidence(BaseEvidence):
    """表格证据"""

    # === 标识（必须）===
    evidence_id: str
    document_id: str

    # === 来源定位（必须）===
    company: str
    page: int
    section_path: List[str] = field(default_factory=list)
    bbox: Optional[Tuple[float, float, float, float]] = None
    source_file: str = ""

    # === 内容（必须）===
    text: str = ""
    _block_type: str = field(default="table", init=False, repr=False)

    # === 元数据 ===
    metadata: Dict[str, Any] = field(default_factory=dict)

    # === 风险标签 ===
    # NOTE: Evidence Builder不生成risk_tags
    # risk_tags由后续Risk Agent阶段生成
    risk_tags: List[str] = field(default_factory=list)

    # === 表格特有字段 ===
    table_html: str = ""
    table_data: Dict[str, Any] = field(default_factory=dict)
    table_description: str = ""
    table_index: int = 0

    @property
    def block_type(self) -> str:
        return self._block_type

    def to_citation(self) -> str:
        section_str = " > ".join(self.section_path) if self.section_path else ""
        return f"[Evidence {self.evidence_id}] p.{self.page} {section_str}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "document_id": self.document_id,
            "company": self.company,
            "page": self.page,
            "section_path": self.section_path,
            "bbox": list(self.bbox) if self.bbox else None,
            "source_file": self.source_file,
            "block_type": self.block_type,
            "text": self.text,
            "metadata": self.metadata,
            "risk_tags": self.risk_tags,
            "table_html": self.table_html,
            "table_data": self.table_data,
            "table_description": self.table_description,
            "table_index": self.table_index,
        }


# ============================================================================
# ImageEvidence
# ============================================================================


@dataclass
class ImageEvidence(BaseEvidence):
    """图片证据"""

    # === 标识（必须）===
    evidence_id: str
    document_id: str

    # === 来源定位（必须）===
    company: str
    page: int
    section_path: List[str] = field(default_factory=list)
    bbox: Optional[Tuple[float, float, float, float]] = None
    source_file: str = ""

    # === 内容（必须）===
    text: str = ""
    _block_type: str = field(default="image", init=False, repr=False)

    # === 元数据 ===
    metadata: Dict[str, Any] = field(default_factory=dict)

    # === 风险标签 ===
    # NOTE: Evidence Builder不生成risk_tags
    # risk_tags由后续Risk Agent阶段生成
    risk_tags: List[str] = field(default_factory=list)

    # === 图片特有字段 ===
    image_path: str = ""
    image_hash: str = ""
    image_caption: str = ""
    image_width: int = 0
    image_height: int = 0

    @property
    def block_type(self) -> str:
        return self._block_type

    def to_citation(self) -> str:
        section_str = " > ".join(self.section_path) if self.section_path else ""
        return f"[Evidence {self.evidence_id}] p.{self.page} {section_str}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "document_id": self.document_id,
            "company": self.company,
            "page": self.page,
            "section_path": self.section_path,
            "bbox": list(self.bbox) if self.bbox else None,
            "source_file": self.source_file,
            "block_type": self.block_type,
            "text": self.text,
            "metadata": self.metadata,
            "risk_tags": self.risk_tags,
            "image_path": self.image_path,
            "image_hash": self.image_hash,
            "image_caption": self.image_caption,
            "image_width": self.image_width,
            "image_height": self.image_height,
        }


# Union type for type hints
Evidence = Union[TextEvidence, TableEvidence, ImageEvidence]


# ============================================================================
# Document 对象
# ============================================================================


@dataclass
class Document:
    """招股书文档对象"""

    document_id: str
    company: str
    stock_code: str
    listing_date: str
    industry: str
    source_file: str
    total_pages: int
    file_size_mb: float
    parsed_at: datetime
    parser_version: str
    content_list_path: str
    images_dir: str
    markdown_path: str
    evidence_store_path: str = ""  # Evidence输出目录
    evidences: List[Any] = field(default_factory=list)
    text_count: int = 0
    table_count: int = 0
    image_count: int = 0

    def to_dict(self):
        return {
            "document_id": self.document_id,
            "company": self.company,
            "stock_code": self.stock_code,
            "listing_date": self.listing_date,
            "industry": self.industry,
            "source_file": self.source_file,
            "total_pages": self.total_pages,
            "file_size_mb": self.file_size_mb,
            "parsed_at": self.parsed_at.isoformat(),
            "parser_version": self.parser_version,
            "content_list_path": self.content_list_path,
            "images_dir": self.images_dir,
            "markdown_path": self.markdown_path,
            "evidence_store_path": self.evidence_store_path,
            "text_count": self.text_count,
            "table_count": self.table_count,
            "image_count": self.image_count,
        }
