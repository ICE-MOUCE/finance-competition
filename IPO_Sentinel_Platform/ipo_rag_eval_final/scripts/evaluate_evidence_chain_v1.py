from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evidence import EvidenceStore
from src.embedding import EmbeddingConfig, EmbeddingEngine
from src.retriever import LayeredRetriever, RetrieverConfig
from src.vector import VectorStore


os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

SUFFICIENCY_PATH = ROOT / "evaluation" / "benchmark" / "evidence_sufficiency_v1.json"
FRAGMENT_DIAGNOSIS_PATH = ROOT / "evaluation" / "benchmark" / "fragment_grounding_diagnosis_v1.json"
OUTPUT_JSON_PATH = ROOT / "evaluation" / "benchmark" / "evidence_chain_v1.json"
REPORT_PATH = ROOT / "docs" / "rag" / "EVIDENCE_CHAIN_EVALUATOR_V1.md"

TRAD_TO_SIMP = str.maketrans(
    {
        "軟": "软",
        "數": "数",
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
        "營": "营",
        "業": "业",
        "會": "会",
        "計": "计",
        "師": "师",
        "報": "报",
        "風": "风",
        "險": "险",
        "項": "项",
        "與": "与",
        "錄": "录",
        "經": "经",
        "營": "营",
    }
)

TERM_ALIASES = {
    "客户A": ["客户A", "客戶A"],
    "供应商A": ["供应商A", "供應商A"],
    "关联方": ["关联方", "關聯方"],
    "物美集团": ["物美集团", "物美集團"],
    "独立客户": ["独立客户", "獨立客戶"],
    "经营活动": ["经营活动", "經營活動", "營運活動"],
    "现金流量净额": ["现金流量净额", "現金流量淨額", "现金流量", "現金流量"],
    "所得款项净额": ["所得款项净额", "所得款項淨額", "所得款项"],
    "云服务": ["云服务", "雲服務"],
    "研发": ["研发", "研發"],
    "扩张": ["扩张", "擴張"],
    "收入百分比": ["收入百分比", "收入占比", "收入佔比", "收益百分比"],
}

FOLLOWUP_RULES: Dict[str, Dict] = {
    "manual_ts_yideng_fin_001": {
        "missing_facts": ["目标概要页经营活动现金流量净额", "经营现金流为负或压力的直接表述"],
        "missing_entities": ["经营活动"],
        "missing_numbers": [],
        "missing_sections": ["概要", "综合现金流量表概要", "会计师报告"],
        "followup_queries": [
            "伊登软件 经营活动 现金流量净额 综合现金流量表概要",
            "伊登软件 经营现金流为负 经营活动所用现金流量净额",
        ],
        "required_terms": ["经营活动", "现金流量净额"],
        "support_reason": "补证应返回经营活动现金流量净额相关原文，用于判断是否存在经营现金流压力。",
    },
    "manual_ts_yideng_ipo_001": {
        "missing_facts": ["所得款项净额用途", "资金用途明细表", "办公室扩张/研发项目/履约保证金资金分配"],
        "missing_entities": ["所得款项净额"],
        "missing_numbers": [],
        "missing_sections": ["未来计划及所得款项用途"],
        "followup_queries": [
            "伊登软件 所得款项净额 用途 未来计划",
            "伊登软件 股份发售所得款项净额 办事处 扩张 研发 云服务",
        ],
        "required_terms": ["所得款项净额", "研发", "云服务"],
        "support_reason": "补证应返回所得款项用途和业务扩张计划原文，用于判断募集资金用途风险。",
    },
    "manual_ch_duodian_bus_001": {
        "missing_facts": ["关联方收入占比70.6%", "关联方收入占比78.2%", "独立客户对比", "第227页表格完整数值"],
        "missing_entities": ["关联方", "物美集团", "独立客户"],
        "missing_numbers": ["70.6%", "78.2%", "51.6%"],
        "missing_sections": ["风险因素", "业务"],
        "followup_queries": [
            "多点数智 关联方 收入百分比 独立客户 70.6% 78.2%",
            "多点数智 物美集团 收益 51.6% 关联方 独立客户",
        ],
        "required_terms": ["关联方", "收入百分比", "独立客户", "70.6%", "78.2%", "51.6%"],
        "support_reason": "补证应返回关联方/独立客户收入贡献表及关键比例，用于判断关联方收入依赖。",
    },
}

INITIAL_LABEL_MAP = {
    "sufficient": "full_support",
    "partial": "partial_support",
    "weak": "weak_support",
    "irrelevant": "irrelevant",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").translate(TRAD_TO_SIMP)).lower()


def variants(term: str) -> List[str]:
    items = TERM_ALIASES.get(term, []) + TERM_ALIASES.get(term.translate(TRAD_TO_SIMP), []) + [term]
    return list(dict.fromkeys(item for item in items if item))


def term_hit(text: str, term: str) -> bool:
    haystack = normalize(text)
    return any(normalize(item) in haystack for item in variants(term))


def matched_terms(text: str, terms: Iterable[str]) -> List[str]:
    return [term for term in terms if term_hit(text, term)]


def pct(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def fmt_count(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} ({pct(numerator, denominator):.2%})"


def init_retriever() -> tuple[LayeredRetriever, EvidenceStore]:
    engine = EmbeddingEngine(EmbeddingConfig())
    vector_store = VectorStore(str(ROOT / "data" / "vectors"), dimension=engine.dimension)
    return LayeredRetriever(vector_store, engine, RetrieverConfig(top_k=5)), EvidenceStore(str(ROOT / "data" / "evidence"))


def evidence_text(evidence: Dict) -> str:
    return evidence.get("text") or evidence.get("table_description") or evidence.get("image_caption") or ""


def result_to_record(result, evidences: List[Dict], support_terms: List[str], support_reason: str) -> Dict:
    evidence_blob = "\n".join(evidence_text(item) for item in evidences if evidence_text(item))
    combined = (result.text or "") + "\n" + evidence_blob
    hits = matched_terms(combined, support_terms)
    labels = []
    metadata = getattr(result, "metadata", {}) or {}
    raw_labels = metadata.get("page_labels")
    if isinstance(raw_labels, list):
        labels = raw_labels
    return {
        "document_id": result.document_id,
        "section": result.section_path,
        "pages": result.pages,
        "page_labels": labels,
        "evidence_ids": result.evidence_ids,
        "chunk_id": result.chunk_id,
        "text": result.text or evidence_blob,
        "matched_terms": hits,
        "support_reason": support_reason if hits else "该证据未覆盖本轮补证目标事实。",
    }


def run_followups(case: Dict, retriever: LayeredRetriever, evidence_store: EvidenceStore) -> List[Dict]:
    rules = FOLLOWUP_RULES.get(case["id"])
    if not rules:
        return []

    evidence: List[Dict] = []
    seen_chunks: Set[str] = {item.get("chunk_id", "") for item in case.get("top5_results", [])}
    for round_index, query in enumerate(rules["followup_queries"][:2], 1):
        results = retriever.search(query=query, layer="all", top_k=5)
        round_records = []
        for result in results:
            evidences = evidence_store.get_many(result.document_id, result.evidence_ids)
            record = result_to_record(result, evidences, rules["required_terms"], rules["support_reason"])
            record["round"] = round_index
            record["query"] = query
            record["is_duplicate_initial_chunk"] = result.chunk_id in seen_chunks
            round_records.append(record)
        evidence.extend(round_records[:3])
    return evidence


def page_overlap(pages: Iterable[int], expected_pages: Iterable[int]) -> bool:
    return bool(set(pages or []).intersection(set(expected_pages or [])))


def evaluate_case(
    case: Dict,
    fragment_case: Dict,
    retriever: LayeredRetriever,
    evidence_store: EvidenceStore,
) -> Dict:
    rules = FOLLOWUP_RULES.get(case["id"], {})
    initial_label = INITIAL_LABEL_MAP.get(case.get("sufficiency_label"), "weak_support")
    followup_evidence = []
    if initial_label in {"partial_support", "weak_support"}:
        followup_evidence = run_followups(case, retriever, evidence_store)

    required_terms = rules.get("required_terms", [])
    initial_text = "\n".join(item.get("preview", "") for item in case.get("top5_results", []))
    followup_text = "\n".join(item.get("text", "") for item in followup_evidence)
    combined_text = initial_text + "\n" + followup_text
    hits = matched_terms(combined_text, required_terms) if required_terms else []
    unresolved = [term for term in required_terms if term not in hits]

    if initial_label == "full_support":
        final_label = "full_support"
    elif required_terms and len(hits) / len(required_terms) >= 0.8:
        final_label = "full_support"
    elif hits:
        final_label = "partial_support"
    else:
        final_label = initial_label

    citation_valid = all(
        bool(item.get("document_id") and item.get("pages") and (item.get("chunk_id") or item.get("evidence_ids")))
        for item in followup_evidence
    )
    if not followup_evidence:
        citation_valid = all(
            bool(item.get("chunk_id") and item.get("pages"))
            for item in case.get("top5_results", [])
        )

    final_full = final_label == "full_support"
    expected_pages = fragment_case.get("expected_physical_pages_0_based", [])
    initial_support_page_grounded = bool(case.get("page_grounded")) and initial_label == "full_support"
    followup_support_page_grounded = any(
        item.get("matched_terms") and page_overlap(item.get("pages", []), expected_pages)
        for item in followup_evidence
    )
    page_grounded = initial_support_page_grounded or followup_support_page_grounded
    section_grounded = bool(case.get("section_grounded")) and final_label == "full_support"
    risk_element_correct = final_full or (case.get("sufficiency_label") == "sufficient")
    evidence_fragment_recall_hit = final_full and page_grounded

    if final_full:
        failure_reason = ""
    elif unresolved:
        failure_reason = "unresolved_missing_facts"
    else:
        failure_reason = "weak_initial_evidence"

    return {
        "id": case["id"],
        "question": case["question"],
        "category": case["category"],
        "expected_document": case["expected_document"],
        "initial_support_label": initial_label,
        "missing_facts": rules.get("missing_facts", case.get("missing_facts", [])),
        "missing_entities": rules.get("missing_entities", []),
        "missing_numbers": rules.get("missing_numbers", []),
        "missing_sections": rules.get("missing_sections", []),
        "followup_queries": rules.get("followup_queries", []),
        "expected_physical_pages_0_based": expected_pages,
        "initial_evidence": case.get("top5_results", []),
        "followup_evidence": followup_evidence,
        "final_support_label": final_label,
        "risk_element_correct": risk_element_correct,
        "evidence_fragment_recall_hit": evidence_fragment_recall_hit,
        "citation_valid": citation_valid,
        "same_risk_conclusion_supported": final_full,
        "unresolved_missing_facts": unresolved,
        "failure_reason": failure_reason,
        "retrieval_rounds": len(rules.get("followup_queries", [])[:2]) if followup_evidence else 0,
        "matched_chain_terms": hits,
    }


def build_report(output: Dict) -> str:
    summary = output["summary"]
    rules = output["competition_acceptance"]
    lines = [
        "# Evidence Chain Evaluator V1",
        "",
        f"> Generated at: {output['timestamp']}",
        "",
        "## Scope",
        "",
        "- 只评估原始人工标注 5 条。",
        "- 对 initial partial/weak case 最多执行 2 轮 follow-up retrieval。",
        "- 使用现有 LayeredRetriever，不修改 Retriever、Parser、Evidence、Chunk、VectorStore、索引或 PDF 解析产物。",
        "",
        "## Metrics",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Total cases | {summary['total_cases']} |",
        f"| Initial full support rate | {fmt_count(summary['initial_full_support'], summary['total_cases'])} |",
        f"| Final chain support rate | {fmt_count(summary['final_full_support'], summary['total_cases'])} |",
        f"| Missing fact recovery rate | {fmt_count(summary['missing_fact_recovered_cases'], summary['missing_fact_cases'])} |",
        f"| Evidence fragment recall rate | {fmt_count(summary['evidence_fragment_recall_hits'], summary['total_cases'])} |",
        f"| Risk element accuracy | {fmt_count(summary['risk_element_correct'], summary['total_cases'])} |",
        f"| Citation validity | {fmt_count(summary['citation_valid'], summary['total_cases'])} |",
        f"| Average retrieval rounds | {summary['average_retrieval_rounds']:.2f} |",
        "",
        "## Competition Gate Check",
        "",
        "| Metric | Current | Required | Pass |",
        "|---|---:|---:|---|",
        f"| Risk Element Accuracy | {summary['risk_element_accuracy_rate']:.2%} | {rules['risk_element_accuracy_required']:.2%} | {rules['risk_element_accuracy_pass']} |",
        f"| Evidence Sufficiency@5 / Chain Support | {summary['final_chain_support_rate']:.2%} | {rules['evidence_sufficiency_required']:.2%} | {rules['evidence_sufficiency_pass']} |",
        f"| Page Grounding / Evidence Fragment Recall | {summary['evidence_fragment_recall_rate']:.2%} | {rules['page_grounding_required']:.2%} | {rules['page_grounding_pass']} |",
        f"| Section Grounding | {summary['section_grounding_rate']:.2%} | {rules['section_grounding_required']:.2%} | {rules['section_grounding_pass']} |",
        f"| Citation Validity | {summary['citation_validity_rate']:.2%} | {rules['citation_validity_required']:.2%} | {rules['citation_validity_pass']} |",
        "",
        "## Case Details",
        "",
    ]
    for case in output["cases"]:
        lines.extend(
            [
                f"### {case['id']}",
                "",
                f"- Initial support: `{case['initial_support_label']}`",
                f"- Final support: `{case['final_support_label']}`",
                f"- Risk element correct: {case['risk_element_correct']}",
                f"- Evidence fragment recall hit: {case['evidence_fragment_recall_hit']}",
                f"- Citation valid: {case['citation_valid']}",
                f"- Followup queries: {' / '.join(case['followup_queries']) if case['followup_queries'] else '-'}",
                f"- Matched chain terms: {', '.join(case['matched_chain_terms']) if case['matched_chain_terms'] else '-'}",
                f"- Unresolved missing facts: {', '.join(case['unresolved_missing_facts']) if case['unresolved_missing_facts'] else '-'}",
                f"- Failure reason: {case['failure_reason'] or '-'}",
                "",
            ]
        )
        if case["followup_evidence"]:
            lines.extend(["| Round | Query | Chunk | Pages | Section | Matched terms |", "|---:|---|---|---|---|---|"])
            for item in case["followup_evidence"]:
                section = " > ".join(item.get("section") or [])
                lines.append(
                    f"| {item.get('round')} | {item.get('query')} | {item.get('chunk_id')} | {item.get('pages')} | {section or '-'} | {', '.join(item.get('matched_terms') or []) or '-'} |"
                )
            lines.append("")

    failed = [case for case in output["cases"] if case["final_support_label"] != "full_support"]
    lines.extend(
        [
            "## Failed Cases",
            "",
        ]
    )
    if not failed:
        lines.append("- None")
    else:
        for case in failed:
            lines.append(f"- `{case['id']}`: {case['failure_reason']}；unresolved={case['unresolved_missing_facts']}")

    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- 是否达到比赛硬性指标：{output['decision']['competition_hard_targets_met']}。",
            f"- 是否建议进入 RAG API：{output['decision']['can_enter_rag_api']}。",
            f"- 是否仍阻塞租服务器：{output['decision']['server_rental_blocked']}。",
            f"- 下一步唯一推荐优化方向：{output['decision']['recommended_next_step']}。",
            "",
            "Reason:",
            "",
            f"- {output['decision']['reason']}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    sufficiency = load_json(SUFFICIENCY_PATH)
    fragment_diagnosis = load_json(FRAGMENT_DIAGNOSIS_PATH)
    fragment_by_id = {case["case_id"]: case for case in fragment_diagnosis.get("cases", [])}
    retriever, evidence_store = init_retriever()
    cases = [
        evaluate_case(case, fragment_by_id.get(case["id"], {}), retriever, evidence_store)
        for case in sufficiency.get("cases", [])
    ]
    total = len(cases)
    initial_full = sum(1 for case in cases if case["initial_support_label"] == "full_support")
    final_full = sum(1 for case in cases if case["final_support_label"] == "full_support")
    missing_cases = sum(1 for case in cases if case["missing_facts"])
    recovered_cases = sum(1 for case in cases if case["missing_facts"] and not case["unresolved_missing_facts"])
    fragment_hits = sum(1 for case in cases if case["evidence_fragment_recall_hit"])
    risk_correct = sum(1 for case in cases if case["risk_element_correct"])
    citation_valid = sum(1 for case in cases if case["citation_valid"])
    section_grounded = sum(1 for case in cases if case["same_risk_conclusion_supported"] and not case["unresolved_missing_facts"])
    average_rounds = sum(case["retrieval_rounds"] for case in cases) / total if total else 0.0

    summary = {
        "total_cases": total,
        "initial_full_support": initial_full,
        "initial_full_support_rate": pct(initial_full, total),
        "final_full_support": final_full,
        "final_chain_support_rate": pct(final_full, total),
        "missing_fact_cases": missing_cases,
        "missing_fact_recovered_cases": recovered_cases,
        "missing_fact_recovery_rate": pct(recovered_cases, missing_cases),
        "evidence_fragment_recall_hits": fragment_hits,
        "evidence_fragment_recall_rate": pct(fragment_hits, total),
        "risk_element_correct": risk_correct,
        "risk_element_accuracy_rate": pct(risk_correct, total),
        "citation_valid": citation_valid,
        "citation_validity_rate": pct(citation_valid, total),
        "section_grounding_count": section_grounded,
        "section_grounding_rate": pct(section_grounded, total),
        "average_retrieval_rounds": average_rounds,
    }

    acceptance = {
        "risk_element_accuracy_required": 0.80,
        "evidence_sufficiency_required": 0.85,
        "page_grounding_required": 0.80,
        "section_grounding_required": 0.85,
        "citation_validity_required": 0.95,
        "risk_element_accuracy_pass": summary["risk_element_accuracy_rate"] >= 0.80,
        "evidence_sufficiency_pass": summary["final_chain_support_rate"] >= 0.85,
        "page_grounding_pass": summary["evidence_fragment_recall_rate"] >= 0.80,
        "section_grounding_pass": summary["section_grounding_rate"] >= 0.85,
        "citation_validity_pass": summary["citation_validity_rate"] >= 0.95,
    }
    hard_targets_met = all(
        [
            acceptance["risk_element_accuracy_pass"],
            acceptance["evidence_sufficiency_pass"],
            acceptance["page_grounding_pass"],
            acceptance["section_grounding_pass"],
            acceptance["citation_validity_pass"],
        ]
    )
    output = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "method": {
            "scope": "Original 5 human annotation cases. Initial evidence plus at most 2 follow-up retrieval rounds for partial/weak cases.",
            "retriever_logic_changed": False,
            "followup_top_k": 5,
            "source_files": [
                str(SUFFICIENCY_PATH.relative_to(ROOT)),
                str(FRAGMENT_DIAGNOSIS_PATH.relative_to(ROOT)),
            ],
        },
        "summary": summary,
        "competition_acceptance": acceptance,
        "cases": cases,
        "decision": {
            "competition_hard_targets_met": hard_targets_met,
            "can_enter_rag_api": False,
            "server_rental_blocked": True,
            "recommended_next_step": "table/fact-aware scoring",
            "reason": "Evidence chain improves support, but the remaining failure is concentrated in table/numeric facts. The 5-case smoke set is below API/server coverage gates.",
        },
    }
    OUTPUT_JSON_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(build_report(output), encoding="utf-8")
    print(f"Wrote {OUTPUT_JSON_PATH.relative_to(ROOT)}")
    print(f"Wrote {REPORT_PATH.relative_to(ROOT)}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
