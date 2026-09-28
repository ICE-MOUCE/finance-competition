#!/usr/bin/env python3
"""Diagnose Manual Gold V1 Retriever failures without changing Retriever logic."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from opencc import OpenCC

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_rag_benchmark import CATEGORY_LAYERS

BENCHMARK_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1.json"
RESULTS_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1_results.json"
AUDIT_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1_audit.json"
OUTPUT_PATH = ROOT / "evaluation" / "benchmark" / "retriever_failure_diagnostics_v2.json"
REPORT_PATH = ROOT / "docs" / "rag" / "RETRIEVER_FAILURE_DIAGNOSIS_V2.md"
VECTOR_DIR = ROOT / "data" / "vectors"
EVIDENCE_DIR = ROOT / "data" / "evidence"
CHUNK_DIR = ROOT / "data" / "chunks"

NORMALIZER = OpenCC("t2s")
COMPLETE_RECALL_THRESHOLD = 0.95
PARTIAL_RECALL_THRESHOLD = 0.15
CONTENT_MISSING_STATUSES = {
    "evidence_content_missing",
    "chunk_content_missing",
    "vector_content_missing",
}


def norm(text: Any) -> str:
    return "".join(NORMALIZER.convert(str(text)).lower().split())


def normalize_for_match(text: Any) -> str:
    converted = NORMALIZER.convert(str(text)).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", converted)


def pct(hits: int, denominator: int) -> str:
    if denominator == 0:
        return "N/A"
    return f"{hits}/{denominator} ({hits / denominator:.2%})"


def metric_dict(hits: int, denominator: int) -> Dict[str, Any]:
    return {
        "hits": hits,
        "denominator": denominator,
        "rate": round(hits / denominator, 4) if denominator else None,
    }


def metric_text(metric: Dict[str, Any]) -> str:
    return pct(metric.get("hits", 0), metric.get("denominator", 0))


def overlaps(pages: Iterable[int], ranges: List[List[int]]) -> bool:
    clean = []
    for page in pages or []:
        try:
            clean.append(int(page))
        except (TypeError, ValueError):
            pass
    return any(start <= page <= end for page in clean for start, end in ranges)


def get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def get_metadata(item: Any) -> Dict[str, Any]:
    metadata = get_value(item, "metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_chunks(document_id: str) -> List[Dict]:
    path = CHUNK_DIR / document_id / "chunks.json"
    if not path.exists():
        return []
    return load_json(path)


def load_evidences(document_id: str) -> List[Dict]:
    path = EVIDENCE_DIR / document_id / "evidences.json"
    if not path.exists():
        return []
    return load_json(path)


def chunk_text(chunk: Dict) -> str:
    return " ".join(str(chunk.get(key, "")) for key in ("text", "table_description", "image_description", "image_caption"))


def vector_document_text(doc: Any) -> str:
    metadata = get_metadata(doc)
    return " ".join(str(value) for value in [
        metadata.get("text_preview", ""),
        metadata.get("table_description", ""),
        metadata.get("image_description", ""),
        metadata.get("image_caption", ""),
    ] if value)


def measure_text_coverage(expected_text: str, actual_text: str) -> Dict[str, Any]:
    expected = normalize_for_match(expected_text)
    actual = normalize_for_match(actual_text)
    if not expected:
        recall = 1.0
        exact = True
    else:
        exact = expected in actual
        if len(expected) < 4:
            recall = 1.0 if exact else 0.0
        else:
            grams = {expected[index:index + 4] for index in range(len(expected) - 3)}
            recall = sum(1 for gram in grams if gram in actual) / len(grams) if grams else 0.0
    if exact or recall >= COMPLETE_RECALL_THRESHOLD:
        status = "complete"
    elif recall >= PARTIAL_RECALL_THRESHOLD:
        status = "partial"
    else:
        status = "missing"
    return {
        "normalized_exact_containment": exact,
        "four_gram_recall": round(recall, 4),
        "coverage_status": status,
        "expected_normalized_length": len(expected),
        "actual_normalized_length": len(actual),
        "thresholds": {
            "complete_recall": COMPLETE_RECALL_THRESHOLD,
            "partial_recall": PARTIAL_RECALL_THRESHOLD,
        },
    }


def section_matches_expected(items: List[Any], expected_sections: List[str]) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
    expected = [norm(section) for section in expected_sections if section]
    if not expected:
        return True, [], []
    matched = []
    mismatches = []
    for item in items:
        section_path = get_value(item, "section_path", []) or []
        actual = [norm(section) for section in section_path]
        if any(exp in act for exp in expected for act in actual):
            matched.append(get_value(item, "chunk_id", ""))
        else:
            mismatches.append({
                "chunk_id": get_value(item, "chunk_id", ""),
                "section_path": section_path,
                "pages": get_value(item, "pages", []) or [],
                "block_type": get_value(item, "block_type", ""),
            })
    return bool(matched), matched, mismatches[:5]


def evaluate_expected_evidence_chain(
    case: Dict[str, Any],
    evidences: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    vector_documents: List[Any],
) -> Dict[str, Any]:
    expected_text = case.get("expected_evidence_text", "")
    expected_pages = case.get("expected_physical_page_ranges_0_based", [])
    expected_docs = set(case.get("expected_document_ids", []))

    target_evidences = [ev for ev in evidences if overlaps([ev.get("page")], expected_pages)]
    target_chunks = [chunk for chunk in chunks if overlaps(chunk.get("pages", []), expected_pages)]
    target_vectors = []
    for doc in vector_documents:
        doc_id = get_value(doc, "document_id", "")
        if expected_docs and doc_id and doc_id not in expected_docs:
            continue
        if overlaps(get_value(doc, "pages", []) or [], expected_pages):
            target_vectors.append(doc)

    evidence_text = " ".join(str(ev.get("text", "")) for ev in target_evidences)
    chunks_text = " ".join(chunk_text(chunk) for chunk in target_chunks)
    vectors_text = " ".join(vector_document_text(doc) for doc in target_vectors)

    evidence_coverage = measure_text_coverage(expected_text, evidence_text)
    chunk_coverage = measure_text_coverage(expected_text, chunks_text)
    vector_coverage = measure_text_coverage(expected_text, vectors_text)
    section_ok, section_match_ids, section_mismatches = section_matches_expected(target_chunks, case.get("expected_sections", []))

    if evidence_coverage["coverage_status"] == "missing":
        status = "evidence_content_missing"
    elif chunk_coverage["coverage_status"] == "missing":
        status = "chunk_content_missing"
    elif vector_coverage["coverage_status"] == "missing":
        status = "vector_content_missing"
    elif "partial" in {evidence_coverage["coverage_status"], chunk_coverage["coverage_status"], vector_coverage["coverage_status"]}:
        status = "content_partial"
    elif not section_ok:
        status = "section_metadata_mismatch"
    else:
        status = "data_chain_complete"

    block_types = sorted(Counter(chunk.get("block_type", "unknown") for chunk in target_chunks).items())
    return {
        "status": status,
        "evidence_count_on_target_pages": len(target_evidences),
        "chunk_count_on_target_pages": len(target_chunks),
        "vector_count_on_target_pages": len(target_vectors),
        "block_type_counts_on_target_pages": dict(block_types),
        "evidence_coverage": evidence_coverage,
        "chunk_coverage": chunk_coverage,
        "vector_document_coverage": vector_coverage,
        "section_metadata_matches_expected": section_ok,
        "section_match_chunk_ids": section_match_ids[:20],
        "section_mismatch_examples": section_mismatches,
        "target_chunk_ids": [chunk.get("chunk_id") for chunk in target_chunks],
        "target_vector_chunk_ids": [get_value(doc, "chunk_id", "") for doc in target_vectors],
        "notes": "Coverage uses normalized exact containment and character 4-gram recall after traditional/simplified, whitespace, case and punctuation normalization.",
    }


def build_company_catalog(vector_documents: List[Any]) -> List[Dict[str, Any]]:
    by_name: Dict[str, Dict[str, Any]] = {}
    for doc in vector_documents:
        document_id = get_value(doc, "document_id", "") or ""
        company = get_value(doc, "company", "") or ""
        names = {company}
        parts = document_id.split("_", 2)
        if len(parts) == 3:
            names.add(parts[2])
        for name in names:
            normalized = normalize_for_match(name)
            if len(normalized) < 2:
                continue
            entry = by_name.setdefault(normalized, {"normalized_name": normalized, "names": set(), "document_ids": set()})
            entry["names"].add(name)
            if document_id:
                entry["document_ids"].add(document_id)
    return [
        {
            "normalized_name": value["normalized_name"],
            "names": sorted(value["names"]),
            "document_ids": sorted(value["document_ids"]),
        }
        for value in sorted(by_name.values(), key=lambda item: (-len(item["normalized_name"]), item["normalized_name"]))
    ]


def detect_company_route(query: str, catalog: List[Dict[str, Any]]) -> Dict[str, Any]:
    normalized_query = normalize_for_match(query)
    matches = [entry for entry in catalog if entry["normalized_name"] in normalized_query]
    if not matches:
        return {"status": "no_match", "document_id": None, "matched_name": None, "candidate_document_ids": [], "normalized_query": normalized_query}
    longest = max(len(entry["normalized_name"]) for entry in matches)
    longest_matches = [entry for entry in matches if len(entry["normalized_name"]) == longest]
    if len(longest_matches) != 1:
        return {
            "status": "ambiguous",
            "document_id": None,
            "matched_name": None,
            "candidate_document_ids": sorted({doc for entry in longest_matches for doc in entry["document_ids"]}),
            "normalized_query": normalized_query,
        }
    selected = longest_matches[0]
    if len(selected["document_ids"]) != 1:
        return {
            "status": "ambiguous",
            "document_id": None,
            "matched_name": selected["names"][0] if selected["names"] else selected["normalized_name"],
            "candidate_document_ids": selected["document_ids"],
            "normalized_query": normalized_query,
        }
    return {
        "status": "matched",
        "document_id": selected["document_ids"][0],
        "matched_name": selected["names"][0] if selected["names"] else selected["normalized_name"],
        "candidate_document_ids": selected["document_ids"],
        "normalized_query": normalized_query,
    }


def raw_result_text(raw: Dict, chunk_map: Dict[str, Dict]) -> str:
    chunk = chunk_map.get(raw.get("chunk_id", ""), {})
    if chunk:
        return chunk_text(chunk)
    metadata = raw.get("metadata", {}) or {}
    return metadata.get("text_preview", "")


def section_hit_for_rows(rows: List[Dict], case: Dict) -> bool:
    expected = [norm(s) for s in case.get("expected_sections", []) if s]
    if not expected:
        return False
    actual = [norm(s) for row in rows for s in row.get("section_path", [])]
    return any(exp in act for exp in expected for act in actual)


def page_hit_for_rows(rows: List[Dict], case: Dict) -> bool:
    pages = [page for row in rows for page in row.get("pages", [])]
    return overlaps(pages, case.get("expected_physical_page_ranges_0_based", []))


def doc_hit_for_rows(rows: List[Dict], case: Dict) -> bool:
    expected = set(case.get("expected_document_ids", []))
    return any(row.get("document_id") in expected for row in rows)


def label_hit_for_rows(rows: List[Dict], case: Dict) -> Optional[bool]:
    label_ranges = case.get("expected_page_labels") or []
    if not label_ranges:
        return None
    labels = [label for row in rows for label in row.get("page_labels", [])]
    if not labels:
        return None
    return overlaps(labels, label_ranges)


def metrics_for_case_rows(case_rows: List[Tuple[Dict, List[Dict]]]) -> Dict:
    total = len(case_rows)
    doc_hits = sum(doc_hit_for_rows(rows, case) for case, rows in case_rows)
    section_hits = sum(section_hit_for_rows([r for r in rows if r.get("document_id") in set(case.get("expected_document_ids", []))], case) for case, rows in case_rows)
    page_hits = sum(page_hit_for_rows([r for r in rows if r.get("document_id") in set(case.get("expected_document_ids", []))], case) for case, rows in case_rows)
    label_values = [label_hit_for_rows([r for r in rows if r.get("document_id") in set(case.get("expected_document_ids", []))], case) for case, rows in case_rows]
    label_values = [v for v in label_values if v is not None]
    label_hits = sum(v is True for v in label_values)
    return {
        "case_count": total,
        "document_hit": metric_dict(doc_hits, total),
        "section_hit": metric_dict(section_hits, total),
        "normalized_physical_page_hit": metric_dict(page_hits, total),
        "pdf_page_label_hit": metric_dict(label_hits, len(label_values)),
    }


def grouped_metrics(case_rows: List[Tuple[Dict, List[Dict]]], field: str) -> Dict:
    grouped = defaultdict(list)
    for case, rows in case_rows:
        value = case.get(field)
        values = value if isinstance(value, list) else [value or "unknown"]
        for item in values or ["unknown"]:
            grouped[str(item)].append((case, rows))
    return {key: metrics_for_case_rows(items) for key, items in sorted(grouped.items())}


def materialize_raw(raw: Dict, chunk_map: Dict[str, Dict], rank: int) -> Dict:
    return {
        "rank": rank,
        "chunk_id": raw.get("chunk_id", ""),
        "document_id": raw.get("document_id", ""),
        "company": raw.get("company", ""),
        "pages": raw.get("pages", []),
        "page_labels": [],
        "section_path": raw.get("section_path", []),
        "block_type": raw.get("block_type", ""),
        "score": raw.get("score", 0.0),
        "text_preview": raw_result_text(raw, chunk_map)[:240],
        "metadata_keys": sorted((raw.get("metadata") or {}).keys()),
    }


def first_target_rank(rows: List[Dict], case: Dict) -> Optional[int]:
    expected = set(case.get("expected_document_ids", []))
    ranges = case.get("expected_physical_page_ranges_0_based", [])
    for row in rows:
        if row.get("document_id") in expected and overlaps(row.get("pages", []), ranges):
            return row.get("rank")
    return None


def remove_company_terms(question: str, companies: List[str]) -> str:
    changed = question
    variants = set(companies)
    variants.update(NORMALIZER.convert(company) for company in companies)
    for company in sorted(variants, key=len, reverse=True):
        if company:
            changed = changed.replace(company, "")
    return changed.strip(" ，,。？?") or question


def expected_doc_chunks(case: Dict, vector_documents: List[Any]) -> Dict:
    document_id = case["expected_document_ids"][0]
    return evaluate_expected_evidence_chain(case, load_evidences(document_id), load_chunks(document_id), vector_documents)


def inspect_company_routing(case: Dict, raw_rows: List[Dict], detection: Optional[Dict[str, Any]] = None) -> Dict:
    expected_doc = case["expected_document_ids"][0]
    expected_companies = case.get("expected_companies", [])
    normalized_question = norm(case.get("question", ""))
    normalized_doc = norm(expected_doc)
    normalized_companies = [norm(c) for c in expected_companies]
    rows_expected_doc = [row for row in raw_rows if row.get("document_id") == expected_doc]
    row_companies = sorted(set(row.get("company", "") for row in raw_rows[:20]))
    company_in_question = [c for c in normalized_companies if c and c in normalized_question]
    company_in_doc_id = [c for c in normalized_companies if c and c in normalized_doc]
    company_in_chunk_text = []
    for row in rows_expected_doc[:10]:
        haystack = norm(" ".join(str(v) for v in [row.get("company"), row.get("document_id"), row.get("text_preview")]))
        for c in normalized_companies:
            if c and c in haystack:
                company_in_chunk_text.append(c)
    return {
        "normalized_question": normalized_question,
        "expected_companies_normalized": normalized_companies,
        "expected_document_normalized": normalized_doc,
        "company_in_question": sorted(set(company_in_question)),
        "company_in_document_id": sorted(set(company_in_doc_id)),
        "company_in_top20_metadata_companies": row_companies,
        "company_in_expected_doc_top10_text_or_metadata": sorted(set(company_in_chunk_text)),
        "automatic_detection": detection or {},
        "company_used_for_filter_boost_or_rerank": False,
        "company_participation_note": "Production LayeredRetriever does not route by company unless metadata_filters are explicitly supplied; V2 automatic detection is diagnostic-only.",
    }


def make_search_rows(retriever: Any, query: str, layer: str, top_k: int, metadata_filters: Optional[Dict[str, str]] = None) -> List[Dict]:
    results = retriever.search(query, layer=layer, top_k=top_k, metadata_filters=metadata_filters)
    rows = []
    for index, result in enumerate(results, 1):
        rows.append({
            "rank": index,
            "chunk_id": result.chunk_id,
            "document_id": result.document_id,
            "company": result.company,
            "pages": result.pages,
            "page_labels": [],
            "section_path": result.section_path,
            "block_type": result.block_type,
            "score": result.score,
            "text_preview": (result.text or "")[:240],
        })
    return rows


def raw_search_rows(engine: Any, store: Any, query: str, top_k: int, chunk_maps: Dict[str, Dict[str, Dict]], document_filter: Optional[str] = None) -> List[Dict]:
    raw_k = top_k if document_filter is None else store.get_stats().get("total_vectors", top_k)
    raw = store.search(engine.embed_text(query), top_k=raw_k)
    if document_filter:
        raw = [row for row in raw if row.get("document_id") == document_filter][:top_k]
    rows = []
    for index, row in enumerate(raw, 1):
        doc_id = row.get("document_id", "")
        rows.append(materialize_raw(row, chunk_maps.get(doc_id, {}), index))
    return rows


def derive_terms(retriever: Any, query: str, rows: List[Dict]) -> List[str]:
    from src.retriever.models import SearchResult
    results = [SearchResult(
        chunk_id=row.get("chunk_id", ""), evidence_ids=[], document_id=row.get("document_id", ""), company=row.get("company", ""),
        pages=row.get("pages", []), section_path=row.get("section_path", []), block_type=row.get("block_type", ""),
        score=row.get("score", 0.0), text=row.get("text_preview", ""), metadata={},
    ) for row in rows]
    return retriever._query_terms(query, results)


def classify_root_cause(
    case: Dict,
    data_chain: Dict,
    current: Dict,
    raw50_rank: Optional[int],
    oracle_rank: Optional[int],
    auto_route_fixed_document: bool = False,
) -> str:
    if data_chain.get("status") in CONTENT_MISSING_STATUSES:
        return data_chain["status"]
    if data_chain.get("status") == "section_metadata_mismatch" and current.get("expected_section_hit") is False:
        return "section_metadata_mismatch"
    if current.get("correct_document_hit") is False and auto_route_fixed_document:
        return "company_routing_failure"
    if current.get("answer_type") == "table" and raw50_rank is None and oracle_rank is None:
        return "table_representation_failure"
    if raw50_rank is None and oracle_rank is None:
        return "candidate_recall_failure"
    if current.get("correct_document_hit") is False and oracle_rank is not None:
        return "document_routing_upper_bound_only"
    if raw50_rank is not None and raw50_rank > 5:
        return "rerank_failure"
    if current.get("expected_section_hit") is False and current.get("normalized_physical_page_hit") is False:
        return "section_metadata_mismatch" if data_chain.get("status") == "section_metadata_mismatch" else "rerank_failure"
    return "other"


def recommended_fix(root_cause: str) -> str:
    mapping = {
        "company_routing_failure": "公司识别与 metadata routing",
        "document_routing_upper_bound_only": "公司识别实验继续校准",
        "chinese_query_tokenization": "中文 query 规范化/分词",
        "candidate_recall_failure": "BM25/Hybrid Retrieval",
        "rerank_failure": "通用 reranking",
        "section_metadata_mismatch": "section-aware reranking",
        "table_representation_failure": "表格 Chunk 表达",
        "evidence_content_missing": "数据层修复",
        "chunk_content_missing": "数据层修复",
        "vector_content_missing": "数据层修复",
        "content_partial": "数据层修复",
        "corpus_or_index_missing": "数据层修复",
        "other": "section-aware reranking",
    }
    return mapping[root_cause]


def route_metrics(detections: List[Dict[str, Any]], case_rows: List[Tuple[Dict, List[Dict]]]) -> Dict[str, Any]:
    total = len(detections)
    matched = [item for item in detections if item["status"] == "matched"]
    correct = [item for item in matched if item["detected_document_id"] in set(item["expected_document_ids"])]
    no_match = [item for item in detections if item["status"] == "no_match"]
    ambiguous = [item for item in detections if item["status"] == "ambiguous"]
    incorrect = [item for item in matched if item["detected_document_id"] not in set(item["expected_document_ids"])]
    metrics = metrics_for_case_rows(case_rows)
    metrics.update({
        "company_detection_coverage": metric_dict(len(matched), total),
        "detection_precision": metric_dict(len(correct), len(matched)),
        "no_match": metric_dict(len(no_match), total),
        "ambiguous": metric_dict(len(ambiguous), total),
        "incorrect_route": metric_dict(len(incorrect), total),
    })
    return metrics


def run() -> Dict:
    from src.embedding import EmbeddingConfig, EmbeddingEngine
    from src.retriever import LayeredRetriever, RetrieverConfig
    from src.vector import VectorStore

    cases = load_json(BENCHMARK_PATH)
    baseline = load_json(RESULTS_PATH)
    audit = load_json(AUDIT_PATH)
    baseline_by_id = {row["id"]: row for row in baseline["cases"]}
    audit_by_id = {row["case_id"]: row for row in audit["cases"]}

    engine = EmbeddingEngine(EmbeddingConfig())
    store = VectorStore(str(VECTOR_DIR), dimension=engine.dimension)
    retriever_on = LayeredRetriever(store, engine, RetrieverConfig(enable_layer_filter=True))
    retriever_off = LayeredRetriever(store, engine, RetrieverConfig(enable_layer_filter=False))

    company_catalog = build_company_catalog(store.documents)
    chunk_maps: Dict[str, Dict[str, Dict]] = {}
    for doc in store.documents:
        doc_id = get_value(doc, "document_id", "")
        if doc_id not in chunk_maps and (CHUNK_DIR / doc_id / "chunks.json").exists():
            chunk_maps[doc_id] = {chunk.get("chunk_id", ""): chunk for chunk in load_chunks(doc_id)}

    diagnostics = []
    ablation_case_rows: Dict[str, List[Tuple[Dict, List[Dict]]]] = defaultdict(list)
    automatic_route_case_rows: List[Tuple[Dict, List[Dict]]] = []
    automatic_detections: List[Dict[str, Any]] = []
    route_changes = []

    for case in cases:
        current = baseline_by_id[case["id"]]
        layer = CATEGORY_LAYERS[case["category"]]
        expected_doc = case["expected_document_ids"][0]
        question = case["question"]
        no_company_question = remove_company_terms(question, case.get("expected_companies", []))

        detection = detect_company_route(question, company_catalog)
        route_filter = {"document_id": detection["document_id"]} if detection["status"] == "matched" else None

        raw20 = raw_search_rows(engine, store, question, 20, chunk_maps)
        raw50 = raw_search_rows(engine, store, question, 50, chunk_maps)
        oracle5 = make_search_rows(retriever_on, question, layer, 5, metadata_filters={"document_id": expected_doc})
        no_layer5 = make_search_rows(retriever_off, question, layer, 5)
        all_layer5 = make_search_rows(retriever_on, question, "all", 5)
        no_company5 = make_search_rows(retriever_on, no_company_question, layer, 5)
        current5 = make_search_rows(retriever_on, question, layer, 5)
        automatic5 = make_search_rows(retriever_on, question, layer, 5, metadata_filters=route_filter) if route_filter else current5

        for name, rows in {
            "A_current_global_top5": current5,
            "B_global_raw_top20": raw20,
            "C_global_raw_top50": raw50,
            "D_expected_document_oracle_top5_upper_bound": oracle5,
            "E_layer_filter_on_top5": current5,
            "E_layer_filter_off_top5": no_layer5,
            "E_all_layer_top5": all_layer5,
            "F_question_without_company_top5": no_company5,
            "G_automatic_company_route_top5": automatic5,
        }.items():
            ablation_case_rows[name].append((case, rows))
        automatic_route_case_rows.append((case, automatic5))

        auto_doc_hit = doc_hit_for_rows(automatic5, case)
        auto_section_hit = section_hit_for_rows([r for r in automatic5 if r.get("document_id") == expected_doc], case)
        auto_page_hit = page_hit_for_rows([r for r in automatic5 if r.get("document_id") == expected_doc], case)
        detection_row = {
            "case_id": case["id"],
            "status": detection["status"],
            "detected_document_id": detection["document_id"],
            "matched_name": detection["matched_name"],
            "expected_document_ids": case.get("expected_document_ids", []),
            "correct_route": detection["status"] == "matched" and detection["document_id"] in set(case.get("expected_document_ids", [])),
        }
        automatic_detections.append(detection_row)
        route_changes.append({
            "case_id": case["id"],
            "route_status": detection["status"],
            "detected_document_id": detection["document_id"],
            "baseline_document_hit": current.get("correct_document_hit"),
            "automatic_document_hit": auto_doc_hit,
            "baseline_section_hit": current.get("expected_section_hit"),
            "automatic_section_hit": auto_section_hit,
            "baseline_normalized_page_hit": current.get("normalized_physical_page_hit"),
            "automatic_normalized_page_hit": auto_page_hit,
            "document_improved": current.get("correct_document_hit") is False and auto_doc_hit is True,
            "section_improved": current.get("expected_section_hit") is False and auto_section_hit is True,
            "page_improved": current.get("normalized_physical_page_hit") is False and auto_page_hit is True,
        })

        ranks = {
            "current_global_top5_target_rank": first_target_rank(current5, case),
            "global_raw_top20_target_rank": first_target_rank(raw20, case),
            "global_raw_top50_target_rank": first_target_rank(raw50, case),
            "expected_document_oracle_top5_target_rank": first_target_rank(oracle5, case),
            "automatic_company_route_top5_target_rank": first_target_rank(automatic5, case),
            "layer_filter_off_top5_target_rank": first_target_rank(no_layer5, case),
            "all_layer_top5_target_rank": first_target_rank(all_layer5, case),
            "without_company_top5_target_rank": first_target_rank(no_company5, case),
        }
        raw_terms = derive_terms(retriever_on, question, raw50[:10])
        current_terms = derive_terms(retriever_on, question, current5)
        no_company_terms = derive_terms(retriever_on, no_company_question, no_company5)
        data_chain = expected_doc_chunks(case, store.documents)
        company_routing = inspect_company_routing(case, raw50, detection)
        root = classify_root_cause(
            case,
            data_chain,
            current,
            ranks["global_raw_top50_target_rank"],
            ranks["expected_document_oracle_top5_target_rank"],
            auto_route_fixed_document=current.get("correct_document_hit") is False and auto_doc_hit is True,
        )

        diagnostics.append({
            "case_id": case["id"],
            "category": case["category"],
            "answer_type": case["answer_type"],
            "question": question,
            "question_without_company": no_company_question,
            "expected_document": expected_doc,
            "expected_section": case.get("expected_sections", []),
            "expected_physical_page": case.get("expected_physical_page_ranges_0_based", []),
            "baseline": {
                "document_hit": current.get("correct_document_hit"),
                "section_hit": current.get("expected_section_hit"),
                "normalized_physical_page_hit": current.get("normalized_physical_page_hit"),
                "page_label_hit": current.get("page_label_hit"),
                "keyword_coverage": current.get("expected_keyword_coverage"),
                "top5_rows": current5,
            },
            "automatic_company_route": {
                "detection": detection,
                "document_hit": auto_doc_hit,
                "section_hit": auto_section_hit,
                "normalized_physical_page_hit": auto_page_hit,
                "top5_rows": automatic5,
            },
            "data_chain": data_chain,
            "query_terms": {
                "raw_candidate_terms": raw_terms,
                "current_top5_terms": current_terms,
                "without_company_terms": no_company_terms,
                "split_method": "re.split(r'\\s+', query.strip())",
            },
            "company_routing": company_routing,
            "ablation_ranks": ranks,
            "layer_filter_effect": {
                "on_target_rank": ranks["current_global_top5_target_rank"],
                "off_target_rank": ranks["layer_filter_off_top5_target_rank"],
                "all_layer_target_rank": ranks["all_layer_top5_target_rank"],
                "changed_document_hit": doc_hit_for_rows(current5, case) != doc_hit_for_rows(no_layer5, case),
                "changed_page_hit": page_hit_for_rows([r for r in current5 if r.get("document_id") == expected_doc], case) != page_hit_for_rows([r for r in no_layer5 if r.get("document_id") == expected_doc], case),
            },
            "root_cause": root,
            "recommended_fix": recommended_fix(root),
            "raw_top20_rows": raw20[:10],
            "raw_top50_expected_document_rows": [row for row in raw50 if row.get("document_id") == expected_doc][:10],
            "oracle_top5_rows": oracle5,
            "audit_failure_reason": audit_by_id.get(case["id"], {}).get("failure_reason"),
        })

    ablations = {}
    for name, pairs in ablation_case_rows.items():
        summary = metrics_for_case_rows(pairs)
        summary["by_answer_type"] = grouped_metrics(pairs, "answer_type")
        ranks = [first_target_rank(rows, case) for case, rows in pairs]
        summary["target_chunk_rank"] = {
            "available_count": sum(rank is not None for rank in ranks),
            "denominator": len(pairs),
            "first_ranks": [rank for rank in ranks if rank is not None],
        }
        ablations[name] = summary

    failed = [d for d in diagnostics if not (d["baseline"]["document_hit"] and d["baseline"]["section_hit"] and d["baseline"]["normalized_physical_page_hit"])]
    root_counts = Counter(item["root_cause"] for item in failed)
    recommendation_counts = Counter(item["recommended_fix"] for item in failed)
    automatic_metrics = route_metrics(automatic_detections, automatic_route_case_rows)
    improvements = {
        "document": metric_dict(sum(row["document_improved"] for row in route_changes), len(route_changes)),
        "section": metric_dict(sum(row["section_improved"] for row in route_changes), len(route_changes)),
        "normalized_page": metric_dict(sum(row["page_improved"] for row in route_changes), len(route_changes)),
    }
    recommended_first = "公司识别与 metadata routing" if improvements["document"]["hits"] else "数据层修复 / routing 证据不足"

    return {
        "timestamp": datetime.now().isoformat(),
        "benchmark_file": str(BENCHMARK_PATH.relative_to(ROOT)),
        "baseline_results_file": str(RESULTS_PATH.relative_to(ROOT)),
        "diagnostic_scope": "Manual Gold V1 Retriever failure diagnosis V2; no Gold or Retriever production logic changes.",
        "content_coverage_thresholds": {
            "complete_recall": COMPLETE_RECALL_THRESHOLD,
            "partial_recall": PARTIAL_RECALL_THRESHOLD,
        },
        "summary": {
            "case_count": len(cases),
            "failed_case_count": len(failed),
            "root_cause_counts": dict(root_counts),
            "recommended_fix_counts": dict(recommendation_counts),
            "recommended_first_optimization": recommended_first,
            "automatic_route_improvements": improvements,
            "vector_count": store.get_stats().get("total_vectors"),
        },
        "automatic_company_routing": {
            "catalog_size": len(company_catalog),
            "metrics": automatic_metrics,
            "detections": automatic_detections,
            "case_changes": route_changes,
            "note": "Gold expected document/company fields are used only after retrieval for scoring; the catalog is built from VectorStore metadata/document_id.",
        },
        "ablation_matrix": ablations,
        "cases": diagnostics,
    }


def write_report(report: Dict, path: Path) -> None:
    automatic = report["automatic_company_routing"]
    auto_metrics = automatic["metrics"]
    data_chain_counts = Counter(case["data_chain"]["status"] for case in report["cases"])
    root_counts = report["summary"]["root_cause_counts"]
    failed_cases = [
        case for case in report["cases"]
        if not (case["baseline"]["document_hit"] and case["baseline"]["section_hit"] and case["baseline"]["normalized_physical_page_hit"])
    ]
    lines = [
        "# Retriever Failure Diagnosis V2",
        "",
        f"> Generated at: {report['timestamp']}",
        "",
        "## 结论",
        "",
        f"- 本轮唯一推荐项：**{report['summary']['recommended_first_optimization']}**。",
        "- 本轮只修改诊断工具、专项测试和 V2 报告；未修改 Retriever 生产逻辑、Gold、Parser、Evidence、Chunk 或 VectorStore。",
        "- expected-document oracle 仅保留为文档内检索 upper bound，不作为自动路由成绩。",
        "",
        "## Baseline 与自动路由",
        "",
        "| 指标 | 当前 baseline | 自动公司路由 | expected-document oracle upper bound |",
        "|---|---:|---:|---:|",
    ]
    baseline = report["ablation_matrix"]["A_current_global_top5"]
    auto = report["ablation_matrix"]["G_automatic_company_route_top5"]
    oracle = report["ablation_matrix"]["D_expected_document_oracle_top5_upper_bound"]
    for label, key in [("document hit", "document_hit"), ("section hit", "section_hit"), ("normalized physical page hit", "normalized_physical_page_hit")]:
        lines.append(f"| {label} | {metric_text(baseline[key])} | {metric_text(auto[key])} | {metric_text(oracle[key])} |")
    lines.extend([
        "",
        "## 自动公司识别指标",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| company detection coverage | {metric_text(auto_metrics['company_detection_coverage'])} |",
        f"| detection precision | {metric_text(auto_metrics['detection_precision'])} |",
        f"| no-match | {metric_text(auto_metrics['no_match'])} |",
        f"| ambiguous | {metric_text(auto_metrics['ambiguous'])} |",
        f"| incorrect-route | {metric_text(auto_metrics['incorrect_route'])} |",
        f"| document improved vs baseline | {metric_text(report['summary']['automatic_route_improvements']['document'])} |",
        f"| section improved vs baseline | {metric_text(report['summary']['automatic_route_improvements']['section'])} |",
        f"| normalized page improved vs baseline | {metric_text(report['summary']['automatic_route_improvements']['normalized_page'])} |",
        "",
        "## 证据内容链覆盖",
        "",
        f"阈值：complete = normalized exact containment 或 4-gram recall >= {COMPLETE_RECALL_THRESHOLD:.2f}；partial = 4-gram recall >= {PARTIAL_RECALL_THRESHOLD:.2f}；否则 missing。",
        "",
        "| data_chain_status | count |",
        "|---|---:|",
    ])
    for status, count in sorted(data_chain_counts.items()):
        lines.append(f"| {status} | {count} |")
    lines.extend([
        "",
        "| case_id | status | evidence recall | chunk recall | vector recall | evidence exact | chunk exact | vector exact |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for case in report["cases"]:
        chain = case["data_chain"]
        ev = chain["evidence_coverage"]
        ch = chain["chunk_coverage"]
        vd = chain["vector_document_coverage"]
        lines.append(
            f"| `{case['case_id']}` | {chain['status']} | {ev['four_gram_recall']:.2%} | {ch['four_gram_recall']:.2%} | {vd['four_gram_recall']:.2%} | {ev['normalized_exact_containment']} | {ch['normalized_exact_containment']} | {vd['normalized_exact_containment']} |"
        )
    lines.extend([
        "",
        "## 修正后根因统计",
        "",
        "| root_cause | count |",
        "|---|---:|",
    ])
    for reason, count in sorted(root_counts.items()):
        lines.append(f"| {reason} | {count} |")
    lines.extend([
        "",
        "## 逐条失败归因",
        "",
        "| case_id | baseline doc | auto doc | baseline page | auto page | data_chain | global raw rank | oracle upper-bound rank | root_cause | recommended_fix |",
        "|---|---:|---:|---:|---:|---|---:|---:|---|---|",
    ])
    for case in failed_cases:
        b = case["baseline"]
        a = case["automatic_company_route"]
        ranks = case["ablation_ranks"]
        lines.append(
            f"| `{case['case_id']}` | {b['document_hit']} | {a['document_hit']} | {b['normalized_physical_page_hit']} | {a['normalized_physical_page_hit']} | {case['data_chain']['status']} | {ranks['global_raw_top50_target_rank']} | {ranks['expected_document_oracle_top5_target_rank']} | {case['root_cause']} | {case['recommended_fix']} |"
        )
    lines.extend([
        "",
        "## 决策",
        "",
        "- 自动公司路由实验只证明可由 VectorStore metadata/document_id 派生的公司识别信号，不再用 Gold expected document 证明自动路由有效。",
        "- 自动路由修复的 document、section、page 案例数已分别报告；不再声称 4 条 document miss 都能改善 page grounding。",
        "- 当前可以进入最小 metadata routing 设计评审，但仍不建议启动 Agent/API 或 568 PDF 服务器全量跑数。",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose Retriever failures for Manual Gold V1.")
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    output_path = args.output_path if args.output_path.is_absolute() else ROOT / args.output_path
    report_path = args.report_path if args.report_path.is_absolute() else ROOT / args.report_path
    report = run()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(report, report_path)
    print(f"diagnostics written: {output_path}")
    print(f"report written: {report_path}")
    print(f"recommended_first_optimization: {report['summary']['recommended_first_optimization']}")


if __name__ == "__main__":
    main()
