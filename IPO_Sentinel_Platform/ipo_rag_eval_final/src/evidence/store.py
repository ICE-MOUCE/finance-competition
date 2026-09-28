"""
Evidence Layer - Evidence Store

轻量读取 data/evidence/{document_id}/evidences.json，按 evidence_id 回查证据。
"""

import json
from pathlib import Path
from typing import Dict, List


class EvidenceStore:
    """Evidence JSON 读取器"""

    def __init__(self, base_dir: str = "data/evidence"):
        self.base_dir = Path(base_dir)
        self._cache: Dict[str, Dict[str, dict]] = {}

    def load_document(self, document_id: str) -> Dict[str, dict]:
        """加载单个文档的Evidence索引"""
        if document_id in self._cache:
            return self._cache[document_id]

        evidence_path = self.base_dir / document_id / "evidences.json"
        if not evidence_path.exists():
            self._cache[document_id] = {}
            return self._cache[document_id]

        with open(evidence_path, "r", encoding="utf-8") as f:
            evidences = json.load(f)

        self._cache[document_id] = {
            evidence.get("evidence_id", ""): evidence for evidence in evidences
        }
        return self._cache[document_id]

    def get(self, document_id: str, evidence_id: str) -> dict:
        """按ID获取单条Evidence"""
        return self.load_document(document_id).get(evidence_id, {})

    def get_many(self, document_id: str, evidence_ids: List[str]) -> List[dict]:
        """批量获取Evidence，保留传入顺序"""
        evidence_map = self.load_document(document_id)
        return [evidence_map[eid] for eid in evidence_ids if eid in evidence_map]
