
"""Local use-of-proceeds cross-page representation repair.

Rebuilds Chunk (+ optional Vector) for documents that contain use-of-proceeds
allocation evidence, using the updated ChunkBuilder packing/enrichment logic.

This is intentionally local and reversible:
- dry-run first
- no Gold edits
- no ranking flag defaults changed
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chunk import ChunkBuilder, ChunkConfig, ChunkStore  # noqa: E402
from src.chunk.use_of_proceeds_packing import is_uop_unit  # noqa: E402
from src.embedding import EmbeddingConfig, EmbeddingEngine, VectorDocument  # noqa: E402
from src.vector import VectorStore  # noqa: E402


def find_docs(evidence_dir: Path, only: List[str] | None = None) -> List[str]:
    docs = sorted(p.name for p in evidence_dir.iterdir() if p.is_dir())
    if only:
        selected = []
        for item in only:
            for doc in docs:
                if item == doc or item in doc:
                    if doc not in selected:
                        selected.append(doc)
        return selected
    return docs


def document_has_uop_units(evidence_path: Path) -> dict:
    evidences = json.loads(evidence_path.read_text(encoding="utf-8"))
    units = [e for e in evidences if is_uop_unit(e)]
    pages = sorted({int(e.get("page") or 0) for e in units})
    return {
        "evidence_count": len(evidences),
        "uop_unit_count": len(units),
        "uop_pages": pages[:30],
        "triggered": len(units) >= 3,
    }


def flatten_chunks(chunks_by_type: dict) -> List[dict]:
    out: List[dict] = []
    for block_type, items in chunks_by_type.items():
        for chunk in items:
            data = chunk.to_dict() if hasattr(chunk, "to_dict") else dict(chunk.__dict__)
            data.setdefault("block_type", block_type)
            out.append(data)
    return out


def backup_file(path: Path, backup_root: Path) -> Path | None:
    if not path.exists():
        return None
    backup_root.mkdir(parents=True, exist_ok=True)
    target = backup_root / path.name
    shutil.copy2(path, target)
    return target


def rebuild_chunks(document_id: str, evidence_dir: Path, chunk_dir: Path, backup_root: Path | None = None) -> dict:
    evidences = json.loads((evidence_dir / document_id / "evidences.json").read_text(encoding="utf-8"))
    old_path = chunk_dir / document_id / "chunks.json"
    old_count = 0
    if old_path.exists():
        old_count = len(json.loads(old_path.read_text(encoding="utf-8")))
        if backup_root is not None:
            backup_file(old_path, backup_root / document_id)
    built = ChunkBuilder(ChunkConfig()).build(evidences)
    new_chunks = flatten_chunks(built)
    store = ChunkStore(str(chunk_dir))
    # ChunkStore API may vary; write directly for stability
    out_dir = chunk_dir / document_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "chunks.json").write_text(json.dumps(new_chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "document_id": document_id,
        "old_chunk_count": old_count,
        "new_chunk_count": len(new_chunks),
        "text_chunks": len(built.get("text", [])),
        "table_chunks": len(built.get("table", [])),
        "image_chunks": len(built.get("image", [])),
    }


def get_chunk_text(chunk: dict) -> str:
    block_type = chunk.get("block_type", "")
    if block_type == "text":
        return chunk.get("text", "") or ""
    if block_type == "table":
        return chunk.get("table_description", "") or ""
    return chunk.get("image_description") or chunk.get("image_caption") or chunk.get("text") or ""


def build_vector_documents(chunks: List[dict], embeddings: List[List[float]]) -> List[VectorDocument]:
    docs: List[VectorDocument] = []
    for chunk, embedding in zip(chunks, embeddings):
        text = get_chunk_text(chunk)
        if not text:
            continue
        docs.append(
            VectorDocument(
                id=chunk.get("chunk_id", ""),
                chunk_id=chunk.get("chunk_id", ""),
                document_id=chunk.get("document_id", ""),
                company=chunk.get("company", ""),
                pages=chunk.get("pages", []),
                section_path=chunk.get("section_path", []),
                block_type=chunk.get("block_type", ""),
                embedding=embedding,
                metadata={
                    "source": "use_of_proceeds_crosspage_repair_v1",
                    "text_preview": text[:500],
                    "evidence_ids": chunk.get("evidence_ids", []),
                },
            )
        )
    return docs


def rebuild_faiss_after_replacement(store: VectorStore, document_id: str, new_docs: List[VectorDocument]) -> Tuple[int, int]:
    kept_embeddings = []
    kept_docs = []
    for row_id, doc in enumerate(store.documents):
        if doc.document_id == document_id:
            continue
        kept_docs.append(doc)
        kept_embeddings.append(store.index.reconstruct(row_id))
    new_embeddings = [np.asarray(doc.embedding, dtype=np.float32) for doc in new_docs if doc.embedding is not None]
    index = faiss.IndexFlatIP(store.dimension)
    if kept_embeddings or new_embeddings:
        vectors = np.vstack(kept_embeddings + new_embeddings).astype(np.float32)
        index.add(vectors)
    store.index = index
    store.documents = kept_docs + list(new_docs)
    store.doc_id_map = {idx: doc.chunk_id for idx, doc in enumerate(store.documents)}
    store.chunk_ids = {doc.chunk_id for doc in store.documents}
    return len(kept_docs), len(new_docs)


def replace_document_vectors(document_id: str, chunk_dir: Path, vector_dir: Path, backup_root: Path | None = None) -> dict:
    chunks = json.loads((chunk_dir / document_id / "chunks.json").read_text(encoding="utf-8"))
    engine = EmbeddingEngine(EmbeddingConfig())
    texts = [get_chunk_text(chunk) for chunk in chunks]
    # keep alignment even if empty text; build_vector_documents will skip empties
    embeddings = []
    for text in texts:
        embeddings.append(engine.embed_text(text) if text else None)
    paired_chunks = []
    paired_embeddings = []
    for chunk, emb in zip(chunks, embeddings):
        if emb is None:
            continue
        paired_chunks.append(chunk)
        paired_embeddings.append(emb)
    docs = build_vector_documents(paired_chunks, paired_embeddings)
    store = VectorStore(str(vector_dir))
    before = store.get_stats()
    if backup_root is not None:
        backup_file(vector_dir / "documents.json", backup_root / "vectors")
        backup_file(vector_dir / "faiss.index", backup_root / "vectors")
    kept, replaced = rebuild_faiss_after_replacement(store, document_id, docs)
    store.save()
    after = store.get_stats()
    return {
        "document_id": document_id,
        "vector_before": before,
        "vector_after": after,
        "kept_vectors": kept,
        "replaced_vectors": replaced,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild-vectors", action="store_true")
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--evidence-dir", default=str(ROOT / "data/evidence"))
    parser.add_argument("--chunk-dir", default=str(ROOT / "data/chunks"))
    parser.add_argument("--vector-dir", default=str(ROOT / "data/vectors"))
    parser.add_argument("--all-triggered", action="store_true", help="repair all docs with UOP units")
    args = parser.parse_args()

    evidence_dir = Path(args.evidence_dir)
    chunk_dir = Path(args.chunk_dir)
    vector_dir = Path(args.vector_dir)
    docs = find_docs(evidence_dir, args.document_id or None)
    rows = []
    for doc in docs:
        info = document_has_uop_units(evidence_dir / doc / "evidences.json")
        row = {"document_id": doc, **info}
        rows.append(row)
    triggered = [r for r in rows if r["triggered"]]
    if args.document_id:
        selected = docs
    elif args.all_triggered:
        selected = [r["document_id"] for r in triggered]
    else:
        # default safe set: only explicitly requested docs
        selected = []

    report = {
        "dry_run": args.dry_run,
        "rebuild_vectors": args.rebuild_vectors,
        "scanned_docs": len(rows),
        "triggered_docs": len(triggered),
        "selected_docs": selected,
        "triggered_sample": triggered[:20],
        "actions": [],
    }
    if args.dry_run or not selected:
        out = ROOT / "evaluation/benchmark/use_of_proceeds_crosspage_repair_dry_run_v1.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"saved": str(out), "triggered_docs": len(triggered), "selected_docs": selected}, ensure_ascii=False))
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = ROOT / "data" / "_backup_uop_crosspage" / stamp
    for doc in selected:
        action = {"document_id": doc}
        action["chunks"] = rebuild_chunks(doc, evidence_dir, chunk_dir, backup_root)
        if args.rebuild_vectors:
            action["vectors"] = replace_document_vectors(doc, chunk_dir, vector_dir, backup_root)
        report["actions"].append(action)
        print("repaired", doc, action["chunks"])
    out = ROOT / "evaluation/benchmark/use_of_proceeds_crosspage_repair_v1_actions.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", out)


if __name__ == "__main__":
    main()
