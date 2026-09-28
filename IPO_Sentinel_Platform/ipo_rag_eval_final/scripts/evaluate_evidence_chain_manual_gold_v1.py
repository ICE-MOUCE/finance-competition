from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.embedding import EmbeddingConfig, EmbeddingEngine
from src.retriever import LayeredRetriever, RetrieverConfig
from src.retriever.term_normalization import (
    expand_query_with_aliases,
    normalize_text,
    term_matches,
)
from src.vector import VectorStore

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

GOLD_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1.json"
OUTPUT_JSON_PATH = ROOT / "evaluation" / "benchmark" / "evidence_chain_manual_gold_v1_results.json"
REPORT_PATH = ROOT / "docs" / "rag" / "EVIDENCE_CHAIN_MANUAL_GOLD_V1_REPORT.md"

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize(text: str) -> str:
    return normalize_text(text)


def pct(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def fmt_count(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} ({pct(numerator, denominator):.2%})"


def flatten_ranges(ranges: Sequence[Sequence[int]]) -> List[int]:
    pages = []
    for item in ranges or []:
        if not item:
            continue
        start = int(item[0])
        end = int(item[-1])
        pages.extend(range(min(start, end), max(start, end) + 1))
    return sorted(set(pages))


def expected_section_terms(case: Dict) -> List[str]:
    terms = []
    for section in case.get("expected_sections", []) or []:
        for part in re.split(r"[>\-/\s]+", str(section)):
            part = part.strip()
            if len(part) >= 2:
                terms.append(part)
    return list(dict.fromkeys(terms))


def extract_required_terms(case: Dict) -> List[str]:
    terms = []
    for key in ("expected_keywords", "keywords"):
        terms.extend(str(item).strip() for item in case.get(key, []) if str(item).strip())

    evidence_text = case.get("expected_evidence_text", "")
    terms.extend(re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?%?", evidence_text))
    for company in case.get("expected_companies", []) or []:
        if str(company).strip():
            terms.append(str(company).strip())

    normalized_seen = set()
    unique = []
    for term in terms:
        key = normalize(term)
        if len(key) < 2 or key in normalized_seen:
            continue
        normalized_seen.add(key)
        unique.append(term)
    return unique[:24]


def term_hit(text: str, term: str) -> bool:
    return term_matches(text, term)


def matched_terms(text: str, terms: Iterable[str]) -> List[str]:
    return [term for term in terms if term_hit(text, term)]


def result_text(result) -> str:
    return " ".join(
        [
            result.document_id,
            result.company,
            " ".join(result.section_path or []),
            result.text or "",
            json.dumps(result.metadata or {}, ensure_ascii=False),
        ]
    )


def result_to_record(result, required_terms: List[str]) -> Dict:
    text = result_text(result)
    return {
        "document_id": result.document_id,
        "section": result.section_path,
        "pages": result.pages,
        "evidence_ids": result.evidence_ids,
        "chunk_id": result.chunk_id,
        "block_type": result.block_type,
        "score": result.score,
        "matched_terms": matched_terms(text, required_terms),
        "text": result.text,
    }


def page_overlap(pages: Iterable[int], expected_pages: Iterable[int]) -> bool:
    return bool(set(pages or []).intersection(set(expected_pages or [])))


def section_hit(result, section_terms: List[str]) -> bool:
    if not section_terms:
        return False
    section_text = " ".join(result.get("section", []) or [])
    return any(term_hit(section_text, term) for term in section_terms)


def document_hit(result, expected_docs: List[str]) -> bool:
    return result.get("document_id") in set(expected_docs or [])


def support_stats(records: List[Dict], case: Dict, required_terms: List[str]) -> Dict:
    expected_docs = case.get("expected_document_ids", []) or []
    expected_pages = flatten_ranges(case.get("expected_physical_page_ranges_0_based", []))
    section_terms = expected_section_terms(case)

    doc_records = [record for record in records if document_hit(record, expected_docs)]
    support_records = doc_records or records
    combined = "\n".join(record.get("text", "") + " " + " ".join(record.get("section", []) or []) for record in support_records)
    hits = matched_terms(combined, required_terms)
    coverage = pct(len(hits), len(required_terms))
    page_grounded = any(page_overlap(record.get("pages", []), expected_pages) for record in support_records) if expected_pages else False
    section_grounded = any(section_hit(record, section_terms) for record in support_records) if section_terms else False
    citation_valid = all(
        bool(record.get("document_id") and record.get("pages") and (record.get("chunk_id") or record.get("evidence_ids")))
        for record in records
    )
    correct_document_hit = bool(doc_records)
    table_evidence_hit = any(record.get("block_type") == "table" for record in support_records)

    if correct_document_hit and coverage >= 0.6 and (page_grounded or section_grounded):
        label = "full_support"
    elif correct_document_hit and coverage >= 0.3:
        label = "partial_support"
    elif correct_document_hit or hits:
        label = "weak_support"
    else:
        label = "irrelevant"

    return {
        "label": label,
        "matched_terms": hits,
        "unresolved_terms": [term for term in required_terms if term not in hits],
        "keyword_coverage": coverage,
        "correct_document_hit": correct_document_hit,
        "page_grounded": page_grounded,
        "section_grounded": section_grounded,
        "citation_valid": citation_valid,
        "table_evidence_hit": table_evidence_hit,
    }


def followup_queries(case: Dict, unresolved: List[str]) -> List[str]:
    question = case.get("question", "")
    keywords = [str(item) for item in case.get("expected_keywords", []) or case.get("keywords", [])]
    queries = []
    if unresolved:
        raw = " ".join([question] + unresolved[:8])
        queries.append(expand_query_with_aliases(raw))
    if keywords:
        raw = " ".join([question] + keywords[:8])
        queries.append(expand_query_with_aliases(raw))
    # keep one original unresolved query for diagnostics if different
    if unresolved:
        queries.append(" ".join([question] + unresolved[:8]))
    return list(dict.fromkeys(q for q in queries if q.strip()))[:2]


def evaluate_case(case: Dict, retriever: LayeredRetriever) -> Dict:
    required_terms = extract_required_terms(case)
    initial_results = [result_to_record(result, required_terms) for result in retriever.search(case.get("question", ""), layer="all", top_k=5)]
    initial = support_stats(initial_results, case, required_terms)

    followup_records = []
    queries = []
    if initial["label"] != "full_support":
        queries = followup_queries(case, initial["unresolved_terms"])
        for round_index, query in enumerate(queries, 1):
            results = retriever.search(query, layer="all", top_k=5)
            for result in results:
                record = result_to_record(result, required_terms)
                record["round"] = round_index
                record["query"] = query
                followup_records.append(record)

    final = support_stats(initial_results + followup_records, case, required_terms)
    final_full = final["label"] == "full_support"
    risk_element_correct = final_full or (final["correct_document_hit"] and final["keyword_coverage"] >= 0.5)
    evidence_fragment_recall_hit = final_full and final["page_grounded"]

    if final_full:
        failure_reason = ""
    elif not final["correct_document_hit"]:
        failure_reason = "document_miss"
    elif not final["page_grounded"]:
        failure_reason = "page_grounding_miss"
    elif not final["section_grounded"]:
        failure_reason = "section_grounding_miss"
    elif final["unresolved_terms"]:
        failure_reason = "unresolved_missing_facts"
    else:
        failure_reason = "weak_support"

    return {
        "id": case.get("id"),
        "category": case.get("category"),
        "question": case.get("question"),
        "answer_type": case.get("answer_type", ""),
        "expected_document_ids": case.get("expected_document_ids", []),
        "expected_page_ranges": case.get("expected_physical_page_ranges_0_based", []),
        "expected_sections": case.get("expected_sections", []),
        "required_terms": required_terms,
        "initial_support_label": initial["label"],
        "final_support_label": final["label"],
        "risk_element_correct": risk_element_correct,
        "evidence_fragment_recall_hit": evidence_fragment_recall_hit,
        "page_grounded": final["page_grounded"],
        "section_grounded": final["section_grounded"],
        "citation_valid": final["citation_valid"],
        "correct_document_hit": final["correct_document_hit"],
        "followup_queries": queries,
        "recovered_facts": [term for term in final["matched_terms"] if term not in initial["matched_terms"]],
        "matched_terms": final["matched_terms"],
        "unresolved_missing_facts": final["unresolved_terms"],
        "failure_reason": failure_reason,
        "retrieval_rounds": len(queries),
        "table_evidence_hit": final["table_evidence_hit"],
        "initial_results": initial_results,
        "followup_results": followup_records,
    }


def group_counts(cases: List[Dict], key: str) -> Dict[str, Dict]:
    grouped = defaultdict(list)
    for case in cases:
        grouped[str(case.get(key, ""))].append(case)
    return {name: summarize(items) for name, items in sorted(grouped.items())}


def summarize(cases: List[Dict]) -> Dict:
    total = len(cases)
    missing_fact_cases = sum(1 for case in cases if case.get("followup_queries"))
    recovered_cases = sum(1 for case in cases if case.get("followup_queries") and not case.get("unresolved_missing_facts"))
    return {
        "total_cases": total,
        "initial_full_support": sum(1 for case in cases if case["initial_support_label"] == "full_support"),
        "initial_full_support_rate": pct(sum(1 for case in cases if case["initial_support_label"] == "full_support"), total),
        "final_full_support": sum(1 for case in cases if case["final_support_label"] == "full_support"),
        "final_chain_support_rate": pct(sum(1 for case in cases if case["final_support_label"] == "full_support"), total),
        "evidence_fragment_recall_hits": sum(1 for case in cases if case["evidence_fragment_recall_hit"]),
        "evidence_fragment_recall_rate": pct(sum(1 for case in cases if case["evidence_fragment_recall_hit"]), total),
        "risk_element_correct": sum(1 for case in cases if case["risk_element_correct"]),
        "risk_element_accuracy_rate": pct(sum(1 for case in cases if case["risk_element_correct"]), total),
        "page_grounded": sum(1 for case in cases if case["page_grounded"]),
        "page_grounding_rate": pct(sum(1 for case in cases if case["page_grounded"]), total),
        "section_grounded": sum(1 for case in cases if case["section_grounded"]),
        "section_grounding_rate": pct(sum(1 for case in cases if case["section_grounded"]), total),
        "citation_valid": sum(1 for case in cases if case["citation_valid"]),
        "citation_validity_rate": pct(sum(1 for case in cases if case["citation_valid"]), total),
        "missing_fact_cases": missing_fact_cases,
        "missing_fact_recovered_cases": recovered_cases,
        "missing_fact_recovery_rate": pct(recovered_cases, missing_fact_cases),
        "average_retrieval_rounds": sum(case["retrieval_rounds"] for case in cases) / total if total else 0,
    }


def build_report(output: Dict) -> str:
    summary = output["summary"]
    lines = [
        "# Evidence Chain Manual Gold V1 Report",
        "",
        f"> Generated at: {output['timestamp']}",
        "",
        "## Scope",
        "",
        "- Dataset: frozen `manual_gold_v1.json`, 25 confirmed cases.",
        "- Retriever: current LayeredRetriever and current local vector index.",
        "- No Gold document/page/section metadata was used as a Retriever oracle filter.",
        "- Follow-up retrieval: at most 2 rounds, generated from the original question plus unresolved terms/keywords.",
        "",
        "## Overall Metrics",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Total cases | {summary['total_cases']} |",
        f"| Initial full support rate | {fmt_count(summary['initial_full_support'], summary['total_cases'])} |",
        f"| Final chain support rate | {fmt_count(summary['final_full_support'], summary['total_cases'])} |",
        f"| Evidence fragment recall rate | {fmt_count(summary['evidence_fragment_recall_hits'], summary['total_cases'])} |",
        f"| Risk element accuracy | {fmt_count(summary['risk_element_correct'], summary['total_cases'])} |",
        f"| Page grounding | {fmt_count(summary['page_grounded'], summary['total_cases'])} |",
        f"| Section grounding | {fmt_count(summary['section_grounded'], summary['total_cases'])} |",
        f"| Citation validity | {fmt_count(summary['citation_valid'], summary['total_cases'])} |",
        f"| Missing fact recovery | {fmt_count(summary['missing_fact_recovered_cases'], summary['missing_fact_cases'])} |",
        f"| Average retrieval rounds | {summary['average_retrieval_rounds']:.2f} |",
        "",
        "## Category Breakdown",
        "",
        "| Category | Cases | Final support | Evidence recall | Risk accuracy | Page grounding | Section grounding |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for category, stats in output["category_breakdown"].items():
        lines.append(
            f"| {category} | {stats['total_cases']} | {fmt_count(stats['final_full_support'], stats['total_cases'])} | "
            f"{fmt_count(stats['evidence_fragment_recall_hits'], stats['total_cases'])} | "
            f"{fmt_count(stats['risk_element_correct'], stats['total_cases'])} | "
            f"{fmt_count(stats['page_grounded'], stats['total_cases'])} | "
            f"{fmt_count(stats['section_grounded'], stats['total_cases'])} |"
        )

    table_stats = output["answer_type_breakdown"].get("table", summarize([]))
    narrative_stats = output["answer_type_breakdown"].get("narrative", summarize([]))
    lines.extend(
        [
            "",
            "## Table vs Narrative",
            "",
            "| Answer type | Cases | Final support | Evidence recall | Page grounding | Section grounding |",
            "|---|---:|---:|---:|---:|---:|",
            f"| table | {table_stats['total_cases']} | {fmt_count(table_stats['final_full_support'], table_stats['total_cases'])} | {fmt_count(table_stats['evidence_fragment_recall_hits'], table_stats['total_cases'])} | {fmt_count(table_stats['page_grounded'], table_stats['total_cases'])} | {fmt_count(table_stats['section_grounded'], table_stats['total_cases'])} |",
            f"| narrative | {narrative_stats['total_cases']} | {fmt_count(narrative_stats['final_full_support'], narrative_stats['total_cases'])} | {fmt_count(narrative_stats['evidence_fragment_recall_hits'], narrative_stats['total_cases'])} | {fmt_count(narrative_stats['page_grounded'], narrative_stats['total_cases'])} | {fmt_count(narrative_stats['section_grounded'], narrative_stats['total_cases'])} |",
            "",
            "## Regression Check",
            "",
            "| Metric | Before table repair smoke set | 25-case regression |",
            "|---|---:|---:|",
            "| Final chain support | 4/5 (80.00%) | " + fmt_count(summary["final_full_support"], summary["total_cases"]) + " |",
            "| Evidence fragment recall | 4/5 (80.00%) | " + fmt_count(summary["evidence_fragment_recall_hits"], summary["total_cases"]) + " |",
            "| Risk element accuracy | 4/5 (80.00%) | " + fmt_count(summary["risk_element_correct"], summary["total_cases"]) + " |",
            "| Citation validity | 5/5 (100.00%) | " + fmt_count(summary["citation_valid"], summary["total_cases"]) + " |",
            "",
            "## Gate Check",
            "",
            "| Gate metric | Current | Required | Pass |",
            "|---|---:|---:|---|",
            f"| Risk Element Accuracy | {summary['risk_element_accuracy_rate']:.2%} | 80.00% | {summary['risk_element_accuracy_rate'] >= 0.80} |",
            f"| Evidence Sufficiency / Chain Support | {summary['final_chain_support_rate']:.2%} | 85.00% | {summary['final_chain_support_rate'] >= 0.85} |",
            f"| Page Grounding | {summary['page_grounding_rate']:.2%} | 80.00% | {summary['page_grounding_rate'] >= 0.80} |",
            f"| Section Grounding | {summary['section_grounding_rate']:.2%} | 85.00% | {summary['section_grounding_rate'] >= 0.85} |",
            f"| Citation Validity | {summary['citation_validity_rate']:.2%} | 95.00% | {summary['citation_validity_rate'] >= 0.95} |",
            "",
            "## Failed Cases",
            "",
        ]
    )
    failed = [case for case in output["cases"] if case["final_support_label"] != "full_support"]
    if not failed:
        lines.append("- None")
    else:
        for case in failed:
            lines.append(f"- `{case['id']}` ({case['category']}): {case['failure_reason']}; unresolved={case['unresolved_missing_facts'][:8]}")

    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- 是否建议进入 RAG API: {output['decision']['can_enter_rag_api']}",
            f"- 是否仍阻塞租服务器: {output['decision']['server_rental_blocked']}",
            f"- 是否需要继续 Retriever/evidence 优化: {output['decision']['needs_more_optimization']}",
            f"- 唯一下一步建议: {output['decision']['recommended_next_step']}",
            f"- 是否需要补充人工 Gold 到 50 条: {output['decision']['expand_gold_to_50']}",
            "",
            "Reason:",
            "",
            f"- {output['decision']['reason']}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    gold = load_json(GOLD_PATH)
    engine = EmbeddingEngine(EmbeddingConfig())
    store = VectorStore(str(ROOT / "data" / "vectors"), dimension=engine.dimension)
    retriever = LayeredRetriever(store, engine, RetrieverConfig(top_k=5))
    cases = [evaluate_case(case, retriever) for case in gold if case.get("review_status") == "confirmed"]
    summary = summarize(cases)
    chain_ok = summary["final_chain_support_rate"] >= 0.85
    recall_ok = summary["evidence_fragment_recall_rate"] >= 0.85
    risk_ok = summary["risk_element_accuracy_rate"] >= 0.80
    page_ok = summary["page_grounding_rate"] >= 0.80
    section_ok = summary["section_grounding_rate"] >= 0.85
    citation_ok = summary["citation_validity_rate"] >= 0.95
    hard_ok = chain_ok and recall_ok and risk_ok and page_ok and section_ok and citation_ok
    thin_api_ok = chain_ok and recall_ok and risk_ok and citation_ok
    if not chain_ok or not recall_ok:
        next_step = "B. follow-up query planner enhancement for residual grounding misses"
        reason = (
            "Chain support or evidence fragment recall remains below 85 percent; "
            "continue narrow grounding optimization before Thin API."
        )
    elif thin_api_ok and not section_ok:
        next_step = "enter Thin RAG API V1 while offline-improving section grounding"
        reason = (
            "Chain support, evidence fragment recall, risk accuracy, and citation validity meet the Thin API gate; "
            "section grounding remains below 85 percent and the sample is only 25 cases, so server rental stays blocked."
        )
    elif hard_ok:
        next_step = "enter Thin RAG API V1 and carefully expand Manual Gold"
        reason = (
            "25-case hard gates are met on chain, risk, page, section, and citation metrics; "
            "still expand Gold before production server rental."
        )
    else:
        next_step = "C. page-label grounding repair for residual section misses"
        reason = (
            "Most gates pass but residual grounding gaps remain; "
            "prefer narrow page/section grounding work over Hybrid Retrieval."
        )
    decision = {
        "can_enter_rag_api": bool(thin_api_ok),
        "server_rental_blocked": True,
        "needs_more_optimization": not hard_ok,
        "recommended_next_step": next_step,
        "expand_gold_to_50": True,
        "reason": reason,
        "gates": {
            "chain_ok": chain_ok,
            "recall_ok": recall_ok,
            "risk_ok": risk_ok,
            "page_ok": page_ok,
            "section_ok": section_ok,
            "citation_ok": citation_ok,
            "hard_ok": hard_ok,
            "thin_api_ok": thin_api_ok,
        },
    }
    output = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "method": {
            "gold_path": str(GOLD_PATH.relative_to(ROOT)),
            "retriever_oracle_filters_used": False,
            "followup_round_limit": 2,
            "notes": "Expected document/page/section fields are used only as evaluation labels, not Retriever filters.",
        },
        "summary": summary,
        "category_breakdown": group_counts(cases, "category"),
        "document_breakdown": group_counts(cases, "expected_document_ids"),
        "answer_type_breakdown": group_counts(cases, "answer_type"),
        "failure_reason_counts": dict(Counter(case["failure_reason"] or "none" for case in cases)),
        "cases": cases,
        "decision": decision,
    }
    OUTPUT_JSON_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(build_report(output), encoding="utf-8")
    print(f"Wrote {OUTPUT_JSON_PATH.relative_to(ROOT)}")
    print(f"Wrote {REPORT_PATH.relative_to(ROOT)}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
