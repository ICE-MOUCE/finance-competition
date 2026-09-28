"""Small rule-based query intent expansion for single-document retrieval."""
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

from .term_normalization import normalize_text


INTENT_AUX_QUERIES: Dict[str, List[str]] = {
    "use_of_proceeds": [
        "未来计划及所得款项用途 所得款项净额 百分比 港元",
        "所得款项用途 募资 用于 预计",
    ],
    "pre_ipo_rights": [
        "首次公开发售前投资 市盈率 每股成本 发售价折让 禁售 特别权利",
        "Pre-IPO 投资者 协定市盈率 折让 禁售期 无权享有特别权利",
    ],
    "no_litigation": [
        "并无尚未完结或面临重大诉讼或申索",
        "概无任何待决或遭受威胁的重大诉讼 仲裁 申索",
    ],
    "admin_compliance_gap": [
        "社会保险 住房公积金 未足额 缴纳 滞纳金 罚款",
        "许可证 牌照 批文 合规 处罚 监管",
    ],
    "connected_transaction": [
        "关连交易 关联方交易 控股股东 持续关连交易",
        "关联方 收入 占比 独立客户 控股股东",
    ],
    # Narrow business-risk consequence chains (aux only; do not boost financing/market-size noise).
    "customer_credit_deterioration": [
        "客户财政困难 延迟付款 无法履行付款责任 修改付款安排",
        "贸易应收 客户付款 营运资金 流失客户",
    ],
    "competitive_pricing_pressure": [
        "竞争激烈 进入壁垒低 议价能力 降价",
        "利润减少 失去市场地位 流失客户 收入减少",
    ],
    "customer_concentration": [
        "五大客户 最大客户 收入贡献 客户集中",
        "主要客户 停止使用我们的服务 客户流失 总收入",
    ],
    # Working-capital mechanism: prepay/advance + collection timing mismatch + negative OCF.
    # Prefer mechanism narrative over pure cash-flow statement / single OCF footnote.
    "working_capital_mechanism": [
        "预付款项 垫付款 时间错配 贸易应收款项 流动资金风险",
        "向媒体 虚拟代币 收到客户付款 经营现金流 营运资金",
    ],
}


def infer_query_intent(query: str) -> str:
    q = normalize_text(query)
    # Order matters: specific business consequence chains before broader finance/market cues.
    if any(
        term in q
        for term in [
            "主要客户",
            "五大客户",
            "最大客户",
            "客户集中",
            "客户集中度",
            "少数主要客户",
            "依赖少数",
            "高度依赖",
        ]
    ) and any(
        term in q
        for term in [
            "客户",
            "客戶",
            "流失",
            "依赖",
            "依賴",
            "集中",
            "收入",
            "影响",
            "影響",
        ]
    ):
        return "customer_concentration"
    if any(term in q for term in ["五大客户", "最大客户", "客户集中度", "主要客户流失", "依赖少数主要客户"]):
        return "customer_concentration"
    # Working-capital timing/prepay mechanism (before broad customer-credit cues).
    # Require explicit prepay/advance/mismatch cues; bare 回款+营运资金 stays customer_credit.
    has_wc_or_ocf = any(
        term in q
        for term in [
            "负经营现金流",
            "負經營現金流",
            "负经营现金流量",
            "負經營現金流量",
            "经营现金流",
            "經營現金流",
            "经营现金流量",
            "經營現金流量",
            "营运资金",
            "營運資金",
            "流动资金",
            "流動資金",
        ]
    )
    has_prepay_or_mismatch = any(
        term in q
        for term in [
            "垫付",
            "墊付",
            "预付",
            "預付",
            "错配",
            "錯配",
            "时间错配",
            "時間錯配",
            "回款错配",
        ]
    )
    # Optional stronger OCF + mismatch/prepay pair even if WC word absent.
    has_ocf = any(
        term in q
        for term in [
            "负经营现金流",
            "負經營現金流",
            "负经营现金流量",
            "負經營現金流量",
            "经营现金流",
            "經營現金流",
        ]
    )
    if has_prepay_or_mismatch and (has_wc_or_ocf or has_ocf):
        return "working_capital_mechanism"
    if any(
        term in q
        for term in [
            "客户财务",
            "客户财政",
            "付款能力",
            "延迟付款",
            "延遲付款",
            "财政困难",
            "財務狀況惡化",
            "财务状况恶化",
            "回款",
            "贸易应收",
        ]
    ) and any(
        term in q
        for term in [
            "营运资金",
            "營運資金",
            "流失客户",
            "流失客戶",
            "接单",
            "接單",
            "付款",
            "回款",
            "压力",
            "壓力",
        ]
    ):
        # If also clearly a prepay/timing-mismatch working-capital mechanism question,
        # keep the more specific intent (already returned above).
        return "customer_credit_deterioration"
    if any(term in q for term in ["客户财务状况恶化", "付款能力下降", "客户财政困难", "延迟向我们付款"]):
        return "customer_credit_deterioration"
    if any(term in q for term in ["财政困难", "财务状况恶化", "付款能力"]) and any(
        term in q for term in ["客户", "客戶", "回款", "营运资金", "營運資金"]
    ):
        return "customer_credit_deterioration"
    if any(
        term in q
        for term in [
            "竞争加剧",
            "竞争激烈",
            "競爭加劇",
            "競爭激烈",
            "降价",
            "降價",
            "定价压力",
            "定價壓力",
        ]
    ) and any(
        term in q
        for term in [
            "利润",
            "利潤",
            "客户流失",
            "客戶流失",
            "流失客户",
            "流失客戶",
            "收入减少",
            "收入減少",
            "市场地位",
            "市場地位",
        ]
    ):
        return "competitive_pricing_pressure"
    if any(term in q for term in ["竞争加剧", "竞争激烈", "進入壁壘", "进入壁垒"]) and any(
        term in q for term in ["降价", "降價", "利润下降", "利潤下降", "客户流失", "流失"]
    ):
        return "competitive_pricing_pressure"
    if any(term in q for term in ["所得款项", "募资", "募集资金", "上市所得", "用途"]):
        return "use_of_proceeds"
    if any(term in q for term in ["首次公开发售前", "发售前投资", "preipo", "特殊权利", "禁售"]):
        return "pre_ipo_rights"
    if any(term in q for term in ["不存在重大诉讼", "无重大诉讼", "并无", "概无", "待决", "申索"]):
        return "no_litigation"
    if any(term in q for term in ["社会保险", "住房公积金", "未足额", "合规缺口", "许可证", "牌照", "处罚"]):
        return "admin_compliance_gap"
    if any(term in q for term in ["关连交易", "关联交易", "关联方", "关连方", "控股股东"]):
        return "connected_transaction"
    if any(term in q for term in ["发售价", "发行价", "交易价格", "成交价", "公开市场", "流动性", "波动", "重大损失"]):
        return "share_price_volatility"
    return "generic_other"


def build_intent_queries(query: str, max_aux_queries: int = 2) -> List[str]:
    intent = infer_query_intent(query)
    if intent == "generic_other" or max_aux_queries <= 0:
        return []
    queries = [f"{query} {aux}" for aux in INTENT_AUX_QUERIES.get(intent, [])]
    return list(dict.fromkeys(q for q in queries if q.strip()))[:max_aux_queries]


def merge_multiquery_results(primary: List[dict], auxiliary_runs: Iterable[List[dict]]) -> List[dict]:
    merged: Dict[str, dict] = {}

    def add(item: dict) -> None:
        key = str(item.get("chunk_id") or id(item))
        score = float(item.get("score") or 0.0)
        current = merged.get(key)
        if current is None or score > float(current.get("score") or 0.0):
            merged[key] = dict(item)

    for item in primary:
        add(item)
    for run in auxiliary_runs:
        for item in run:
            add(item)
    return sorted(merged.values(), key=lambda item: float(item.get("score") or 0.0), reverse=True)


def section_hard_prior_score(query: str, section_path: Sequence[str], text: str) -> float:
    intent = infer_query_intent(query)
    section = normalize_text(" ".join(str(item) for item in (section_path or [])))
    body = normalize_text(text or "")
    combined = section + body[:1200]

    if intent == "use_of_proceeds":
        if "未来计划及所得款项用途" in section or "所得款项用途" in section:
            return 0.48
        if "所得款项" in body and any(term in body for term in ["将用于", "预期将用于", "拟用于"]) and ("%" in body or "港元" in body):
            return 0.18
        if "上市开支" in body and "将用于" not in body:
            return -0.12
    if intent == "pre_ipo_rights":
        if "首次公开发售前投资" in combined and any(term in combined for term in ["特殊权利", "特别权利", "禁售", "折让"]):
            return 0.42
        if "历史" in section and "重组" in section and "首次公开发售前投资" in body:
            return 0.32
    if intent == "no_litigation":
        if any(term in combined for term in ["并无尚未完结", "概无任何待决", "无尚未完结", "重大诉讼或申索"]):
            return 0.48
        if any(term in section for term in ["法定及一般资料", "附录"]) and "诉讼" in combined:
            return 0.24
    if intent == "admin_compliance_gap":
        has_gap = any(term in combined for term in ["社会保险", "住房公积金", "未足额", "未完成", "许可证", "牌照"])
        has_consequence = any(term in combined for term in ["罚款", "滞纳金", "处罚", "补缴", "吊销"])
        if has_gap and has_consequence:
            return 0.42
    if intent == "connected_transaction":
        if any(term in combined for term in ["持续关连交易", "关连交易", "关联方交易", "关联方"]) and any(
            term in combined for term in ["控股股东", "收入", "收益", "占"]
        ):
            return 0.32
    if intent == "customer_credit_deterioration":
        has_trigger = any(
            term in combined
            for term in ["财政困难", "财务状况恶化", "延迟付款", "延遲付款", "无法履行付款", "修改付款", "无力偿债", "破产"]
        )
        has_consequence = any(
            term in combined for term in ["营运资金", "營運資金", "流失客户", "流失客戶", "贸易应收", "客户付款"]
        )
        if has_trigger and has_consequence:
            return 0.36
        if has_trigger:
            return 0.18
        # demote pure internal financing noise under this intent
        if any(term in combined for term in ["银行贷款", "股东贷款", "业务保理", "内部产生资金"]) and not has_trigger:
            return -0.10
    if intent == "customer_concentration":
        has_top_customers = any(
            term in combined
            for term in ["五大客户", "五大客戶", "最大客户", "最大客戶", "主要客户", "主要客戶", "现有主要客户", "現有主要客戶"]
        )
        has_share = any(term in combined for term in ["%", "总收入", "總收入", "收入贡献", "收入貢獻", "占比", "佔"])
        has_loss_impact = any(
            term in combined
            for term in ["停止使用", "客户流失", "客戶流失", "无法在合理时间", "無法在合理時間", "集中风险", "集中風險"]
        )
        if has_top_customers and (has_share or has_loss_impact):
            return 0.40
        if has_top_customers:
            return 0.18
        if any(term in combined for term in ["毛利率", "经营历史有限", "經營歷史有限", "复合年增长率", "複合年增長率"]) and not has_top_customers:
            return -0.12
    if intent == "competitive_pricing_pressure":
        has_competition = any(
            term in combined
            for term in [
                "竞争激烈",
                "竞争加剧",
                "更趋激烈",
                "更趨激烈",
                "日趋激烈",
                "日趨激烈",
                "進入壁壘",
                "进入壁垒",
                "议价能力",
                "議價能力",
            ]
        ) or ("竞争" in combined and "激烈" in combined)
        has_consequence = any(
            term in combined
            for term in [
                "降价",
                "降價",
                "利润减少",
                "利潤減少",
                "利润下降",
                "利潤下降",
                "流失客户",
                "流失客戶",
                "收入减少",
                "收入減少",
                "失去市场地位",
                "失去市場地位",
            ]
        )
        if has_competition and has_consequence:
            return 0.36
        if has_consequence:
            return 0.16
        if any(term in combined for term in ["市场规模", "複合年增長率", "复合年增长率", "cagr", "行业前景"]) and not has_consequence:
            return -0.12
    return 0.0
