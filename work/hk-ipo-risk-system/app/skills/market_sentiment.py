from __future__ import annotations

from .base import BaseSkill, SkillContext, format_claims, format_evidence, format_prediction


class MarketSentimentSkill(BaseSkill):
    skill_id = "market_sentiment"
    agent_name = "MARKET_SENTIMENT_AGENT"
    label = "市场情绪 Agent"
    description = "评估 IPO 窗口、板块映射、认购与情绪共振，强调时点一致性与 PREDICT 禁未来数据。"
    # Prefer DeepSeek by default: Doubao currently needs DOUBAO_API_KEY (Ark key),
    # while AK/SK alone cannot pass chat/completions auth.
    default_provider = "deepseek"
    temperature = 0.15
    role_color = "#5d7092"

    def build_system_prompt(self, context: SkillContext) -> str:
        base = super().build_system_prompt(context)
        return (
            base
            + "你是投行资本市场 / 市场情绪负责人。"
            + "评估 IPO 窗口、板块映射、认购热度与情绪共振。"
            + "PREDICT 模式下严禁使用 prediction_as_of 之后的信息；"
            + "不得编造发行结果或二级市场走势。"
        )

    def build_user_prompt(self, context: SkillContext) -> str:
        market_claims = [
            item
            for item in context.claims
            if str(item.get("risk_code", "")).startswith("MKT_")
            or "市场" in str(item.get("claim", ""))
            or "认购" in str(item.get("claim", ""))
            or "窗口" in str(item.get("claim", ""))
        ]
        related = market_claims or [
            item for item in context.claims if item.get("audit_status") in {"accepted", "revised"}
        ] or context.claims
        return f"""
【任务】对 {context.company_name} ({context.stock_code}) 做市场情绪会诊。
模式={context.mode} | 上市日={context.listing_date} | as_of={context.prediction_as_of}

【相关风险结论】
{format_claims(related, 10)}

【证据片段】
{format_evidence(context.evidence, 8)}

【结构化模型/规则结果】
{format_prediction(context.prediction)}

【协作板】
{context.shared_board}

要求：只输出规定五段标题；明确时点边界；禁止寒暄与粘贴原始输入。
""".strip()
