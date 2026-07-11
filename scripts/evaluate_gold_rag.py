#!/usr/bin/env python3
"""Evaluate Retriever against manually labeled gold risk evidence."""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from opencc import OpenCC

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.embedding import EmbeddingConfig, EmbeddingEngine
from src.retriever import LayeredRetriever, RetrieverConfig
from src.vector import VectorStore


GOLD_PATH = ROOT / "evaluation" / "gold" / "gold_risk_annotations.json"
RESULTS_PATH = ROOT / "evaluation" / "results" / "gold_rag_results.json"
REPORT_PATH = ROOT / "docs" / "rag" / "RAG_GOLD_VALIDATION_REPORT.md"
RISK_EXTRACTION_THRESHOLD = 0.75
RISK_TERM_HINTS = [
    "COVID-19", "最大客户", "五大客户", "客户集中度", "最大供应商", "五大供应商", "供应商集中度",
    "收入占比", "采购占比", "项目初期", "净现金流出", "现金流错配", "现金流消耗", "客户付款",
    "经营活动", "现金流出", "诉讼", "租赁纠纷", "赔偿", "上诉", "牌照", "资格", "注册", "合规",
    "亏损", "收益减少", "毛利率", "毛利", "资产负债比率", "银行借款", "租赁负债",
    "非经常性项目", "项目数量", "服务需求下降", "经营", "财务表现", "履约保证", "质押",
    "现金存款", "流动资金", "新项目", "延后", "客户付款能力", "应收款", "可收回性",
    "劳工短缺", "业务中断", "项目延误", "供应商", "分包商", "延误", "无法提供", "材料",
    "产品", "劳工", "服务", "违约", "工程变更令", "数量", "时间", "收益", "下降",
    "成本无法收回", "合约资产", "入账", "全额收回", "实际时间", "成本", "超支",
    "利润低于预期", "不履约", "表现不达标", "延期履约", "服务质量下降", "材料短缺",
    "延误交付", "材料缺陷", "无法按时完成", "保险", "覆盖", "潜在风险", "损失",
    "未充分投保", "未投保",
]
RISK_TERM_STOPWORDS = {
    "可能", "导致", "存在", "公司", "本集团", "影响", "风险", "以及", "及", "或", "和", "与",
    "并", "从而", "未来", "当前", "现有", "所有", "潜在", "主要", "成为", "造成", "不利",
}
RISK_TERM_ALIASES = {
    "客户集中度": ["五大客户应占收益", "最大客户应占收益", "占总收益"],
    "收入占比": ["收益占比", "收益比例", "收入比例", "应占收益", "占总收益", "收益合共"],
    "供应商集中度": ["五大供应商应占采购额", "最大供应商应占采购额", "占总采购额"],
    "采购占比": ["采购额占比", "采购比例", "采购额比例", "应占采购额", "占总采购额", "采购额合共"],
    "现金流消耗": ["现金流出", "现金流量流出", "经营活动所用现金"],
    "服务需求下降": ["需求下降", "服务需求减少"],
    "客户付款能力": ["客户付款"],
    "可收回性": ["可收回", "收回"],
    "业务中断": ["中断"],
    "项目延误": ["工程延误", "项目延期", "延误"],
    "成本无法收回": ["无法收回", "成本收回"],
    "全额收回": ["收回"],
    "利润低于预期": ["利润低", "低于预期"],
    "服务质量下降": ["服务质量", "质量下降"],
    "材料缺陷": ["有缺陷材料", "缺陷材料"],
    "无法按时完成": ["无法按时", "按时完成"],
}
OPENCC_T2S = OpenCC("t2s")


def flatten_evidence_ids(results) -> List[str]:
    ids = []
    for result in results:
        ids.extend(result.evidence_ids)
    return ids


def flatten_pages(results) -> List[int]:
    pages = []
    for result in results:
        pages.extend(result.pages)
    return pages


def normalize_metric_text(text: str) -> str:
    return re.sub(r"\s+", "", OPENCC_T2S.convert(str(text))).lower()


def extract_expected_risk_keywords(risk_element: str) -> List[str]:
    normalized = normalize_metric_text(risk_element)
    keywords = [term for term in RISK_TERM_HINTS if normalize_metric_text(term) in normalized]
    if keywords:
        return list(dict.fromkeys(keywords))

    rough_terms = re.split(r"[，。；、：,.；;（）()]+|可能|导致|存在|以及|从而|并|或|及|和|与|会|而", risk_element)
    for term in rough_terms:
        cleaned = normalize_metric_text(term)
        if len(cleaned) >= 3 and cleaned not in RISK_TERM_STOPWORDS:
            keywords.append(cleaned)
    return list(dict.fromkeys(keywords))


def evaluate_risk_extraction(case: Dict, results) -> Dict:
    expected_keywords = extract_expected_risk_keywords(case.get("risk_element", ""))
    returned_text = normalize_metric_text(" ".join(getattr(result, "text", "") or "" for result in results))
    matched_keywords = [
        keyword for keyword in expected_keywords
        if keyword_matches_text(keyword, returned_text)
    ]
    coverage = len(matched_keywords) / len(expected_keywords) if expected_keywords else 0.0
    return {
        "risk_element_hit": coverage >= RISK_EXTRACTION_THRESHOLD,
        "keyword_coverage": round(coverage, 4),
        "expected_keywords": expected_keywords,
        "matched_keywords": matched_keywords,
        "threshold": RISK_EXTRACTION_THRESHOLD,
    }


def keyword_matches_text(keyword: str, normalized_text: str) -> bool:
    candidates = [keyword, *RISK_TERM_ALIASES.get(keyword, [])]
    return any(normalize_metric_text(candidate) in normalized_text for candidate in candidates)


def evaluate_case(retriever: LayeredRetriever, case: Dict, top_k: int) -> Dict:
    start = time.perf_counter()
    metadata_filters = {
        "document_id": case["document_id"],
        "company": case["company"],
        "year": case["document_id"].split("_", 1)[0],
    }
    results = retriever.search(
        case["query"],
        layer=case["layer"],
        top_k=top_k,
        metadata_filters=metadata_filters,
    )
    elapsed = time.perf_counter() - start

    got_evidence_ids = flatten_evidence_ids(results)
    got_pages = flatten_pages(results)
    expected_ids = set(case["expected_evidence_ids"])
    expected_pages = set(case["expected_pages"])

    exact_hit = bool(expected_ids.intersection(got_evidence_ids))
    page_hit = bool(expected_pages.intersection(got_pages))
    extraction = evaluate_risk_extraction(case, results)

    return {
        "id": case["id"],
        "risk_type": case["risk_type"],
        "query": case["query"],
        "layer": case["layer"],
        "metadata_filters": metadata_filters,
        "top_k": top_k,
        "elapsed_seconds": round(elapsed, 4),
        "exact_evidence_hit": exact_hit,
        "page_hit": page_hit,
        "expected_evidence_ids": case["expected_evidence_ids"],
        "expected_pages": case["expected_pages"],
        "returned_evidence_ids": got_evidence_ids,
        "returned_pages": got_pages,
        "returned_chunks": [r.chunk_id for r in results],
        "risk_element_hit": extraction["risk_element_hit"],
        "risk_keyword_coverage": extraction["keyword_coverage"],
        "expected_risk_keywords": extraction["expected_keywords"],
        "matched_risk_keywords": extraction["matched_keywords"],
        "risk_extraction_threshold": extraction["threshold"],
    }


def summarize(rows: List[Dict]) -> Dict:
    total = len(rows)
    return {
        "total_cases": total,
        "exact_evidence_recall": round(sum(r["exact_evidence_hit"] for r in rows) / total, 4) if total else 0.0,
        "page_recall": round(sum(r["page_hit"] for r in rows) / total, 4) if total else 0.0,
        "failed_exact_cases": [r["id"] for r in rows if not r["exact_evidence_hit"]],
    }


def summarize_risk_extraction(rows: List[Dict]) -> Dict:
    total = len(rows)
    hits = sum(row.get("risk_element_hit", False) for row in rows)
    avg_coverage = sum(row.get("risk_keyword_coverage", 0.0) for row in rows) / total if total else 0.0
    return {
        "total_cases": total,
        "accuracy": round(hits / total, 4) if total else 0.0,
        "hits": hits,
        "threshold": RISK_EXTRACTION_THRESHOLD,
        "average_keyword_coverage": round(avg_coverage, 4),
        "failed_cases": [row["id"] for row in rows if not row.get("risk_element_hit", False)],
    }


def build_ui_summary(report: Dict) -> Dict:
    gold_count = report["gold_count"]
    top5 = report["summary"]["top5"]
    top10 = report["summary"]["top10"]
    extraction = report["summary"].get("risk_extraction", {})
    top5_hits = gold_count - len(top5["failed_exact_cases"])
    top10_hits = gold_count - len(top10["failed_exact_cases"])
    return {
        "gold_count": gold_count,
        "top5_exact": f"{top5['exact_evidence_recall']:.2%}",
        "top10_exact": f"{top10['exact_evidence_recall']:.2%}",
        "top5_page": f"{top5['page_recall']:.2%}",
        "top10_page": f"{top10['page_recall']:.2%}",
        "top5_hits": f"{top5_hits}/{gold_count}",
        "top10_hits": f"{top10_hits}/{gold_count}",
        "target_met": top5["exact_evidence_recall"] >= 0.85,
        "risk_extraction_accuracy": f"{extraction.get('accuracy', 0):.2%}" if extraction else "N/A",
        "risk_extraction_target_met": extraction.get("accuracy", 0) >= 0.8 if extraction else False,
    }


def write_report(report: Dict, report_path: Path = REPORT_PATH) -> None:
    top5 = report["summary"]["top5"]
    top10 = report["summary"]["top10"]
    extraction = report["summary"]["risk_extraction"]
    companies = sorted({case.get("company", "") for case in report["gold_cases"] if case.get("company")})
    coverage = sorted({case.get("risk_type", "") for case in report["gold_cases"] if case.get("risk_type")})
    lines = [
        "# RAG Gold Validation Report",
        "",
        f"> Generated at: {report['timestamp']}",
        "",
        "## Conclusion",
        "",
        f"- Top5 exact evidence recall: {top5['exact_evidence_recall']:.2%}",
        f"- Top10 exact evidence recall: {top10['exact_evidence_recall']:.2%}",
        f"- Top5 page recall: {top5['page_recall']:.2%}",
        f"- Top10 page recall: {top10['page_recall']:.2%}",
        f"- Risk element extraction accuracy: {extraction['accuracy']:.2%}",
        f"- Risk element extraction threshold: keyword coverage >= {extraction['threshold']:.0%}",
        f"- Average risk keyword coverage: {extraction['average_keyword_coverage']:.2%}",
        "",
        "Current metrics are computed dynamically from Retriever results and the manually labeled Gold set.",
        "",
        "## Gold Set",
        "",
        f"- Gold file: `{report['gold_file']}`",
        f"- Cases: {report['gold_count']}",
        f"- Company: {', '.join(companies) if companies else '-'}",
        f"- Coverage: {', '.join(coverage) if coverage else '-'}",
        "",
        "## Case Results",
        "",
        "| ID | Risk type | Top5 exact | Top10 exact | Top5 page | Top10 page | Risk extraction | Keyword coverage |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    top5_by_id = {r["id"]: r for r in report["cases"]["top5"]}
    top10_by_id = {r["id"]: r for r in report["cases"]["top10"]}
    for case_id, row5 in top5_by_id.items():
        row10 = top10_by_id[case_id]
        lines.append(
            f"| `{case_id}` | {row5['risk_type']} | {row5['exact_evidence_hit']} | "
            f"{row10['exact_evidence_hit']} | {row5['page_hit']} | {row10['page_hit']} | "
            f"{row5['risk_element_hit']} | {row5['risk_keyword_coverage']:.2%} |"
        )

    lines.extend([
        "",
        "## Failed Top5 Exact Cases",
        "",
    ])
    for case_id in top5["failed_exact_cases"]:
        row = top5_by_id[case_id]
        lines.append(f"- `{case_id}` {row['risk_type']}: expected {row['expected_evidence_ids']}")

    if top5["exact_evidence_recall"] >= 0.85:
        interpretation = [
            "- The current Retriever meets the 85% Top5 exact evidence recall target on this gold set.",
            f"- The current rule-based risk element extraction metric is {'above' if extraction['accuracy'] >= 0.8 else 'below'} the 80% target on this gold set.",
            "- This extraction metric checks whether returned evidence contains the manually labeled risk element keywords; it is not a chat Agent score.",
        ]
    else:
        interpretation = [
            "- The current Retriever can often find the right page or nearby chunk, but Top5 exact Evidence ID recall is not stable enough for the competition threshold.",
            "- A document/company filter is needed; without it, same-risk evidence from other prospectuses can outrank the target document.",
            "- Risk element extraction should be interpreted only after evidence recall is stable, because extraction depends on returned evidence text.",
        ]

    lines.extend(["", "## Interpretation", "", *interpretation])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def run_gold_evaluation(
    gold_path: Path = GOLD_PATH,
    results_path: Path = RESULTS_PATH,
    report_path: Path = REPORT_PATH,
) -> Dict:
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    engine = EmbeddingEngine(EmbeddingConfig())
    retriever = LayeredRetriever(
        VectorStore(str(ROOT / "data" / "vectors"), dimension=engine.dimension),
        engine,
        RetrieverConfig(),
    )
    cases = {
        "top5": [evaluate_case(retriever, case, 5) for case in gold],
        "top10": [evaluate_case(retriever, case, 10) for case in gold],
    }
    report = {
        "timestamp": datetime.now().isoformat(),
        "gold_file": str(gold_path.relative_to(ROOT) if gold_path.is_relative_to(ROOT) else gold_path),
        "gold_count": len(gold),
        "gold_cases": gold,
        "summary": {
            "top5": summarize(cases["top5"]),
            "top10": summarize(cases["top10"]),
            "risk_extraction": summarize_risk_extraction(cases["top5"]),
        },
        "cases": cases,
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(report, report_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Retriever against a labeled Gold set.")
    parser.add_argument("--gold-path", type=Path, default=GOLD_PATH)
    parser.add_argument("--results-path", type=Path)
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()

    gold_path = args.gold_path if args.gold_path.is_absolute() else ROOT / args.gold_path
    result_name = gold_path.stem.replace("gold_risk_annotations", "gold_rag_results")
    results_path = args.results_path or (ROOT / "evaluation" / "results" / f"{result_name}.json")
    report_path = args.report_path or (ROOT / "docs" / "rag" / f"{result_name.upper()}_REPORT.md")
    if not results_path.is_absolute():
        results_path = ROOT / results_path
    if not report_path.is_absolute():
        report_path = ROOT / report_path

    report = run_gold_evaluation(gold_path, results_path, report_path)

    print("Gold RAG evaluation complete")
    print(f"Gold file: {report['gold_file']}")
    print(f"Gold cases: {report['gold_count']}")
    print(f"Top5 exact evidence recall: {report['summary']['top5']['exact_evidence_recall']:.2%}")
    print(f"Top10 exact evidence recall: {report['summary']['top10']['exact_evidence_recall']:.2%}")
    print(f"Risk element extraction accuracy: {report['summary']['risk_extraction']['accuracy']:.2%}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
