from __future__ import annotations

from .base import BaseSkill, SkillContext, format_evidence


class RagRetrievalSkill(BaseSkill):
    skill_id = "rag_retrieval"
    agent_name = "RAG_RETRIEVAL_AGENT"
    label = "RAG 检索 Agent"
    description = "调用 Thin RAG API 检索招股书证据，先检索再交给专家推理。"
    default_provider = "offline"
    temperature = 0.0
    role_color = "#6b8cae"

    def build_user_prompt(self, context: SkillContext) -> str:
        retrieved = list(context.extra.get("retrieved_evidence") or context.evidence)
        queries = context.extra.get("rag_queries") or {}
        warnings = context.extra.get("rag_warnings") or []
        document_id = context.extra.get("rag_document_id") or context.parse_metadata.get("document_id")
        query_lines = "\n".join(f"- {name}: {query}" for name, query in queries.items()) or "（无检索词）"
        warning_text = "；".join(str(item) for item in warnings[:6]) or "无"
        return f"""
【任务】为 {context.company_name} ({context.stock_code}) 准备 RAG 证据包。
模式={context.mode} | as_of={context.prediction_as_of} | document_id={document_id}

【检索词】
{query_lines}

【命中证据】
{format_evidence(retrieved, 10)}

【警告】
{warning_text}

要求：只输出规定五段标题；说明是否足够支撑专家尽调；禁止编造 evidence_id。
""".strip()