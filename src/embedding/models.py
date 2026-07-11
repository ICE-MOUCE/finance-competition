"""
Embedding Layer - 数据模型
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VectorDocument:
    """向量化文档"""
    id: str                    # 唯一ID
    chunk_id: str              # 关联的Chunk ID
    document_id: str           # 文档ID
    company: str               # 公司名称
    pages: List[int]           # 页码列表
    section_path: List[str] = field(default_factory=list)
    block_type: str = ""       # text/table/image
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "company": self.company,
            "pages": self.pages,
            "section_path": self.section_path,
            "block_type": self.block_type,
            "metadata": self.metadata,
        }
