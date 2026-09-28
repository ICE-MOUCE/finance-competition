#!/usr/bin/env python3
"""Run Manual Gold V1 with production Company Routing V1 enabled."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_rag_benchmark import (  # noqa: E402
    CATEGORY_LAYERS,
    EVIDENCE_DIR,
    VECTOR_DIR,
    evaluate_case,
    group_failures,
    metric_text,
    summarize,
    validate_cases,
)
from src.embedding import EmbeddingConfig, EmbeddingEngine  # noqa: E402
from src.evidence import EvidenceStore  # noqa: E402
from src.retriever import LayeredRetriever, RetrieverConfig  # noqa: E402
from src.vector import VectorStore  # noqa: E402

BENCHMARK_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1.json"
BASELINE_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1_results.json"
V2_PERFORMANCE_PATH = ROOT / "evaluation" / "benchmark" / "company_routing_performance.json"
RESULTS_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1_company_routing_results.json"
PERFORMANCE_PATH = ROOT / "evaluation" / "benchmark" / "company_routing_v1_performance.json"
REPORT_PATH = ROOT / "docs" / "rag" / "COMPANY_ROUTING_V1_REPORT.md"


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def metric_counts(rows: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    eligible = [row.get(key) for row in rows if row.get(key) is not None]
    hits = sum(1 for value in eligible if value is True)
    return {"hits": hits, "denominator": len(eligible), "rate": round(hits / len(eligible), 4) if eligible else None}


def pct(metric: Dict[str, Any]) -> str:
    denominator = metric.get("denominator", 0)
    hits = metric.get("hits", 0)
    return "N/A" if not denominator else f"{hits}/{denominator} ({hits / denominator:.2%})"


def percentile(values: List[float], q: float) -> float | None:
    if not values:
        return None
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


def timing_summary(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"runs": 0, "p50_ms": None, "p95_ms": None, "max_ms": None, "mean_ms": None}
    return {
        "runs": len(values),
        "p50_ms": round(statistics.median(values), 3),
        "p95_ms": round(percentile(values, 0.95), 3),
        "max_ms": round(max(values), 3),
        "mean_ms": round(statistics.fmean(values), 3),
    }


def routing_meta(row: Dict[str, Any]) -> Dict[str, Any]:
    return row.get("routing_metadata") or {}


def build_route_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    status_counts = Counter()
    source_counts = Counter()
    incorrect = []
    candidate_counts = []
    calls_total_vectors = False
    used_subset = 0
    for row in rows:
        meta = routing_meta(row)
        status = meta.get("routing_status") or "unknown"
        source = meta.get("routing_source") or "unknown"
        status_counts[status] += 1
        source_counts[source] += 1
        candidate = meta.get("routing_candidate_count")
        if candidate is not None:
            candidate_counts.append(int(candidate))
        used_subset += int(bool(meta.get("routing_used_row_id_subset")))
        calls_total_vectors = calls_total_vectors or bool(meta.get("routing_calls_top_k_total_vectors"))
        routed_doc = meta.get("routing_document_id")
        expected_docs = set(row.get("expected_document_ids") or [])
        if status == "matched" and routed_doc and expected_docs and routed_doc not in expected_docs:
            incorrect.append({"case_id": row["id"], "routing_document_id": routed_doc, "expected_document_ids": sorted(expected_docs)})
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "incorrect_routes": incorrect,
        "incorrect_route_count": len(incorrect),
        "used_row_id_subset_count": used_subset,
        "candidate_count": {
            "min": min(candidate_counts) if candidate_counts else 0,
            "mean": round(statistics.fmean(candidate_counts), 2) if candidate_counts else 0,
            "max": max(candidate_counts) if candidate_counts else 0,
        },
        "calls_top_k_total_vectors_from_metadata": calls_total_vectors,
    }


def probe_global_fallback(retriever: LayeredRetriever) -> Dict[str, Any]:
    query = "financial risk without company"
    results = retriever.search(query, layer="financial", top_k=5)
    meta = results[0].metadata if results else {}
    return {
        "query": query,
        "result_count": len(results),
        "routing_status": meta.get("routing_status"),
        "routing_source": meta.get("routing_source"),
        "used_row_id_subset": bool(meta.get("routing_used_row_id_subset")),
        "calls_top_k_total_vectors": bool(meta.get("routing_calls_top_k_total_vectors")),
    }


def compare_summary(results_summary: Dict[str, Any], baseline: Dict[str, Any], v2_perf: Dict[str, Any]) -> Dict[str, Any]:
    baseline_summary = (baseline or {}).get("summary", {})
    v2_summary = (((v2_perf or {}).get("strategies") or {}).get("metadata_filters_exhaustive_top5") or {}).get("summary", {})
    return {
        "baseline_global_top5": {
            "document_hit": baseline_summary.get("correct_document_hit_rate"),
            "section_hit": baseline_summary.get("expected_section_hit_rate"),
            "normalized_page_hit": baseline_summary.get("normalized_physical_page_hit_rate"),
        },
        "v2_exhaustive_upper_bound": {
            "document_hit": v2_summary.get("document_hit"),
            "section_hit": v2_summary.get("section_hit"),
            "normalized_page_hit": v2_summary.get("normalized_physical_page_hit"),
        },
        "company_routing_v1": {
            "document_hit": results_summary.get("correct_document_hit_rate"),
            "section_hit": results_summary.get("expected_section_hit_rate"),
            "normalized_page_hit": results_summary.get("normalized_physical_page_hit_rate"),
        },
    }


def metric_from_summary(summary: Dict[str, Any], key: str) -> Dict[str, Any]:
    raw = summary.get(key) or {}
    if "hits" in raw:
        return raw
    denominator = raw.get("denominator", 0)
    rate = raw.get("rate")
    hits = int(round(rate * denominator)) if rate is not None else 0
    return {"hits": hits, "denominator": denominator, "rate": rate}


def write_report(result: Dict[str, Any], path: Path) -> None:
    summary = result["summary"]
    perf = result["performance"]
    route = result["routing"]
    comparison = result["comparison"]
    gate = result["decision_gate"]
    baseline = comparison["baseline_global_top5"]
    upper = comparison["v2_exhaustive_upper_bound"]
    current = comparison["company_routing_v1"]

    lines = [
        "# Company Routing V1 Report",
        "",
        f"> Generated at: {result['timestamp']}",
        "",
        "## Summary",
        "",
        f"- Document hit: {metric_text(summary['correct_document_hit_rate'])}",
        f"- Section hit: {metric_text(summary['expected_section_hit_rate'])}",
        f"- Normalized physical page hit: {metric_text(summary['normalized_physical_page_hit_rate'])}",
        f"- Evidence completeness: {summary['evidence_completeness']:.2%}",
        f"- Page reference rate: {summary['page_reference_rate']:.2%}",
        "",
        "## Baseline Comparison",
        "",
        "| Strategy | Document hit | Section hit | Normalized page hit |",
        "|---|---:|---:|---:|",
        f"| Global top-5 baseline | {metric_text(baseline['document_hit'])} | {metric_text(baseline['section_hit'])} | {metric_text(baseline['normalized_page_hit'])} |",
        f"| V2 exhaustive upper bound | {pct(upper['document_hit'])} | {pct(upper['section_hit'])} | {pct(upper['normalized_page_hit'])} |",
        f"| Company Routing V1 | {metric_text(current['document_hit'])} | {metric_text(current['section_hit'])} | {metric_text(current['normalized_page_hit'])} |",
        "",
        "## Routing Behavior",
        "",
        f"- Routing status counts: `{route['status_counts']}`.",
        f"- Routing source counts: `{route['source_counts']}`.",
        f"- Incorrect route: {route['incorrect_route_count']}/{summary['total_cases']} ({route['incorrect_route_count'] / summary['total_cases']:.2%}).",
        f"- Row-id subset used: {route['used_row_id_subset_count']}/{summary['total_cases']} ({route['used_row_id_subset_count'] / summary['total_cases']:.2%}).",
        f"- Candidate pool min/mean/max: {route['candidate_count']['min']} / {route['candidate_count']['mean']} / {route['candidate_count']['max']}.",
        f"- Calls `top_k=total_vectors`: {perf['calls_top_k_total_vectors']}.",
        "",
        "## Performance",
        "",
        f"- Runs: {perf['timing_ms']['runs']} measured searches.",
        f"- p50 / p95 / max: {perf['timing_ms']['p50_ms']} ms / {perf['timing_ms']['p95_ms']} ms / {perf['timing_ms']['max_ms']} ms.",
        f"- Warmups per case: {perf['warmups_per_case']}; repeats per case: {perf['repeats_per_case']}.",
        "",
        "## Global Fallback Regression",
        "",
        f"- No-company probe status/source: `{perf['global_fallback_probe']['routing_status']}` / `{perf['global_fallback_probe']['routing_source']}`.",
        f"- No-company probe used row-id subset: {perf['global_fallback_probe']['used_row_id_subset']}.",
        "",
        "## Decision Gate",
        "",
    ]
    for item, passed in gate.items():
        lines.append(f"- {item}: {'PASS' if passed else 'FAIL'}")
    lines.extend([
        "",
        "## Notes",
        "",
        "- Candidate pool rule: routed searches use all FAISS row ids for the matched document, then reuse existing LayeredRetriever post-processing. This reproduces the V2 exhaustive upper-bound candidate order within the routed document without querying all corpus vectors.",
        "- This implementation does not add Hybrid Retrieval, BM25, reranking, Agent, API, vector rebuild, or PDF reparse.",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_benchmark(repeats: int, warmups: int) -> Dict[str, Any]:
    cases = load_json(BENCHMARK_PATH)
    validate_cases(cases)
    engine = EmbeddingEngine(EmbeddingConfig())
    store = VectorStore(str(VECTOR_DIR), dimension=engine.dimension)
    total_vectors = store.get_stats().get("total_vectors", 0)
    search_calls: List[int] = []
    subset_calls: List[int] = []
    original_search = store.search
    original_subset_search = store.search_by_row_ids

    def recorded_search(query_embedding: List[float], top_k: int = 10) -> List[Dict[str, Any]]:
        search_calls.append(top_k)
        return original_search(query_embedding, top_k=top_k)

    def recorded_subset_search(query_embedding: List[float], row_ids: List[int], top_k: int) -> List[Dict[str, Any]]:
        subset_calls.append(top_k)
        return original_subset_search(query_embedding, row_ids=row_ids, top_k=top_k)

    store.search = recorded_search  # type: ignore[method-assign]
    store.search_by_row_ids = recorded_subset_search  # type: ignore[method-assign]

    retriever = LayeredRetriever(store, engine, RetrieverConfig(enable_layer_filter=True))
    last_search_metadata: Dict[str, Any] = {}
    original_retriever_search = retriever.search

    def recorded_retriever_search(*args: Any, **kwargs: Any) -> List[Any]:
        nonlocal last_search_metadata
        results = original_retriever_search(*args, **kwargs)
        last_search_metadata = dict(results[0].metadata) if results else {}
        return results

    retriever.search = recorded_retriever_search  # type: ignore[method-assign]
    evidence_store = EvidenceStore(str(EVIDENCE_DIR))
    timings = []
    rows = []
    per_case = []
    for case in cases:
        layer = CATEGORY_LAYERS[case["category"]]
        for _ in range(warmups):
            retriever.search(case["question"], layer=layer, top_k=5)
        case_timings = []
        last_row = None
        for _ in range(repeats):
            last_row = evaluate_case(retriever, evidence_store, case, top_k=5)
            last_row["routing_metadata"] = dict(last_search_metadata)
            for result_row in last_row.get("results", []):
                result_row["routing_metadata"] = dict(last_search_metadata)
            elapsed_ms = float(last_row.get("elapsed_seconds", 0.0)) * 1000
            timings.append(elapsed_ms)
            case_timings.append(elapsed_ms)
        rows.append(last_row)
        meta = routing_meta(last_row)
        per_case.append({
            "case_id": case["id"],
            "timing_ms": timing_summary(case_timings),
            "routing_status": meta.get("routing_status"),
            "routing_source": meta.get("routing_source"),
            "routing_document_id": meta.get("routing_document_id"),
            "routing_candidate_count": meta.get("routing_candidate_count"),
            "document_hit": last_row.get("correct_document_hit"),
            "section_hit": last_row.get("expected_section_hit"),
            "normalized_physical_page_hit": last_row.get("normalized_physical_page_hit"),
        })

    summary = summarize(rows, store.get_stats())
    route_summary = build_route_summary(rows)
    calls_total_vectors = any(call == total_vectors for call in search_calls)
    performance = {
        "timing_ms": timing_summary(timings),
        "warmups_per_case": warmups,
        "repeats_per_case": repeats,
        "global_search_call_count": len(search_calls),
        "row_id_subset_call_count": len(subset_calls),
        "global_search_top_k_values": search_calls,
        "row_id_subset_top_k_min_mean_max": {
            "min": min(subset_calls) if subset_calls else 0,
            "mean": round(statistics.fmean(subset_calls), 2) if subset_calls else 0,
            "max": max(subset_calls) if subset_calls else 0,
        },
        "calls_top_k_total_vectors": calls_total_vectors or route_summary["calls_top_k_total_vectors_from_metadata"],
        "global_fallback_probe": probe_global_fallback(retriever),
    }
    comparison = compare_summary(summary, load_json(BASELINE_PATH, {}), load_json(V2_PERFORMANCE_PATH, {}))
    document_metric = metric_from_summary(summary, "correct_document_hit_rate")
    section_metric = metric_from_summary(summary, "expected_section_hit_rate")
    page_metric = metric_from_summary(summary, "normalized_physical_page_hit_rate")
    gate = {
        "document_hit_at_least_25_of_25": document_metric["hits"] >= 25 and document_metric["denominator"] == 25,
        "section_hit_at_least_17_of_25": section_metric["hits"] >= 17 and section_metric["denominator"] == 25,
        "normalized_page_hit_at_least_17_of_25": page_metric["hits"] >= 17 and page_metric["denominator"] == 25,
        "incorrect_route_is_zero": route_summary["incorrect_route_count"] == 0,
        "routed_path_no_top_k_total_vectors": not performance["calls_top_k_total_vectors"],
        "p95_under_100_ms": (performance["timing_ms"]["p95_ms"] or 999999) < 100,
    }
    return {
        "timestamp": datetime.now().isoformat(),
        "benchmark_file": str(BENCHMARK_PATH.relative_to(ROOT)),
        "top_k": 5,
        "vector_stats": store.get_stats(),
        "summary": summary,
        "failure_analysis": group_failures(rows),
        "cases": rows,
        "routing": route_summary,
        "performance": performance,
        "comparison": comparison,
        "decision_gate": gate,
        "per_case_performance": per_case,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Company Routing V1 on Manual Gold V1.")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--results-path", type=Path, default=RESULTS_PATH)
    parser.add_argument("--performance-path", type=Path, default=PERFORMANCE_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    result = run_benchmark(repeats=args.repeats, warmups=args.warmups)
    results_path = args.results_path if args.results_path.is_absolute() else ROOT / args.results_path
    performance_path = args.performance_path if args.performance_path.is_absolute() else ROOT / args.performance_path
    report_path = args.report_path if args.report_path.is_absolute() else ROOT / args.report_path
    benchmark_payload = {key: result[key] for key in ["timestamp", "benchmark_file", "top_k", "vector_stats", "summary", "failure_analysis", "cases"]}
    performance_payload = {key: result[key] for key in ["timestamp", "benchmark_file", "top_k", "vector_stats", "routing", "performance", "comparison", "decision_gate", "per_case_performance"]}
    write_json(results_path, benchmark_payload)
    write_json(performance_path, performance_payload)
    write_report(result, report_path)
    print(f"results written: {results_path}")
    print(f"performance written: {performance_path}")
    print(f"report written: {report_path}")


if __name__ == "__main__":
    main()
