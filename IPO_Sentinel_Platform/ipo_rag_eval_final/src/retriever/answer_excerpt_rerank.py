"""Answer-excerpt quality rerank: promote concrete answer excerpts, demote hard negatives."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List

from .models import SearchResult
from .term_normalization import normalize_text


@dataclass(frozen=True)
class ExcerptScore:
    intent: str
    boost: float
    penalty: float
    reason: str


ACTUAL_LITIGATION_TERMS = (
    "接获", "收到", "提出", "申索", "索赔", "起诉", "被诉", "诉讼", "仲裁",
    "法院", "中级人民法院", "高级人民法院", "知识产权侵权", "侵权申索",
)
DEFENSIVE_IP_TERMS = (
    "保护知识产权", "保护我们的知识产权", "并无涉及任何我们认为侵犯我们知识产权",
    "我们或会对疑似侵害", "维持竞争优势",
)
NO_LITIGATION_POSITIVE = (
    "并无尚未完结", "并无尚未了结", "概无任何待决", "概无待决", "不存在重大诉讼",
    "无重大诉讼", "并无重大诉讼", "未涉及任何重大诉讼", "并无面临重大诉讼",
    "并无尚未完结或面临重大诉讼或申索", "董事确认", "据董事所知",
)
STATUTE_APPENDIX_TERMS = (
    "中华人民共和国证券法", "仲裁法", "民事诉讼法", "主要法律及监管规定概要",
    "法定及一般资料", "两审终审", "人民法院采用",
)
FUTURE_LAWSUIT_TEMPLATE = (
    "可能被提出诉讼", "可能面临诉讼", "可能被起诉", "可能对我们提出申索",
    "无法保证不会", "概不保证", "或会面对", "可能产生重大法律",
)
WORKING_CAPITAL_MECHANISM_TERMS = (
    "时间错配", "時間錯配", "错配", "錯配",
    "垫付", "墊付", "预付款", "預付款", "预付款项", "預付款項",
    "虚拟代币", "虛擬代幣", "媒体发布商", "媒體發佈商", "媒体发佈商",
    "贸易应收", "貿易應收", "客户付款", "客戶付款", "后续结算", "後續結算",
    "流动资金风险", "流動資金風險", "营运资金", "營運資金",
    "负经营现金流", "負經營現金流", "经营现金流", "經營現金流",
    "经营活动所用现金", "經營活動所用現金", "现金需求", "現金需求",
)
WORKING_CAPITAL_CFS_ONLY_TERMS = (
    "现金流量表", "現金流量表",
    "经营活动所得现金流量", "經營活動所得現金流量",
    "营运资金变动前经营现金流量", "營運資金變動前經營現金流量",
    "营运资金变动", "營運資金變動",
    "投资活动所得现金", "投資活動所得現金",
    "融资活动所得现金", "融資活動所得現金",
)
WORKING_CAPITAL_FOOTNOTE_ONLY_TERMS = (
    "除所得税前溢利", "除所得稅前溢利",
    "加回非现金项目", "加回非現金項目",
    "折旧及摊销", "折舊及攤銷",
    "经营<fim-middle>活动所用现金净额约", "經營活動所用現金淨額約",
    "现金流出净额主要归属于", "現金流出淨額主要歸屬於",
)

CUSTOMER_CREDIT_TERMS = (

    "财政困难", "財務困難", "财务状况恶化", "財務狀況惡化",
    "延迟付款", "延遲付款", "延迟向我们付款", "延遲向我們付款",
    "修改付款", "修改付款安排", "无法履行付款", "無法履行付款",
    "无力偿债", "無力償債", "破产", "破產",
    "营运资金", "營運資金", "流失客户", "流失客戶", "流失现有客户", "流失現有客戶",
    "信贷市场", "信貸市場", "贸易应收", "貿易應收",
)
INTERNAL_FINANCE_NOISE = (
    "内部产生资金", "内部產生資金", "股东及董事贷款", "股東及董事貸款",
    "业务保理协议", "業務保理協議", "银行贷款", "銀行貸款", "资本贡献", "資本貢獻",
)
COMPETITION_PRESSURE_TERMS = (
    "竞争激烈", "競爭激烈", "竞争加剧", "競爭加劇", "更趋激烈", "更趨激烈", "日趋激烈", "日趨激烈",
    "降价", "降價", "降低价格", "降低價格",
    "议价能力", "議價能力",
    "利润下降", "利潤下降", "利润减少", "利潤減少",
    "流失客户", "流失客戶", "流失现有客户", "流失現有客戶",
    "进入壁垒", "進入壁壘", "进入壁垒低", "進入壁壘低",
    "定价压力", "定價壓力",
    "失去市场地位", "失去市場地位", "收入减少", "收入減少",
)
MARKET_SIZE_NOISE = (
    "市场规模", "市場規模", "市场增长", "市場增長", "复合年增长率", "複合年增長率",
    "cagr", "亿人民币", "億人民幣", "行业前景", "行業前景",
    "移动广告市场", "移動廣告市場", "预计将由", "預計將由",
)
CONNECTED_TX_TERMS = (
    "持续关连交易", "关连交易", "关联方交易", "非获豁免", "上市规则第14a", "关连交易一节",
)
CUSTOMER_CONCENTRATION_TERMS = (
    "五大客户", "五大客戶", "最大客户", "最大客戶", "主要客户", "主要客戶",
    "总收入", "總收入", "收入贡献", "收入貢獻",
    "客户集中", "客戶集中", "集中风险", "集中風險",
    "停止使用我们的服务", "停止使用我們的服務", "停止使用", "客户流失", "客戶流失",
)
CUSTOMER_CONCENTRATION_NOISE = (
    "毛利率下降", "利润率下降", "經營歷史有限", "经营历史有限",
    "快速增长", "快速增長", "复合年增长率", "複合年增長率",
    "回头客", "回頭客", "客户流失率乃根据", "客戶流失率乃根據",
)



PREIPO_VALUATION_TERMS = (
    "市盈率", "协定市盈率", "協定市盈率", "每股成本", "认购价", "認購價", "认购", "認購",
)
PREIPO_DISCOUNT_TERMS = (
    "发售价折让", "發售價折讓", "发行价折让", "發行價折讓", "折让", "折讓", "折价", "折價",
)
PREIPO_LOCKUP_TERMS = (
    "禁售", "禁售期", "锁定期", "鎖定期",
)
PREIPO_RIGHTS_TERMS = (
    "特别权利", "特別權利", "特殊权利", "特殊權利", "优先权", "優先權", "赎回权", "贖回權",
)
PREIPO_RIGHTS_ABSENT_TERMS = (
    "无权享有", "無權享有", "不享有", "并无", "並無", "没有特别权利", "沒有特別權利", "无特别权利", "無特別權利",
)
PREIPO_BACKGROUND_ONLY_TERMS = (
    "两轮", "兩輪", "首轮", "首輪", "二轮", "二輪", "总投资", "總投資", "投资总额", "投資總額",
    "战略投资者", "戰略投資者", "首次公开招股前投资的背景", "首次公開招股前投資的背景",
)
PREIPO_SPONSOR_OPINION_TERMS = (
    "保荐人认为", "保薦人認為", "符合临时指引", "符合臨時指引", "董事认为", "董事認為",
)


def preipo_terms_coverage(text: str) -> dict:
    """Count generic pre-IPO term-package dimensions (no company/case literals)."""
    body = normalize_text(text or "")
    raw = text or ""
    has_valuation = _has(body, PREIPO_VALUATION_TERMS)
    # Discount needs explicit percent or 折让+number pattern, not bare word alone if possible.
    has_discount_word = _has(body, PREIPO_DISCOUNT_TERMS)
    has_discount_pct = bool(re.search(r"(\d+(?:\.\d+)?)\s*%", raw)) or bool(
        re.search(r"折[讓让].{0,16}\d", body)
    )
    has_discount = has_discount_word and (has_discount_pct or "%" in raw or "％" in raw)
    has_lockup = _has(body, PREIPO_LOCKUP_TERMS)
    has_rights_word = _has(body, PREIPO_RIGHTS_TERMS)
    has_rights_absent = _has(body, PREIPO_RIGHTS_ABSENT_TERMS)
    has_rights_granted = has_rights_word and _has(body, ("享有", "授予", "附有", "拥有", "擁有")) and not has_rights_absent
    has_rights_conclusion = has_rights_word and (has_rights_absent or has_rights_granted or _has(body, ("无权", "無權")))
    dims = {
        "valuation": has_valuation,
        "discount": bool(has_discount),
        "lockup": has_lockup,
        "rights": bool(has_rights_conclusion),
    }
    score = sum(1 for v in dims.values() if v)
    background_only = _has(body, PREIPO_BACKGROUND_ONLY_TERMS) and score <= 1
    sponsor_opinion = _has(body, PREIPO_SPONSOR_OPINION_TERMS)
    return {
        "dims": dims,
        "score": score,
        "background_only": background_only,
        "sponsor_opinion": sponsor_opinion,
        "table_like": ("表格" in raw) or ("|" in raw and has_valuation),
    }


def infer_excerpt_intent(query: str) -> str:
    q = normalize_text(query)
    if any(t in q for t in ["不存在重大诉讼", "无重大诉讼", "并无", "概无", "是否披露不存在"]):
        return "no_litigation_disclosure"
    if any(t in q for t in ["专利侵权", "知识产权", "法律纠纷", "诉讼等重大", "被诉", "侵权"]):
        return "actual_litigation_disclosure"
    if any(t in q for t in ["主要客户", "五大客户", "最大客户", "客户集中", "少数主要客户", "高度依赖少数"]):
        return "customer_concentration"
    # Working-capital mechanism sufficiency: require prepay/advance/mismatch (not bare 回款+营运资金).
    if (
        any(t in q for t in ["负经营现金流", "负经营现金流量", "经营现金流", "经营现金流量", "营运资金", "流动资金"])
        and any(t in q for t in ["垫付", "预付", "错配", "时间错配", "回款错配"])
    ):
        return "working_capital_mechanism"
    if any(t in q for t in ["客户财务", "付款能力", "回款", "延迟付款", "营运资金", "财政困难"]):
        return "customer_credit_deterioration"
    # customer loss alone is ambiguous; prefer concentration if major-customer cues exist.
    if any(t in q for t in ["竞争加剧", "竞争激烈", "降价", "利润下降"]) or (
        "客户流失" in q and any(t in q for t in ["竞争", "降价", "利润"])
    ):
        return "competitive_pricing_pressure"
    if any(t in q for t in ["关连交易", "关联交易", "关联方交易", "持续关连"]):
        return "connected_transaction_governance"
    if any(
        t in q
        for t in [
            "首次公开招股前",
            "首次公开发售前",
            "发售前投资",
            "preipo",
            "pre-ipo",
            "特殊权利",
            "特别权利",
            "禁售",
            "发售价折让",
            "市盈率",
            "每股成本",
        ]
    ):
        return "pre_ipo_rights"
    return "generic_other"


def _has(text: str, terms: tuple[str, ...]) -> bool:
    return any(normalize_text(t) in text for t in terms)


def _hits(text: str, terms: tuple[str, ...]) -> int:
    return sum(1 for t in terms if normalize_text(t) in text)


def _court_or_claim_fact(text: str) -> bool:
    """True only for concrete received/filed claim facts, not defensive templates.

    Generic prospectus patterns only: named defendants/cities are never necessary.
    """
    n = normalize_text(text)
    defensive = _has(
        n,
        (
            "我们或会",
            "或会对应",
            "为保护知识产权",
            "保护知识产权及维持",
            "并无涉及任何我们认为侵犯我们",
        ),
    )
    concrete_received = _has(n, ("接获", "收到", "接获通知", "收到若干"))
    if defensive and not concrete_received:
        return False
    received = concrete_received
    filed_against_us = (
        _has(
            n,
            (
                "向本集团申索",
                "向本公司申索",
                "对我们提出",
                "对本集团提出",
                "对本公司提出",
                "提出若干知识产权侵权申索",
                "提出的若干知识产权侵权",
            ),
        )
        or (
            _has(n, ("提出", "申索", "索赔", "起诉", "被申诉"))
            and _has(n, ("法院", "中级人民法院", "高级人民法院", "仲裁"))
        )
    )
    forum_or_claim_type = _has(
        n,
        (
            "法院",
            "中级人民法院",
            "高级人民法院",
            "仲裁",
            "侵权申索",
            "知识产权侵权申索",
            "专利侵权",
            "索赔",
        ),
    )
    return (received or filed_against_us) and forum_or_claim_type


def score_answer_excerpt(query: str, result: SearchResult) -> ExcerptScore:
    intent = infer_excerpt_intent(query)
    if intent == "generic_other":
        return ExcerptScore(intent=intent, boost=0.0, penalty=0.0, reason="not_applicable")

    section = normalize_text(" ".join(result.section_path or []))
    body = normalize_text(result.text or "")
    combined = f"{section} {body}"
    boost = 0.0
    penalty = 0.0
    reasons: list[str] = []

    if intent == "actual_litigation_disclosure":
        if _court_or_claim_fact(combined):
            boost += 0.28
            reasons.append("concrete_claim_fact")
            boost += min(_hits(combined, ACTUAL_LITIGATION_TERMS), 4) * 0.03
            # denser specific disclosure (forum / amount / received-claim) outranks vague procedure.
            # Named counterparties/cities are optional weak cues only and must not be required.
            specificity = 0
            if _has(combined, ("法院", "中级人民法院", "高级人民法院", "仲裁庭", "仲裁")):
                specificity += 1
            if _has(combined, ("人民币", "百万元", "万元", "或有赔偿", "索赔金额", "专利")):
                specificity += 1
            if _has(combined, ("接获", "收到若干", "向本集团申索", "向本公司申索", "对我们提出")):
                specificity += 1
            boost += min(specificity, 3) * 0.06
            if specificity:
                reasons.append("claim_specificity")
        if _has(combined, DEFENSIVE_IP_TERMS) and not _court_or_claim_fact(combined):
            penalty += 0.26
            reasons.append("defensive_ip_boilerplate")
        if _has(combined, ("并无涉及任何我们认为侵犯我们知识产权", "我们或会对疑似侵害")) and not _court_or_claim_fact(combined):
            penalty += 0.08
            reasons.append("own_ip_enforcement_template")
        if _has(combined, STATUTE_APPENDIX_TERMS) and not _court_or_claim_fact(combined):
            penalty += 0.18
            reasons.append("statute_appendix")
        if _has(combined, ("两审终审", "民事诉讼", "清算", "通知债权人")) and not _court_or_claim_fact(combined):
            penalty += 0.10
            reasons.append("procedure_noise")
        if _has(combined, FUTURE_LAWSUIT_TEMPLATE) and not _court_or_claim_fact(combined):
            penalty += 0.12
            reasons.append("future_lawsuit_template")

    elif intent == "no_litigation_disclosure":
        if _has(combined, NO_LITIGATION_POSITIVE):
            boost += 0.30
            reasons.append("negative_disclosure")
        if _has(combined, ("据董事所知", "董事确认", "董事已获告知", "董事所知")):
            boost += 0.08
            reasons.append("director_confirmation")
        if _has(combined, STATUTE_APPENDIX_TERMS) and not _has(combined, NO_LITIGATION_POSITIVE):
            penalty += 0.24
            reasons.append("statute_not_disclosure")
        if _has(combined, FUTURE_LAWSUIT_TEMPLATE) and not _has(combined, NO_LITIGATION_POSITIVE):
            penalty += 0.16
            reasons.append("future_template_not_negation")

    elif intent == "working_capital_mechanism":
        mech_hits = _hits(combined, WORKING_CAPITAL_MECHANISM_TERMS)
        # Timing-mismatch / advance-payment mechanism (not bare OCF footnote WC lines).
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
                "支付预付款项及从客户收取款项之间",
                "支付預付款項及從客戶收取款項之間",
            ),
        )
        has_token_media = _has(
            combined,
            ("虚拟代币", "虛擬代幣", "媒体发布商", "媒體發佈商", "媒体发佈商", "媒體发布商"),
        )
        has_advance = _has(combined, ("垫付", "墊付", "垫付款", "墊付款", "预先购入", "預先購入", "预先购买", "預先購買"))
        has_prepay_item = _has(combined, ("预付款项", "預付款項", "向媒体", "向媒體"))
        has_collection = _has(
            combined,
            (
                "客户付款",
                "客戶付款",
                "收到客户付款",
                "收到客戶付款",
                "贸易应收",
                "貿易應收",
                "后续结算",
                "後續結算",
                "授出信贷期",
                "授出信貸期",
                "结付贸易应收",
                "結付貿易應收",
            ),
        )
        has_neg_ocf = _has(
            combined,
            (
                "负经营",
                "負經營",
                "经营现金流",
                "經營現金流",
                "经营活动所用现金",
                "經營活動所用現金",
                "所用现金净额",
                "所用現金淨額",
                "负经营现金",
                "負經營現金",
            ),
        )
        has_wc_risk = _has(
            combined,
            (
                "流动资金风险",
                "流動資金風險",
                "现金需求",
                "現金需求",
                "庞大现金",
                "龐大現金",
                "营运资金压力",
                "營運資金壓力",
            ),
        )
        # True mechanism core: explicit timing mismatch/gap, or token + advance/垫付 (not bare prepay balance).
        # Bare 预付款项+贸易应收 without mismatch is common in OCF/liquidity footnotes and must not dominate.
        mechanism_core = has_mismatch or (has_token_media and has_advance and has_collection)
        strong_mechanism = mechanism_core and (has_collection or has_wc_risk or has_neg_ocf or has_token_media)
        gold_like = has_mismatch and has_token_media and has_collection
        if gold_like:
            boost += 0.48 + min(mech_hits, 6) * 0.02
            reasons.append("wc_token_timing_mismatch_mechanism")
        elif strong_mechanism and has_wc_risk:
            boost += 0.36 + min(mech_hits, 5) * 0.02
            reasons.append("wc_timing_prepay_mechanism")
        elif strong_mechanism:
            boost += 0.28 + min(mech_hits, 4) * 0.02
            reasons.append("wc_prepay_mismatch_chain")
        elif mechanism_core:
            boost += 0.18
            reasons.append("wc_partial_mechanism")
        elif has_prepay_item and has_collection and has_token_media:
            boost += 0.12
            reasons.append("wc_token_prepay_context")
        elif has_neg_ocf and mech_hits >= 2 and not _has(combined, WORKING_CAPITAL_FOOTNOTE_ONLY_TERMS):
            boost += 0.06
            reasons.append("wc_ocf_with_partial_context")

        # Hard negatives: pure CFS table / OCF reconciliation footnote without mechanism core.
        cfs_only = (
            result.block_type == "table"
            or _has(combined, WORKING_CAPITAL_CFS_ONLY_TERMS)
            or ((result.text or "").startswith("表格") and _has(combined, ("经营活动", "經營活動", "营运资金变动", "營運資金變動")))
        )
        footnote_recon = _has(combined, WORKING_CAPITAL_FOOTNOTE_ONLY_TERMS)
        if cfs_only and not mechanism_core:
            penalty += 0.32
            reasons.append("wc_cashflow_statement_without_mechanism")
        if footnote_recon and not mechanism_core:
            penalty += 0.30
            reasons.append("wc_ocf_footnote_without_mechanism")
        # Bare prepayment balance / AR days discussion without mismatch/token mechanism.
        if has_prepay_item and has_collection and not mechanism_core and not has_token_media:
            penalty += 0.14
            reasons.append("wc_prepay_balance_without_timing_mechanism")
        if _has(combined, ("保理", "银行贷款", "銀行貸款", "股东贷款", "股東貸款")) and not mechanism_core:
            penalty += 0.14
            reasons.append("wc_financing_noise")
        if _has(combined, ("财政困难", "財務困難", "延迟付款", "延遲付款", "流失客户", "流失客戶")) and not mechanism_core:
            penalty += 0.12
            reasons.append("wc_customer_credit_near_miss")

    elif intent == "customer_credit_deterioration":
        chain_hits = _hits(combined, CUSTOMER_CREDIT_TERMS)
        # True customer-credit trigger is macroeconomic/customer deterioration, not generic insolvency wording in IFRS notes.
        has_true_trigger = _has(
            combined,
            (
                "财政困难",
                "財務困難",
                "财务状况恶化",
                "財務狀況惡化",
                "延迟付款",
                "延遲付款",
                "延迟向我们付款",
                "延遲向我們付款",
                "修改付款",
                "修改付款安排",
                "无法履行付款",
                "無法履行付款",
                "客户出现财政困难",
                "客戶出現財政困難",
            ),
        )
        has_weak_insolvency = _has(combined, ("无力偿债", "無力償債", "破产", "破產"))
        has_consequence = _has(
            combined,
            ("营运资金", "營運資金", "流失客户", "流失客戶", "流失现有客户", "流失現有客戶", "无法接受额外广告订单", "無法接受額外廣告訂單"),
        )
        has_full_chain = has_true_trigger and has_consequence
        if has_full_chain or (chain_hits >= 3 and has_true_trigger):
            boost += 0.34 + min(max(chain_hits, 3), 6) * 0.04
            reasons.append("credit_consequence_chain")
        elif has_true_trigger or (has_consequence and chain_hits >= 2):
            boost += 0.14
            reasons.append("partial_credit_signal")
        elif has_weak_insolvency and not has_true_trigger:
            # IFRS / accounting notes often mention insolvency without customer-credit story.
            penalty += 0.16
            reasons.append("generic_insolvency_note")
        if _has(combined, INTERNAL_FINANCE_NOISE) and not has_full_chain:
            penalty += 0.20
            reasons.append("internal_finance_noise")
        if _has(
            combined,
            (
                "2019冠状病毒",
                "2019冠狀病毒",
                "业务营运及财务表现并无受到重大不利",
                "業務營運及財務表現並無受到重大不利",
                "初步审阅",
                "初步審閱",
            ),
        ) and not has_full_chain:
            penalty += 0.12
            reasons.append("covid_ops_boilerplate")
        if _has(combined, ("向媒体发布商支付的预付款项", "向媒體發佈商支付的預付款項")) and not has_true_trigger:
            penalty += 0.12
            reasons.append("media_prepayment_noise")
        if _has(
            combined,
            (
                "综合财务状况表",
                "綜合財務狀況表",
                "金融资产与负债可互相抵销",
                "金融資產與負債可互相抵銷",
                "贸易及其他应收款项",
                "貿易及其他應收款項",
                "按净额基准结清",
                "按淨額基準結清",
            ),
        ) and not has_full_chain:
            penalty += 0.18
            reasons.append("ifrs_accounting_noise")
        if _has(combined, ("贸易应收款项周转天数", "貿易應收款項周轉天數", "负经营现金流量", "負經營現金流量")) and not has_true_trigger:
            penalty += 0.10
            reasons.append("ar_turnover_ops_noise")


    elif intent == "competitive_pricing_pressure":
        chain_hits = _hits(combined, COMPETITION_PRESSURE_TERMS)
        has_price_or_profit = _has(combined, ("降价", "降價", "利润减少", "利潤減少", "利润下降", "利潤下降", "收入减少", "收入減少"))
        has_churn_or_position = _has(combined, ("流失客户", "流失客戶", "流失现有客户", "流失現有客戶", "失去市场地位", "失去市場地位"))
        has_competition = _has(
            combined,
            ("竞争激烈", "競爭激烈", "竞争加剧", "競爭加劇", "更趋激烈", "更趨激烈", "日趋激烈", "日趨激烈", "进入壁垒", "進入壁壘"),
        )
        if chain_hits >= 2 or (has_competition and has_price_or_profit) or (has_price_or_profit and has_churn_or_position):
            boost += 0.28 + min(max(chain_hits, 2), 5) * 0.05
            reasons.append("competition_consequence_chain")
        elif has_price_or_profit or has_churn_or_position:
            boost += 0.14
            reasons.append("partial_competition_signal")
        if _has(combined, MARKET_SIZE_NOISE) and chain_hits < 2 and not (has_price_or_profit and has_churn_or_position):
            penalty += 0.22
            reasons.append("market_size_review")
        if _has(combined, ("广告主是价值链", "廣告主是價值鏈", "移动广告公司所增添的价值", "移動廣告公司所增添的價值", "行业经验及专业知识", "行業經驗及專業知識")) and not (
            has_price_or_profit and has_churn_or_position
        ):
            penalty += 0.12
            reasons.append("industry_overview_noise")

    elif intent == "customer_concentration":
        chain_hits = _hits(combined, CUSTOMER_CONCENTRATION_TERMS)
        # Require explicit top-customer dependence facts, not merely a named customer mention.
        has_top_label = _has(combined, ("五大客户", "五大客戶", "最大客户", "最大客戶"))
        has_named_major = _has(combined, ("主要客户", "主要客戶", "现有主要客户", "現有主要客戶"))
        has_share = _has(combined, ("总收入", "總收入", "收入贡献", "收入貢獻")) and (
            "%" in (result.text or "") or _has(combined, ("约占", "約佔", "贡献", "貢獻", "占比", "佔"))
        )
        has_impact = _has(
            combined,
            (
                "停止使用我们的服务",
                "停止使用我們的服務",
                "停止使用",
                "无法在合理时间内",
                "無法在合理時間內",
                "集中风险",
                "集中風險",
            ),
        )
        has_retention_table = _has(
            combined,
            ("回头客", "回頭客", "客户流失率", "客戶流失率", "客户保留率", "客戶保留率"),
        )
        strong_fact = has_top_label and has_share
        if strong_fact:
            boost += 0.36 + min(chain_hits, 5) * 0.04
            reasons.append("major_customer_share_fact")
            if has_impact:
                boost += 0.08
                reasons.append("major_customer_loss_impact")
        elif has_top_label and has_impact:
            boost += 0.24
            reasons.append("major_customer_impact_only")
        elif has_named_major and has_share and has_impact and not has_retention_table:
            boost += 0.18
            reasons.append("named_major_customer_dependence")
        elif chain_hits >= 2 and has_top_label:
            boost += 0.10
            reasons.append("partial_concentration_signal")
        # Hard negatives: retention/margin/history near-misses without top-customer share facts.
        if has_retention_table and not strong_fact:
            penalty += 0.28
            reasons.append("retention_table_without_top_customer_dependence")
        if _has(combined, CUSTOMER_CONCENTRATION_NOISE) and not strong_fact:
            penalty += 0.16
            reasons.append("concentration_near_miss_noise")
        if _has(combined, ("毛利率", "利润率")) and not strong_fact:
            penalty += 0.14
            reasons.append("margin_story_without_customer_share")
        if _has(combined, ("经营历史有限", "經營歷史有限", "快速增长", "快速增長")) and not strong_fact:
            penalty += 0.14
            reasons.append("ops_history_growth_boilerplate")
        if has_named_major and not strong_fact and not has_impact:
            # bare "主要客户" without share/impact dependence should not win.
            penalty += 0.08
            reasons.append("named_customer_without_share_fact")
    elif intent == "connected_transaction_governance":
        if _has(combined, CONNECTED_TX_TERMS):
            boost += 0.18
            reasons.append("connected_tx_disclosure")
        if _has(combined, ("与关联方的合作", "关联方进行大量业务交易")) and not _has(combined, ("持续关连交易", "关连交易", "非获豁免")):
            # business relationship narrative without governance/listing-rule framing
            penalty += 0.06
            reasons.append("related_party_ops_without_connected_tx_frame")
    elif intent == "pre_ipo_rights":
        cov = preipo_terms_coverage(result.text or "")
        dims = cov["dims"]
        complete_n = int(cov["score"])
        # Full term package: valuation/pricing + discount% + lockup + rights conclusion.
        if complete_n >= 4:
            boost += 0.48
            reasons.append("preipo_complete_terms_package")
            if cov.get("table_like"):
                boost += 0.04
                reasons.append("preipo_terms_table_like")
        elif complete_n == 3:
            boost += 0.30
            reasons.append("preipo_strong_partial_terms")
        elif complete_n == 2:
            boost += 0.12
            reasons.append("preipo_partial_terms")
        elif complete_n == 1:
            boost += 0.04
            reasons.append("preipo_single_term")
        # Half-package background: investment rounds / total amount without pricing+rights conclusion.
        if cov["background_only"] or (
            complete_n <= 2
            and dims.get("lockup")
            and not dims.get("discount")
            and not dims.get("rights")
            and _has(combined, ("总投资", "總投資", "两轮", "兩輪", "所得款项总额", "所得款項總額", "1%", "股權", "股权"))
        ):
            penalty += 0.22
            reasons.append("preipo_half_package_overview")
        if cov["sponsor_opinion"] and complete_n < 3:
            penalty += 0.28
            reasons.append("preipo_sponsor_opinion_without_terms")
        # Use-of-proceeds / listing expense / corporate structure noise under pre-IPO terms questions.
        if _has(combined, ("所得款项用途", "所得款項用途", "上市开支", "上市開支", "包销佣金", "包銷佣金")) and complete_n < 3:
            penalty += 0.18
            reasons.append("preipo_uop_or_listing_expense_noise")
        if _has(combined, ("公司架构", "公司架構", "股權架構", "股权架构", "重组", "重組")) and complete_n < 2:
            penalty += 0.14
            reasons.append("preipo_structure_noise")

    delta_cap = 0.55
    boost = max(0.0, min(boost, delta_cap))
    penalty = max(0.0, min(penalty, delta_cap))
    return ExcerptScore(
        intent=intent,
        boost=boost,
        penalty=penalty,
        reason="+".join(reasons) if reasons else "neutral",
    )


def rerank_answer_excerpt(query: str, results: List[SearchResult]) -> List[SearchResult]:
    if not results:
        return results
    intent = infer_excerpt_intent(query)
    if intent == "generic_other":
        return results

    rescored = []
    for index, result in enumerate(results):
        scored = score_answer_excerpt(query, result)
        result.score = float(result.score) + scored.boost - scored.penalty
        if result.metadata is None:
            result.metadata = {}
        result.metadata["answer_excerpt_intent"] = scored.intent
        result.metadata["answer_excerpt_boost"] = round(scored.boost, 4)
        result.metadata["answer_excerpt_penalty"] = round(scored.penalty, 4)
        result.metadata["answer_excerpt_reason"] = scored.reason
        rescored.append((result.score, -index, result))
    rescored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in rescored]
