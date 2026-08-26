from __future__ import annotations

from .base import BaseSkill, SkillContext, format_claims, format_evidence


class LegalComplianceSkill(BaseSkill):
    skill_id = "legal_compliance"
    agent_name = "LEGAL_COMPLIANCE_AGENT"
    label = "法务合规 Agent"
    description = "审查诉讼、监管处罚、牌照、知识产权与数据合规风险，强调条款生命周期与证据闭环。"
    default_provider = "deepseek"
    temperature = 0.1
    role_color = "#f6bd16"

    def build_system_prompt(self, context: SkillContext) -> str:
        base = super().build_system_prompt(context)
        return (
            base
            + "你是投行法务合规尽调负责人。"
            + "只评估诉讼、监管、牌照、知识产权、数据合规与跨境合规。"
            + "已终止/已豁免条款不得作为现时风险；无证据不下结论。"
        )

    def build_user_prompt(self, context: SkillContext) -> str:
        legal_claims = [
            item
            for item in context.claims
            if str(item.get("risk_code", "")).startswith("LEGAL_")
            or "法" in str(item.get("claim", ""))
            or "监管" in str(item.get("claim", ""))
        ]
        related = legal_claims or [
            item for item in context.claims if item.get("audit_status") in {"accepted", "revised"}
        ] or context.claims
        return f"""
【任务】对 {context.company_name} ({context.stock_code}) 做法务合规会诊。
模式={context.mode} | 上市日={context.listing_date} | as_of={context.prediction_as_of}

【相关风险结论】
{format_claims(related, 10)}

【证据片段】
{format_evidence(context.evidence, 8)}

【协作板】
{context.shared_board}

要求：只输出规定五段标题，突出可执行重点，禁止寒暄与长文复述。
""".strip()
