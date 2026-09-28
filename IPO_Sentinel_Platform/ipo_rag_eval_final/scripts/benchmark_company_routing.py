
#!/usr/bin/env python3
"""Benchmark scalable company routing strategies without changing Retriever logic."""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple

import numpy as np
from opencc import OpenCC

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_rag_benchmark import CATEGORY_LAYERS

BENCHMARK_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1.json"
NEGATIVE_CASES_PATH = ROOT / "evaluation" / "benchmark" / "company_routing_negative_cases.json"
OUTPUT_PATH = ROOT / "evaluation" / "benchmark" / "company_routing_performance.json"
REPORT_PATH = ROOT / "docs" / "rag" / "SCALABLE_COMPANY_ROUTING_DESIGN.md"
VECTOR_DIR = ROOT / "data" / "vectors"
NORMALIZER = OpenCC("t2s")


def get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        if key in item:
            return item.get(key, default)
        metadata = item.get("metadata") or {}
        if isinstance(metadata, dict) and key in metadata:
            return metadata.get(key, default)
        return default
    value = getattr(item, key, default)
    if value is not default:
        return value
    metadata = getattr(item, "metadata", {}) or {}
    if isinstance(metadata, dict):
        return metadata.get(key, default)
    return default


def normalize_for_match(text: Any) -> str:
    converted = NORMALIZER.convert(str(text)).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", converted)


def norm_section(text: Any) -> str:
    return "".join(NORMALIZER.convert(str(text)).lower().split())


def metric_dict(hits: int, denominator: int) -> Dict[str, Any]:
    return {"hits": hits, "denominator": denominator, "rate": round(hits / denominator, 4) if denominator else None}


def metric_text(metric: Dict[str, Any]) -> str:
    denominator = metric.get("denominator", 0)
    hits = metric.get("hits", 0)
    return "N/A" if not denominator else f"{hits}/{denominator} ({hits / denominator:.2%})"


def percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize_timings_ms(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"runs": 0, "p50_ms": None, "p95_ms": None, "max_ms": None, "mean_ms": None}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "runs": len(values),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "max_ms": round(max(values), 3),
        "mean_ms": round(statistics.fmean(values), 3),
    }


def build_company_catalog(vector_documents: List[Any]) -> List[Dict[str, Any]]:
    by_name: Dict[str, Dict[str, Any]] = {}
    for doc in vector_documents:
        document_id = str(get_value(doc, "document_id", "") or "")
        company = str(get_value(doc, "company", "") or "")
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
        {"normalized_name": item["normalized_name"], "names": sorted(item["names"]), "document_ids": sorted(item["document_ids"])}
        for item in sorted(by_name.values(), key=lambda value: (-len(value["normalized_name"]), value["normalized_name"]))
    ]


def detect_company_route(query: str, catalog: List[Dict[str, Any]]) -> Dict[str, Any]:
    normalized_query = normalize_for_match(query)
    matches = [entry for entry in catalog if entry["normalized_name"] in normalized_query]
    if not matches:
        return {"status": "no_match", "document_id": None, "matched_name": None, "candidate_document_ids": [], "normalized_query": normalized_query}
    longest = max(len(entry["normalized_name"]) for entry in matches)
    longest_matches = [entry for entry in matches if len(entry["normalized_name"]) == longest]
    if len(longest_matches) != 1:
        return {"status": "ambiguous", "document_id": None, "matched_name": None, "candidate_document_ids": sorted({doc for entry in longest_matches for doc in entry["document_ids"]}), "normalized_query": normalized_query}
    selected = longest_matches[0]
    if len(selected["document_ids"]) != 1:
        return {"status": "ambiguous", "document_id": None, "matched_name": selected["names"][0] if selected["names"] else selected["normalized_name"], "candidate_document_ids": selected["document_ids"], "normalized_query": normalized_query}
    return {"status": "matched", "document_id": selected["document_ids"][0], "matched_name": selected["names"][0] if selected["names"] else selected["normalized_name"], "candidate_document_ids": selected["document_ids"], "normalized_query": normalized_query}


def build_document_row_id_map(vector_documents: List[Any]) -> Dict[str, List[int]]:
    mapping: Dict[str, List[int]] = defaultdict(list)
    for row_id, doc in enumerate(vector_documents):
        document_id = str(get_value(doc, "document_id", "") or "")
        if document_id:
            mapping[document_id].append(row_id)
    return dict(mapping)


def estimate_subset_memory_bytes(row_count: int, dimension: int) -> int:
    return int(row_count) * int(dimension) * 4


def overlaps(pages: Iterable[int], ranges: List[List[int]]) -> bool:
    clean_pages = []
    for page in pages or []:
        try:
            clean_pages.append(int(page))
        except (TypeError, ValueError):
            continue
    return any(start <= page <= end for page in clean_pages for start, end in ranges)


def materialize_doc(doc: Any, score: float, rank: int) -> Dict[str, Any]:
    return {"rank": rank, "chunk_id": get_value(doc, "chunk_id", ""), "document_id": get_value(doc, "document_id", ""), "company": get_value(doc, "company", ""), "pages": get_value(doc, "pages", []) or [], "section_path": get_value(doc, "section_path", []) or [], "block_type": get_value(doc, "block_type", ""), "score": float(score)}


def materialize_raw(row: Dict[str, Any], rank: int) -> Dict[str, Any]:
    return {"rank": rank, "chunk_id": row.get("chunk_id", ""), "document_id": row.get("document_id", ""), "company": row.get("company", ""), "pages": row.get("pages", []) or [], "section_path": row.get("section_path", []) or [], "block_type": row.get("block_type", ""), "score": float(row.get("score", 0.0))}


def materialize_result(result: Any, rank: int) -> Dict[str, Any]:
    return {"rank": rank, "chunk_id": result.chunk_id, "document_id": result.document_id, "company": result.company, "pages": result.pages, "section_path": result.section_path, "block_type": result.block_type, "score": float(result.score)}


def doc_hit_for_rows(rows: List[Dict[str, Any]], case: Dict[str, Any]) -> bool:
    expected = set(case.get("expected_document_ids", []))
    return any(row.get("document_id") in expected for row in rows)


def section_hit_for_rows(rows: List[Dict[str, Any]], case: Dict[str, Any]) -> bool:
    expected_sections = [norm_section(section) for section in case.get("expected_sections", []) if section]
    if not expected_sections:
        return False
    expected_docs = set(case.get("expected_document_ids", []))
    actual_sections = [norm_section(section) for row in rows if row.get("document_id") in expected_docs for section in row.get("section_path", [])]
    return any(expected in actual for expected in expected_sections for actual in actual_sections)


def page_hit_for_rows(rows: List[Dict[str, Any]], case: Dict[str, Any]) -> bool:
    expected_docs = set(case.get("expected_document_ids", []))
    pages = [page for row in rows if row.get("document_id") in expected_docs for page in row.get("pages", [])]
    return overlaps(pages, case.get("expected_physical_page_ranges_0_based", []))


def metrics_for_case_rows(case_rows: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]) -> Dict[str, Any]:
    total = len(case_rows)
    return {"case_count": total, "document_hit": metric_dict(sum(doc_hit_for_rows(rows, case) for case, rows in case_rows), total), "section_hit": metric_dict(sum(section_hit_for_rows(rows, case) for case, rows in case_rows), total), "normalized_physical_page_hit": metric_dict(sum(page_hit_for_rows(rows, case) for case, rows in case_rows), total)}


def grouped_metrics(case_rows: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]], field: str) -> Dict[str, Any]:
    grouped: Dict[str, List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]] = defaultdict(list)
    for case, rows in case_rows:
        grouped[str(case.get(field) or "unknown")].append((case, rows))
    return {key: metrics_for_case_rows(value) for key, value in sorted(grouped.items())}


def evaluate_negative_cases(cases: List[Dict[str, Any]], catalog: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for case in cases:
        case_catalog = list(catalog)
        if case.get("synthetic_catalog_entries"):
            case_catalog = build_company_catalog(case.get("synthetic_catalog_entries", [])) + case_catalog
        detection = detect_company_route(case["question"], case_catalog)
        expected_status = case.get("expected_status")
        expected_doc = case.get("expected_document_id")
        correct_status = detection["status"] == expected_status
        correct_doc = expected_doc is None or detection.get("document_id") == expected_doc
        rows.append({"id": case["id"], "type": case.get("type", ""), "question": case["question"], "expected_status": expected_status, "expected_document_id": expected_doc, "actual_status": detection["status"], "actual_document_id": detection.get("document_id"), "matched_name": detection.get("matched_name"), "candidate_document_ids": detection.get("candidate_document_ids", []), "pass": bool(correct_status and correct_doc)})
    total = len(rows)
    matched = [row for row in rows if row["actual_status"] == "matched"]
    positive = [row for row in rows if row.get("expected_status") == "matched"]
    no_match = [row for row in rows if row["actual_status"] == "no_match"]
    ambiguous = [row for row in rows if row["actual_status"] == "ambiguous"]
    false_positive_denominator = len([row for row in rows if row.get("expected_status") in {"no_match", "ambiguous"}])
    false_positive_hits = len([row for row in rows if row.get("expected_status") in {"no_match", "ambiguous"} and row["actual_status"] == "matched"])
    correct_positive = [row for row in positive if row["actual_status"] == "matched" and row["actual_document_id"] == row.get("expected_document_id")]
    metrics = {"case_count": total, "pass": metric_dict(sum(row["pass"] for row in rows), total), "coverage": metric_dict(len(matched), total), "detection_precision": metric_dict(len(correct_positive), len(matched)), "false_positive": metric_dict(false_positive_hits, false_positive_denominator), "no_match": metric_dict(len(no_match), total), "ambiguous": metric_dict(len(ambiguous), total)}
    return {"metrics": metrics, "cases": rows}


def make_negative_cases(catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    no_company_questions = [
        "是否存在持续亏损或现金流压力",
        "客户集中度是否构成重大经营风险",
        "供应商依赖是否会影响业务稳定性",
        "是否存在重大诉讼或仲裁事项",
        "是否存在牌照或许可证合规风险",
        "募集资金用途是否清晰",
        "上市前投资是否存在特殊权利",
        "毛利率下降是否提示盈利质量风险",
        "控股股东是否可能影响公司治理",
        "是否存在破发或估值波动风险",
    ]
    cases = [{"id": f"no_company_{index:03d}", "type": "no_company", "question": question, "expected_status": "no_match"} for index, question in enumerate(no_company_questions, 1)]
    actual_entries = [entry for entry in catalog if len(entry.get("document_ids", [])) == 1 and entry.get("names")]
    for index, entry in enumerate(actual_entries[:4], 1):
        name = entry["names"][0]
        cases.append({"id": f"actual_catalog_positive_{index:03d}", "type": "actual_catalog_positive", "question": f"{name}是否存在财务或经营风险", "expected_status": "matched", "expected_document_id": entry["document_ids"][0]})
    if actual_entries:
        short = actual_entries[0]
        long_name = str(short["names"][0]) + "控股有限公司"
        cases.append({"id": "longest_unique_name_001", "type": "longest_unique_name", "question": f"{long_name}是否存在合规风险", "expected_status": "matched", "expected_document_id": "synthetic_long_doc", "synthetic_catalog_entries": [{"document_id": short["document_ids"][0], "company": short["names"][0]}, {"document_id": "synthetic_long_doc", "company": long_name}]})
    cases.append({"id": "ambiguous_same_name_001", "type": "ambiguous_same_name", "question": "同名控股是否存在诉讼风险", "expected_status": "ambiguous", "synthetic_catalog_entries": [{"document_id": "2099_00001_同名控股", "company": "同名控股"}, {"document_id": "2099_00002_同名控股", "company": "同名控股"}]})
    cases.append({"id": "no_fuzzy_guess_001", "type": "no_fuzzy_guess", "question": "多点这家公司是否存在监管处罚", "expected_status": "no_match"})
    return cases


def run_timed_strategy(name: str, cases: List[Dict[str, Any]], repeats: int, warmups: int, run_one: Callable[[Dict[str, Any]], Tuple[List[Dict[str, Any]], Dict[str, Any]]]) -> Dict[str, Any]:
    timings = []
    case_rows = []
    per_case = []
    for case in cases:
        for _ in range(warmups):
            run_one(case)
        last_rows: List[Dict[str, Any]] = []
        last_meta: Dict[str, Any] = {}
        case_timings = []
        for _ in range(repeats):
            start = time.perf_counter()
            last_rows, last_meta = run_one(case)
            elapsed = (time.perf_counter() - start) * 1000
            timings.append(elapsed)
            case_timings.append(elapsed)
        case_rows.append((case, last_rows))
        per_case.append({"case_id": case["id"], "document_id": case.get("expected_document_ids", [None])[0], "timing_ms": summarize_timings_ms(case_timings), "candidate_count": last_meta.get("candidate_count"), "returned_count": len(last_rows), "document_hit": doc_hit_for_rows(last_rows, case), "section_hit": section_hit_for_rows(last_rows, case), "normalized_physical_page_hit": page_hit_for_rows(last_rows, case), "top_chunk_ids": [row.get("chunk_id") for row in last_rows[:5]], "metadata": last_meta})
    summary = metrics_for_case_rows(case_rows)
    summary["timing_ms"] = summarize_timings_ms(timings)
    summary["by_answer_type"] = grouped_metrics(case_rows, "answer_type")
    summary["candidate_count"] = {"min": min((row["candidate_count"] or 0) for row in per_case) if per_case else 0, "max": max((row["candidate_count"] or 0) for row in per_case) if per_case else 0, "mean": round(statistics.fmean((row["candidate_count"] or 0) for row in per_case), 2) if per_case else 0}
    return {"name": name, "summary": summary, "per_case": per_case}


def row_subset_exact_search(store: Any, query_embedding: List[float], row_ids: List[int], top_k: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not hasattr(store.index, "reconstruct_batch"):
        return [], {"available": False, "reason": "faiss_index_has_no_reconstruct_batch", "candidate_count": len(row_ids)}
    if not row_ids:
        return [], {"available": True, "reason": "empty_row_id_subset", "candidate_count": 0}
    ids = np.asarray(row_ids, dtype="int64")
    vectors = store.index.reconstruct_batch(ids)
    query = np.asarray(query_embedding, dtype=np.float32)
    scores = vectors @ query
    take = min(top_k, len(row_ids))
    top_positions = np.argsort(-scores)[:take]
    rows = []
    for rank, position in enumerate(top_positions, 1):
        row_id = int(row_ids[int(position)])
        rows.append(materialize_doc(store.documents[row_id], float(scores[int(position)]), rank))
    return rows, {"available": True, "candidate_count": len(row_ids), "approx_extra_memory_bytes": estimate_subset_memory_bytes(len(row_ids), store.dimension)}


def compare_chunk_ids(left: List[str], right: List[str]) -> Dict[str, Any]:
    return {"same_order": left == right, "overlap_count": len(set(left) & set(right)), "left": left, "right": right}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_benchmark(repeats: int, warmups: int) -> Dict[str, Any]:
    from loguru import logger
    from src.embedding import EmbeddingConfig, EmbeddingEngine
    from src.retriever import LayeredRetriever, RetrieverConfig
    from src.vector import VectorStore

    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    cases = load_json(BENCHMARK_PATH)
    engine = EmbeddingEngine(EmbeddingConfig())
    store = VectorStore(str(VECTOR_DIR), dimension=engine.dimension)
    retriever = LayeredRetriever(store, engine, RetrieverConfig(enable_layer_filter=True))
    total_vectors = store.get_stats().get("total_vectors", 0)
    catalog = build_company_catalog(store.documents)
    row_id_map = build_document_row_id_map(store.documents)
    negative_cases = make_negative_cases(catalog)
    negative_result = evaluate_negative_cases(negative_cases, catalog)

    def route_doc(case: Dict[str, Any]) -> Dict[str, Any]:
        return detect_company_route(case["question"], catalog)

    def run_global(case: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        layer = CATEGORY_LAYERS[case["category"]]
        results = retriever.search(case["question"], layer=layer, top_k=5)
        fetch_k = 10 if layer == "all" else 25
        return [materialize_result(result, index) for index, result in enumerate(results, 1)], {"candidate_count": min(fetch_k, total_vectors), "calls_top_k_total_vectors": False, "approx_extra_memory_bytes": 0}

    def run_exhaustive_filter(case: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        layer = CATEGORY_LAYERS[case["category"]]
        detection = route_doc(case)
        filters = {"document_id": detection["document_id"]} if detection["status"] == "matched" else None
        results = retriever.search(case["question"], layer=layer, top_k=5, metadata_filters=filters)
        return [materialize_result(result, index) for index, result in enumerate(results, 1)], {"route_status": detection["status"], "route_document_id": detection.get("document_id"), "candidate_count": total_vectors if filters else min(25, total_vectors), "calls_top_k_total_vectors": bool(filters), "approx_extra_memory_bytes": 0}

    def make_oversampling(candidate_k: int) -> Callable[[Dict[str, Any]], Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
        def run(case: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
            detection = route_doc(case)
            query_embedding = engine.embed_text(case["question"])
            raw = store.search(query_embedding, top_k=candidate_k)
            rows = [materialize_raw(row, index) for index, row in enumerate(raw, 1)]
            rows = [row for row in rows if row.get("document_id") == detection["document_id"]][:5] if detection["status"] == "matched" else rows[:5]
            return rows, {"route_status": detection["status"], "route_document_id": detection.get("document_id"), "candidate_count": min(candidate_k, total_vectors), "calls_top_k_total_vectors": False, "approx_extra_memory_bytes": min(candidate_k, total_vectors) * 256}
        return run

    def run_row_subset(case: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        detection = route_doc(case)
        if detection["status"] != "matched":
            return run_global(case)
        rows, meta = row_subset_exact_search(store, engine.embed_text(case["question"]), row_id_map.get(detection["document_id"], []), top_k=5)
        meta.update({"route_status": detection["status"], "route_document_id": detection.get("document_id"), "calls_top_k_total_vectors": False})
        return rows, meta

    strategy_defs = [("current_global_top5", run_global), ("metadata_filters_exhaustive_top5", run_exhaustive_filter), ("global_oversampling_filter_k50", make_oversampling(50)), ("global_oversampling_filter_k100", make_oversampling(100)), ("global_oversampling_filter_k500", make_oversampling(500)), ("document_row_id_subset_exact_top5", run_row_subset)]
    strategy_results = {name: run_timed_strategy(name, cases, repeats, warmups, runner) for name, runner in strategy_defs}

    exhaustive_cases = {row["case_id"]: row for row in strategy_results["metadata_filters_exhaustive_top5"]["per_case"]}
    subset_cases = {row["case_id"]: row for row in strategy_results["document_row_id_subset_exact_top5"]["per_case"]}
    comparisons = []
    same_order = 0
    for case in cases:
        comparison = compare_chunk_ids(exhaustive_cases[case["id"]]["top_chunk_ids"], subset_cases[case["id"]]["top_chunk_ids"])
        comparison["case_id"] = case["id"]
        comparisons.append(comparison)
        same_order += int(comparison["same_order"])
    row_counts = [len(ids) for ids in row_id_map.values()]
    projection = {"current_vectors": total_vectors, "capacity_plan_low_vectors": 258000, "capacity_plan_baseline_vectors": 469000, "capacity_plan_high_vectors": 738000, "current_document_count_in_vector_store": len(row_id_map), "current_document_rows": {"min": min(row_counts) if row_counts else 0, "p50": round(percentile(row_counts, 0.50), 2) if row_counts else 0, "p95": round(percentile(row_counts, 0.95), 2) if row_counts else 0, "max": max(row_counts) if row_counts else 0}, "flat_index_complexity": "O(total_vectors * dimension)", "row_subset_complexity": "O(chunks_in_routed_document * dimension)"}
    return {"timestamp": datetime.now().isoformat(), "benchmark_file": str(BENCHMARK_PATH.relative_to(ROOT)), "negative_cases_file": str(NEGATIVE_CASES_PATH.relative_to(ROOT)), "repeats_per_query_after_warmup": repeats, "warmups_per_query": warmups, "vector_store": store.get_stats(), "company_catalog": {"size": len(catalog)}, "negative_cases": negative_result, "strategies": strategy_results, "row_subset_exhaustive_comparison": {"same_order_top5": metric_dict(same_order, len(cases)), "cases": comparisons, "faiss_reconstruct_batch_supported": hasattr(store.index, "reconstruct_batch")}, "corpus_projection": projection, "api_routing_contract": api_contract(), "recommended_production_design": recommended_design()}


def api_contract() -> Dict[str, str]:
    return {
        "recommended_contract": "explicit parameter first with query recognition fallback",
        "explicit_document_id": "If supplied and present in the current vector catalog, route directly to that document.",
        "explicit_company": "If supplied and uniquely maps to one document, route to that document; if it maps to multiple documents, return an ambiguity signal or require document_id.",
        "query_fallback": "If no explicit parameter is supplied, use longest unique exact company-name detection from the VectorStore catalog.",
        "no_match": "Fall back to global retrieval and mark routing_status=no_match.",
        "ambiguous": "Do not guess; return ambiguity metadata. For interactive UI/API, ask caller to choose document_id.",
        "wrong_parameter": "Return a validation error if explicit document_id is absent from the vector catalog.",
        "cross_company_query": "Do not force single-document routing unless caller supplies document_id; use global retrieval or a future multi-document contract.",
        "contest_single_company_qa": "Call with explicit document_id whenever the UI/task already knows the prospectus.",
    }


def recommended_design() -> Dict[str, Any]:
    return {
        "single_next_step": "add company recognition plus row-id subset candidate retrieval, then reuse existing LayeredRetriever post-processing",
        "keep_existing_search_interface": True,
        "new_non_breaking_method_needed": True,
        "minimal_signature": "search_by_row_ids(query_embedding: List[float], row_ids: List[int], top_k: int) -> List[Dict[str, Any]]",
        "requires_rebuild": False,
        "affects_incremental_update": "No index rebuild is required; the document_id to row-id map can be rebuilt from VectorStore.documents after load or append.",
        "not_recommended": "Do not use metadata_filters exhaustive top_k=total_vectors as the production routing implementation.",
    }


def write_report(result: Dict[str, Any], path: Path) -> None:
    strategies = result["strategies"]
    lines = [
        "# Scalable Company Routing Design",
        "",
        f"> Generated at: {result['timestamp']}",
        "",
        "## Conclusion",
        "",
        "- Recommended next production design: explicit parameter first with query recognition fallback, backed by row-id subset candidate retrieval plus existing LayeredRetriever post-processing.",
        "- Keep the existing `VectorStore.search()` interface unchanged.",
        "- Add only one non-breaking method in the next round if production implementation is approved: `search_by_row_ids(query_embedding, row_ids, top_k)` for candidate generation.",
        "- Do not promote the current exhaustive `metadata_filters` path to production routing; it calls `top_k=total_vectors` and scales with the full corpus.",
        "- V2 coverage wording correction: persisted vector coverage is `persisted_text_preview_coverage`, because `documents.json` stores `metadata.text_preview` up to 500 chars, not the full embedding input text.",
        "- This round did not modify `src/retriever/`, `src/vector/`, Gold labels, FAISS index files, Parser, Evidence, Chunk, Agent, API, Hybrid Retrieval, BM25, or reranker.",
        "",
        "## Performance Matrix",
        "",
        f"Warmup per query: {result['warmups_per_query']}; measured repeats per query: {result['repeats_per_query_after_warmup']}.",
        "",
        "| Strategy | Document hit | Section hit | Page hit | p50 ms | p95 ms | max ms | candidate count min/mean/max | approx extra memory max | calls top_k=total_vectors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    order = ["current_global_top5", "metadata_filters_exhaustive_top5", "global_oversampling_filter_k50", "global_oversampling_filter_k100", "global_oversampling_filter_k500", "document_row_id_subset_exact_top5"]
    for key in order:
        summary = strategies[key]["summary"]
        timing = summary["timing_ms"]
        candidates = summary["candidate_count"]
        per_case_meta = [row["metadata"] for row in strategies[key]["per_case"]]
        calls_total = any(meta.get("calls_top_k_total_vectors") for meta in per_case_meta)
        memory = max(int(meta.get("approx_extra_memory_bytes") or 0) for meta in per_case_meta) if per_case_meta else 0
        lines.append(f"| {key} | {metric_text(summary['document_hit'])} | {metric_text(summary['section_hit'])} | {metric_text(summary['normalized_physical_page_hit'])} | {timing['p50_ms']} | {timing['p95_ms']} | {timing['max_ms']} | {candidates['min']} / {candidates['mean']} / {candidates['max']} | {memory} bytes | {calls_total} |")
    lines.extend([
        "",
        "## Row-Id Subset Prototype",
        "",
        f"- FAISS `reconstruct_batch` supported: {result['row_subset_exhaustive_comparison']['faiss_reconstruct_batch_supported']}.",
        f"- Exhaustive-filter vs row-id subset same-order top5 chunk IDs: {metric_text(result['row_subset_exhaustive_comparison']['same_order_top5'])}.",
        "- The row-id subset prototype reconstructs only the routed document rows at query time and performs exact inner-product ranking in memory.",
        "- It does not write FAISS, rebuild vectors, or create per-company permanent indexes.",
        "- Difference from exhaustive `LayeredRetriever.search(metadata_filters=...)`: the prototype does raw vector ranking inside one document and does not yet apply layer filtering, chunk text loading, or keyword boosts. Production must insert row-id search at the candidate-generation seam and then reuse existing post-processing; raw subset top5 is not the final answer path.",
        "",
        "## Routing Negative Cases",
        "",
        "| Metric | Result |",
        "|---|---:|",
    ])
    neg = result["negative_cases"]["metrics"]
    for key in ["pass", "coverage", "detection_precision", "false_positive", "no_match", "ambiguous"]:
        lines.append(f"| {key} | {metric_text(neg[key])} |")
    lines.extend([
        "",
        "Negative cases include 10 no-company queries, actual catalog positives, a longest-unique-name case, an ambiguous same-name case, and a no-fuzzy-guess case.",
        "",
        "## API Routing Contract",
        "",
        "Recommended contract: explicit parameter first with query recognition fallback.",
        "",
        "| Scenario | Behavior |",
        "|---|---|",
    ])
    contract = result["api_routing_contract"]
    for key in ["explicit_document_id", "explicit_company", "query_fallback", "no_match", "ambiguous", "wrong_parameter", "cross_company_query", "contest_single_company_qa"]:
        lines.append(f"| {key} | {contract[key]} |")
    projection = result["corpus_projection"]
    lines.extend([
        "",
        "## 568-PDF Scaling View",
        "",
        f"- Current local vector count: {projection['current_vectors']}.",
        f"- Capacity plan vector range: low {projection['capacity_plan_low_vectors']}, baseline {projection['capacity_plan_baseline_vectors']}, high {projection['capacity_plan_high_vectors']}.",
        f"- Current document row distribution: min {projection['current_document_rows']['min']}, p50 {projection['current_document_rows']['p50']}, p95 {projection['current_document_rows']['p95']}, max {projection['current_document_rows']['max']}.",
        "- Exhaustive metadata filtering complexity: `O(total_vectors * dimension)` plus Python filtering.",
        "- Row-id subset complexity: `O(chunks_in_routed_document * dimension)` after company/document routing.",
        "",
        "## Recommended Production Design",
        "",
        "Single next implementation item: company recognition plus row-id subset candidate retrieval behind a non-breaking VectorStore method, followed by existing LayeredRetriever post-processing.",
        "",
        "- Existing `VectorStore.search()` stays unchanged.",
        "- Minimal new method signature for next round: `search_by_row_ids(query_embedding: List[float], row_ids: List[int], top_k: int) -> List[Dict[str, Any]]`.",
        "- Build `document_id -> row_ids` from `VectorStore.documents` after load and append; no vector rebuild is required.",
        "- No permanent per-company FAISS indexes are needed for the first production slice.",
        "- Main risk at 568 PDFs is long-tail company-name ambiguity and per-query reconstruct allocation; both should be measured again after one larger indexed batch.",
        "",
        "## Decision Gate",
        "",
        "- Proceed to design review for production company routing: yes.",
        "- Proceed to implement Hybrid Retrieval, BM25, reranker, Agent, or API now: no.",
        "- Proceed to 568-PDF server full run now: no; first implement routing and re-run Manual Gold V1 baseline locally.",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark scalable company routing designs.")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--output-path", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--negative-cases-path", type=Path, default=NEGATIVE_CASES_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    result = run_benchmark(repeats=args.repeats, warmups=args.warmups)
    output_path = args.output_path if args.output_path.is_absolute() else ROOT / args.output_path
    negative_path = args.negative_cases_path if args.negative_cases_path.is_absolute() else ROOT / args.negative_cases_path
    report_path = args.report_path if args.report_path.is_absolute() else ROOT / args.report_path
    write_json(negative_path, result["negative_cases"]["cases"])
    write_json(output_path, result)
    write_report(result, report_path)
    print(f"negative cases written: {negative_path}")
    print(f"performance written: {output_path}")
    print(f"report written: {report_path}")
    print(f"recommended design: {result['recommended_production_design']['single_next_step']}")


if __name__ == "__main__":
    main()


