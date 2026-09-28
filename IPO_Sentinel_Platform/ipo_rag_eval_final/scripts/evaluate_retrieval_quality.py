#!/usr/bin/env python3
"""
Retriever 质量评估脚本

输出：
- data/vectors/retrieval_quality_report.json
- RETRIEVAL_QUALITY_REPORT.md
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, ".")

from src.embedding import EmbeddingConfig, EmbeddingEngine
from src.evidence import EvidenceStore
from src.retriever import LayeredRetriever, RetrieverConfig
from src.vector import VectorStore


VECTOR_DIR = "data/vectors"
REPORT_JSON = "data/vectors/retrieval_quality_report.json"
REPORT_MD = "RETRIEVAL_QUALITY_REPORT.md"


TEST_CASES = [
    {
        "query": "现金流风险",
        "layer": "financial",
        "keywords": ["現金流", "现金流", "流動資金", "流动资金", "營運資金", "营运资金"],
    },
    {
        "query": "流动资金压力",
        "layer": "financial",
        "keywords": ["流動資金", "流动资金", "現金", "现金", "融資", "融资"],
    },
    {
        "query": "监管合规风险",
        "layer": "legal",
        "keywords": ["監管", "监管", "合規", "合规", "牌照", "法例", "條例", "条例"],
    },
    {
        "query": "诉讼纠纷处罚",
        "layer": "legal",
        "keywords": ["訴訟", "诉讼", "糾紛", "纠纷", "處罰", "处罚", "法律"],
    },
    {
        "query": "股权稀释",
        "layer": "governance",
        "keywords": ["股份", "股權", "股权", "配發", "配发", "購股權", "购股权"],
    },
    {
        "query": "客户集中风险",
        "layer": "market",
        "keywords": ["客戶", "客户", "集中", "主要客戶", "主要客户"],
    },
]


def has_any_keyword(text: str, keywords: List[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def evaluate_case(retriever: LayeredRetriever, evidence_store: EvidenceStore, case: Dict, top_k: int) -> Dict:
    start = time.time()
    results = retriever.search(case["query"], layer=case["layer"], top_k=top_k)
    elapsed = time.time() - start

    rows = []
    keyword_hits = 0
    results_with_evidence = 0
    image_results = 0

    for rank, result in enumerate(results, 1):
        text = result.text or ""
        evidence_ids = result.evidence_ids
        evidences = evidence_store.get_many(result.document_id, evidence_ids[:3])
        evidence_text = " ".join(e.get("text", "") for e in evidences)
        combined_text = text + " " + evidence_text
        keyword_hit = has_any_keyword(combined_text, case["keywords"])

        if keyword_hit:
            keyword_hits += 1
        if evidence_ids:
            results_with_evidence += 1
        if result.block_type == "image":
            image_results += 1

        rows.append({
            "rank": rank,
            "chunk_id": result.chunk_id,
            "document_id": result.document_id,
            "company": result.company,
            "pages": result.pages,
            "section_path": result.section_path,
            "block_type": result.block_type,
            "score": result.score,
            "keyword_hit": keyword_hit,
            "evidence_count": len(evidence_ids),
            "preview": text[:160],
        })

    count = len(results)
    return {
        "query": case["query"],
        "layer": case["layer"],
        "top_k": top_k,
        "elapsed": round(elapsed, 4),
        "count": count,
        "keyword_hit_rate": round(keyword_hits / count, 4) if count else 0.0,
        "evidence_coverage": round(results_with_evidence / count, 4) if count else 0.0,
        "image_result_count": image_results,
        "avg_score": round(sum(r.score for r in results) / count, 4) if count else 0.0,
        "results": rows,
    }


def write_markdown(report: Dict) -> None:
    lines = [
        "# Retrieval Quality Report",
        "",
        f"> Generated at: {report['timestamp']}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Test cases | {report['summary']['total_cases']} |",
        f"| Average keyword hit rate | {report['summary']['avg_keyword_hit_rate']:.2%} |",
        f"| Average evidence coverage | {report['summary']['avg_evidence_coverage']:.2%} |",
        f"| Total image results | {report['summary']['total_image_results']} |",
        f"| Vector count | {report['vector_stats']['total_vectors']} |",
        "",
        "## Cases",
        "",
    ]

    for case in report["cases"]:
        lines.extend([
            f"### {case['query']} ({case['layer']})",
            "",
            f"- Keyword hit rate: {case['keyword_hit_rate']:.2%}",
            f"- Evidence coverage: {case['evidence_coverage']:.2%}",
            f"- Image results: {case['image_result_count']}",
            f"- Latency: {case['elapsed']:.4f}s",
            "",
            "| Rank | Score | Type | Pages | Keyword | Evidence | Chunk | Preview |",
            "|---:|---:|---|---|---|---:|---|---|",
        ])
        for row in case["results"]:
            preview = row["preview"].replace("|", " ").replace("\n", " ")
            pages = ",".join(str(p) for p in row["pages"])
            lines.append(
                f"| {row['rank']} | {row['score']:.4f} | {row['block_type']} | {pages} | "
                f"{row['keyword_hit']} | {row['evidence_count']} | `{row['chunk_id']}` | {preview} |"
            )
        lines.append("")

    Path(REPORT_MD).write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    top_k = 5
    engine = EmbeddingEngine(EmbeddingConfig())
    store = VectorStore(VECTOR_DIR, dimension=engine.dimension)
    retriever = LayeredRetriever(store, engine, RetrieverConfig())
    evidence_store = EvidenceStore("data/evidence")

    cases = [evaluate_case(retriever, evidence_store, case, top_k) for case in TEST_CASES]
    summary = {
        "total_cases": len(cases),
        "avg_keyword_hit_rate": round(sum(c["keyword_hit_rate"] for c in cases) / len(cases), 4),
        "avg_evidence_coverage": round(sum(c["evidence_coverage"] for c in cases) / len(cases), 4),
        "total_image_results": sum(c["image_result_count"] for c in cases),
    }
    report = {
        "timestamp": datetime.now().isoformat(),
        "vector_stats": store.get_stats(),
        "summary": summary,
        "cases": cases,
    }

    Path(REPORT_JSON).parent.mkdir(parents=True, exist_ok=True)
    Path(REPORT_JSON).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report)

    print("Retrieval quality evaluation complete")
    print(f"Cases: {summary['total_cases']}")
    print(f"Average keyword hit rate: {summary['avg_keyword_hit_rate']:.2%}")
    print(f"Average evidence coverage: {summary['avg_evidence_coverage']:.2%}")
    print(f"Total image results: {summary['total_image_results']}")
    print(f"JSON: {REPORT_JSON}")
    print(f"Markdown: {REPORT_MD}")


if __name__ == "__main__":
    main()
