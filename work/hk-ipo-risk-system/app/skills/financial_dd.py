from __future__ import annotations

from .base import BaseSkill, SkillContext, format_claims, format_evidence, format_prediction


class FinancialDDSkill(BaseSkill):
    skill_id = "financial_dd"
    agent_name = "FINANCIAL_DD_AGENT"
    label = "财务穿透 Agent"
    description = "穿透现金续航、现金流、盈利质量、杠杆、集中度、关联交易与募资用途。"
    default_provider = "deepseek"
    temperature = 0.1
    role_color = "#5ad8a6"

    def build_system_prompt(self, context: SkillContext) -> str:
        base = super().build_system_prompt(context)
        return (
            base
            + "你是投行财务尽调负责人。"
            + "聚焦现金续航、经营现金流、盈利质量、杠杆偿债、集中度、关联交易与募资用途。"
            + "数值必须来自给定证据或系统结构化结果，不得编造。"
        )

    def build_user_prompt(self, context: SkillContext) -> str:
        fin_claims = [
            item
            for item in context.claims
            if str(item.get("risk_code", "")).startswith("FIN_")
            or "现金" in str(item.get("claim", ""))
            or "负债" in str(item.get("claim", ""))
        ]
        related = fin_claims or [
            item for item in context.claims if item.get("audit_status") in {"accepted", "revised"}
        ] or context.claims
        return f"""
【任务】对 {context.company_name} ({context.stock_code}) 做财务穿透会诊。
模式={context.mode} | 发行价={context.issue_price} | as_of={context.prediction_as_of}

【相关风险结论】
{format_claims(related, 10)}

【证据片段】
{format_evidence(context.evidence, 8)}

【结构化模型/规则结果】
{format_prediction(context.prediction)}

【协作板】
{context.shared_board}

要求：只输出规定五段标题，突出高风险点与证据缺口，禁止寒暄与长文复述。
""".strip()
