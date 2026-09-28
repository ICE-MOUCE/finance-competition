from __future__ import annotations

from .base import BaseSkill, SkillContext, format_claims, format_evidence, format_prediction


class CategoryRiskSkill(BaseSkill):
    """Shared implementation for the six visible Agent Room risk seats."""

    risk_prefixes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    focus: str = ""

    def build_system_prompt(self, context: SkillContext) -> str:
        return (
            super().build_system_prompt(context)
            + f"你是投行{self.label.replace(' Agent', '')}负责人。"
            + f"重点评估{self.focus}。"
            + "只能使用已提供的 claims、evidence 和结构化结果；没有证据时明确写出缺口。"
        )

    def build_user_prompt(self, context: SkillContext) -> str:
        related = [
            item for item in context.claims
            if any(str(item.get("risk_code", "")).startswith(prefix) for prefix in self.risk_prefixes)
            or any(keyword in str(item.get("claim", "")) for keyword in self.keywords)
        ]
        related = related or [
            item for item in context.claims
            if item.get("audit_status") in {"accepted", "revised"}
        ] or context.claims
        return f"""
【任务】对 {context.company_name} ({context.stock_code}) 做{self.label.replace(' Agent', '')}会诊。
模式={context.mode} | 上市日={context.listing_date} | as_of={context.prediction_as_of}

【相关风险结论】
{format_claims(related, 12)}

【证据片段】
{format_evidence(context.evidence, 10)}

【结构化模型/规则结果】
{format_prediction(context.prediction)}

【协作板】
{context.shared_board}

要求：只输出规定五段标题；围绕本席位职责给出风险、证据和可执行建议；禁止寒暄与长文复述。
""".strip()


class EquityRiskSkill(CategoryRiskSkill):
    skill_id = "equity_risk"
    agent_name = "EQUITY_RISK_AGENT"
    label = "股权风险 Agent"
    description = "审查股权结构、控制权、特殊权利、稀释、锁定期与股东安排。"
    role_color = "#9270ca"
    risk_prefixes = ("EQUITY_",)
    keywords = ("股权", "控制权", "投票", "稀释", "禁售", "锁定", "赎回", "对赌")
    focus = "股权结构、控制权稳定性、特殊股东权利、稀释风险和锁定期安排"


class BusinessRiskSkill(CategoryRiskSkill):
    skill_id = "business_risk"
    agent_name = "BUSINESS_RISK_AGENT"
    label = "经营风险 Agent"
    description = "审查客户供应商依赖、产品管线、商业化、技术与业务模式稳定性。"
    role_color = "#d48806"
    risk_prefixes = ("BIZ_",)
    keywords = ("客户", "供应商", "管线", "商业化", "产品", "业务模式", "竞争", "产能")
    focus = "客户与供应商集中、产品管线、商业化能力、技术依赖和竞争格局"


class NonstandardRiskSkill(CategoryRiskSkill):
    skill_id = "nonstandard_risk"
    agent_name = "NONSTANDARD_RISK_AGENT"
    label = "非标风险 Agent"
    description = "审查对赌、回购、优先权、特殊表决、异常承诺及难以量化的非标准安排。"
    role_color = "#cf6679"
    risk_prefixes = ("TEXT_", "EQUITY_")
    keywords = ("非标", "对赌", "回购", "回赎", "优先", "特殊安排", "无法量化", "不能保证", "重大不利")
    focus = "非标准条款、特殊权利、异常承诺、模糊披露和关键风险量化缺口"
