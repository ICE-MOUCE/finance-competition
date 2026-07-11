"""
Retriever Layer - 配置
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class RetrieverConfig:
    """检索器配置"""
    top_k: int = 10
    min_score: float = 0.3
    enable_layer_filter: bool = True


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
