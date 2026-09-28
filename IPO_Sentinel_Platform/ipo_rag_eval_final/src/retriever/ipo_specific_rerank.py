"""Flag-gated local rerank rules for IPO-specific evidence."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List

from .models import SearchResult
from .query_intent import infer_query_intent
from .term_normalization import normalize_text


@dataclass(frozen=True)
class IpoSpecificScore:
    intent: str
    boost: float
    penalty: float
    reason: str


IPO_INTENTS = {"use_of_proceeds", "pre_ipo_rights", "share_price_volatility"}


def _has(text: str, terms: list[str]) -> bool:
    return any(normalize_text(term) in text for term in terms)


def _hits(text: str, terms: list[str]) -> int:
    return sum(1 for term in terms if normalize_text(term) in text)


def _percent_marker_count(text: str) -> int:
    return len(re.findall(r"\d+(?:\.\d+)?\s*%", text or ""))


def score_ipo_specific(query: str, result: SearchResult) -> IpoSpecificScore:
    intent = infer_query_intent(query)
    if intent not in IPO_INTENTS:
        return IpoSpecificScore(intent=intent, boost=0.0, penalty=0.0, reason="not_ipo_specific")

    section = normalize_text(" ".join(result.section_path or []))
    body = normalize_text(result.text or "")
    combined = section + " " + body
    boost = 0.0
    penalty = 0.0
    reasons: list[str] = []

    if intent == "use_of_proceeds":
        section_terms = ["所得款项用途", "所得款項用途", "未来计划及所得款项用途", "未來計劃及所得款項用途"]
        proceeds_terms = ["所得款项净额", "所得款項淨額", "全球发售所得款项", "全球發售所得款項", "募集资金", "募資"]
        use_terms = ["用于", "用於", "将用于", "將用於", "分配", "百分比", "%", "港元", "百万", "百萬"]
        purpose_terms = ["研发", "研發", "商业化", "商業化", "销售网络", "銷售網絡", "营运资金", "營運資金", "品牌建设", "品牌建設"]
        if _has(section, section_terms):
            boost += 0.16
            reasons.append("use_section")
        if _has(combined, proceeds_terms):
            boost += 0.14
            reasons.append("proceeds_terms")
        fact_hits = _hits(body, use_terms) + _hits(body, purpose_terms)
        if fact_hits >= 3 and _has(body, use_terms):
            boost += 0.22
            reasons.append("allocation_fact_density")
        elif fact_hits >= 2:
            boost += 0.12
            reasons.append("partial_allocation_fact")
        if _percent_marker_count(result.text or "") >= 4 and _has(body, use_terms):
            boost += 0.08
            reasons.append("allocation_bullet_density")
        if "概要" in section and fact_hits >= 3:
            boost += 0.05
            reasons.append("summary_with_facts")
        if _has(body, ["股份发售", "股份發售"]) and not (_has(combined, proceeds_terms) or fact_hits >= 2):
            penalty += 0.10
            reasons.append("generic_share_offer")
        if _has(combined, ["公司章程", "控股股东", "控股股東", "诚信义务", "誠信義務"]) and not _has(section, section_terms):
            penalty += 0.16
            reasons.append("governance_boilerplate")
        boost = min(boost, 0.55)

    elif intent == "pre_ipo_rights":
        pre_terms = ["首次公开发售前投资", "首次公開發售前投資", "首次公开招股前投资", "首次公開招股前投資", "preipo", "pre-ipo"]
        section_terms = ["历史", "歷史", "重组", "重組", "公司架构", "公司架構"]
        rights_terms = ["特殊权利", "特殊權利", "特别权利", "特別權利", "禁售", "终止", "終止"]
        pricing_terms = ["折让", "折讓", "每股成本", "市盈率", "投资者", "投資者"]
        if _has(section, pre_terms) or (_has(section, section_terms) and _has(body, pre_terms)):
            boost += 0.16
            reasons.append("pre_ipo_section")
        if _has(body, pre_terms):
            boost += 0.12
            reasons.append("pre_ipo_terms")
        if _has(body, rights_terms):
            boost += 0.18
            reasons.append("rights_terms")
        if _has(body, pricing_terms):
            boost += 0.12
            reasons.append("pricing_terms")
        if _has(body, ["股份发售", "股份發售"]) and not (_has(body, rights_terms) or _has(body, pricing_terms)):
            penalty += 0.08
            reasons.append("generic_share_offer")
        boost = min(boost, 0.50)

    elif intent == "share_price_volatility":
        price_terms = ["发售价", "發售價", "成交价", "成交價", "交易价格", "交易價格"]
        market_terms = ["公开市场", "公開市場", "流动性", "流動性", "波动", "波動", "重大损失", "重大損失"]
        if _has(section, ["风险因素", "風險因素"]):
            boost += 0.08
            reasons.append("risk_section")
        if _has(body, price_terms):
            boost += 0.18
            reasons.append("price_terms")
        market_hits = _hits(body, market_terms)
        if market_hits >= 2:
            boost += 0.18
            reasons.append("market_volatility_terms")
        elif market_hits == 1:
            boost += 0.08
            reasons.append("partial_market_terms")
        if _has(body, ["公司章程", "控股股东", "控股股東", "诚信义务", "誠信義務"]) and not _has(body, price_terms):
            penalty += 0.10
            reasons.append("governance_boilerplate")
        boost = min(boost, 0.45)

    return IpoSpecificScore(
        intent=intent,
        boost=round(boost, 4),
        penalty=round(penalty, 4),
        reason=",".join(reasons) or "neutral",
    )


def rerank_ipo_specific(query: str, results: List[SearchResult]) -> List[SearchResult]:
    if infer_query_intent(query) not in IPO_INTENTS:
        return results
    scored = []
    for index, result in enumerate(results):
        score = score_ipo_specific(query, result)
        result.score += score.boost - score.penalty
        metadata = dict(result.metadata or {})
        metadata["ipo_specific_rerank"] = {
            "intent": score.intent,
            "boost": score.boost,
            "penalty": score.penalty,
            "reason": score.reason,
        }
        result.metadata = metadata
        scored.append((result.score, -index, result))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [result for _, _, result in scored]
