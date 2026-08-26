from __future__ import annotations

from app.llm.base import ChatMessage
from app.llm.factory import OfflineLLMClient, get_llm_client, llm_status
from app.skills import DEFAULT_SKILL_ORDER, skill_registry
from app.skills.base import SkillContext, extract_sections, pick_summary


def test_skill_registry_contains_core_skills():
    manifests = skill_registry.list_manifests()
    ids = [item["skill_id"] for item in manifests]
    assert ids == DEFAULT_SKILL_ORDER
    assert ids[0] == "rag_retrieval"
    ordered = skill_registry.resolve_order([
        "market_sentiment",
        "legal_compliance",
        "orchestrator_decision",
        "financial_dd",
    ])
    assert ordered[-1] == "orchestrator_decision"
    market = next(item for item in manifests if item["skill_id"] == "market_sentiment")
    assert market["default_provider"] == "deepseek"


def test_offline_skill_run_returns_content():
    skill = skill_registry.create("legal_compliance", provider="offline")
    context = SkillContext(
        analysis_id="analysis_demo",
        company_name="Demo Co",
        stock_code="09999.HK",
        mode="PREDICT",
        listing_date="2025-01-01",
        prediction_as_of="2024-12-31T00:00:00+08:00",
        issue_price=10.0,
        claims=[{
            "risk_code": "LEGAL_LITIGATION",
            "claim": "exists litigation",
            "severity": 7,
            "confidence": 0.8,
            "audit_status": "accepted",
            "evidence_ids": ["ev_1"],
        }],
        evidence=[{
            "evidence_id": "ev_1",
            "page": 12,
            "section_path": ["Risk Factors"],
            "text": "litigation disclosure",
        }],
        prediction={"model_version": None, "rule_score": 12, "probabilities": None},
        parse_metadata={"pages": 10},
    )
    result = skill.run(context)
    assert result.agent_name == "LEGAL_COMPLIANCE_AGENT"
    assert result.content
    assert result.status in {"success", "degraded"}
    assert "结论摘要" in result.content or result.summary
    assert result.risks or result.findings or result.recommendations


def test_offline_llm_client_chat():
    client = OfflineLLMClient()
    response = client.chat([
        ChatMessage(role="system", content="legal expert"),
        ChatMessage(role="user", content="discuss litigation risk"),
    ])
    assert response.provider == "offline"
    assert "offline" in response.content.lower() or "离线" in response.content
    assert "结论摘要" in response.content


def test_get_llm_client_offline_provider():
    get_llm_client.cache_clear()
    client = get_llm_client("offline")
    assert isinstance(client, OfflineLLMClient)
    get_llm_client.cache_clear()


def test_section_parser_picks_summary():
    text = """
## 结论摘要
项目风险中等，需补证据。

## 主要风险
- FIN_LEVERAGE 杠杆偏高
- LEGAL_DATA 证据不足

## 建议
- 补齐债务明细
"""
    sections = extract_sections(text)
    assert "summary" in sections
    summary = pick_summary(text)
    assert "中等" in summary or "证据" in summary


def test_doubao_without_api_key_is_not_ready():
    status = llm_status()
    # If only AK/SK present in env, ready should track API key, not AK/SK.
    assert "doubao" in status
    assert "ready" in status["doubao"]
    assert status["doubao"]["ready"] == status["doubao"]["has_api_key"]
