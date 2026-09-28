#!/usr/bin/env python3
"""使用版本化 RAG Benchmark 评估当前 Retriever。"""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

from opencc import OpenCC

try:
    import fitz
except ImportError:  # PyMuPDF is only needed for optional PDF page-label diagnostics.
    fitz = None

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
PAGE_LABEL_CACHE = {}


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
        for field in ("raw_annotated_page_ranges", "expected_page_labels", "expected_physical_page_ranges_0_based"):
            if field in case and not isinstance(case[field], list):
                raise ValueError(f"{case['id']}: {field} must be a list when present")
            for page_range in case.get(field, []):
                if not isinstance(page_range, list) or len(page_range) != 2 or page_range[0] > page_range[1]:
                    raise ValueError(f"{case['id']}: invalid {field} range {page_range}")


def normalize_pages(pages: Iterable[int]) -> List[int]:
    normalized = []
    for page in pages:
        try:
            normalized.append(int(page))
        except (TypeError, ValueError):
            continue
    return normalized


def overlaps_page_ranges(pages: Iterable[int], ranges: List[List[int]]) -> bool:
    clean_pages = normalize_pages(pages)
    return any(start <= page <= end for page in clean_pages for start, end in ranges)


def shift_page_ranges(ranges: List[List[int]], offset: int) -> List[List[int]]:
    return [[start + offset, end + offset] for start, end in ranges]


def numeric_pdf_page_labels(document_id: str, pages: Iterable[int]) -> List[int]:
    if fitz is None or not document_id:
        return []

    labels = []
    for page in normalize_pages(pages):
        cache_key = (document_id, page)
        if cache_key not in PAGE_LABEL_CACHE:
            label_value = None
            document_path = EVIDENCE_DIR / document_id / "document.json"
            try:
                document = json.loads(document_path.read_text(encoding="utf-8"))
                source_file = document.get("source_file", "")
                if source_file:
                    pdf_path = Path(source_file)
                    if not pdf_path.is_absolute():
                        pdf_path = ROOT / pdf_path
                    pdf = fitz.open(str(pdf_path))
                    if 0 <= page < pdf.page_count:
                        raw_label = str(pdf[page].get_label()).strip()
                        if raw_label.isdigit():
                            label_value = int(raw_label)
                    pdf.close()
            except Exception:
                label_value = None
            PAGE_LABEL_CACHE[cache_key] = label_value
        if PAGE_LABEL_CACHE[cache_key] is not None:
            labels.append(PAGE_LABEL_CACHE[cache_key])
    return labels


def page_range_diagnostics(
    pages: Iterable[int],
    page_labels: Iterable[int],
    raw_ranges: List[List[int]],
    physical_ranges: List[List[int]] | None = None,
    label_ranges: List[List[int]] | None = None,
) -> Dict:
    physical_ranges = physical_ranges if physical_ranges is not None else raw_ranges
    label_ranges = label_ranges if label_ranges is not None else raw_ranges
    if not raw_ranges and not physical_ranges and not label_ranges:
        return {
            "strict_page_hit": None,
            "expected_minus_1_page_hit": None,
            "expected_plus_1_page_hit": None,
            "offset_page_hit": None,
            "page_label_hit": None,
            "normalized_physical_page_hit": None,
            "page_range_hit": None,
        }

    strict_hit = overlaps_page_ranges(pages, raw_ranges) if raw_ranges else None
    minus_1_hit = overlaps_page_ranges(pages, shift_page_ranges(raw_ranges, -1)) if raw_ranges else None
    plus_1_hit = overlaps_page_ranges(pages, shift_page_ranges(raw_ranges, 1)) if raw_ranges else None
    label_pages = normalize_pages(page_labels)
    label_hit = overlaps_page_ranges(label_pages, label_ranges) if label_ranges and label_pages else None
    physical_hit = overlaps_page_ranges(pages, physical_ranges) if physical_ranges else None
    return {
        "strict_page_hit": strict_hit,
        "expected_minus_1_page_hit": minus_1_hit,
        "expected_plus_1_page_hit": plus_1_hit,
        "offset_page_hit": (minus_1_hit or plus_1_hit) and not strict_hit if raw_ranges else None,
        "page_label_hit": label_hit,
        "normalized_physical_page_hit": physical_hit,
        "page_range_hit": physical_hit,
    }


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
    expected_documents = set(case["expected_document_ids"])
    documents = set()
    companies = set()
    sections = []
    diagnostic_sections = []
    diagnostic_pages = []
    diagnostic_page_labels = []
    complete_count = 0
    page_ref_count = 0
    rows = []
    for rank, result in enumerate(results, 1):
        text, complete, has_page = collect_result_text(result, evidence_store)
        result_text.append(text)
        documents.add(result.document_id)
        companies.add(normalize(result.company))
        normalized_sections = [normalize(section) for section in result.section_path]
        sections.extend(normalized_sections)
        labels = numeric_pdf_page_labels(result.document_id, result.pages)
        if not expected_documents or result.document_id in expected_documents:
            diagnostic_sections.extend(normalized_sections)
            diagnostic_pages.extend(result.pages)
            diagnostic_page_labels.extend(labels)
        complete_count += int(complete)
        page_ref_count += int(has_page)
        rows.append({
            "rank": rank,
            "chunk_id": result.chunk_id,
            "document_id": result.document_id,
            "company": result.company,
            "pages": result.pages,
            "page_labels": labels,
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
    section_pool = diagnostic_sections if expected_documents else sections
    matched_sections = [section for section in expected_sections if any(section in actual for actual in section_pool)]
    expected_companies = [normalize(company) for company in case["expected_companies"] if company]
    document_hit = bool(expected_documents.intersection(documents)) if expected_documents else None
    company_hit = any(company in companies for company in expected_companies) if expected_companies else None
    section_hit = bool(matched_sections) if expected_sections else None
    raw_page_ranges = case.get("raw_annotated_page_ranges", case["expected_page_ranges"])
    physical_page_ranges = case.get("expected_physical_page_ranges_0_based") or case["expected_page_ranges"]
    label_page_ranges = case.get("expected_page_labels") or raw_page_ranges
    page_diagnostics = page_range_diagnostics(
        diagnostic_pages,
        diagnostic_page_labels,
        raw_page_ranges,
        physical_page_ranges,
        label_page_ranges,
    )
    page_hit = page_diagnostics["page_range_hit"]
    keyword_coverage = len(matched_keywords) / len(expected_keywords) if expected_keywords else None
    confidence = rows[0]["score"] if rows else 0.0
    low_confidence = not rows or confidence < retriever.config.min_score + 0.08 or keyword_coverage == 0

    return {
        "id": case["id"],
        "category": case["category"],
        "label_status": case.get("label_status", "unspecified"),
        "annotator": case.get("annotator", "unknown"),
        "source_annotation_file": case.get("source_annotation_file"),
        "page_basis": case.get("page_basis", "unknown"),
        "page_mapping_status": case.get("page_mapping_status", "unknown"),
        "mapping_note": case.get("mapping_note", ""),
        "question": case["question"],
        "layer": layer,
        "answer_type": case["answer_type"],
        "difficulty": case["difficulty"],
        "expected_document_ids": case["expected_document_ids"],
        "expected_companies": case["expected_companies"],
        "expected_sections": case["expected_sections"],
        "expected_page_ranges": case["expected_page_ranges"],
        "raw_annotated_page_ranges": raw_page_ranges,
        "expected_page_labels": label_page_ranges,
        "expected_physical_page_ranges_0_based": physical_page_ranges,
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
        "page_evaluation_pages": sorted(set(normalize_pages(diagnostic_pages))),
        "page_evaluation_labels": sorted(set(normalize_pages(diagnostic_page_labels))),
        "strict_page_hit": page_diagnostics["strict_page_hit"],
        "normalized_physical_page_hit": page_diagnostics["normalized_physical_page_hit"],
        "expected_minus_1_page_hit": page_diagnostics["expected_minus_1_page_hit"],
        "expected_plus_1_page_hit": page_diagnostics["expected_plus_1_page_hit"],
        "offset_page_hit": page_diagnostics["offset_page_hit"],
        "page_label_hit": page_diagnostics["page_label_hit"],
        "evidence_completeness": round(complete_count / len(rows), 4) if rows else 0.0,
        "page_reference_rate": round(page_ref_count / len(rows), 4) if rows else 0.0,
        "low_confidence": low_confidence,
        "top_score": round(confidence, 4),
        "results": rows,
    }


def rate(rows: List[Dict], key: str) -> Dict:
    eligible = [row[key] for row in rows if row[key] is not None]
    return {"rate": round(sum(eligible) / len(eligible), 4) if eligible else None, "denominator": len(eligible)}


def metric_counts(rows: List[Dict], key: str) -> Dict:
    eligible = [row.get(key) for row in rows if row.get(key) is not None]
    hits = sum(1 for value in eligible if value is True)
    return {"hits": hits, "denominator": len(eligible), "rate": round(hits / len(eligible), 4) if eligible else None}


def grouped_metrics(rows: List[Dict], field: str) -> Dict:
    grouped = defaultdict(list)
    for row in rows:
        values = row.get(field)
        if isinstance(values, list):
            values = values or ["unknown"]
        else:
            values = [values or "unknown"]
        for value in values:
            grouped[str(value)].append(row)
    return {
        key: {
            "case_count": len(items),
            "document_hit": metric_counts(items, "correct_document_hit"),
            "section_hit": metric_counts(items, "expected_section_hit"),
            "normalized_physical_page_hit": metric_counts(items, "normalized_physical_page_hit"),
            "strict_page_hit": metric_counts(items, "strict_page_hit"),
            "pdf_page_label_hit": metric_counts(items, "page_label_hit"),
        }
        for key, items in sorted(grouped.items())
    }


def summarize(rows: List[Dict], vector_stats: Dict) -> Dict:
    keyword_rows = [row["expected_keyword_coverage"] for row in rows if row["expected_keyword_coverage"] is not None]
    return {
        "total_cases": len(rows),
        "correct_document_hit_rate": rate(rows, "correct_document_hit"),
        "correct_company_hit_rate": rate(rows, "correct_company_hit"),
        "expected_section_hit_rate": rate(rows, "expected_section_hit"),
        "page_range_hit_rate": rate(rows, "page_range_hit"),
        "normalized_physical_page_hit_rate": rate(rows, "normalized_physical_page_hit"),
        "strict_page_hit_rate": rate(rows, "strict_page_hit"),
        "offset_page_hit_rate": rate(rows, "offset_page_hit"),
        "page_label_hit_rate": rate(rows, "page_label_hit"),
        "expected_keyword_coverage": round(sum(keyword_rows) / len(keyword_rows), 4) if keyword_rows else None,
        "keyword_coverage_denominator": len(keyword_rows),
        "evidence_completeness": round(sum(row["evidence_completeness"] for row in rows) / len(rows), 4) if rows else 0.0,
        "page_reference_rate": round(sum(row["page_reference_rate"] for row in rows) / len(rows), 4) if rows else 0.0,
        "no_result_rate": round(sum(not row["result_count"] for row in rows) / len(rows), 4) if rows else 0.0,
        "low_confidence_cases": [row["id"] for row in rows if row["low_confidence"]],
        "failed_cases": [row["id"] for row in rows if row["correct_document_hit"] is False],
        "vector_count": vector_stats.get("total_vectors", 0),
        "label_status_counts": {status: sum(row["label_status"] == status for row in rows) for status in sorted({row["label_status"] for row in rows})},
        "valid_page_gold_cases": sum(bool(row.get("expected_physical_page_ranges_0_based")) for row in rows),
        "by_annotator": grouped_metrics(rows, "annotator"),
        "by_document": grouped_metrics(rows, "expected_document_ids"),
        "by_category": grouped_metrics(rows, "category"),
    }


def group_failures(rows: List[Dict]) -> Dict[str, List[Dict]]:
    special_categories = {"ownership_risk", "compliance_risk", "ipo_specific_risk"}
    return {
        "document_hits": [row for row in rows if row["correct_document_hit"] is True],
        "complete_misses": [row for row in rows if row["correct_document_hit"] is False],
        "document_hit_keyword_miss": [row for row in rows if row["correct_document_hit"] is True and row["expected_keyword_coverage"] == 0],
        "keyword_mismatch": [row for row in rows if row["expected_keyword_coverage"] is not None and row["expected_keyword_coverage"] < 1],
        "keyword_hit_section_miss": [row for row in rows if row["expected_keyword_coverage"] not in (None, 0) and row["expected_section_hit"] is False],
        "page_missing_or_untrusted": [row for row in rows if row["page_range_hit"] is False or (row["expected_physical_page_ranges_0_based"] and row["page_reference_rate"] == 0)],
        "table_cases": [row for row in rows if row["answer_type"] == "table"],
        "special_risk_low_coverage": [row for row in rows if row["category"] in special_categories and (row["expected_keyword_coverage"] or 0) < 0.5],
        "needs_manual_review": [row for row in rows if row["label_status"] != "gold_seed"],
    }


def metric_text(value: Dict) -> str:
    if value["rate"] is None:
        return "N/A"
    hits = int(round(value["rate"] * value["denominator"]))
    return f"{value['rate']:.2%} ({hits}/{value['denominator']})"


def write_report(report: Dict, report_path: Path = REPORT_PATH) -> None:
    summary = report["summary"]
    failures = report["failure_analysis"]
    lines = [
        "# RAG Benchmark 报告",
        "",
        f"> 生成时间：{report['timestamp']}",
        "",
        "## 评估范围",
        "",
        "本 Benchmark 评估的是检索 grounding 能力，而不是最终生成答案的准确率。`gold_seed` 表示来源标签已人工核验；`catalog_document_label` 只校验当前本地样本文档与检索术语，章节与页码仍需后续人工补标。",
        "",
        "## 总体结果",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 问题数量 | {summary['total_cases']} |",
        f"| 有有效页码 Gold 的案例数 | {summary['valid_page_gold_cases']} |",
        f"| 正确文档命中率 | {metric_text(summary['correct_document_hit_rate'])} |",
        f"| 正确公司命中率 | {metric_text(summary['correct_company_hit_rate'])} |",
        f"| 预期关键词覆盖率 | {summary['expected_keyword_coverage']:.2%} ({summary['keyword_coverage_denominator']} 条有标签) |",
        f"| 预期章节命中率 | {metric_text(summary['expected_section_hit_rate'])} |",
        f"| 标准化 0-based 物理页命中率 | {metric_text(summary['normalized_physical_page_hit_rate'])} |",
        f"| 原始页码 strict hit rate | {metric_text(summary['strict_page_hit_rate'])} |",
        f"| Offset page hit rate (+/-1 diagnostic) | {metric_text(summary['offset_page_hit_rate'])} |",
        f"| PDF page-label hit rate | {metric_text(summary['page_label_hit_rate'])} |",
        f"| Evidence 完整率 | {summary['evidence_completeness']:.2%} |",
        f"| 页码引用存在率 | {summary['page_reference_rate']:.2%} |",
        f"| 无结果占比 | {summary['no_result_rate']:.2%} |",
        f"| 低置信问题数 | {len(summary['low_confidence_cases'])} |",
        f"| 向量文档数 | {summary['vector_count']} |",
        "",
        "## 标签覆盖情况",
        "",
        *[f"- `{status}`: {count}" for status, count in summary["label_status_counts"].items()],
        "",
        "## 按标注成员统计",
        "",
        "| 标注成员 | 案例数 | 文档命中 | 章节命中 | 标准物理页命中 | PDF page-label 命中 |",
        "|---|---:|---:|---:|---:|---:|",
        *[f"| {name} | {item['case_count']} | {metric_text(item['document_hit'])} | {metric_text(item['section_hit'])} | {metric_text(item['normalized_physical_page_hit'])} | {metric_text(item['pdf_page_label_hit'])} |" for name, item in summary['by_annotator'].items()],
        "",
        "## 按文档统计",
        "",
        "| 文档 | 案例数 | 文档命中 | 章节命中 | 标准物理页命中 | PDF page-label 命中 |",
        "|---|---:|---:|---:|---:|---:|",
        *[f"| {name} | {item['case_count']} | {metric_text(item['document_hit'])} | {metric_text(item['section_hit'])} | {metric_text(item['normalized_physical_page_hit'])} | {metric_text(item['pdf_page_label_hit'])} |" for name, item in summary['by_document'].items()],
        "",
        "## 按风险类别统计",
        "",
        "| 风险类别 | 案例数 | 文档命中 | 章节命中 | 标准物理页命中 | PDF page-label 命中 |",
        "|---|---:|---:|---:|---:|---:|",
        *[f"| {name} | {item['case_count']} | {metric_text(item['document_hit'])} | {metric_text(item['section_hit'])} | {metric_text(item['normalized_physical_page_hit'])} | {metric_text(item['pdf_page_label_hit'])} |" for name, item in summary['by_category'].items()],
        "",
        "## 失败案例分析",
        "",
    ]
    labels = {
        "document_hits": "命中文档的样本",
        "complete_misses": "完全未命中文档",
        "document_hit_keyword_miss": "命中文档但未命中预期关键词",
        "keyword_mismatch": "关键词不完全匹配",
        "keyword_hit_section_miss": "命中关键词但章节明显不对",
        "page_missing_or_untrusted": "页码缺失或页码不可信",
        "table_cases": "表格类问题",
        "special_risk_low_coverage": "治理 / 合规 / IPO 特殊风险中的低覆盖问题",
        "needs_manual_review": "需要人工复核的样本",
    }
    for key, title in labels.items():
        rows = failures[key]
        lines.extend([f"### {title}", ""])
        if not rows:
            lines.append("- None")
        else:
            for row in rows:
                lines.append(f"- `{row['id']}` [{row['category']}] doc={row['correct_document_hit']} keyword={row['expected_keyword_coverage']} section={row['expected_section_hit']} normalized_page={row['normalized_physical_page_hit']} label_page={row['page_label_hit']}")
        lines.append("")

    lines.extend([
        "## 下一步决策建议",
        "",
        "- 不建议仅凭这一版结果就直接上 Hybrid Retrieval。先扩充 `gold_seed`，并为 catalog 类问题补齐章节和页码标签。",
        "- 如果扩充后的 Gold 子集显示“文档命中了，但关键词经常漏掉”，优先测试关键词过滤；如果文档和关键词都对但排序靠后，优先测试 rerank，再考虑 BM25。",
        "- 只有在人工核验后的失败案例明确显示“精确词项没有进入向量 TopK”时，BM25 才是高优先级；如果主要问题是命错章节，再考虑章节过滤。",
        "- 不建议仅根据这份 Benchmark 就直接启动 568 份 PDF 全量跑数，也不建议立刻开始做 RAG API；应以前面的生产就绪度审查门槛和整本 PDF 验收跑为准。",
        "- 表格类问题应单独复盘。如果表格覆盖持续偏低，应优先改进 table description 和 table chunk 表达，而不是先改检索架构。",
    ])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def run_benchmark(benchmark_path: Path, results_path: Path, top_k: int, report_path: Path = REPORT_PATH) -> Dict:
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
    write_report(report, report_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="评估 RAG Benchmark。")
    parser.add_argument("--benchmark-path", type=Path, default=BENCHMARK_PATH)
    parser.add_argument("--results-path", type=Path, default=RESULTS_PATH)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    benchmark_path = args.benchmark_path if args.benchmark_path.is_absolute() else ROOT / args.benchmark_path
    results_path = args.results_path if args.results_path.is_absolute() else ROOT / args.results_path
    report_path = args.report_path if args.report_path.is_absolute() else ROOT / args.report_path
    report = run_benchmark(benchmark_path, results_path, args.top_k, report_path)
    print(f"RAG Benchmark 评估完成：共 {report['summary']['total_cases']} 条问题")
    print(f"结果文件：{results_path}")
    print(f"报告文件：{report_path}")


if __name__ == "__main__":
    main()
