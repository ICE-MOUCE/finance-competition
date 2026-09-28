from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
HUMAN_AUDIT_PATH = ROOT / "evaluation" / "benchmark" / "human_annotation_retrieval_audit.json"
FRAGMENT_DIAGNOSIS_PATH = ROOT / "evaluation" / "benchmark" / "fragment_grounding_diagnosis_v1.json"
ORIGINAL_EXTRACTS_PATH = ROOT / "evaluation" / "benchmark" / "manual_annotation_original_extracts.json"
OUTPUT_JSON_PATH = ROOT / "evaluation" / "benchmark" / "evidence_sufficiency_v1.json"
REPORT_PATH = ROOT / "docs" / "rag" / "EVIDENCE_SUFFICIENCY_BENCHMARK_V1.md"


SUFFICIENCY_REVIEWS: Dict[str, Dict] = {
    "manual_ts_yideng_bus_001": {
        "label": "sufficient",
        "reason": "Top5 的完整 chunk 合并后覆盖客户A依赖、收入占比和美国禁令风险，足以支持同一客户集中风险结论；人工摘录中的事实分布在不同返回 chunk 中。",
        "missing_facts": [],
        "best_rank": 2,
        "different": True,
    },
    "manual_ts_yideng_bus_002": {
        "label": "sufficient",
        "reason": "Top5 第4条完整 chunk 覆盖供应商A、采购/框架关系及41.9%、60.8%、67.0%、69.1%等关键比例，足以支持供应商依赖风险结论。",
        "missing_facts": [],
        "best_rank": 4,
        "different": False,
    },
    "manual_ts_yideng_fin_001": {
        "label": "partial",
        "reason": "Top5 返回会计师报告中的现金流相关内容，能说明存在现金流数据和变化，但未稳定落到人工标注的概要页经营活动现金流净额证据，不能完整支撑经营现金流压力判断。",
        "missing_facts": ["目标概要页经营活动现金流净额", "经营现金流为负或压力的直接表述"],
        "best_rank": None,
        "different": False,
    },
    "manual_ts_yideng_ipo_001": {
        "label": "partial",
        "reason": "Top5 返回研发、云服务、业务扩张等计划相关片段，能支持部分业务扩张合理性，但缺少所得款项净额用途明细和资金分配表，不能完整支撑募集资金用途判断。",
        "missing_facts": ["所得款项净额用途", "资金用途明细表", "办公室扩张/研发项目/履约保证金资金分配"],
        "best_rank": None,
        "different": False,
    },
    "manual_ch_duodian_bus_001": {
        "label": "partial",
        "reason": "Top5 能支持多点数智与关联方存在密切业务关系和关联方收入依赖方向，但缺少70.6%、78.2%及独立客户对比等表格核心数值，证据不足以完整支撑人工风险结论。",
        "missing_facts": ["关联方收入占比70.6%", "关联方收入占比78.2%", "独立客户对比", "第227页表格完整数值"],
        "best_rank": None,
        "different": False,
    },
}

CATEGORY_BY_CASE = {
    "manual_ts_yideng_fin_001": "financial_risk",
    "manual_ts_yideng_ipo_001": "ipo_specific_risk",
}

TRAD_TO_SIMP = str.maketrans(
    {
        "概": "概",
        "風": "风",
        "險": "险",
        "業": "业",
        "務": "务",
        "來": "来",
        "計": "计",
        "劃": "划",
        "項": "项",
        "淨": "净",
        "額": "额",
        "會": "会",
        "計": "计",
        "師": "师",
        "報": "报",
        "告": "告",
    }
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def pct(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def fmt_count(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} ({pct(numerator, denominator):.2%})"


def flat_ranges(ranges: List[List[int]]) -> List[int]:
    pages: List[int] = []
    for item in ranges or []:
        if not item:
            continue
        low, high = sorted((int(item[0]), int(item[-1])))
        pages.extend(range(low, high + 1))
    return sorted(set(pages))


def infer_category(case_id: str, original: Dict) -> str:
    if case_id in CATEGORY_BY_CASE:
        return CATEGORY_BY_CASE[case_id]
    if "_bus_" in case_id:
        return "business_risk"
    if "_own_" in case_id:
        return "ownership_risk"
    if "_compliance_" in case_id:
        return "compliance_risk"
    return "business_risk"


def normalize_heading(text: str) -> str:
    return "".join((text or "").translate(TRAD_TO_SIMP).split()).lower()


def section_hit(result: Dict, expected_section: str) -> bool:
    if not expected_section:
        return False
    expected_parts = [
        normalize_heading(part)
        for part in expected_section.replace("；", ";").replace("-", ";").split(";")
        if part.strip()
    ]
    section_text = normalize_heading(" ".join(result.get("section_path") or []))
    return any(part and (part in section_text or section_text in part) for part in expected_parts)


def build_case(
    human_case: Dict,
    diagnosis_case: Dict,
    original_case: Dict,
) -> Dict:
    case_id = human_case["case_id"]
    review = SUFFICIENCY_REVIEWS[case_id]
    top5 = diagnosis_case.get("top5_results") or human_case.get("system_top5", [])
    expected_pages = diagnosis_case.get("expected_physical_pages_0_based") or flat_ranges(
        human_case.get("expected_physical_page_ranges_0_based", [])
    )
    expected_sections = [original_case.get("best_section", "")]
    page_grounded = bool(human_case.get("physical_page_hit") or any(set(result.get("pages", [])).intersection(expected_pages) for result in top5))
    section_grounded = any(section_hit(result, expected_sections[0]) for result in top5)
    label = review["label"]

    return {
        "id": case_id,
        "question": human_case.get("question", diagnosis_case.get("question", "")),
        "category": infer_category(case_id, original_case),
        "expected_document": diagnosis_case.get("expected_document")
        or (human_case.get("expected_document_ids") or [""])[0],
        "human_annotation_excerpt": human_case.get("manual_original_excerpt", ""),
        "top5_results": [
            {
                "rank": result.get("rank"),
                "chunk_id": result.get("chunk_id"),
                "pages": result.get("pages", []),
                "page_labels": result.get("page_labels", []),
                "section_path": result.get("section_path", []),
                "block_type": result.get("block_type", ""),
                "coverage": result.get("coverage")
                if "coverage" in result
                else (result.get("core_fact_check") or {}).get("coverage"),
                "preview": result.get("preview", ""),
            }
            for result in top5
        ],
        "best_sufficient_rank": review["best_rank"],
        "sufficiency_label": label,
        "sufficiency_reason": review["reason"],
        "missing_facts": review["missing_facts"],
        "same_risk_conclusion_supported": label == "sufficient",
        "page_grounded": page_grounded,
        "section_grounded": section_grounded,
        "different_from_human_excerpt_but_sufficient": bool(review["different"]),
        "diagnostic": {
            "fragment_failure_reason": diagnosis_case.get("failure_reason"),
            "full_top5_core_fact_hit": bool(diagnosis_case.get("top5_core_fact_hit")),
            "full_top5_partial_fact_coverage": diagnosis_case.get("top5_partial_fact_coverage")
            or diagnosis_case.get("live_top5_partial_fact_coverage"),
            "saved_preview_top5_core_fact_hit": bool(diagnosis_case.get("saved_preview_top5_core_fact_hit")),
        },
    }


def build_report(output: Dict) -> str:
    summary = output["summary"]
    lines = [
        "# Evidence Sufficiency Benchmark V1",
        "",
        f"> Generated at: {output['timestamp']}",
        "",
        "## Scope",
        "",
        "- 只评估原始人工标注 5 条。",
        "- 评估对象是现有 Retriever Top5 返回证据是否足以支撑同一风险判断。",
        "- 不要求系统返回文本与人工摘录逐字一致。",
        "- 不修改 Retriever、Parser、Evidence、Chunk、VectorStore、向量索引或 PDF 解析产物。",
        "",
        "## Rubric",
        "",
        "| Label | Meaning |",
        "|---|---|",
        "| sufficient | 足以支持同一风险结论，关键实体和关键事实基本完整 |",
        "| partial | 能支持部分风险方向，但缺少关键事实、数字或表格结构 |",
        "| weak | 相关但说服力不足，不能稳定支持风险判断 |",
        "| irrelevant | 不能支持该风险判断 |",
        "",
        "## Metrics",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Total cases | {summary['total_cases']} |",
        f"| Evidence Sufficiency Top1 | {fmt_count(summary['top1_sufficient'], summary['total_cases'])} |",
        f"| Evidence Sufficiency Top3 | {fmt_count(summary['top3_sufficient'], summary['total_cases'])} |",
        f"| Evidence Sufficiency Top5 | {fmt_count(summary['top5_sufficient'], summary['total_cases'])} |",
        f"| Partial rate | {fmt_count(summary['partial_count'], summary['total_cases'])} |",
        f"| Weak / irrelevant rate | {fmt_count(summary['weak_irrelevant_count'], summary['total_cases'])} |",
        f"| Page grounded but insufficient | {summary['page_grounded_but_insufficient_count']} |",
        f"| Sufficient but different from human excerpt | {summary['sufficient_but_different_from_human_excerpt_count']} |",
        f"| Page grounded | {fmt_count(summary['page_grounded_count'], summary['total_cases'])} |",
        f"| Section grounded | {fmt_count(summary['section_grounded_count'], summary['total_cases'])} |",
        "",
        "## Case Analysis",
        "",
    ]

    for case in output["cases"]:
        lines.extend(
            [
                f"### {case['id']}",
                "",
                f"- Question: {case['question']}",
                f"- Category: `{case['category']}`",
                f"- Expected document: `{case['expected_document']}`",
                f"- Sufficiency: `{case['sufficiency_label']}`",
                f"- Best sufficient rank: {case['best_sufficient_rank'] if case['best_sufficient_rank'] is not None else '-'}",
                f"- Same risk conclusion supported: {case['same_risk_conclusion_supported']}",
                f"- Page grounded: {case['page_grounded']}",
                f"- Section grounded: {case['section_grounded']}",
                f"- Different from human excerpt but sufficient: {case['different_from_human_excerpt_but_sufficient']}",
                f"- Reason: {case['sufficiency_reason']}",
                f"- Missing facts: {', '.join(case['missing_facts']) if case['missing_facts'] else '-'}",
                "",
                "| Rank | Pages | Section | Coverage | Preview |",
                "|---:|---|---|---:|---|",
            ]
        )
        for result in case["top5_results"]:
            preview = (result.get("preview") or "").replace("\n", " ")[:220]
            section = " > ".join(result.get("section_path") or [])
            coverage = result.get("coverage")
            coverage_text = f"{coverage:.2f}" if isinstance(coverage, (int, float)) else "-"
            lines.append(
                f"| {result.get('rank')} | {result.get('pages', [])} | {section or '-'} | {coverage_text} | {preview} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Decision",
            "",
            f"- Evidence Sufficiency Top5 = {fmt_count(summary['top5_sufficient'], summary['total_cases'])}.",
            "- 是否可以进入 Retriever 优化：可以。当前失败主要是部分证据不足和表格数值缺失，适合进入下一轮小范围 Retriever/evidence 优化诊断。",
            "- 是否可以进入 RAG API：不建议。Top5 sufficiency 未达到临时门槛 80%，且样本只有 5 条。",
            "- 是否仍然阻塞租服务器：仍然阻塞。Page grounding 为 3/5 (60.00%)，低于 80%；5 条小样本也不能解除生产级决策阻塞。",
            "- 是否需要继续扩大人工 Gold 样本：需要。5 条只能作为小样本诊断，不能代表 568 份全量招股书表现。",
            "",
            "## Recommended Next Step",
            "",
            "下一步建议：扩大 Evidence Sufficiency Benchmark 到 Manual Gold V1 中已人工确认的 25 条，并保持 Retriever/index 冻结后复测。",
            "",
            "理由：当前 5 条已经足以说明 API/服务器决策不能只看文档命中和页码命中；但样本量不足以决定生产级路线。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    human_audit = load_json(HUMAN_AUDIT_PATH)
    diagnosis = load_json(FRAGMENT_DIAGNOSIS_PATH)
    originals = {item["gold_case_id"]: item for item in load_json(ORIGINAL_EXTRACTS_PATH)}
    diagnosis_by_id = {item["case_id"]: item for item in diagnosis.get("cases", [])}

    cases = [
        build_case(case, diagnosis_by_id[case["case_id"]], originals.get(case["case_id"], {}))
        for case in human_audit.get("cases", [])
        if case["case_id"] in SUFFICIENCY_REVIEWS and case["case_id"] in diagnosis_by_id
    ]

    total = len(cases)
    top1 = sum(1 for case in cases if case["best_sufficient_rank"] == 1)
    top3 = sum(1 for case in cases if case["best_sufficient_rank"] is not None and case["best_sufficient_rank"] <= 3)
    top5 = sum(1 for case in cases if case["best_sufficient_rank"] is not None and case["best_sufficient_rank"] <= 5)
    partial = sum(1 for case in cases if case["sufficiency_label"] == "partial")
    weak_irrelevant = sum(1 for case in cases if case["sufficiency_label"] in {"weak", "irrelevant"})
    page_grounded = sum(1 for case in cases if case["page_grounded"])
    section_grounded = sum(1 for case in cases if case["section_grounded"])

    output = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "method": {
            "scope": "Original 5 teamer_ex human annotation cases only.",
            "rubric": {
                "sufficient": "足以支持同一风险结论，关键实体和关键事实基本完整。",
                "partial": "能支持部分风险方向，但缺少关键事实、数字或表格结构。",
                "weak": "相关但说服力不足。",
                "irrelevant": "不能支持该风险判断。",
            },
            "no_retriever_logic_changed": True,
            "source_files": [
                str(HUMAN_AUDIT_PATH.relative_to(ROOT)),
                str(FRAGMENT_DIAGNOSIS_PATH.relative_to(ROOT)),
                str(ORIGINAL_EXTRACTS_PATH.relative_to(ROOT)),
            ],
        },
        "summary": {
            "total_cases": total,
            "top1_sufficient": top1,
            "top3_sufficient": top3,
            "top5_sufficient": top5,
            "top1_sufficient_rate": pct(top1, total),
            "top3_sufficient_rate": pct(top3, total),
            "top5_sufficient_rate": pct(top5, total),
            "partial_count": partial,
            "partial_rate": pct(partial, total),
            "weak_irrelevant_count": weak_irrelevant,
            "weak_irrelevant_rate": pct(weak_irrelevant, total),
            "page_grounded_but_insufficient_count": sum(
                1 for case in cases if case["page_grounded"] and case["sufficiency_label"] != "sufficient"
            ),
            "sufficient_but_different_from_human_excerpt_count": sum(
                1 for case in cases if case["different_from_human_excerpt_but_sufficient"]
            ),
            "page_grounded_count": page_grounded,
            "page_grounded_rate": pct(page_grounded, total),
            "section_grounded_count": section_grounded,
            "section_grounded_rate": pct(section_grounded, total),
        },
        "cases": cases,
        "decision": {
            "can_enter_retriever_optimization": True,
            "can_enter_rag_api": False,
            "server_rental_blocked": True,
            "need_more_manual_gold": True,
            "reason": "Top5 sufficiency is below 80%, page grounding is below 80%, and sample size is only 5.",
        },
    }

    OUTPUT_JSON_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(build_report(output), encoding="utf-8")
    print(f"Wrote {OUTPUT_JSON_PATH.relative_to(ROOT)}")
    print(f"Wrote {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
