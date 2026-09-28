"""
Retriever Layer - 数据模型
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SearchResult:
    """检索结果"""
    chunk_id: str
    evidence_ids: List[str]
    document_id: str
    company: str
    pages: List[int]
    section_path: List[str]
    block_type: str
    score: float
    text: str = ""
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
            "score": self.score,
            "text": self.text,
            "metadata": self.metadata,
        }

    def preview(self, max_chars: int = 50) -> str:
        """预览文本"""
        if self.text:
            return self.text[:max_chars] + ("..." if len(self.text) > max_chars else "")
        return ""
