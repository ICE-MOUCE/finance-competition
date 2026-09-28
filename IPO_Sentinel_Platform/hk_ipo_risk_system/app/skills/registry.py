from __future__ import annotations

from typing import Iterable

from .base import BaseSkill
from .financial_dd import FinancialDDSkill
from .legal_compliance import LegalComplianceSkill
from .market_sentiment import MarketSentimentSkill
from .orchestrator_decision import OrchestratorSkill
from .rag_retrieval import RagRetrievalSkill
from .category_skills import EquityRiskSkill, BusinessRiskSkill, NonstandardRiskSkill


# These are the six visible seats in Agent 会诊室. RAG retrieval and the
# orchestrator remain registered as internal capabilities, but are not seats.
DEFAULT_SKILL_ORDER = [
    "financial_risk",
    "legal_risk",
    "equity_risk",
    "business_risk",
    "market_risk",
    "nonstandard_risk",
]

INTERNAL_SKILL_ORDER = ["rag_retrieval", *DEFAULT_SKILL_ORDER, "orchestrator_decision"]


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, type[BaseSkill]] = {}
        self.register_defaults()

    def register(self, skill_cls: type[BaseSkill]) -> None:
        self._skills[skill_cls.skill_id] = skill_cls

    def register_defaults(self) -> None:
        for skill_cls in (
            RagRetrievalSkill,
            LegalComplianceSkill,
            FinancialDDSkill,
            MarketSentimentSkill,
            EquityRiskSkill,
            BusinessRiskSkill,
            NonstandardRiskSkill,
            OrchestratorSkill,
        ):
            self.register(skill_cls)

    def get(self, skill_id: str) -> type[BaseSkill]:
        if skill_id not in self._skills:
            raise KeyError(f"skill not registered: {skill_id}")
        return self._skills[skill_id]

    def create(self, skill_id: str, provider: str | None = None) -> BaseSkill:
        return self.get(skill_id)(provider=provider)

    def list_manifests(self) -> list[dict]:
        items = [cls().manifest for cls in self._skills.values()]
        order = {skill_id: index for index, skill_id in enumerate(INTERNAL_SKILL_ORDER)}
        items.sort(key=lambda item: order.get(item["skill_id"], 999))
        visible = set(DEFAULT_SKILL_ORDER)
        return [item for item in items if item["skill_id"] in visible]

    def resolve_order(self, skill_ids: Iterable[str] | None = None) -> list[str]:
        if not skill_ids:
            return list(DEFAULT_SKILL_ORDER)
        known = [item for item in skill_ids if item in self._skills]
        # Always put the hidden orchestrator last if explicitly requested.
        others = [item for item in known if item != "orchestrator_decision"]
        if "orchestrator_decision" in known:
            others.append("orchestrator_decision")
        return others


skill_registry = SkillRegistry()
