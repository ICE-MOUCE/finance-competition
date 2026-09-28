#!/usr/bin/env python3
"""Audit manual benchmark page grounding against normalized physical pages and PDF labels."""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "evaluation" / "benchmark" / "manual_teamer_results.json"
AUDIT_PATH = ROOT / "evaluation" / "benchmark" / "page_grounding_audit.json"
REPORT_PATH = ROOT / "docs" / "rag" / "PAGE_GROUNDING_AUDIT.md"
TEAMER_DIR = ROOT / "team_work" / "teamer_ex"


def normalize_pages(pages):
    normalized = []
    for page in pages:
        try:
            normalized.append(int(page))
        except (TypeError, ValueError):
            continue
    return normalized


def overlaps(pages, ranges):
    clean_pages = normalize_pages(pages)
    return any(start <= page <= end for page in clean_pages for start, end in ranges)


def flatten_ranges(ranges):
    return [page for start, end in ranges for page in range(start, end + 1)]


def nearest_delta(expected_ranges, returned_pages):
    expected_pages = flatten_ranges(expected_ranges)
    clean_returned = normalize_pages(returned_pages)
    if not expected_pages or not clean_returned:
        return None
    candidates = []
    for expected in expected_pages:
        for returned in clean_returned:
            candidates.append((abs(returned - expected), returned - expected, expected, returned))
    _, delta, expected, returned = sorted(candidates)[0]
    return {"delta": delta, "expected_page": expected, "returned_page": returned}


def returned_doc_rows(case):
    expected_docs = set(case.get("expected_document_ids", []))
    rows = []
    pages = []
    labels = []
    for result in case.get("results", []):
        if expected_docs and result.get("document_id") not in expected_docs:
            continue
        row = {
            "rank": result.get("rank"),
            "document_id": result.get("document_id"),
            "pages": result.get("pages", []),
            "page_labels": result.get("page_labels", []),
            "section_path": result.get("section_path", []),
            "score": result.get("score"),
            "chunk_id": result.get("chunk_id"),
            "cross_page_chunk": len(result.get("pages", [])) > 1,
        }
        rows.append(row)
        pages.extend(row["pages"])
        labels.extend(row["page_labels"])
    return sorted(set(normalize_pages(pages))), sorted(set(normalize_pages(labels))), rows


def infer_failure_reason(case, audit_row):
    if not case.get("expected_physical_page_ranges_0_based"):
        return "annotation_ambiguous"
    if case.get("page_mapping_status") == "source_pdf_unavailable":
        return "source_pdf_unavailable"
    if case.get("page_mapping_status") not in ("mapped_verified", "mapped", "confirmed"):
        return "page_mapping_error"
    if audit_row["normalized_physical_page_hit"] is True:
        return None
    if case.get("correct_document_hit") is not True:
        return "retrieval_page_miss"
    if case.get("page_basis") in ("unknown", None):
        return "annotation_ambiguous"
    if audit_row.get("nearest_physical_page_delta") and abs(audit_row["nearest_physical_page_delta"].get("delta", 9999)) <= 1:
        return "cross_page_chunk"
    return "retrieval_page_miss"


def audit_case(case):
    pages, labels, rows = returned_doc_rows(case)
    raw_ranges = case.get("raw_annotated_page_ranges") or case.get("expected_page_ranges", [])
    label_ranges = case.get("expected_page_labels") or raw_ranges
    physical_ranges = case.get("expected_physical_page_ranges_0_based") or []
    strict_hit = overlaps(pages, raw_ranges) if raw_ranges else None
    label_hit = overlaps(labels, label_ranges) if label_ranges and labels else None
    normalized_hit = overlaps(pages, physical_ranges) if physical_ranges else None
    audit_row = {
        "case_id": case["id"],
        "id": case["id"],
        "annotator": case.get("annotator", "unknown"),
        "category": case.get("category"),
        "label_status": case.get("label_status"),
        "question": case.get("question"),
        "expected_document": case.get("expected_document_ids", []),
        "expected_document_ids": case.get("expected_document_ids", []),
        "raw_annotated_page_ranges": raw_ranges,
        "expected_page_ranges": case.get("expected_page_ranges", []),
        "page_basis": case.get("page_basis", "unknown"),
        "expected_page_labels": label_ranges,
        "expected_physical_page_ranges_0_based": physical_ranges,
        "page_mapping_status": case.get("page_mapping_status", "unknown"),
        "mapping_note": case.get("mapping_note", ""),
        "retriever_returned_pages": pages,
        "retriever_returned_page_labels": labels,
        "topk_expected_document_rows": rows,
        "document_hit": case.get("correct_document_hit"),
        "section_hit": case.get("expected_section_hit"),
        "page_label_hit": label_hit,
        "strict_hit": strict_hit,
        "normalized_physical_page_hit": normalized_hit,
        "page_reference_rate": case.get("page_reference_rate"),
        "evidence_completeness": case.get("evidence_completeness"),
        "nearest_physical_page_delta": nearest_delta(physical_ranges, pages),
        "document_hit_but_page_mismatch": case.get("correct_document_hit") is True and normalized_hit is False,
        "manual_review_required": case.get("label_status") != "gold_seed" or normalized_hit is not True,
    }
    audit_row["failure_reason"] = infer_failure_reason(case, audit_row)
    return audit_row


def metric(rows, key):
    values = [row.get(key) for row in rows if row.get(key) is not None]
    hits = sum(1 for value in values if value is True)
    return {"hits": hits, "denominator": len(values), "rate": round(hits / len(values), 4) if values else None}


def grouped(rows, field):
    buckets = defaultdict(list)
    for row in rows:
        value = row.get(field)
        if isinstance(value, list):
            values = value or ["unknown"]
        else:
            values = [value or "unknown"]
        for item in values:
            buckets[str(item)].append(row)
    return {
        key: {
            "case_count": len(items),
            "document_hit": metric(items, "document_hit"),
            "section_hit": metric(items, "section_hit"),
            "normalized_physical_page_hit": metric(items, "normalized_physical_page_hit"),
            "strict_hit": metric(items, "strict_hit"),
            "page_label_hit": metric(items, "page_label_hit"),
        }
        for key, items in sorted(buckets.items())
    }


def source_annotation_summary():
    summary = []
    for path in sorted(TEAMER_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        summary.append({
            "file": str(path.relative_to(ROOT)),
            "has_page_range_notation": "[[" in text and "]]" in text,
            "has_multiple_page_ranges": "], [" in text,
            "mentions_physical_page": "物理页" in text,
            "mentions_pdf_reader_page": "阅读器" in text or "PDF页" in text,
            "mentions_printed_page": "印刷页" in text,
        })
    return summary


def pct(item):
    if item["rate"] is None:
        return "N/A"
    return f"{item['rate']:.2%} ({item['hits']}/{item['denominator']})"


def write_group_table(lines, title, data):
    lines.extend([
        f"## {title}",
        "",
        "| 分组 | 案例数 | 文档命中 | 章节命中 | 标准物理页命中 | 原始 strict 命中 | PDF page-label 命中 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for name, item in data.items():
        lines.append(f"| {name} | {item['case_count']} | {pct(item['document_hit'])} | {pct(item['section_hit'])} | {pct(item['normalized_physical_page_hit'])} | {pct(item['strict_hit'])} | {pct(item['page_label_hit'])} |")
    lines.append("")


def write_report(audit, report_path=REPORT_PATH):
    summary = audit["summary"]
    lines = [
        "# Page Grounding Audit",
        "",
        f"> Generated at: {audit['timestamp']}",
        "",
        "## Conclusion",
        "",
        "- System pages use MinerU `page_idx`, i.e. 0-based physical PDF page indexes.",
        "- Manual annotations have now been standardized as derived fields. The original human page ranges are preserved as raw annotations and page labels.",
        "- The primary page grounding metric is `normalized_physical_page_hit`, evaluated against `expected_physical_page_ranges_0_based`.",
        "- PDF page-label hit remains a diagnostic metric and does not replace the primary metric.",
        "",
        "## Metrics",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| manual benchmark total cases | {summary['total_cases']} |",
        f"| valid page Gold cases | {summary['valid_page_gold_cases']} |",
        f"| document hit | {pct(summary['document_hit'])} |",
        f"| section hit | {pct(summary['section_hit'])} |",
        f"| normalized physical page hit | {pct(summary['normalized_physical_page_hit'])} |",
        f"| raw strict page hit | {pct(summary['strict_hit'])} |",
        f"| PDF page-label hit | {pct(summary['page_label_hit'])} |",
        f"| evidence completeness | {summary['evidence_completeness']:.2%} |",
        f"| vector count | {summary['vector_count']} |",
        "",
        "## Source Annotation Page Basis",
        "",
    ]
    for item in audit["source_annotation_files"]:
        lines.append(f"- `{item['file']}`: range_notation={item['has_page_range_notation']}, multiple_ranges={item['has_multiple_page_ranges']}, mentions_physical={item['mentions_physical_page']}, mentions_reader={item['mentions_pdf_reader_page']}, mentions_printed={item['mentions_printed_page']}")
    lines.append("")
    write_group_table(lines, "按标注成员统计", audit["by_annotator"])
    write_group_table(lines, "按文档统计", audit["by_document"])
    write_group_table(lines, "按风险类别统计", audit["by_category"])
    lines.extend([
        "## Failure Reason Summary",
        "",
        "| failure_reason | count |",
        "|---|---:|",
    ])
    for reason, count in sorted(audit["failure_reason_counts"].items()):
        lines.append(f"| {reason} | {count} |")
    lines.extend(["", "## Cases", ""])
    for case in audit["cases"]:
        lines.append(f"### {case['case_id']}")
        lines.append("")
        lines.append(f"- annotator: `{case['annotator']}`")
        lines.append(f"- question: {case['question']}")
        lines.append(f"- expected_document: `{case['expected_document']}`")
        lines.append(f"- raw_annotated_page_ranges: `{case['raw_annotated_page_ranges']}`")
        lines.append(f"- page_basis: `{case['page_basis']}`")
        lines.append(f"- expected_page_labels: `{case['expected_page_labels']}`")
        lines.append(f"- expected_physical_page_ranges_0_based: `{case['expected_physical_page_ranges_0_based']}`")
        lines.append(f"- retriever_returned_pages: `{case['retriever_returned_pages']}`")
        lines.append(f"- document_hit: `{case['document_hit']}`")
        lines.append(f"- section_hit: `{case['section_hit']}`")
        lines.append(f"- page_label_hit: `{case['page_label_hit']}`")
        lines.append(f"- normalized_physical_page_hit: `{case['normalized_physical_page_hit']}`")
        lines.append(f"- failure_reason: `{case['failure_reason']}`")
        lines.append(f"- mapping_note: {case['mapping_note']}")
        lines.append("")
    lines.extend([
        "## Dependency Note",
        "",
        "- `opencc` is required by `scripts/evaluate_rag_benchmark.py` for traditional/simplified Chinese normalization of keywords and companies.",
        "- It is not required for page grounding itself.",
        "- No dependency was installed in this audit.",
    ])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def run(results_path=RESULTS_PATH, audit_path=AUDIT_PATH, report_path=REPORT_PATH):
    results = json.loads(Path(results_path).read_text(encoding="utf-8"))
    cases = [audit_case(case) for case in results["cases"]]
    valid_page_cases = [case for case in cases if case.get("expected_physical_page_ranges_0_based")]
    failures = [case for case in cases if case.get("failure_reason")]
    summary = {
        "total_cases": len(cases),
        "valid_page_gold_cases": len(valid_page_cases),
        "document_hit": metric(cases, "document_hit"),
        "section_hit": metric(cases, "section_hit"),
        "normalized_physical_page_hit": metric(valid_page_cases, "normalized_physical_page_hit"),
        "strict_hit": metric(cases, "strict_hit"),
        "page_label_hit": metric(cases, "page_label_hit"),
        "evidence_completeness": results["summary"].get("evidence_completeness", 0.0),
        "page_reference_rate": results["summary"].get("page_reference_rate", 0.0),
        "vector_count": results["summary"].get("vector_count"),
    }
    audit = {
        "timestamp": datetime.now().isoformat(),
        "results_file": str(Path(results_path).relative_to(ROOT)),
        "system_page_basis": "MinerU page_idx, 0-based physical PDF page index",
        "manual_page_basis_conclusion": "Manual ranges were standardized as printed_page_label with verified mapping to 0-based physical pages.",
        "source_annotation_files": source_annotation_summary(),
        "summary": summary,
        "by_annotator": grouped(cases, "annotator"),
        "by_document": grouped(cases, "expected_document"),
        "by_category": grouped(cases, "category"),
        "failure_reason_counts": dict(Counter(case["failure_reason"] for case in failures)),
        "remaining_failed_cases": failures,
        "cases": cases,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(audit, report_path)
    return audit


def main():
    parser = argparse.ArgumentParser(description="Audit page grounding for manual benchmark results.")
    parser.add_argument("--results-path", type=Path, default=RESULTS_PATH)
    parser.add_argument("--audit-path", type=Path, default=AUDIT_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    results_path = args.results_path if args.results_path.is_absolute() else ROOT / args.results_path
    audit_path = args.audit_path if args.audit_path.is_absolute() else ROOT / args.audit_path
    report_path = args.report_path if args.report_path.is_absolute() else ROOT / args.report_path
    audit = run(results_path, audit_path, report_path)
    print(f"Page grounding audit complete: {audit['summary']['total_cases']} cases")
    print(f"Audit JSON: {audit_path}")
    print(f"Audit report: {report_path}")


if __name__ == "__main__":
    main()
