from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RetrieverConfig:
    """检索器配置"""
    top_k: int = 10
    min_score: float = 0.3
    enable_layer_filter: bool = True
    # P0 ranking experiments (default off so baseline is reproducible)
    enable_sufficiency_rerank: bool = False
    enable_intent_multiquery: bool = False
    enable_section_hard_prior: bool = False
    enable_ipo_specific_rerank: bool = False
    enable_answer_excerpt_rerank: bool = False
    enable_evidence_role_rerank: bool = False
    enable_related_party_quant_complement: bool = False
    candidate_pool_multiplier: int = 3
    max_intent_aux_queries: int = 2
    ranking_profile: str = "default"


# Layer关键词映射
LAYER_KEYWORDS: Dict[str, List[str]] = {
    "financial": [
        "财务", "財務", "现金流", "現金流", "现金", "現金", "流动资金", "流動資金",
        "收入", "收益", "利润", "利潤", "溢利", "资产负债", "資產負債", "资产", "資產",
        "负债", "負債", "盈利", "亏损", "虧損", "银行借款", "銀行借款",
    ],
    "legal": [
        "法律", "合规", "合規", "监管", "監管", "诉讼", "訴訟", "仲裁", "法规", "法規",
        "处罚", "處罰", "罚款", "罰款", "纠纷", "糾紛", "不合規", "牌照",
    ],
    "governance": [
        "股权", "股權", "董事", "管理层", "管理層", "薪酬", "关联交易", "關聯交易",
        "高管", "股东", "股東", "投票权", "投票權", "控股股東", "不同投票權",
    ],
    "market": [
        "市场", "市場", "竞争", "競爭", "客户", "客戶", "供应商", "供應商", "行业",
        "行業", "份额", "份額", "增长", "增長", "需求", "市場份額",
    ],
}


def normalize_ranking_profile(profile: Optional[str]) -> str:
    raw = str(profile or "default").strip().lower()
    if raw in {"hge", "h+g+e", "h_plus_g_plus_e", "eval", "demo", "hge_role", "h+g+e+role"}:
        return "hge"
    return "default"


def build_retriever_config(
    profile: str = "default",
    *,
    top_k: Optional[int] = None,
    **overrides,
) -> RetrieverConfig:
    """Factory for default vs H+G+E ranking profiles.

    Defaults stay safe/off. The HGE profile is opt-in for eval/demo only.
    HGE includes evidence-role awareness and related-party quant complement (opt-in table/quant merge).
    """
    name = normalize_ranking_profile(profile)
    if name == "hge":
        cfg = RetrieverConfig(
            enable_sufficiency_rerank=False,
            enable_intent_multiquery=True,
            enable_section_hard_prior=False,
            enable_ipo_specific_rerank=True,
            enable_answer_excerpt_rerank=True,
            enable_evidence_role_rerank=True,
            enable_related_party_quant_complement=True,
            ranking_profile="hge",
        )
    else:
        cfg = RetrieverConfig(ranking_profile="default")
    if top_k is not None:
        cfg.top_k = int(top_k)
    for key, value in overrides.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg
