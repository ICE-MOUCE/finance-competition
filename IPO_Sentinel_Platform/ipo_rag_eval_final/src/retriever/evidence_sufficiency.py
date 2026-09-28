"""Rule-based evidence sufficiency reranking for Retriever candidates."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from .models import SearchResult
from .term_normalization import infer_section_families, normalize_text, section_family_match


@dataclass(frozen=True)
class SufficiencyScore:
    intent: str
    boost: float
    generic_penalty: float
    fact_signal: float
    reason: str


GENERIC_RISK_TERMS = ("可能", "或会", "倘", "若", "无法保证", "存在风险", "不利影响")
ACTUAL_EVENT_TERMS = (
    "于往绩记录期", "往绩记录期间", "截至", "录得", "并未", "未能", "未完成",
    "未足额", "接获", "卷入", "发生", "受到", "涉及", "冻结", "申索", "诉讼",
)
LEGAL_CONSEQUENCE_TERMS = ("罚款", "处罚", "滞纳金", "追缴", "补缴", "吊销", "限制", "责任")
QUANT_TERMS = ("%", "人民币", "港元", "百万元", "亿元", "占", "总收入", "总收益", "净额")
BOILERPLATE_TERMS = ("可能会", "或会", "无法保证", "概不保证", "可能对我们的业务")
DEFINITION_TERMS = ("风险指", "合规风险指", "法律风险指", "一般而言")
FUTURE_TERMS = ("未来", "预计", "预期", "可能", "会否", "监管收紧")


def infer_sufficiency_intent(query: str) -> str:
    q = normalize_text(query)
    if any(term in q for term in ["所得款项", "募资", "募集资金", "用途"]):
        return "use_of_proceeds"
    if any(term in q for term in ["不存在重大诉讼", "并无", "概无", "无重大诉讼"]):
        return "no_litigation"
    if any(term in q for term in ["合规缺口", "未足额", "追缴", "处罚", "许可证", "牌照"]):
        if any(term in q for term in ["未来", "监管收紧", "会否"]):
            return "future_regulatory_risk"
        return "actual_admin_gap"
    if any(term in q for term in ["占比", "依赖", "集中", "客户", "供应商", "关联方"]):
        return "quant_dependency"
    if any(term in q for term in FUTURE_TERMS):
        return "future_regulatory_risk"
    return "generic_other"


def _has_any(normalized_text: str, terms: tuple[str, ...]) -> bool:
    return any(normalize_text(term) in normalized_text for term in terms)


def score_evidence_sufficiency(query: str, result: SearchResult) -> SufficiencyScore:
    text = f"{' '.join(result.section_path)} {result.text or ''}"
    ntext = normalize_text(text)
    intent = infer_sufficiency_intent(query)

    has_number = bool(re.search(r"\d", result.text or ""))
    has_actual = _has_any(ntext, ACTUAL_EVENT_TERMS)
    has_legal = _has_any(ntext, LEGAL_CONSEQUENCE_TERMS)
    has_quant = has_number and _has_any(ntext, QUANT_TERMS)
    tax_noise = any(term in ntext for term in ["企业所得税", "所得税", "增值税", "税率"])
    business_quant_context = any(term in ntext for term in ["收入", "收益", "客户", "供应商", "采购", "销售", "所得款项"])
    if tax_noise and not business_quant_context:
        has_quant = False
    if tax_noise and "无关" in ntext:
        has_quant = False
    has_generic = _has_any(ntext, GENERIC_RISK_TERMS)
    has_boilerplate = _has_any(ntext, BOILERPLATE_TERMS)
    has_definition = _has_any(ntext, DEFINITION_TERMS)
    has_hypothetical = any(term in ntext for term in ["若", "如果", "倘"])
    has_concrete_anchor = any(term in ntext for term in ["往绩记录", "截至", "并未", "未足额", "未完成", "接获", "冻结", "录得"])
    if has_hypothetical and not has_concrete_anchor:
        has_actual = False
    section_match = section_family_match(result.section_path, infer_section_families(query))

    fact_signal = 0.0
    if has_actual:
        fact_signal += 0.22
    if has_legal:
        fact_signal += 0.14
    if has_quant:
        fact_signal += 0.16
    if section_match:
        fact_signal += 0.08
    if result.block_type == "table" and has_number:
        fact_signal += 0.06

    generic_penalty = 0.0
    if has_boilerplate and not (has_actual or has_quant or has_legal):
        generic_penalty += 0.18
    if has_definition and not has_quant:
        generic_penalty += 0.22
    if has_generic and intent in {"actual_admin_gap", "no_litigation", "quant_dependency"} and not (has_actual or has_quant):
        generic_penalty += 0.10
    if intent == "future_regulatory_risk":
        generic_penalty = min(generic_penalty, 0.08)

    if intent == "actual_admin_gap" and has_actual and has_legal:
        fact_signal += 0.12
    elif intent == "quant_dependency" and has_quant:
        fact_signal += 0.10
    elif intent == "use_of_proceeds" and section_match and has_quant:
        fact_signal += 0.10
    elif intent == "no_litigation" and any(term in ntext for term in ["并无", "概无", "无尚未完结", "无任何待决"]):
        fact_signal += 0.18

    boost = max(0.0, min(fact_signal, 0.32))
    reason_bits = []
    if has_actual:
        reason_bits.append("actual_event")
    if has_legal:
        reason_bits.append("legal_consequence")
    if has_quant:
        reason_bits.append("quantitative_fact")
    if section_match:
        reason_bits.append("section_match")
    if generic_penalty:
        reason_bits.append("generic_penalty")
    return SufficiencyScore(
        intent=intent,
        boost=round(boost, 4),
        generic_penalty=round(generic_penalty, 4),
        fact_signal=round(fact_signal, 4),
        reason=",".join(reason_bits) or "neutral",
    )


def rerank_by_sufficiency(query: str, results: List[SearchResult]) -> List[SearchResult]:
    scored = []
    for index, result in enumerate(results):
        s = score_evidence_sufficiency(query, result)
        result.score += s.boost - s.generic_penalty
        metadata = dict(result.metadata or {})
        metadata["sufficiency_rerank"] = {
            "intent": s.intent,
            "boost": s.boost,
            "generic_penalty": s.generic_penalty,
            "reason": s.reason,
        }
        result.metadata = metadata
        scored.append((result.score, -index, result))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [result for _, _, result in scored]
