"""Evidence role awareness: promote primary facts, demote mitigation/opinion/noise.

Generic text-role layer for 500+ prospectuses. No case_id / company / document
whitelist and no Gold-text injection.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Sequence

from .models import SearchResult
from .query_intent import infer_query_intent
from .term_normalization import normalize_text


ROLE_PRIMARY_FACT = "primary_fact"
ROLE_MITIGATION = "mitigation_control"
ROLE_OPINION = "third_party_opinion"
ROLE_ADJACENT = "adjacent_noise"
ROLE_BOILERPLATE = "generic_boilerplate"
ROLE_NEUTRAL = "neutral"


# Intents where role awareness is allowed to act.
FACT_INTENTS = {
    # Only residual fact/mitigation/opinion confusions. Other intents already
    # handled by answer_excerpt / ipo_specific stay no-op here.
    "ownership_control",
    "pre_ipo_rights",
    "use_of_proceeds",
    "margin_profitability",
    # Working-capital mechanism vs pure CFS / OCF footnote.
    "working_capital_mechanism",
}


PRIMARY_FACT_MARKERS = (
    "一致行动",
    "一致行動",
    "持股",
    "已发行股本",
    "已發行股本",
    "控制权",
    "控制權",
    "特殊权利",
    "特别权利",
    "特別權利",
    "禁售",
    "折让",
    "折讓",
    "市盈率",
    "每股成本",
    "所得款项净额",
    "所得款項淨額",
    "将用作",
    "將用作",
    "利润率",
    "利潤率",
    "毛利率",
    "下降",
    "五大客户",
    "五大客戶",
    "最大客户",
    "最大客戶",
    "所有权集中",
    "所有權集中",
    "重大影响力",
    "重大影響力",
)

MITIGATION_MARKERS = (
    "内部控制",
    "內部控制",
    "独立经营",
    "獨立經營",
    "独立于控股股东",
    "獨立於控股股東",
    "独立非执行董事",
    "獨立非執行董事",
    "放弃投票",
    "放棄投票",
    "不得计入法定人数",
    "不得計入法定人數",
    "保障少数股东",
    "保障少數股東",
    "财务独立",
    "財務獨立",
    "有效独立判断",
    "有效作出独立判断",
    "有效作出獨立判斷",
)

OPINION_MARKERS = (
    "保荐人认为",
    "獨家保薦人認為",
    "保薦人認為",
    "董事认为",
    "董事認為",
    "符合临时指引",
    "符合臨時指引",
    "指引信",
    "临时指引",
    "臨時指引",
    "我们认为",
    "我們認為",
)

ADJACENT_NOISE_MARKERS = (
    "以股份为基础的付款",
    "以股份為基礎的付款",
    "股份支付",
    "公允价值",
    "公允價值",
    "独立估值师",
    "獨立估值師",
    "债务融资的限制",
    "債務融資的限制",
    "一般公司用途",
)

BOILERPLATE_MARKERS = (
    "一般风险",
    "一般風險",
    "投资者应注意",
    "投資者應注意",
    "无法保证",
    "無法保證",
    "可能受到不利影响",
    "可能受到不利影響",
)


@dataclass(frozen=True)
class RoleScore:
    intent: str
    role: str
    boost: float
    penalty: float
    reason: str

    @property
    def delta(self) -> float:
        return self.boost - self.penalty


def _has(text: str, terms: Sequence[str]) -> bool:
    return any(normalize_text(t) in text for t in terms)


def _hits(text: str, terms: Sequence[str]) -> int:
    return sum(1 for t in terms if normalize_text(t) in text)


def _count_pct(text: str) -> int:
    return len(re.findall(r"\d+(?:\.\d+)?\s*%", text or ""))


def _count_money(text: str) -> int:
    return len(re.findall(r"(?:港元|人民幣|人民币|万元|百萬|百万|亿|億)", text or ""))


def infer_role_intent(query: str) -> str:
    """Map query to a role-aware intent family.

    Reuses query_intent when possible; adds only generic families needed for
    residual fact/mitigation confusions.
    """
    base = infer_query_intent(query)
    if base in FACT_INTENTS:
        return base
    if base == "working_capital_mechanism":
        return "working_capital_mechanism"

    q = normalize_text(query)
    if any(
        t in q
        for t in [
            "一致行动",
            "实际控制人",
            "控股股东",
            "控制权",
            "所有权集中",
            "高度持股",
            "损害其他股东",
            "阻碍控制权",
            "影响力",
        ]
    ):
        return "ownership_control"
    if any(t in q for t in ["毛利率", "利润率", "盈利质量", "盈利能力", "业务利润率"]):
        return "margin_profitability"
    if base in {"pre_ipo_rights", "use_of_proceeds", "customer_concentration"}:
        return base
    if base != "generic_other":
        # Keep known intents available, but role layer no-ops unless in FACT_INTENTS.
        return base
    return "generic_other"


def classify_evidence_role(query: str, result: SearchResult) -> str:
    intent = infer_role_intent(query)
    text = result.text or ""
    body = normalize_text(text)
    section = normalize_text(" ".join(result.section_path or []))
    combined = f"{section} {body}"

    pct_n = _count_pct(text)
    money_n = _count_money(text)
    primary_hits = _hits(combined, PRIMARY_FACT_MARKERS)
    mitigation = _has(combined, MITIGATION_MARKERS)
    opinion = _has(combined, OPINION_MARKERS)
    adjacent = _has(combined, ADJACENT_NOISE_MARKERS)
    boilerplate = _has(combined, BOILERPLATE_MARKERS)

    # Intent-conditioned primary checks.
    if intent == "ownership_control":
        ownership_fact = _has(
            combined,
            (
                "一致行动",
                "一致行動",
                "共同及实益拥有",
                "共同及實益擁有",
                "所有权集中",
                "所有權集中",
                "控制权变动",
                "控制權變動",
                "重大影响力",
                "重大影響力",
                "控股股东",
                "控股股東",
            ),
        ) and (
            pct_n >= 1
            or _has(
                combined,
                (
                    "已发行股本",
                    "已發行股本",
                    "持股",
                    "表决权",
                    "表決權",
                    "窒碍",
                    "窒礙",
                    "延迟或阻止",
                    "延遲或阻止",
                    "有违其他股东",
                    "有違其他股東",
                ),
            )
        )
        if ownership_fact and not mitigation:
            return ROLE_PRIMARY_FACT
        if mitigation and not ownership_fact:
            return ROLE_MITIGATION
        if mitigation and ownership_fact and primary_hits < 2:
            return ROLE_MITIGATION

    if intent == "pre_ipo_rights":
        has_valuation = _has(combined, ("市盈率", "协定市盈率", "協定市盈率", "每股成本", "认购价", "認購價"))
        has_discount = _has(combined, ("折让", "折讓", "发售价折让", "發售價折讓")) and (
            pct_n >= 1 or "%" in (text or "") or "％" in (text or "")
        )
        has_lockup = _has(combined, ("禁售", "禁售期"))
        has_rights = _has(combined, ("特别权利", "特別權利", "特殊权利", "特殊權利")) and _has(
            combined, ("无权享有", "無權享有", "不享有", "并无", "並無", "享有", "授予")
        )
        term_n = sum(1 for x in (has_valuation, has_discount, has_lockup, has_rights) if x)
        # Complete or near-complete term package is primary; bare lockup/background is not.
        preipo_fact = term_n >= 3 or (has_valuation and has_discount and (has_lockup or has_rights))
        half_package = (
            _has(combined, ("首次公开招股前", "首次公開發售前", "pre-ipo", "两轮", "兩輪", "总投资", "總投資"))
            and term_n <= 2
            and not (has_discount and has_rights)
        )
        if preipo_fact and not opinion:
            return ROLE_PRIMARY_FACT
        if opinion and not preipo_fact:
            return ROLE_OPINION
        if opinion and preipo_fact and term_n <= 2:
            return ROLE_OPINION
        if half_package and not preipo_fact:
            return ROLE_ADJACENT

    if intent == "use_of_proceeds":
        alloc_n = len(re.findall(r"(?:约|約)?\d+(?:\.\d+)?\s*%", text or ""))
        uop_fact = _has(
            combined,
            (
                "所得款项",
                "所得款項",
                "将用作",
                "將用作",
                "未来计划及所得款项用途",
                "未來計劃及所得款項用途",
            ),
        ) and alloc_n >= 2
        if uop_fact:
            return ROLE_PRIMARY_FACT
        if _has(combined, ("债务融资", "債務融資", "一般公司用途")) and alloc_n <= 1:
            return ROLE_ADJACENT
        if alloc_n == 1 and _has(combined, ("所得款项", "所得款項")):
            return ROLE_ADJACENT

    if intent == "working_capital_mechanism":
        has_mismatch = _has(
            combined,
            (
                "时间错配",
                "時間錯配",
                "错配",
                "錯配",
                "相隔一段时间",
                "相隔一段時間",
                "时间差距",
                "時間差距",
            ),
        )
        has_token_media = _has(
            combined,
            ("虚拟代币", "虛擬代幣", "媒体发布商", "媒體發佈商", "媒体发佈商"),
        )
        has_advance = _has(combined, ("垫付", "墊付", "预付款项", "預付款項", "预先购入", "預先購入"))
        has_collection = _has(
            combined,
            ("客户付款", "客戶付款", "贸易应收", "貿易應收", "后续结算", "後續結算", "回款", "授出信贷期", "授出信貸期"),
        )
        has_wc = _has(combined, ("流动资金风险", "流動資金風險", "现金需求", "現金需求", "庞大现金", "龐大現金"))
        has_ocf = _has(
            combined,
            ("负经营", "負經營", "经营现金流", "經營現金流", "经营活动所用现金", "經營活動所用現金"),
        )
        cfs_only = _has(
            combined,
            (
                "现金流量表",
                "現金流量表",
                "经营活动所得现金流量",
                "經營活動所得現金流量",
                "营运资金变动前",
                "營運資金變動前",
            ),
        ) or (
            (result.block_type == "table")
            and _has(combined, ("经营活动", "經營活動", "营运资金变动", "營運資金變動"))
        )
        footnote_only = _has(
            combined,
            ("除所得税前溢利", "除所得稅前溢利", "加回非现金", "加回非現金", "折旧及摊销", "折舊及攤銷", "现金流出净额主要归属于", "現金流出淨額主要歸屬於"),
        )
        mechanism_core = has_mismatch or (has_token_media and has_advance and has_collection)
        if mechanism_core and (has_collection or has_wc or has_ocf):
            return ROLE_PRIMARY_FACT
        if cfs_only or (footnote_only and not mechanism_core):
            return ROLE_ADJACENT
        if has_ocf and not mechanism_core:
            return ROLE_ADJACENT
        if has_advance and has_collection and not mechanism_core:
            return ROLE_ADJACENT

    if intent == "margin_profitability":
        margin_fact = (
            _has(combined, ("利润率", "利潤率", "毛利率"))
            and pct_n >= 2
            and _has(combined, ("下降", "减少", "減少", "承压", "不利"))
        )
        if margin_fact and not _has(
            combined,
            ("以股份为基础的付款", "以股份為基礎的付款", "股份支付"),
        ):
            return ROLE_PRIMARY_FACT
        if _has(
            combined,
            (
                "以股份为基础的付款",
                "以股份為基礎的付款",
                "股份支付",
                "公允价值",
                "公允價值",
            ),
        ) and not margin_fact:
            return ROLE_ADJACENT

    if opinion and primary_hits == 0:
        return ROLE_OPINION
    if mitigation and primary_hits <= 1:
        return ROLE_MITIGATION
    if adjacent and primary_hits <= 1:
        return ROLE_ADJACENT
    if boilerplate and primary_hits == 0 and pct_n == 0:
        return ROLE_BOILERPLATE
    if primary_hits >= 2 or pct_n >= 2:
        return ROLE_PRIMARY_FACT
    return ROLE_NEUTRAL


def score_evidence_role(query: str, result: SearchResult) -> RoleScore:
    intent = infer_role_intent(query)
    if intent not in FACT_INTENTS:
        return RoleScore(intent=intent, role=ROLE_NEUTRAL, boost=0.0, penalty=0.0, reason="noop")

    role = classify_evidence_role(query, result)
    text = result.text or ""
    body = normalize_text(text)
    pct_n = _count_pct(text)
    boost = 0.0
    penalty = 0.0
    reasons: List[str] = [role]

    if role == ROLE_PRIMARY_FACT:
        boost += 0.18
        if intent == "working_capital_mechanism" and _has(
            body,
            ("时间错配", "時間錯配", "虚拟代币", "虛擬代幣", "预付款项", "預付款項", "垫付", "墊付"),
        ):
            boost += 0.10
            reasons.append("wc_mechanism_primary")
        if intent == "ownership_control" and _has(
            body,
            (
                "一致行动",
                "一致行動",
                "所有权集中",
                "所有權集中",
                "控制权变动",
                "控制權變動",
            ),
        ):
            boost += 0.10
            reasons.append("ownership_primary")
        if intent == "pre_ipo_rights":
            term_hits = _hits(
                body,
                ("折让", "折讓", "禁售", "特别权利", "特別權利", "市盈率", "每股成本", "发售价折让", "發售價折讓"),
            )
            if term_hits >= 3:
                boost += 0.16
                reasons.append("preipo_complete_primary")
            elif term_hits >= 1:
                boost += 0.08
                reasons.append("preipo_primary")
        if intent == "use_of_proceeds" and len(re.findall(r"\d+(?:\.\d+)?\s*%", text)) >= 3:
            boost += 0.12
            reasons.append("uop_multi_allocation")
        if intent == "margin_profitability" and _has(body, ("利润率", "利潤率", "毛利率")) and pct_n >= 2:
            boost += 0.10
            reasons.append("margin_series_primary")
    elif role == ROLE_MITIGATION:
        # Fact-seeking ownership/control questions should not be answered by independence boilerplate.
        if intent in {"ownership_control", "pre_ipo_rights", "margin_profitability", "use_of_proceeds"}:
            penalty += 0.22
            reasons.append("mitigation_on_fact_question")
    elif role == ROLE_OPINION:
        if intent in {"pre_ipo_rights", "ownership_control", "use_of_proceeds", "margin_profitability"}:
            penalty += 0.24
            reasons.append("opinion_on_fact_question")
    elif role == ROLE_ADJACENT:
        if intent == "working_capital_mechanism":
            penalty += 0.12
            reasons.append("wc_adjacent_cfs_or_footnote")

        penalty += 0.16
        reasons.append("adjacent_noise")
        if intent == "margin_profitability" and _has(
            body,
            ("股份支付", "以股份为基础的付款", "以股份為基礎的付款"),
        ):
            penalty += 0.08
            reasons.append("sbc_noise")
        if intent == "use_of_proceeds" and len(re.findall(r"\d+(?:\.\d+)?\s*%", text)) <= 1:
            penalty += 0.08
            reasons.append("partial_uop_fragment")
    elif role == ROLE_BOILERPLATE:
        penalty += 0.12
        reasons.append("generic_boilerplate")

    # Cap to keep this layer a light complement to existing rerankers.
    boost = max(0.0, min(boost, 0.35))
    penalty = max(0.0, min(penalty, 0.35))
    return RoleScore(
        intent=intent,
        role=role,
        boost=boost,
        penalty=penalty,
        reason="+".join(reasons),
    )


def rerank_evidence_role(query: str, results: List[SearchResult]) -> List[SearchResult]:
    if not results:
        return results
    intent = infer_role_intent(query)
    if intent not in FACT_INTENTS:
        return results

    for index, item in enumerate(results):
        scored = score_evidence_role(query, item)
        item.score = float(item.score or 0.0) + scored.delta
        metadata = dict(item.metadata or {})
        metadata["evidence_role"] = scored.role
        metadata["evidence_role_intent"] = scored.intent
        metadata["evidence_role_reason"] = scored.reason
        metadata["evidence_role_delta"] = round(scored.delta, 4)
        item.metadata = metadata
        # Stable secondary key for sort below via temporary attribute.
        item._role_stable_index = index  # type: ignore[attr-defined]

    results.sort(
        key=lambda x: (float(x.score or 0.0), -int(getattr(x, "_role_stable_index", 0))),
        reverse=True,
    )
    for item in results:
        if hasattr(item, "_role_stable_index"):
            delattr(item, "_role_stable_index")
    return results
