#!/usr/bin/env python3
"""Evaluate the current Retriever against the versioned RAG benchmark."""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

from opencc import OpenCC

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.embedding import EmbeddingConfig, EmbeddingEngine
from src.evidence import EvidenceStore
from src.retriever import LayeredRetriever, RetrieverConfig
from src.vector import VectorStore


BENCHMARK_PATH = ROOT / "evaluation" / "benchmark" / "benchmark_queries.json"
RESULTS_PATH = ROOT / "evaluation" / "benchmark" / "results.json"
REPORT_PATH = ROOT / "docs" / "rag" / "RAG_BENCHMARK_REPORT.md"
VECTOR_DIR = ROOT / "data" / "vectors"
EVIDENCE_DIR = ROOT / "data" / "evidence"

CATEGORY_LAYERS = {
    "financial_risk": "financial",
    "business_risk": "market",
    "ownership_risk": "governance",
    "compliance_risk": "legal",
    "ipo_specific_risk": "all",
}
REQUIRED_FIELDS = {
    "id", "category", "question", "expected_document_ids", "expected_companies",
    "expected_sections", "expected_page_ranges", "expected_keywords", "answer_type",
    "difficulty", "notes",
}
NORMALIZER = OpenCC("t2s")


def normalize(text: str) -> str:
    return "".join(NORMALIZER.convert(str(text)).lower().split())


def validate_cases(cases: List[Dict]) -> None:
    ids = set()
    for case in cases:
        missing = REQUIRED_FIELDS - set(case)
        if missing:
            raise ValueError(f"{case.get('id', '<missing id>')}: missing {sorted(missing)}")
        if case["id"] in ids:
            raise ValueError(f"Duplicate benchmark id: {case['id']}")
        ids.add(case["id"])
        for field in ("expected_document_ids", "expected_companies", "expected_sections", "expected_page_ranges", "expected_keywords"):
            if not isinstance(case[field], list):
                raise ValueError(f"{case['id']}: {field} must be a list")
        for page_range in case["expected_page_ranges"]:
            if not isinstance(page_range, list) or len(page_range) != 2 or page_range[0] > page_range[1]:
                raise ValueError(f"{case['id']}: invalid page range {page_range}")


def overlaps_page_ranges(pages: Iterable[int], ranges: List[List[int]]) -> bool:
    return any(start <= page <= end for page in pages for start, end in ranges)


def collect_result_text(result, evidence_store: EvidenceStore) -> tuple[str, bool, bool]:
    evidences = evidence_store.get_many(result.document_id, result.evidence_ids)
    evidence_text = " ".join(evidence.get("text", "") for evidence in evidences)
    complete = bool(result.evidence_ids) and len(evidences) == len(result.evidence_ids)
    has_page = bool(result.pages) or any(evidence.get("page") is not None for evidence in evidences)
    return f"{result.text or ''} {evidence_text}", complete, has_page


def evaluate_case(retriever: LayeredRetriever, evidence_store: EvidenceStore, case: Dict, top_k: int) -> Dict:
    layer = CATEGORY_LAYERS[case["category"]]
    started = time.perf_counter()
    results = retriever.search(case["question"], layer=layer, top_k=top_k)
    elapsed = time.perf_counter() - started

    result_text = []
    documents = set()
    companies = set()
    sections = []
    pages = []
    complete_count = 0
    page_ref_count = 0
    rows = []
    for rank, result in enumerate(results, 1):
        text, complete, has_page = collect_result_text(result, evidence_store)
        result_text.append(text)
        documents.add(result.document_id)
        companies.add(normalize(result.company))
        sections.extend(normalize(section) for section in result.section_path)
        pages.extend(result.pages)
        complete_count += int(complete)
        page_ref_count += int(has_page)
        rows.append({
            "rank": rank,
            "chunk_id": result.chunk_id,
            "document_id": result.document_id,
            "company": result.company,
            "pages": result.pages,
            "section_path": result.section_path,
            "block_type": result.block_type,
            "score": result.score,
            "evidence_ids": result.evidence_ids,
            "evidence_complete": complete,
            "page_reference_exists": has_page,
            "preview": (result.text or "")[:240],
        })

    returned_text = normalize(" ".join(result_text))
    expected_keywords = [normalize(keyword) for keyword in case["expected_keywords"] if keyword]
    matched_keywords = [keyword for keyword in expected_keywords if keyword in returned_text]
    expected_sections = [normalize(section) for section in case["expected_sections"] if section]
    matched_sections = [section for section in expected_sections if any(section in actual for actual in sections)]
    expected_documents = set(case["expected_document_ids"])
    expected_companies = [normalize(company) for company in case["expected_companies"] if company]
    document_hit = bool(expected_documents.intersection(documents)) if expected_documents else None
    company_hit = any(company in companies for company in expected_companies) if expected_companies else None
    section_hit = bool(matched_sections) if expected_sections else None
    page_hit = overlaps_page_ranges(pages, case["expected_page_ranges"]) if case["expected_page_ranges"] else None
    keyword_coverage = len(matched_keywords) / len(expected_keywords) if expected_keywords else None
    confidence = rows[0]["score"] if rows else 0.0
    low_confidence = not rows or confidence < retriever.config.min_score + 0.08 or keyword_coverage == 0

    return {
        "id": case["id"],
        "category": case["category"],
        "label_status": case.get("label_status", "unspecified"),
        "question": case["question"],
        "layer": layer,
        "answer_type": case["answer_type"],
        "difficulty": case["difficulty"],
        "expected_document_ids": case["expected_document_ids"],
        "expected_companies": case["expected_companies"],
        "expected_sections": case["expected_sections"],
        "expected_page_ranges": case["expected_page_ranges"],
        "expected_keywords": case["expected_keywords"],
        "matched_keywords": matched_keywords,
        "matched_sections": matched_sections,
        "result_count": len(rows),
        "elapsed_seconds": round(elapsed, 4),
        "correct_document_hit": document_hit,
        "correct_company_hit": company_hit,
        "expected_keyword_coverage": round(keyword_coverage, 4) if keyword_coverage is not None else None,
        "expected_section_hit": section_hit,
        "page_range_hit": page_hit,
        "evidence_completeness": round(complete_count / len(rows), 4) if rows else 0.0,
        "page_reference_rate": round(page_ref_count / len(rows), 4) if rows else 0.0,
        "low_confidence": low_confidence,
        "top_score": round(confidence, 4),
        "results": rows,
    }


def rate(rows: List[Dict], key: str) -> Dict:
    eligible = [row[key] for row in rows if row[key] is not None]
    return {"rate": round(sum(eligible) / len(eligible), 4) if eligible else None, "denominator": len(eligible)}


def summarize(rows: List[Dict], vector_stats: Dict) -> Dict:
    keyword_rows = [row["expected_keyword_coverage"] for row in rows if row["expected_keyword_coverage"] is not None]
    return {
        "total_cases": len(rows),
        "correct_document_hit_rate": rate(rows, "correct_document_hit"),
        "correct_company_hit_rate": rate(rows, "correct_company_hit"),
        "expected_section_hit_rate": rate(rows, "expected_section_hit"),
        "page_range_hit_rate": rate(rows, "page_range_hit"),
        "expected_keyword_coverage": round(sum(keyword_rows) / len(keyword_rows), 4) if keyword_rows else None,
        "keyword_coverage_denominator": len(keyword_rows),
        "evidence_completeness": round(sum(row["evidence_completeness"] for row in rows) / len(rows), 4) if rows else 0.0,
        "page_reference_rate": round(sum(row["page_reference_rate"] for row in rows) / len(rows), 4) if rows else 0.0,
        "no_result_rate": round(sum(not row["result_count"] for row in rows) / len(rows), 4) if rows else 0.0,
        "low_confidence_cases": [row["id"] for row in rows if row["low_confidence"]],
        "failed_cases": [row["id"] for row in rows if row["correct_document_hit"] is False],
        "vector_count": vector_stats.get("total_vectors", 0),
        "label_status_counts": {status: sum(row["label_status"] == status for row in rows) for status in sorted({row["label_status"] for row in rows})},
    }


def group_failures(rows: List[Dict]) -> Dict[str, List[Dict]]:
    special_categories = {"ownership_risk", "compliance_risk", "ipo_specific_risk"}
    return {
        "complete_misses": [row for row in rows if row["correct_document_hit"] is False],
        "document_hit_keyword_miss": [row for row in rows if row["correct_document_hit"] is True and row["expected_keyword_coverage"] == 0],
        "keyword_hit_section_miss": [row for row in rows if row["expected_keyword_coverage"] not in (None, 0) and row["expected_section_hit"] is False],
        "page_missing_or_untrusted": [row for row in rows if row["page_range_hit"] is False or (row["expected_page_ranges"] and row["page_reference_rate"] == 0)],
        "table_cases": [row for row in rows if row["answer_type"] == "table"],
        "special_risk_low_coverage": [row for row in rows if row["category"] in special_categories and (row["expected_keyword_coverage"] or 0) < 0.5],
    }


def write_report(report: Dict) -> None:
    summary = report["summary"]
    failures = report["failure_analysis"]
    def metric(name: str, value: Dict) -> str:
        return "N/A" if value["rate"] is None else f"{value['rate']:.2%} ({value['denominator']} labeled)"

    lines = [
        "# RAG Benchmark Report",
        "",
        f"> Generated: {report['timestamp']}",
        "",
        "## Scope",
        "",
        "This benchmark evaluates retrieval grounding, not generated-answer accuracy. `gold_seed` cases have manually verified source labels; `catalog_document_label` cases verify the named local pilot document and retrieval terms but require later human section/page annotation.",
        "",
        "## Summary",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Cases | {summary['total_cases']} |",
        f"| Correct document hit rate | {metric('document', summary['correct_document_hit_rate'])} |",
        f"| Correct company hit rate | {metric('company', summary['correct_company_hit_rate'])} |",
        f"| Expected keyword coverage | {summary['expected_keyword_coverage']:.2%} ({summary['keyword_coverage_denominator']} labeled) |",
        f"| Expected section hit rate | {metric('section', summary['expected_section_hit_rate'])} |",
        f"| Page range hit rate | {metric('page', summary['page_range_hit_rate'])} |",
        f"| Evidence completeness | {summary['evidence_completeness']:.2%} |",
        f"| Page reference rate | {summary['page_reference_rate']:.2%} |",
        f"| No-result rate | {summary['no_result_rate']:.2%} |",
        f"| Low-confidence cases | {len(summary['low_confidence_cases'])} |",
        f"| Vector documents | {summary['vector_count']} |",
        "",
        "## Label Coverage",
        "",
        *[f"- `{status}`: {count}" for status, count in summary["label_status_counts"].items()],
        "",
        "## Failure Analysis",
        "",
    ]
    labels = {
        "complete_misses": "Complete document misses",
        "document_hit_keyword_miss": "Document hit but expected keyword miss",
        "keyword_hit_section_miss": "Keyword hit but expected section miss",
        "page_missing_or_untrusted": "Missing or untrusted page references",
        "table_cases": "Table-answer cases",
        "special_risk_low_coverage": "Low coverage in governance, compliance, or IPO-specific risk",
    }
    for key, title in labels.items():
        rows = failures[key]
        lines.extend([f"### {title}", ""])
        if not rows:
            lines.append("- None")
        else:
            for row in rows:
                lines.append(f"- `{row['id']}` [{row['category']}] doc={row['correct_document_hit']} keyword={row['expected_keyword_coverage']} section={row['expected_section_hit']} page={row['page_range_hit']}")
        lines.append("")

    lines.extend([
        "## Decision Guidance",
        "",
        "- Do not introduce Hybrid Retrieval from this v1 alone. First increase the `gold_seed` subset across companies and complete section/page labels for catalog cases.",
        "- If the expanded gold subset shows document hits but keyword misses, test keyword filtering first. If document/keyword hits are good but ranking is poor, test reranking before BM25.",
        "- BM25 is justified only when manually labeled failures show exact lexical terms are absent from vector TopK. Section filtering is justified only when section labels show recurring wrong-section hits.",
        "- Do not start the 568-PDF production run or an RAG API based on this benchmark alone; use the Production Readiness Review gates and a representative full-PDF acceptance run.",
        "- Table cases should be reviewed separately. Persistently low table coverage is evidence to improve table descriptions/chunks before changing retrieval architecture.",
    ])
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def run_benchmark(benchmark_path: Path, results_path: Path, top_k: int) -> Dict:
    cases = json.loads(benchmark_path.read_text(encoding="utf-8"))
    validate_cases(cases)
    engine = EmbeddingEngine(EmbeddingConfig())
    store = VectorStore(str(VECTOR_DIR), dimension=engine.dimension)
    retriever = LayeredRetriever(store, engine, RetrieverConfig())
    evidence_store = EvidenceStore(str(EVIDENCE_DIR))
    rows = [evaluate_case(retriever, evidence_store, case, top_k) for case in cases]
    report = {
        "timestamp": datetime.now().isoformat(),
        "benchmark_file": str(benchmark_path.relative_to(ROOT)),
        "top_k": top_k,
        "vector_stats": store.get_stats(),
        "summary": summarize(rows, store.get_stats()),
        "failure_analysis": group_failures(rows),
        "cases": rows,
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the RAG benchmark.")
    parser.add_argument("--benchmark-path", type=Path, default=BENCHMARK_PATH)
    parser.add_argument("--results-path", type=Path, default=RESULTS_PATH)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    benchmark_path = args.benchmark_path if args.benchmark_path.is_absolute() else ROOT / args.benchmark_path
    results_path = args.results_path if args.results_path.is_absolute() else ROOT / args.results_path
    report = run_benchmark(benchmark_path, results_path, args.top_k)
    print(f"RAG benchmark complete: {report['summary']['total_cases']} cases")
    print(f"Results: {results_path}")
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
