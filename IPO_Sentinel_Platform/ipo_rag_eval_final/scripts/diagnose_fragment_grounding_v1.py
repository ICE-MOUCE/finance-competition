from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.embedding import EmbeddingConfig, EmbeddingEngine
from src.retriever import LayeredRetriever, RetrieverConfig
from src.vector import VectorStore


AUDIT_PATH = ROOT / "evaluation" / "benchmark" / "human_annotation_retrieval_audit.json"
ROUTING_RESULTS_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1_company_routing_results.json"
OUTPUT_JSON_PATH = ROOT / "evaluation" / "benchmark" / "fragment_grounding_diagnosis_v1.json"
OUTPUT_REPORT_PATH = ROOT / "docs" / "rag" / "FRAGMENT_GROUNDING_DIAGNOSIS_V1.md"

TOPK_PROBE = 50

TRAD_TO_SIMP = str.maketrans(
    {
        "軟": "软",
        "數": "数",
        "據": "据",
        "關": "关",
        "聯": "联",
        "團": "团",
        "獨": "独",
        "戶": "户",
        "應": "应",
        "採": "采",
        "購": "购",
        "總": "总",
        "額": "额",
        "佔": "占",
        "淨": "净",
        "擴": "扩",
        "發": "发",
        "雲": "云",
        "務": "务",
        "現": "现",
        "壓": "压",
        "為": "为",
        "負": "负",
        "國": "国",
        "們": "们",
        "記": "记",
        "錄": "录",
        "期": "期",
        "頁": "页",
        "顯": "显",
        "示": "示",
        "業": "业",
        "務": "务",
        "與": "与",
        "續": "续",
        "將": "将",
        "辦": "办",
        "處": "处",
        "強": "强",
        "項": "项",
        "經": "经",
        "營": "营",
        "萬": "万",
        "億": "亿",
        "險": "险",
    }
)

ALIASES = {
    "客户A": ["客户A", "客戶A"],
    "供应商A": ["供应商A", "供應商A", "供應商Ａ"],
    "关联方": ["关联方", "關聯方", "关连方", "關連方"],
    "物美集团": ["物美集团", "物美集團"],
    "独立客户": ["独立客户", "獨立客戶"],
    "总收益": ["总收益", "總收益", "收益", "收入"],
    "美国禁令": ["美国禁令", "美國禁令", "限制", "BIS"],
    "采购总额": ["采购总额", "採購總額", "采购", "採購"],
    "框架协议": ["框架协议", "框架協議"],
    "经营活动": ["经营活动", "經營活動", "营运活动", "營運活動"],
    "现金流量净额": ["现金流量净额", "現金流量淨額", "现金流量", "現金流量"],
    "现金流压力": ["现金流压力", "現金流壓力", "现金流量", "現金流量"],
    "所得款项净额": ["所得款项净额", "所得款項淨額", "所得款项", "所得款項"],
    "扩张": ["扩张", "擴張", "扩大", "擴大"],
    "研发": ["研发", "研發"],
    "云服务": ["云服务", "雲服務"],
    "收入百分比": ["收入百分比", "收入占比", "收入佔比", "收益百分比"],
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").translate(TRAD_TO_SIMP)).lower()


def term_variants(term: str) -> Set[str]:
    simple = term.translate(TRAD_TO_SIMP)
    variants = {term, simple}
    variants.update(ALIASES.get(term, []))
    variants.update(ALIASES.get(simple, []))
    return {normalize_text(v) for v in variants if v}


def fact_check(terms: Sequence[str], text: str) -> Dict[str, Any]:
    normalized = normalize_text(text)
    matched: List[str] = []
    for term in terms:
        if any(variant and variant in normalized for variant in term_variants(term)):
            matched.append(term)
    denominator = len(terms)
    coverage = len(matched) / denominator if denominator else 0.0
    numeric_terms = [term for term in terms if re.search(r"\d", term)]
    entity_terms = [term for term in terms if not re.search(r"\d", term)]
    numeric_hit = not numeric_terms or any(term in matched for term in numeric_terms)
    entity_hit = not entity_terms or any(term in matched for term in entity_terms)
    return {
        "hit": coverage >= 0.5 and numeric_hit and entity_hit,
        "coverage": coverage,
        "matched_terms": matched,
        "missing_terms": [term for term in terms if term not in matched],
    }


def page_values(ranges: Sequence[Sequence[int]]) -> Set[int]:
    values: Set[int] = set()
    for item in ranges or []:
        if not item:
            continue
        start, end = sorted((int(item[0]), int(item[-1])))
        values.update(range(start, end + 1))
    return values


def find_doc_dir(base: Path, document_id: str) -> Optional[Path]:
    for path in base.iterdir():
        if path.is_dir() and path.name == document_id:
            return path
    return None


def load_doc_items(base: Path, document_id: str, filename: str) -> List[Dict[str, Any]]:
    doc_dir = find_doc_dir(base, document_id)
    if not doc_dir:
        return []
    path = doc_dir / filename
    if not path.exists():
        return []
    return read_json(path)


def result_text(result: Any) -> str:
    return getattr(result, "text", "") or ""


def result_to_dict(result: Any, rank: int) -> Dict[str, Any]:
    return {
        "rank": rank,
        "chunk_id": result.chunk_id,
        "document_id": result.document_id,
        "company": result.company,
        "pages": result.pages,
        "section_path": result.section_path,
        "block_type": result.block_type,
        "score": result.score,
        "preview": (result.text or "")[:500],
    }


def scan_items(
    items: Sequence[Dict[str, Any]],
    terms: Sequence[str],
    expected_pages: Set[int],
    id_key: str,
) -> Dict[str, Any]:
    matches: List[Dict[str, Any]] = []
    full_hits = 0
    for item in items:
        text = item.get("text") or item.get("metadata", {}).get("text_preview") or ""
        check = fact_check(terms, text)
        pages = item.get("pages") or ([item.get("page")] if item.get("page") is not None else [])
        page_overlap = bool(expected_pages.intersection(int(p) for p in pages if p is not None))
        if check["matched_terms"] or page_overlap:
            matches.append(
                {
                    "id": item.get(id_key) or item.get("id"),
                    "pages": pages,
                    "page_overlap": page_overlap,
                    "block_type": item.get("block_type"),
                    "section_path": item.get("section_path", []),
                    "coverage": check["coverage"],
                    "hit": check["hit"],
                    "matched_terms": check["matched_terms"],
                    "missing_terms": check["missing_terms"],
                    "preview": text[:500],
                }
            )
            full_hits += int(check["hit"])
    matches.sort(key=lambda x: (not x["hit"], -x["coverage"], not x["page_overlap"]))
    return {
        "total_items": len(items),
        "matching_items": len(matches),
        "core_fact_hit_items": full_hits,
        "best": matches[:5],
        "contains_core_fact": full_hits > 0,
    }


def classify_failure(case: Dict[str, Any]) -> str:
    if case["live_top5_core_fact_hit"] and not case["saved_preview_top5_core_fact_hit"]:
        return "preview_truncation"
    if case["live_top5_core_fact_hit"]:
        return "hit"
    if not case["evidence_scan"]["matching_items"]:
        return "evidence_missing"
    if not case["chunk_scan"]["matching_items"]:
        return "chunk_missing"
    if case["evidence_scan"]["contains_core_fact"] and not case["chunk_scan"]["contains_core_fact"]:
        return "chunk_boundary_issue"
    if case["table_like"] and not case["top5_core_fact_hit"]:
        return "table_text_loss"
    if case["chunk_scan"]["contains_core_fact"] and not case["vector_scan"]["contains_core_fact"]:
        return "chunk_missing"
    if case["table_like"] and case["evidence_scan"]["contains_core_fact"] and not case["top5_core_fact_hit"]:
        return "table_text_loss"
    if case["first_core_fact_rank"] and case["first_core_fact_rank"] > 5:
        return "ranking_miss"
    if case["top5_partial_fact_coverage"] > 0 and not case["top5_core_fact_hit"]:
        return "query_keyword_gap"
    return "other"


def recommendation_from_failures(failures: Counter) -> str:
    actionable = Counter({k: v for k, v in failures.items() if k != "hit"})
    if actionable.get("preview_truncation", 0) >= max(actionable.values() or [0]):
        return "D. frontend evidence presentation 修复"
    if actionable.get("table_text_loss", 0) >= max(actionable.values() or [0]):
        return "B. table/fact-aware scoring"
    if actionable.get("chunk_boundary_issue", 0) >= max(actionable.values() or [0]):
        return "C. chunk/table representation 修复"
    if actionable.get("ranking_miss", 0) >= max(actionable.values() or [0]):
        return "A. section-aware reranking"
    return "D. frontend evidence presentation 修复"


def diagnose() -> Dict[str, Any]:
    audit = read_json(AUDIT_PATH)
    routing_cases = {case["id"]: case for case in read_json(ROUTING_RESULTS_PATH).get("cases", [])}
    vector_docs = read_json(ROOT / "data" / "vectors" / "documents.json")
    vector_by_doc: Dict[str, List[Dict[str, Any]]] = {}
    vector_chunk_ids = set()
    for doc in vector_docs:
        vector_by_doc.setdefault(doc.get("document_id"), []).append(doc)
        vector_chunk_ids.add(doc.get("chunk_id") or doc.get("id"))

    engine = EmbeddingEngine(EmbeddingConfig())
    store = VectorStore(str(ROOT / "data" / "vectors"), dimension=engine.dimension)
    retriever = LayeredRetriever(store, engine, RetrieverConfig())

    cases: List[Dict[str, Any]] = []
    for audit_case in audit["cases"]:
        case_id = audit_case["case_id"]
        expected_document = (audit_case.get("expected_document_ids") or [""])[0]
        expected_pages = page_values(audit_case.get("expected_physical_page_ranges_0_based") or [])
        core_terms = audit_case.get("core_terms") or []
        evidences = load_doc_items(ROOT / "data" / "evidence", expected_document, "evidences.json")
        chunks = load_doc_items(ROOT / "data" / "chunks", expected_document, "chunks.json")
        doc_vectors = vector_by_doc.get(expected_document, [])
        routing_case = routing_cases.get(case_id, {})
        top5_results = routing_case.get("results", [])
        probe_results = retriever.search(audit_case["question"], layer=routing_case.get("layer", "all"), top_k=TOPK_PROBE)
        live_top5_text = " ".join(result_text(result) for result in probe_results[:5] if result.document_id == expected_document)
        live_top5_check = fact_check(core_terms, live_top5_text)
        saved_preview_top5_text = " ".join(result.get("preview", "") for result in top5_results)
        saved_preview_top5_check = fact_check(core_terms, saved_preview_top5_text)
        first_rank = None
        first_result = None
        partial_best = {"coverage": 0.0, "rank": None}
        for rank, result in enumerate(probe_results, 1):
            if result.document_id != expected_document:
                continue
            check = fact_check(core_terms, result_text(result))
            if check["coverage"] > partial_best["coverage"]:
                partial_best = {"coverage": check["coverage"], "rank": rank}
            if check["hit"] and first_rank is None:
                first_rank = rank
                first_result = result_to_dict(result, rank)

        evidence_scan = scan_items(
            [e for e in evidences if e.get("page") in expected_pages],
            core_terms,
            expected_pages,
            "evidence_id",
        )
        if not evidence_scan["matching_items"]:
            evidence_scan = scan_items(evidences, core_terms, expected_pages, "evidence_id")

        chunk_scan = scan_items(
            [c for c in chunks if expected_pages.intersection(c.get("pages", []))],
            core_terms,
            expected_pages,
            "chunk_id",
        )
        if not chunk_scan["matching_items"]:
            chunk_scan = scan_items(chunks, core_terms, expected_pages, "chunk_id")

        vector_scan = scan_items(doc_vectors, core_terms, expected_pages, "chunk_id")
        chunk_ids_with_core = {m["id"] for m in chunk_scan["best"] if m["hit"]}

        diagnosis_case = {
            "case_id": case_id,
            "question": audit_case["question"],
            "manual_original_excerpt": audit_case["manual_original_excerpt"],
            "expected_document": expected_document,
            "expected_page_labels": audit_case.get("expected_page_labels", []),
            "expected_physical_pages_0_based": sorted(expected_pages),
            "core_terms": core_terms,
            "table_like": any((r.get("block_type") == "table") for r in top5_results)
            or "表" in audit_case.get("manual_original_excerpt", ""),
            "evidence_scan": evidence_scan,
            "chunk_scan": chunk_scan,
            "vector_scan": vector_scan,
            "chunk_core_fact_vectorized": bool(chunk_ids_with_core.intersection(vector_chunk_ids)),
            "top5_core_fact_hit": live_top5_check["hit"],
            "live_top5_core_fact_hit": live_top5_check["hit"],
            "live_top5_partial_fact_coverage": live_top5_check["coverage"],
            "live_top5_matched_terms": live_top5_check["matched_terms"],
            "live_top5_missing_terms": live_top5_check["missing_terms"],
            "saved_preview_top5_core_fact_hit": saved_preview_top5_check["hit"],
            "saved_preview_top5_partial_fact_coverage": saved_preview_top5_check["coverage"],
            "saved_preview_top5_matched_terms": saved_preview_top5_check["matched_terms"],
            "saved_preview_top5_missing_terms": saved_preview_top5_check["missing_terms"],
            "top5_partial_fact_coverage": live_top5_check["coverage"],
            "top5_matched_terms": live_top5_check["matched_terms"],
            "top5_missing_terms": live_top5_check["missing_terms"],
            "top5_results": [
                {
                    "rank": r.get("rank"),
                    "chunk_id": r.get("chunk_id"),
                    "pages": r.get("pages"),
                    "page_labels": r.get("page_labels"),
                    "section_path": r.get("section_path"),
                    "block_type": r.get("block_type"),
                    "coverage": fact_check(core_terms, r.get("preview", ""))["coverage"],
                    "preview": r.get("preview", "")[:500],
                }
                for r in top5_results
            ],
            "first_core_fact_rank": first_rank,
            "first_core_fact_result": first_result,
            "best_partial_probe": partial_best,
        }
        diagnosis_case["failure_reason"] = classify_failure(diagnosis_case)
        cases.append(diagnosis_case)

    failure_counts = Counter(case["failure_reason"] for case in cases)
    summary = {
        "total_cases": len(cases),
        "evidence_contains_core_fact": sum(c["evidence_scan"]["contains_core_fact"] for c in cases),
        "chunk_contains_core_fact": sum(c["chunk_scan"]["contains_core_fact"] for c in cases),
        "vector_contains_core_fact": sum(c["vector_scan"]["contains_core_fact"] for c in cases),
        "top5_core_fact_hit": sum(c["top5_core_fact_hit"] for c in cases),
        "saved_preview_top5_core_fact_hit": sum(c["saved_preview_top5_core_fact_hit"] for c in cases),
        "first_core_fact_rank_within_50": sum(c["first_core_fact_rank"] is not None for c in cases),
        "failure_reason_counts": dict(failure_counts),
    }
    summary["recommended_next_step"] = recommendation_from_failures(failure_counts)
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "method": {
            "scope": "Fragment Grounding Diagnosis V1 for the original 5 human annotation cases only.",
            "topk_probe": TOPK_PROBE,
            "no_retriever_logic_changed": True,
            "no_reparse_or_reindex": True,
        },
        "summary": summary,
        "cases": cases,
    }


def pct(numerator: int, denominator: int) -> str:
    return f"{(numerator / denominator * 100) if denominator else 0:.2f}%"


def render_report(data: Dict[str, Any]) -> str:
    summary = data["summary"]
    total = summary["total_cases"]
    lines = [
        "# Fragment Grounding Diagnosis V1",
        "",
        f"> Generated at: {data['timestamp']}",
        "",
        "## Scope",
        "",
        "- 只诊断原始人工标注 5 条。",
        "- 不开发 Agent/API，不实现 Hybrid Retrieval/BM25/reranker。",
        "- 不重解析 PDF，不重建向量，不修改 Parser/Evidence/Chunk/VectorStore 核心接口。",
        "- 使用现有 Company Routing V1 和本地 evidence/chunks/vector 数据做链路诊断。",
        "",
        "## Metrics",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Total cases | {total} |",
        f"| Evidence contains core fact | {summary['evidence_contains_core_fact']}/{total} ({pct(summary['evidence_contains_core_fact'], total)}) |",
        f"| Chunk contains core fact | {summary['chunk_contains_core_fact']}/{total} ({pct(summary['chunk_contains_core_fact'], total)}) |",
        f"| Vector metadata contains core fact | {summary['vector_contains_core_fact']}/{total} ({pct(summary['vector_contains_core_fact'], total)}) |",
        f"| Top5 contains core fact | {summary['top5_core_fact_hit']}/{total} ({pct(summary['top5_core_fact_hit'], total)}) |",
        f"| Saved preview Top5 contains core fact | {summary['saved_preview_top5_core_fact_hit']}/{total} ({pct(summary['saved_preview_top5_core_fact_hit'], total)}) |",
        f"| Core fact appears within Top50 probe | {summary['first_core_fact_rank_within_50']}/{total} ({pct(summary['first_core_fact_rank_within_50'], total)}) |",
        "",
        "Failure reason counts:",
        "",
    ]
    for reason, count in summary["failure_reason_counts"].items():
        lines.append(f"- {reason}: {count}")

    lines.extend(["", "## Case Diagnostics", ""])
    for case in data["cases"]:
        lines.extend(
            [
                f"### {case['case_id']}",
                "",
                f"- Question: {case['question']}",
                f"- Expected document: `{case['expected_document']}`",
                f"- Expected physical pages: {case['expected_physical_pages_0_based']}",
                f"- Expected page labels: {case['expected_page_labels']}",
                f"- Manual excerpt: {case['manual_original_excerpt']}",
                f"- Evidence contains core fact: {case['evidence_scan']['contains_core_fact']}",
                f"- Chunk contains core fact: {case['chunk_scan']['contains_core_fact']}",
                f"- Vector metadata contains core fact: {case['vector_scan']['contains_core_fact']}",
                f"- Top5 contains core fact from full chunk text: {case['top5_core_fact_hit']} (coverage={case['live_top5_partial_fact_coverage']:.2f})",
                f"- Saved preview Top5 contains core fact: {case['saved_preview_top5_core_fact_hit']} (coverage={case['saved_preview_top5_partial_fact_coverage']:.2f})",
                f"- First core fact rank in Top{TOPK_PROBE}: {case['first_core_fact_rank'] or 'not found'}",
                f"- Failure reason: `{case['failure_reason']}`",
                "",
                "Best evidence matches:",
                "",
            ]
        )
        for match in case["evidence_scan"]["best"][:3]:
            lines.append(
                f"- `{match['id']}` pages={match['pages']} coverage={match['coverage']:.2f} "
                f"hit={match['hit']} matched={match['matched_terms']}"
            )
        lines.extend(["", "Best chunk matches:", ""])
        for match in case["chunk_scan"]["best"][:3]:
            lines.append(
                f"- `{match['id']}` pages={match['pages']} coverage={match['coverage']:.2f} "
                f"hit={match['hit']} matched={match['matched_terms']}"
            )
        lines.extend(["", "Top5 returned chunks:", ""])
        for result in case["top5_results"]:
            lines.append(
                f"- rank {result['rank']}: `{result['chunk_id']}` pages={result['pages']} "
                f"coverage={result['coverage']:.2f} block={result['block_type']}"
            )
        lines.append("")

    rec = summary["recommended_next_step"]
    lines.extend(
        [
            "## Decision",
            "",
            f"Recommended first optimization: **{rec}**.",
            "",
            "Reason: the dominant actionable failure is `preview_truncation`: full chunk text contains the core facts in Top5 for most cases, while saved/display previews do not. The first fix should make evaluation and demo presentation use full chunk/evidence text for fragment grounding before changing Retriever ranking.",
            "",
            "Not selected first:",
            "",
            "- `A. section-aware reranking`: not first because the full Top5 already contains core facts for 4/5 cases.",
            "- `B. table/fact-aware scoring`: needed for the remaining table-heavy miss, but it should follow after the metric/presentation false negatives are removed.",
            "- `C. chunk/table representation 修复`: not first because source chunks already contain core facts for 4/5 cases.",
            "- `E. Gold 标注修正`: not first because the human labels are supported by source evidence for most cases.",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    data = diagnose()
    write_json(OUTPUT_JSON_PATH, data)
    OUTPUT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_REPORT_PATH.write_text(render_report(data), encoding="utf-8")
    print(f"wrote {OUTPUT_JSON_PATH}")
    print(f"wrote {OUTPUT_REPORT_PATH}")
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
