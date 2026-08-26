from __future__ import annotations

from typing import Iterable

from .base import BaseSkill
from .financial_dd import FinancialDDSkill
from .legal_compliance import LegalComplianceSkill
from .market_sentiment import MarketSentimentSkill
from .orchestrator_decision import OrchestratorSkill
from .rag_retrieval import RagRetrievalSkill


# One agent = one skill. New skills can be registered without changing the room core.
DEFAULT_SKILL_ORDER = [
    "rag_retrieval",
    "legal_compliance",
    "financial_dd",
    "market_sentiment",
    "orchestrator_decision",
]


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
        order = {skill_id: index for index, skill_id in enumerate(DEFAULT_SKILL_ORDER)}
        items.sort(key=lambda item: order.get(item["skill_id"], 999))
        return items

    def resolve_order(self, skill_ids: Iterable[str] | None = None) -> list[str]:
        if not skill_ids:
            return list(DEFAULT_SKILL_ORDER)
        known = [item for item in skill_ids if item in self._skills]
        # Always put orchestrator last if present.
        others = [item for item in known if item != "orchestrator_decision"]
        if "orchestrator_decision" in known:
            others.append("orchestrator_decision")
        return others


skill_registry = SkillRegistry()
