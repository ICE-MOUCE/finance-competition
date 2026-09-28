"""
Chunk Layer - 数据模型

TextChunk / TableChunk / ImageChunk
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Union


TYPE_PREFIX_MAP = {
    "text": "txt",
    "table": "tbl",
    "image": "img",
}


def generate_chunk_id(document_id: str, first_page: int, block_type: str, sequence: int) -> str:
    """
    生成Chunk ID

    格式: chk_{document_id}_p{first_page}_{type_prefix}{seq:03d}

    Example:
        >>> generate_chunk_id("2021_01024_快手", 45, "text", 1)
        'chk_2021_01024_快手_p45_txt001'
    """
    type_prefix = TYPE_PREFIX_MAP[block_type]
    return f"chk_{document_id}_p{first_page}_{type_prefix}{sequence:03d}"


@dataclass
class TextChunk:
    """文本Chunk"""
    chunk_id: str
    evidence_ids: List[str]
    document_id: str
    company: str
    pages: List[int]
    section_path: List[str] = field(default_factory=list)
    block_type: str = "text"
    text: str = ""
    token_count: int = 0
    context_before: str = ""
    context_after: str = ""
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

    def to_text_for_embedding(self) -> str:
        """用于Embedding的文本"""
        return self.text


@dataclass
class TableChunk:
    """表格Chunk"""
    chunk_id: str
    evidence_ids: List[str]
    document_id: str
    company: str
    pages: List[int]
    section_path: List[str] = field(default_factory=list)
    block_type: str = "table"
    table_html: str = ""
    table_data: Dict[str, Any] = field(default_factory=dict)
    table_description: str = ""
    token_count: int = 0
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
        """用于Embedding的文本"""
        return self.table_description


@dataclass
class ImageChunk:
    """图片Chunk"""
    chunk_id: str
    evidence_ids: List[str]
    document_id: str
    company: str
    pages: List[int]
    section_path: List[str] = field(default_factory=list)
    block_type: str = "image"
    image_path: str = ""
    image_caption: str = ""
    image_description: str = ""
    token_count: int = 0
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
        """用于Embedding的文本"""
        return self.image_description or self.image_caption or "图片"


# Union type
Chunk = Union[TextChunk, TableChunk, ImageChunk]
