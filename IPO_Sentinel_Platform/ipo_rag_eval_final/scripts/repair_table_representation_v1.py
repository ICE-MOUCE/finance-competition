from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Tuple

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.chunk import ChunkBuilder, ChunkConfig, ChunkStore
from src.embedding import EmbeddingConfig, EmbeddingEngine, VectorDocument
from src.evidence import EvidenceBuilder
from src.vector import VectorStore

DEFAULT_DOCUMENT_ID = "2024_02586_多點數智"
DEFAULT_PROCESSED_DIR = ROOT / "data" / "processed"
DEFAULT_EVIDENCE_DIR = ROOT / "data" / "evidence"
DEFAULT_CHUNK_DIR = ROOT / "data" / "chunks"
DEFAULT_VECTOR_DIR = ROOT / "data" / "vectors"
DEFAULT_GOLD_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1.json"
DEFAULT_TARGET_FACTS = [
    "70.6%", "78.2%",
    "16,016", "5,818", "18,400", "20,266", "2,188", "1,770", "21,777",
    "901,131", "1,100,093", "2,845,773", "397,235", "1,042,203", "42,559",
    "605,801", "870,809", "1,707,871", "1,142,959", "1,490,454",
    "淨虧損", "淨負債", "經營活動所用現金",
]


def load_manual_gold_document_ids(gold_path: Path | None = None) -> list[str]:
    path = gold_path or DEFAULT_GOLD_PATH
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    docs = []
    for case in data:
        for doc_id in case.get("expected_document_ids") or []:
            if doc_id and doc_id not in docs:
                docs.append(doc_id)
    return docs


def facts_for_document(document_id: str, case_terms: dict[str, list[str]] | None = None) -> list[str]:
    terms = list(DEFAULT_TARGET_FACTS)
    if case_terms and document_id in case_terms:
        for term in case_terms[document_id]:
            if term not in terms:
                terms.append(term)
    return terms



def get_chunk_text(chunk: dict) -> str:
    block_type = chunk.get("block_type", "")
    if block_type == "text":
        return chunk.get("text", "")
    if block_type == "table":
        return chunk.get("table_description", "")
    if block_type == "image":
        return chunk.get("image_description", "") or chunk.get("image_caption", "")
    return ""


def find_mineru_output_dir(processed_dir: Path, document_id: str) -> Path:
    doc_dir = processed_dir / document_id
    if not doc_dir.exists():
        raise FileNotFoundError(f"Processed document directory not found: {doc_dir}")
    candidates = [p for p in doc_dir.rglob("*") if p.is_dir() and list(p.glob("*_content_list.json")) and list(p.glob("*.md"))]
    if not candidates:
        raise FileNotFoundError(f"MinerU output directory not found under: {doc_dir}")
    return sorted(candidates, key=lambda p: len(str(p)))[0]


def load_existing_document_info(evidence_dir: Path, document_id: str) -> dict:
    path = evidence_dir / document_id / "document.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def flatten_chunks(chunks_by_type: dict) -> List[dict]:
    chunks = []
    for chunk_list in chunks_by_type.values():
        chunks.extend(chunk.to_dict() if hasattr(chunk, "to_dict") else chunk for chunk in chunk_list)
    return chunks


def build_vector_documents(chunks: List[dict], embeddings: List[List[float]]) -> List[VectorDocument]:
    docs = []
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
                    "source": "table_representation_repair_v1",
                    "text_preview": text[:500],
                    "text_for_embedding": text if chunk.get("block_type") == "table" else "",
                    "evidence_ids": chunk.get("evidence_ids", []),
                },
            )
        )
    return docs


def replace_document_vectors(store, document_id: str, new_docs: List[VectorDocument]) -> Tuple[int, int]:
    kept_docs = [doc for doc in store.documents if doc.document_id != document_id]
    store.documents = kept_docs + list(new_docs)
    store.doc_id_map = {idx: doc.chunk_id for idx, doc in enumerate(store.documents)}
    store.chunk_ids = {doc.chunk_id for doc in store.documents}
    return len(kept_docs), len(new_docs)


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
    return replace_document_vectors(store, document_id, new_docs)


def repair_document(document_id: str, processed_dir: Path, evidence_dir: Path, chunk_dir: Path, vector_dir: Path, check_terms: list[str] | None = None) -> dict:
    check_terms = check_terms or facts_for_document(document_id)
    mineru_output_dir = find_mineru_output_dir(processed_dir, document_id)
    existing_info = load_existing_document_info(evidence_dir, document_id)

    evidence_builder = EvidenceBuilder(str(evidence_dir))
    document = evidence_builder.build(
        mineru_output_dir=str(mineru_output_dir),
        document_id=document_id,
        company=existing_info.get("company", ""),
        stock_code=existing_info.get("stock_code", ""),
        listing_date=existing_info.get("listing_date", ""),
        industry=existing_info.get("industry", ""),
        source_file=existing_info.get("source_file", ""),
    )
    evidences = [evidence.to_dict() for evidence in document.evidences]

    chunk_builder = ChunkBuilder(ChunkConfig())
    chunks_by_type = chunk_builder.build(evidences)
    ChunkStore(str(chunk_dir)).save(document_id, chunks_by_type)
    chunks = flatten_chunks(chunks_by_type)
    texts = [get_chunk_text(chunk) for chunk in chunks if get_chunk_text(chunk)]

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    engine = EmbeddingEngine(EmbeddingConfig())
    embeddings = engine.embed_batch(texts)
    embed_chunks = [chunk for chunk in chunks if get_chunk_text(chunk)]
    new_docs = build_vector_documents(embed_chunks, embeddings)

    store = VectorStore(str(vector_dir), dimension=engine.dimension)
    old_total = len(store.documents)
    kept, added = rebuild_faiss_after_replacement(store, document_id, new_docs)
    store.save()

    return {
        "document_id": document_id,
        "mineru_output_dir": str(mineru_output_dir),
        "evidence_count": len(evidences),
        "chunk_count": len(chunks),
        "vector_old_total": old_total,
        "vector_kept": kept,
        "vector_added": added,
        "vector_new_total": len(store.documents),
        "facts_in_evidence": contains_facts(evidence_dir / document_id / "evidences.json", terms=check_terms),
        "facts_in_chunks": contains_facts(chunk_dir / document_id / "chunks.json", terms=check_terms),
        "facts_in_vectors": contains_facts(vector_dir / "documents.json", document_id=document_id, terms=check_terms),
        "check_terms": check_terms,
    }


def contains_facts(path: Path, document_id: str = "", terms: list[str] | None = None) -> dict:
    terms = terms or DEFAULT_TARGET_FACTS
    text = path.read_text(encoding="utf-8-sig")
    if document_id:
        data = json.loads(text)
        text = json.dumps([item for item in data if item.get("document_id") == document_id], ensure_ascii=False)
    return {term: term in text for term in terms}


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair table evidence/chunk representation for one or more documents.")
    parser.add_argument("--document-id", action="append", default=None, help="Document id; may be repeated")
    parser.add_argument("--manual-gold", action="store_true", help="Repair all Manual Gold V1 document ids")
    parser.add_argument("--gold-path", default=str(DEFAULT_GOLD_PATH))
    parser.add_argument("--processed-dir", default=str(DEFAULT_PROCESSED_DIR))
    parser.add_argument("--evidence-dir", default=str(DEFAULT_EVIDENCE_DIR))
    parser.add_argument("--chunk-dir", default=str(DEFAULT_CHUNK_DIR))
    parser.add_argument("--vector-dir", default=str(DEFAULT_VECTOR_DIR))
    parser.add_argument("--output-json", default=str(ROOT / "evaluation" / "benchmark" / "table_representation_generalization_v1.json"))
    args = parser.parse_args()

    if args.manual_gold:
        document_ids = load_manual_gold_document_ids(Path(args.gold_path))
    elif args.document_id:
        document_ids = args.document_id
    else:
        document_ids = [DEFAULT_DOCUMENT_ID]

    results = []
    for document_id in document_ids:
        result = repair_document(
            document_id=document_id,
            processed_dir=Path(args.processed_dir),
            evidence_dir=Path(args.evidence_dir),
            chunk_dir=Path(args.chunk_dir),
            vector_dir=Path(args.vector_dir),
        )
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)

    output = {
        "document_ids": document_ids,
        "results": results,
    }
    out_path = Path(args.output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(out_path), "document_count": len(document_ids)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

