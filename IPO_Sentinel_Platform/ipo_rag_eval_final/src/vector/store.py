"""Vector Layer - FAISS Vector Store."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import faiss
import numpy as np
from loguru import logger

from ..embedding.models import VectorDocument


class VectorStore:
    """FAISS vector store."""

    def __init__(self, persist_path: str, dimension: int = 512, reset: bool = False):
        self.persist_path = Path(persist_path)
        self.persist_path.mkdir(parents=True, exist_ok=True)
        self.dimension = dimension
        self.reset = reset

        self.index: Optional[faiss.IndexFlatIP] = None
        self.documents: List[VectorDocument] = []
        self.doc_id_map: Dict[int, str] = {}
        self.chunk_ids: set[str] = set()

        self._init_index()

    def _init_index(self):
        """Initialize FAISS index."""
        index_path = self.persist_path / "faiss.index"
        docs_path = self.persist_path / "documents.json"

        if self.reset:
            self.index = faiss.IndexFlatIP(self.dimension)
            self.documents = []
            self.doc_id_map = {}
            self.chunk_ids = set()
        elif index_path.exists() and docs_path.exists():
            self.load()
        else:
            self.index = faiss.IndexFlatIP(self.dimension)
            self.documents = []
            self.doc_id_map = {}
            self.chunk_ids = set()

    def add_documents(self, docs: List[VectorDocument]) -> int:
        """Add vector documents in batch."""
        if not docs:
            return 0

        embeddings = []
        skipped_missing = 0
        skipped_duplicate = 0
        skipped_dimension = 0
        for doc in docs:
            if doc.embedding is None:
                skipped_missing += 1
                continue
            if doc.chunk_id in self.chunk_ids:
                skipped_duplicate += 1
                continue
            if len(doc.embedding) != self.dimension:
                skipped_dimension += 1
                continue
            embeddings.append(doc.embedding)
            self.documents.append(doc)
            self.doc_id_map[len(self.documents) - 1] = doc.chunk_id
            self.chunk_ids.add(doc.chunk_id)

        if skipped_missing or skipped_duplicate or skipped_dimension:
            logger.warning(
                "Skipped vector documents: "
                f"missing_embedding={skipped_missing}, "
                f"duplicate={skipped_duplicate}, "
                f"dimension_mismatch={skipped_dimension}"
            )

        if embeddings:
            vectors = np.array(embeddings, dtype=np.float32)
            self.index.add(vectors)
            logger.info(f"Added {len(embeddings)} vectors; total: {self.index.ntotal}")

        return len(embeddings)

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search by vector similarity."""
        if self.index.ntotal == 0:
            return []

        query_vector = np.array([query_embedding], dtype=np.float32)
        k = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(query_vector, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.documents):
                continue
            doc = self.documents[idx]
            results.append({
                "chunk_id": doc.chunk_id,
                "document_id": doc.document_id,
                "company": doc.company,
                "pages": doc.pages,
                "section_path": doc.section_path,
                "block_type": doc.block_type,
                "score": float(score),
                "metadata": doc.metadata,
            })

        return results

    def search_by_row_ids(
        self,
        query_embedding: List[float],
        row_ids: List[int],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Search an explicit FAISS row-id subset with exact inner-product ranking."""
        if self.index.ntotal == 0 or not row_ids or top_k <= 0:
            return []

        valid_row_ids = []
        seen = set()
        for row_id in row_ids:
            try:
                row_id = int(row_id)
            except (TypeError, ValueError):
                continue
            if row_id in seen:
                continue
            seen.add(row_id)
            if 0 <= row_id < self.index.ntotal and row_id < len(self.documents):
                valid_row_ids.append(row_id)

        if not valid_row_ids:
            return []

        ids = np.asarray(valid_row_ids, dtype=np.int64)
        if hasattr(self.index, "reconstruct_batch"):
            vectors = self.index.reconstruct_batch(ids)
        else:
            vectors = np.vstack([self.index.reconstruct(int(row_id)) for row_id in valid_row_ids])

        query_vector = np.asarray(query_embedding, dtype=np.float32)
        scores = vectors @ query_vector
        take = min(top_k, len(valid_row_ids))
        top_positions = np.argsort(-scores)[:take]

        results = []
        for position in top_positions:
            row_id = valid_row_ids[int(position)]
            doc = self.documents[row_id]
            results.append({
                "chunk_id": doc.chunk_id,
                "document_id": doc.document_id,
                "company": doc.company,
                "pages": doc.pages,
                "section_path": doc.section_path,
                "block_type": doc.block_type,
                "score": float(scores[int(position)]),
                "metadata": doc.metadata,
            })

        return results

    def save(self) -> None:
        """Persist index and metadata to disk."""
        index_path = self.persist_path / "faiss.index"
        docs_path = self.persist_path / "documents.json"

        tmp_path = str(index_path) + ".tmp"
        faiss.write_index(self.index, tmp_path)
        if index_path.exists():
            os.unlink(str(index_path))
        os.rename(tmp_path, str(index_path))

        docs_data = [doc.to_dict() for doc in self.documents]
        with open(docs_path, "w", encoding="utf-8") as f:
            json.dump(docs_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Index saved: {index_path} ({self.index.ntotal} vectors)")

    def load(self) -> None:
        """Load index and metadata from disk."""
        index_path = self.persist_path / "faiss.index"
        docs_path = self.persist_path / "documents.json"

        if not index_path.exists() or not docs_path.exists():
            logger.warning("Index files not found; creating a new index")
            self._init_index()
            return

        tmp_path = str(index_path) + ".load_tmp"
        with open(tmp_path, "wb") as tmp:
            tmp.write(index_path.read_bytes())
        self.index = faiss.read_index(tmp_path)
        os.unlink(tmp_path)
        self.dimension = self.index.d

        with open(docs_path, "r", encoding="utf-8") as f:
            docs_data = json.load(f)

        self.documents = []
        self.doc_id_map = {}
        self.chunk_ids = set()
        for i, data in enumerate(docs_data):
            doc = VectorDocument(
                id=data.get("id", ""),
                chunk_id=data.get("chunk_id", ""),
                document_id=data.get("document_id", ""),
                company=data.get("company", ""),
                pages=data.get("pages", []),
                section_path=data.get("section_path", []),
                block_type=data.get("block_type", ""),
                metadata=data.get("metadata", {}),
            )
            self.documents.append(doc)
            self.doc_id_map[i] = doc.chunk_id
            self.chunk_ids.add(doc.chunk_id)

        logger.info(f"Index loaded: {self.index.ntotal} vectors, {len(self.documents)} documents")

    def get_stats(self) -> Dict[str, Any]:
        """Return vector store statistics."""
        index_size = 0
        index_path = self.persist_path / "faiss.index"
        if index_path.exists():
            index_size = index_path.stat().st_size

        return {
            "total_vectors": self.index.ntotal if self.index else 0,
            "dimension": self.dimension,
            "total_documents": len(self.documents),
            "index_size_bytes": index_size,
            "index_size_mb": round(index_size / 1024 / 1024, 2),
        }
