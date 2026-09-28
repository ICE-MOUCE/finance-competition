from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


ROOT = Path(__file__).resolve().parents[1]

ANNOTATION_FILES = [
    ROOT / "team_work" / "teamer_ex" / "PDF证据标注模板-谭思怡.txt",
    ROOT / "team_work" / "teamer_ex" / "PDF证据标注模板-陈慧.txt",
]
MANUAL_GOLD_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1.json"
ROUTING_RESULTS_PATH = ROOT / "evaluation" / "benchmark" / "manual_gold_v1_company_routing_results.json"
ORIGINAL_EXTRACTS_PATH = ROOT / "evaluation" / "benchmark" / "manual_annotation_original_extracts.json"
AUDIT_JSON_PATH = ROOT / "evaluation" / "benchmark" / "human_annotation_retrieval_audit.json"
AUDIT_REPORT_PATH = ROOT / "docs" / "rag" / "HUMAN_ANNOTATION_RETRIEVAL_AUDIT.md"

ORIGINAL_CASE_IDS = [
    "manual_ts_yideng_bus_001",
    "manual_ts_yideng_bus_002",
    "manual_ts_yideng_fin_001",
    "manual_ts_yideng_ipo_001",
    "manual_ch_duodian_bus_001",
]

ANNOTATION_ID_TO_GOLD_ID = {
    "cat_bus_new_001": "manual_ts_yideng_bus_001",
    "cat_bus_new_002": "manual_ts_yideng_bus_002",
    "cat_fin_new_001": "manual_ts_yideng_fin_001",
    "cat_ipo_new_001": "manual_ts_yideng_ipo_001",
    "待编号": "manual_ch_duodian_bus_001",
}

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
        "商": "商",
        "採": "采",
        "購": "购",
        "總": "总",
        "額": "额",
        "收": "收",
        "益": "益",
        "佔": "占",
        "價": "价",
        "淨": "净",
        "擴": "扩",
        "研": "研",
        "發": "发",
        "雲": "云",
        "務": "务",
        "現": "现",
        "壓": "压",
        "為": "为",
        "負": "负",
        "險": "险",
        "與": "与",
        "單": "单",
        "賴": "赖",
        "約": "约",
        "顯": "显",
        "計": "计",
        "劃": "划",
        "資": "资",
        "金": "金",
        "業": "业",
        "擬": "拟",
        "辦": "办",
        "處": "处",
        "強": "强",
        "項": "项",
        "萬": "万",
        "幣": "币",
        "風": "风",
        "險": "险",
        "們": "们",
        "國": "国",
        "號": "号",
        "會": "会",
        "標": "标",
        "誌": "志",
        "稱": "称",
        "過": "过",
        "錄": "录",
        "間": "间",
        "來": "来",
        "續": "续",
    }
)

ALIASES = {
    "客户A": ["客户A", "客戶A", "客户a", "客戶a"],
    "供应商A": ["供应商A", "供應商A", "供應商A", "供应商a", "供應商a"],
    "关联方": ["关联方", "關聯方"],
    "物美集团": ["物美集团", "物美集團"],
    "独立客户": ["独立客户", "獨立客戶"],
    "总收益": ["总收益", "總收益", "收益"],
    "美国禁令": ["美国禁令", "美國禁令", "限制"],
    "采购总额": ["采购总额", "採購總額", "采购总额"],
    "框架协议": ["框架协议", "框架協議"],
    "经营活动": ["经营活动", "經營活動", "營運活動"],
    "现金流量净额": ["现金流量净额", "現金流量淨額", "现金流量"],
    "所得款项净额": ["所得款项净额", "所得款項淨額", "所得款项"],
    "云服务": ["云服务", "雲服務"],
    "收入百分比": ["收入百分比", "收入占比", "收入佔比"],
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").translate(TRAD_TO_SIMP)).lower()


def parse_page_ranges(value: str) -> List[List[int]]:
    ranges: List[List[int]] = []
    for start, end in re.findall(r"\[\s*(\d+)\s*,\s*(\d+)\s*\]", value or ""):
        ranges.append([int(start), int(end)])
    return ranges


def parse_keywords(value: str) -> List[str]:
    return [item.strip() for item in re.split(r"[、,，]", value or "") if item.strip()]


def extract_numbers(text: str) -> List[str]:
    numbers = re.findall(r"\d+(?:\.\d+)?%|\d+(?:,\d{3})*(?:\.\d+)?(?:百万|百萬|万元|萬元|亿元|億元)", text or "")
    return sorted(set(numbers), key=numbers.index)


def core_terms(keywords: Sequence[str], excerpt: str) -> List[str]:
    terms: List[str] = []
    for keyword in keywords:
        if keyword and keyword not in terms:
            terms.append(keyword)
    for entity in ["客户A", "供应商A", "关联方", "物美集团", "独立客户", "美国禁令"]:
        if normalize_text(entity) in normalize_text(excerpt) and entity not in terms:
            terms.append(entity)
    for number in extract_numbers(excerpt):
        if number not in terms:
            terms.append(number)
    return terms


def term_variants(term: str) -> Set[str]:
    variants = {term}
    variants.update(ALIASES.get(term, []))
    variants.update(ALIASES.get(term.translate(TRAD_TO_SIMP), []))
    return {normalize_text(item) for item in variants if item}


def matched_terms(terms: Sequence[str], text: str) -> List[str]:
    normalized = normalize_text(text)
    found: List[str] = []
    for term in terms:
        if any(variant and variant in normalized for variant in term_variants(term)):
            found.append(term)
    return found


def fragment_hit(terms: Sequence[str], text: str) -> Dict[str, Any]:
    found = matched_terms(terms, text)
    denominator = len(terms)
    coverage = len(found) / denominator if denominator else 0.0
    numeric_terms = [term for term in terms if re.search(r"\d", term)]
    entity_terms = [term for term in terms if not re.search(r"\d", term)]
    numeric_hit = not numeric_terms or any(term in found for term in numeric_terms)
    entity_hit = not entity_terms or any(term in found for term in entity_terms)
    hit = coverage >= 0.5 and numeric_hit and entity_hit
    return {
        "hit": hit,
        "coverage": coverage,
        "matched_terms": found,
        "missing_terms": [term for term in terms if term not in found],
    }


def parse_annotation_file(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig")
    annotator = ""
    records: List[Dict[str, Any]] = []
    blocks = re.split(r"\n(?=##\s+\d+\.|\n题目编号：)", text)
    for block in blocks:
        if "题目编号：" not in block or "原文摘录：" not in block:
            continue
        local_annotator = re.search(r"填写人：(.+)", block)
        if local_annotator:
            annotator = local_annotator.group(1).strip()
        question_id = re.search(r"题目编号：(.+)", block).group(1).strip()
        excerpt_match = re.search(r"原文摘录：(.+?)(?:\n为什么这是最佳证据：|\n不确定点：|\n建议标注状态：|\Z)", block, re.S)
        record = {
            "source_file": str(path.relative_to(ROOT)),
            "annotation_question_id": question_id,
            "gold_case_id": ANNOTATION_ID_TO_GOLD_ID.get(question_id),
            "annotator": annotator,
            "company_name": field(block, "公司名称"),
            "question": field(block, "问题"),
            "best_section": field(block, "最佳证据所在章节"),
            "best_page_ranges": parse_page_ranges(field(block, "最佳证据页码")),
            "is_table_evidence": field(block, "是否表格证据"),
            "keywords": parse_keywords(field(block, "证据关键词")),
            "original_excerpt": excerpt_match.group(1).strip() if excerpt_match else "",
            "label_status": field(block, "建议标注状态"),
        }
        record["core_terms"] = core_terms(record["keywords"], record["original_excerpt"])
        records.append(record)
    return records


def field(block: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}：(.+)$", block, re.M)
    return match.group(1).strip() if match else ""


def overlap(ranges: Sequence[Sequence[int]], values: Iterable[int]) -> bool:
    value_set = {int(value) for value in values if value is not None}
    for item in ranges or []:
        if not item:
            continue
        start, end = sorted((int(item[0]), int(item[-1])))
        if value_set.intersection(range(start, end + 1)):
            return True
    return False


def rank_hit(results: Sequence[Dict[str, Any]], terms: Sequence[str], top_k: int) -> Dict[str, Any]:
    combined_text = " ".join(result.get("preview") or "" for result in results[:top_k])
    check = fragment_hit(terms, combined_text)
    first_rank = None
    for result in results[:top_k]:
        if fragment_hit(terms, result.get("preview") or "")["hit"]:
            first_rank = result.get("rank")
            break
    return {**check, "rank": first_rank}


def failure_reason(document_hit: bool, page_hit: bool, top5_hit: bool, keyword_coverage: float) -> str:
    if top5_hit:
        return "hit"
    if not document_hit:
        return "wrong_document"
    if page_hit:
        return "page_hit_fragment_miss"
    if keyword_coverage == 0:
        return "keyword_miss"
    return "fragment_miss"


def build_audit() -> Dict[str, Any]:
    extracts: List[Dict[str, Any]] = []
    for path in ANNOTATION_FILES:
        extracts.extend(parse_annotation_file(path))

    gold_by_id = {case["id"]: case for case in read_json(MANUAL_GOLD_PATH)}
    result_cases = {case["id"]: case for case in read_json(ROUTING_RESULTS_PATH).get("cases", [])}

    audit_cases: List[Dict[str, Any]] = []
    summary = {
        "total_original_human_cases": 0,
        "top1_core_fact_hits": 0,
        "top3_core_fact_hits": 0,
        "top5_core_fact_hits": 0,
        "document_hits": 0,
        "physical_page_hits": 0,
        "pdf_page_label_hits": 0,
        "page_hit_fragment_miss": 0,
    }

    for extract in extracts:
        case_id = extract.get("gold_case_id")
        if case_id not in ORIGINAL_CASE_IDS:
            continue
        gold = gold_by_id.get(case_id, {})
        result_case = result_cases.get(case_id, {})
        results = result_case.get("results", [])
        expected_docs = set(gold.get("expected_document_ids") or [])
        returned_docs = {result.get("document_id") for result in results}
        document_hit = bool(expected_docs.intersection(returned_docs))
        physical_page_hit = overlap(gold.get("expected_physical_page_ranges_0_based") or [], (p for r in results for p in r.get("pages", [])))
        page_label_hit = overlap(gold.get("expected_page_labels") or [], (p for r in results for p in r.get("page_labels", [])))
        top1 = rank_hit(results, extract["core_terms"], 1)
        top3 = rank_hit(results, extract["core_terms"], 3)
        top5 = rank_hit(results, extract["core_terms"], 5)

        case_audit = {
            "case_id": case_id,
            "annotation_question_id": extract["annotation_question_id"],
            "annotator": extract["annotator"],
            "company_name": extract["company_name"],
            "question": extract["question"],
            "manual_original_excerpt": extract["original_excerpt"],
            "pdf_review_excerpt": gold.get("expected_evidence_text", ""),
            "expected_document_ids": gold.get("expected_document_ids", []),
            "expected_page_labels": gold.get("expected_page_labels", []),
            "expected_physical_page_ranges_0_based": gold.get("expected_physical_page_ranges_0_based", []),
            "manual_keywords": extract["keywords"],
            "core_terms": extract["core_terms"],
            "document_hit": document_hit,
            "physical_page_hit": physical_page_hit,
            "pdf_page_label_hit": page_label_hit,
            "top1_core_fact_hit": top1["hit"],
            "top3_core_fact_hit": top3["hit"],
            "top5_core_fact_hit": top5["hit"],
            "top1_core_fact": top1,
            "top3_core_fact": top3,
            "top5_core_fact": top5,
            "failure_reason": failure_reason(document_hit, physical_page_hit or page_label_hit, top5["hit"], top5["coverage"]),
            "system_top5": [
                {
                    "rank": result.get("rank"),
                    "document_id": result.get("document_id"),
                    "company": result.get("company"),
                    "pages": result.get("pages", []),
                    "page_labels": result.get("page_labels", []),
                    "section_path": result.get("section_path", []),
                    "block_type": result.get("block_type"),
                    "score": result.get("score"),
                    "chunk_id": result.get("chunk_id"),
                    "preview": result.get("preview", ""),
                    "core_fact_check": fragment_hit(extract["core_terms"], result.get("preview") or ""),
                }
                for result in results[:5]
            ],
        }
        audit_cases.append(case_audit)
        summary["total_original_human_cases"] += 1
        summary["document_hits"] += int(document_hit)
        summary["physical_page_hits"] += int(physical_page_hit)
        summary["pdf_page_label_hits"] += int(page_label_hit)
        summary["top1_core_fact_hits"] += int(top1["hit"])
        summary["top3_core_fact_hits"] += int(top3["hit"])
        summary["top5_core_fact_hits"] += int(top5["hit"])
        summary["page_hit_fragment_miss"] += int((physical_page_hit or page_label_hit) and not top5["hit"])

    for key in [
        "document_hits",
        "physical_page_hits",
        "pdf_page_label_hits",
        "top1_core_fact_hits",
        "top3_core_fact_hits",
        "top5_core_fact_hits",
    ]:
        denom = summary["total_original_human_cases"]
        summary[f"{key}_rate"] = summary[key] / denom if denom else 0.0

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source_annotation_files": [str(path.relative_to(ROOT)) for path in ANNOTATION_FILES],
        "summary": summary,
        "cases": audit_cases,
        "method": {
            "scope": "Only the original 5 teamer_ex human annotation cases are audited.",
            "core_fact_rule": "A TopK hit requires >=50% normalized core-term coverage and at least one entity term plus one numeric term when such terms exist; page hit alone is diagnostic only.",
            "normalization": "Small built-in traditional/simplified normalization and aliases for 客户A/客戶A, 供应商A/供應商A, 关联方/關聯方, 物美集团/物美集團.",
        },
    }


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def render_report(audit: Dict[str, Any]) -> str:
    summary = audit["summary"]
    total = summary["total_original_human_cases"]
    lines = [
        "# Human Annotation Retrieval Audit",
        "",
        "## Scope",
        "",
        "- 只审计 `team_work/teamer_ex/` 两份 txt 中的原始人工标注 5 条。",
        "- 不纳入 Codex 后续补充的 20 条 Manual Gold V1。",
        "- 页码命中只作为诊断项；正式判断增加人工核心事实片段命中。",
        "",
        "## Metrics",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Total original human cases | {total} |",
        f"| Document hit | {summary['document_hits']}/{total} ({pct(summary['document_hits_rate'])}) |",
        f"| Normalized physical page hit | {summary['physical_page_hits']}/{total} ({pct(summary['physical_page_hits_rate'])}) |",
        f"| PDF page-label hit | {summary['pdf_page_label_hits']}/{total} ({pct(summary['pdf_page_label_hits_rate'])}) |",
        f"| Top1 core fact hit | {summary['top1_core_fact_hits']}/{total} ({pct(summary['top1_core_fact_hits_rate'])}) |",
        f"| Top3 core fact hit | {summary['top3_core_fact_hits']}/{total} ({pct(summary['top3_core_fact_hits_rate'])}) |",
        f"| Top5 core fact hit | {summary['top5_core_fact_hits']}/{total} ({pct(summary['top5_core_fact_hits_rate'])}) |",
        f"| Page hit but fragment miss | {summary['page_hit_fragment_miss']}/{total} |",
        "",
        "## Case Audit",
        "",
    ]
    for case in audit["cases"]:
        lines.extend(
            [
                f"### {case['case_id']}",
                "",
                f"- 问题：{case['question']}",
                f"- 人工原文摘录：{case['manual_original_excerpt']}",
                f"- 正确公司：{'命中' if case['document_hit'] else '未命中'}",
                f"- 页码：physical={'命中' if case['physical_page_hit'] else '未命中'}; label={'命中' if case['pdf_page_label_hit'] else '未命中'}",
                f"- 核心事实：Top1={'命中' if case['top1_core_fact_hit'] else '未命中'}; Top3={'命中' if case['top3_core_fact_hit'] else '未命中'}; Top5={'命中' if case['top5_core_fact_hit'] else '未命中'}",
                f"- 失败原因：{case['failure_reason']}",
                "",
                "| Rank | Pages | Page labels | Section | Core fact | Preview |",
                "|---:|---|---|---|---|---|",
            ]
        )
        for result in case["system_top5"]:
            check = result["core_fact_check"]
            preview = (result["preview"] or "").replace("\n", " ")[:120]
            lines.append(
                f"| {result['rank']} | {result['pages']} | {result['page_labels']} | "
                f"{' > '.join(result['section_path']) if result['section_path'] else '-'} | "
                f"{'hit' if check['hit'] else 'miss'} ({pct(check['coverage'])}) | {preview} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    extracts: List[Dict[str, Any]] = []
    for path in ANNOTATION_FILES:
        extracts.extend(parse_annotation_file(path))
    write_json(ORIGINAL_EXTRACTS_PATH, extracts)

    audit = build_audit()
    write_json(AUDIT_JSON_PATH, audit)
    AUDIT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_REPORT_PATH.write_text(render_report(audit), encoding="utf-8")
    print(f"wrote {ORIGINAL_EXTRACTS_PATH}")
    print(f"wrote {AUDIT_JSON_PATH}")
    print(f"wrote {AUDIT_REPORT_PATH}")
    print(json.dumps(audit["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
