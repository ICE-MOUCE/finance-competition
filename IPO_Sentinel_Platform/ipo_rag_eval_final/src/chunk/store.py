"""
Chunk Layer - Chunk Store
"""

import json
from pathlib import Path
from typing import Dict, List

from .models import Chunk


class ChunkStore:
    """Chunk存储"""

    def __init__(self, base_dir: str = "data/chunks"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, document_id: str, chunks: Dict[str, List[Chunk]]) -> None:
        """
        保存Chunk列表

        Args:
            document_id: 文档ID
            chunks: 按类型分组的Chunk列表
        """
        doc_dir = self.base_dir / document_id
        doc_dir.mkdir(parents=True, exist_ok=True)

        # 收集所有Chunk
        all_chunks = []
        for chunk_type, chunk_list in chunks.items():
            all_chunks.extend(chunk_list)

        # 保存chunks.json
        chunks_data = [c.to_dict() for c in all_chunks]
        chunks_path = doc_dir / "chunks.json"
        with open(chunks_path, "w", encoding="utf-8") as f:
            json.dump(chunks_data, f, ensure_ascii=False, indent=2)

        # 保存chunk_index.json
        self.save_index(document_id, all_chunks)

    def save_index(self, document_id: str, chunks: List[Chunk]) -> None:
        """
        保存Chunk索引

        Args:
            document_id: 文档ID
            chunks: Chunk列表
        """
        doc_dir = self.base_dir / document_id
        doc_dir.mkdir(parents=True, exist_ok=True)

        # chunk_id -> evidence_ids 映射
        index = {}
        for chunk in chunks:
            index[chunk.chunk_id] = chunk.evidence_ids

        index_path = doc_dir / "chunk_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    def load(self, document_id: str) -> List[Dict]:
        """加载Chunk列表"""
        chunks_path = self.base_dir / document_id / "chunks.json"
        if not chunks_path.exists():
            return []

        with open(chunks_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_index(self, document_id: str) -> Dict[str, List[str]]:
        """加载Chunk索引"""
        index_path = self.base_dir / document_id / "chunk_index.json"
        if not index_path.exists():
            return {}

        with open(index_path, "r", encoding="utf-8") as f:
            return json.load(f)
