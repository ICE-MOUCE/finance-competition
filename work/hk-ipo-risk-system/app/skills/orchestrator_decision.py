from __future__ import annotations

from .base import BaseSkill, SkillContext, format_claims, format_prediction


class OrchestratorSkill(BaseSkill):
    skill_id = "orchestrator_decision"
    agent_name = "ORCHESTRATOR_AGENT"
    label = "总控决策 Agent"
    description = "汇总专家意见、裁决冲突、标注缺口，形成可追踪的最终会诊决议。"
    default_provider = "deepseek"
    temperature = 0.1
    role_color = "#e86452"

    def build_system_prompt(self, context: SkillContext) -> str:
        base = super().build_system_prompt(context)
        return (
            base
            + "你是投行项目总控 / 决策委员会主席。"
            + "汇总法务、财务、市场意见，裁决冲突，标记缺口，给出最终决议。"
            + "主要风险仅可引用 accepted/revised；概率只能引用系统模型，不可改写。"
        )

    def build_user_prompt(self, context: SkillContext) -> str:
        prior = context.prior_messages or []
        prior_text = "\n\n".join(
            f"### {item.get('label') or item.get('agent_name')}\n"
            f"摘要: {item.get('summary') or ''}\n"
            f"{(item.get('content') or '')[:1200]}"
            for item in prior
        ) or "（尚无专家意见）"
        return f"""
【任务】对 {context.company_name} ({context.stock_code}) 形成总控会诊决议。
模式={context.mode} | as_of={context.prediction_as_of}

【系统已审计结论】
{format_claims(context.claims, 12)}

【结构化模型结果】
{format_prediction(context.prediction)}

【专家会诊意见】
{prior_text}

【共享协作板】
{context.shared_board}

要求：只输出规定五段标题；决议必须可执行；禁止寒暄与长文复述。
""".strip()
