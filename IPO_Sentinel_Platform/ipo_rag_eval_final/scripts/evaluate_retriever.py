#!/usr/bin/env python3
"""Evaluate the current layered retriever with external risk queries."""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.embedding import EmbeddingConfig, EmbeddingEngine
from src.evidence import EvidenceStore
from src.retriever import LayeredRetriever, RetrieverConfig
from src.vector import VectorStore


QUERIES_PATH = ROOT / "evaluation" / "queries" / "queries.json"
RESULTS_PATH = ROOT / "evaluation" / "results" / "results.json"
REPORT_PATH = ROOT / "docs" / "rag" / "RETRIEVER_EVALUATION_REPORT.md"
VECTOR_DIR = ROOT / "data" / "vectors"
EVIDENCE_DIR = ROOT / "data" / "evidence"

CATEGORY_LAYERS = {
    "financial_risk": "financial",
    "business_risk": "market",
    "ownership_risk": "governance",
    "compliance_risk": "legal",
    "ipo_specific_risk": "all",
}


def keyword_hits(text: str, keywords: Iterable[str]) -> List[str]:
    return [keyword for keyword in keywords if keyword and keyword in text]


def evaluate_query(
    retriever: LayeredRetriever,
    evidence_store: EvidenceStore,
    query: Dict,
    top_k: int,
) -> Dict:
    layer = CATEGORY_LAYERS.get(query["category"], "all")
    start = time.time()
    results = retriever.search(query["question"], layer=layer, top_k=top_k)
    elapsed = time.time() - start

    rows = []
    all_hits = set()
    topk_hit = False
    complete_evidence_count = 0
    page_reference_count = 0

    for rank, result in enumerate(results, 1):
        evidences = evidence_store.get_many(result.document_id, result.evidence_ids)
        evidence_text = " ".join(e.get("text", "") for e in evidences)
        combined_text = f"{result.text or ''} {evidence_text}"
        hits = keyword_hits(combined_text, query["keywords"])
        all_hits.update(hits)

        has_complete_evidence = bool(result.evidence_ids) and len(evidences) == len(result.evidence_ids)
        has_page_reference = bool(result.pages) or any(e.get("page") for e in evidences)
        topk_hit = topk_hit or bool(hits)
        complete_evidence_count += int(has_complete_evidence)
        page_reference_count += int(has_page_reference)

        rows.append({
            "rank": rank,
            "chunk_id": result.chunk_id,
            "document_id": result.document_id,
            "company": result.company,
            "pages": result.pages,
            "section_path": result.section_path,
            "block_type": result.block_type,
            "score": result.score,
            "keyword_hits": hits,
            "evidence_ids": result.evidence_ids,
            "evidence_complete": has_complete_evidence,
            "page_reference_exists": has_page_reference,
            "preview": (result.text or "")[:180],
        })

    count = len(results)
    keyword_count = len(query["keywords"])
    return {
        "id": query["id"],
        "category": query["category"],
        "layer": layer,
        "question": query["question"],
        "keywords": query["keywords"],
        "top_k": top_k,
        "result_count": count,
        "elapsed_seconds": round(elapsed, 4),
        "topk_hit": topk_hit,
        "keyword_coverage": round(len(all_hits) / keyword_count, 4) if keyword_count else 0.0,
        "evidence_completeness": round(complete_evidence_count / count, 4) if count else 0.0,
        "page_reference_rate": round(page_reference_count / count, 4) if count else 0.0,
        "results": rows,
    }


def summarize(cases: List[Dict], vector_stats: Dict) -> Dict:
    total = len(cases)
    failed = [case for case in cases if not case["topk_hit"]]
    return {
        "total_queries": total,
        "topk_hit_rate": round(sum(c["topk_hit"] for c in cases) / total, 4) if total else 0.0,
        "avg_keyword_coverage": round(sum(c["keyword_coverage"] for c in cases) / total, 4) if total else 0.0,
        "avg_evidence_completeness": round(sum(c["evidence_completeness"] for c in cases) / total, 4) if total else 0.0,
        "avg_page_reference_rate": round(sum(c["page_reference_rate"] for c in cases) / total, 4) if total else 0.0,
        "failed_case_count": len(failed),
        "vector_count": vector_stats.get("total_vectors", 0),
    }


def write_report(report: Dict) -> None:
    summary = report["summary"]
    lines = [
        "# Retriever 评估报告",
        "",
        f"> 生成时间：{report['timestamp']}",
        "",
        "## 评估摘要",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 测试问题数 | {summary['total_queries']} |",
        f"| TopK 命中率 | {summary['topk_hit_rate']:.2%} |",
        f"| 平均关键词覆盖率 | {summary['avg_keyword_coverage']:.2%} |",
        f"| 平均 Evidence 完整率 | {summary['avg_evidence_completeness']:.2%} |",
        f"| 平均页码引用率 | {summary['avg_page_reference_rate']:.2%} |",
        f"| 失败案例数 | {summary['failed_case_count']} |",
        f"| 向量数量 | {summary['vector_count']} |",
        "",
        "## 当前效果",
        "",
        "当前 Retriever 可以为完整风险测试集返回带 Evidence 和页码引用的 chunks。"
        "本报告只评估检索质量，不评估未来 Risk Agent 的最终回答质量。",
        "",
        "## 失败案例",
        "",
    ]

    failed_cases = [case for case in report["cases"] if not case["topk_hit"]]
    if not failed_cases:
        lines.append("- 本次没有 TopK 关键词命中失败案例。")
    else:
        for case in failed_cases:
            lines.append(
                f"- `{case['id']}` {case['question']} "
                f"(category={case['category']}, layer={case['layer']}, results={case['result_count']})"
            )

    lines.extend([
        "",
        "## 分问题指标",
        "",
        "| ID | 分类 | 检索层 | TopK 命中 | 关键词覆盖率 | Evidence 完整率 | 页码引用率 |",
        "|---|---|---|---:|---:|---:|---:|",
    ])
    for case in report["cases"]:
        lines.append(
            f"| `{case['id']}` | {case['category']} | {case['layer']} | "
            f"{case['topk_hit']} | {case['keyword_coverage']:.2%} | "
            f"{case['evidence_completeness']:.2%} | {case['page_reference_rate']:.2%} |"
        )

    lines.extend([
        "",
        "## 后续优化建议",
        "",
        "- 为每个问题补充人工标注的预期文档和页码，再用标注集评估 recall。",
        "- 对关键词覆盖率低的宽泛风险问题拆分子问题。",
        "- 优先改进财务比率、现金流、负债相关表格 chunk 的描述质量。",
        "- 只有当人工标注显示稳定失败模式后，再考虑加入轻量 rerank。",
    ])

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Retriever on risk queries.")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    engine = EmbeddingEngine(EmbeddingConfig())
    store = VectorStore(str(VECTOR_DIR), dimension=engine.dimension)
    retriever = LayeredRetriever(store, engine, RetrieverConfig())
    evidence_store = EvidenceStore(str(EVIDENCE_DIR))

    cases = [evaluate_query(retriever, evidence_store, query, args.top_k) for query in queries]
    vector_stats = store.get_stats()
    report = {
        "timestamp": datetime.now().isoformat(),
        "top_k": args.top_k,
        "vector_stats": vector_stats,
        "summary": summarize(cases, vector_stats),
        "cases": cases,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(report)

    summary = report["summary"]
    print("Retriever evaluation complete")
    print(f"Queries: {summary['total_queries']}")
    print(f"TopK hit rate: {summary['topk_hit_rate']:.2%}")
    print(f"Average keyword coverage: {summary['avg_keyword_coverage']:.2%}")
    print(f"Average evidence completeness: {summary['avg_evidence_completeness']:.2%}")
    print(f"Average page reference rate: {summary['avg_page_reference_rate']:.2%}")
    print(f"JSON: {RESULTS_PATH}")
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
