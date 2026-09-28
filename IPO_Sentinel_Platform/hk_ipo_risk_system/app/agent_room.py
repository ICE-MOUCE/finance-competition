from __future__ import annotations

from datetime import datetime, timezone
import json
import traceback
import uuid
from typing import Any

from .config import Settings
from .database import Database
from .llm.factory import llm_status
from .skills import SkillContext, skill_registry


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRoomService:
    """Post-analysis multi-agent collaboration room.

    Runs after the deterministic analysis pipeline completes, so expert agents
    debate over audited claims/evidence instead of inventing probabilities.
    """

    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database

    def list_skills(self) -> list[dict]:
        return skill_registry.list_manifests()

    def providers(self) -> dict:
        return llm_status()

    def _load_context_payload(self, analysis_id: str) -> dict[str, Any]:
        analysis = self.database.get_analysis(analysis_id)
        if analysis is None:
            raise KeyError(f"analysis not found: {analysis_id}")
        claims = self.database.list_payloads("claims", analysis_id, limit=200)
        evidence = self.database.list_payloads("evidence", analysis_id, limit=80)
        # Prefer higher-severity accepted/revised claims for discussion.
        claims_sorted = sorted(
            claims,
            key=lambda item: (
                0 if item.get("audit_status") in {"accepted", "revised"} else 1,
                -int(item.get("severity") or 0),
            ),
        )
        return {
            "analysis": analysis,
            "claims": claims_sorted,
            "evidence": evidence,
            "prediction": analysis.get("prediction"),
            "parse_metadata": json.loads(analysis.get("parse_metadata_json") or "{}"),
        }

    def create_session(
        self,
        analysis_id: str,
        *,
        skill_ids: list[str] | None = None,
        provider_overrides: dict[str, str] | None = None,
        auto_start: bool = True,
        title: str | None = None,
    ) -> dict:
        payload = self._load_context_payload(analysis_id)
        analysis = payload["analysis"]
        if analysis.get("status") != "completed":
            raise ValueError("agent room requires a completed analysis")

        order = skill_registry.resolve_order(skill_ids)
        # The six risk seats are visible; the orchestrator is an internal
        # synthesis step that keeps the decision board populated.
        if "orchestrator_decision" not in order:
            order.append("orchestrator_decision")
        session_id = f"room_{uuid.uuid4().hex}"
        session = {
            "session_id": session_id,
            "analysis_id": analysis_id,
            "title": title
            or f"{analysis['company_name']} · 投行多智能体会诊",
            "status": "queued",
            "progress": 0,
            "stage": "会诊排队",
            "skill_order": order,
            "provider_overrides": provider_overrides or {},
            "company_name": analysis["company_name"],
            "stock_code": analysis["stock_code"],
            "mode": analysis["mode"],
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "error": None,
            "shared_board": {
                "objective": "围绕已审计证据与结论，完成财务、法务、股权、经营、市场与非标六类风险会诊。",
                "analysis_id": analysis_id,
                "model_version": (payload.get("prediction") or {}).get("model_version"),
            },
            "decision": None,
        }
        self.database.create_agent_session(session)
        self.database.add_agent_message(
            {
                "message_id": f"msg_{uuid.uuid4().hex}",
                "session_id": session_id,
                "analysis_id": analysis_id,
                "seq": 0,
                "role": "system",
                "agent_name": "SYSTEM",
                "skill_id": None,
                "title": "会诊室已创建",
                "summary": "等待专家 Agent 入场",
                "content": (
                    f"已接入分析 {analysis_id}。参与 Skill: {', '.join(order)}。"
                    "本轮只基于已完成分析的 claims/evidence/prediction 进行讨论。"
                ),
                "status": "success",
                "provider": None,
                "model": None,
                "payload_json": json.dumps({"skill_order": order}, ensure_ascii=False),
                "created_at": utcnow(),
            }
        )
        if auto_start:
            # Caller may execute in background; we still mark queued here.
            pass
        return self.get_session(session_id)

    def run_session(self, session_id: str) -> dict:
        session = self.database.get_agent_session(session_id)
        if session is None:
            raise KeyError(f"session not found: {session_id}")
        analysis_id = session["analysis_id"]
        try:
            payload = self._load_context_payload(analysis_id)
            analysis = payload["analysis"]
            order = session.get("skill_order") or skill_registry.resolve_order()
            overrides = session.get("provider_overrides") or {}
            prior_messages: list[dict] = []
            shared_board = dict(session.get("shared_board") or {})

            self.database.update_agent_session(
                session_id,
                status="running",
                progress=5,
                stage="专家会诊进行中",
                error=None,
            )

            total = max(len(order), 1)
            for index, skill_id in enumerate(order):
                skill_cls = skill_registry.get(skill_id)
                provider = overrides.get(skill_id) or overrides.get(skill_cls.agent_name)
                skill = skill_registry.create(skill_id, provider=provider)
                stage = f"{skill.label} 发言中"
                progress = int(10 + (index / total) * 80)
                self.database.update_agent_session(
                    session_id,
                    progress=progress,
                    stage=stage,
                )

                context = SkillContext(
                    analysis_id=analysis_id,
                    company_name=analysis["company_name"],
                    stock_code=analysis["stock_code"],
                    mode=analysis["mode"],
                    listing_date=analysis["listing_date"],
                    prediction_as_of=analysis["prediction_as_of"],
                    issue_price=analysis.get("issue_price"),
                    claims=payload["claims"],
                    evidence=payload["evidence"],
                    prediction=payload["prediction"],
                    parse_metadata=payload["parse_metadata"],
                    prior_messages=prior_messages,
                    shared_board=shared_board,
                    extra={
                        "retrieved_evidence": payload["evidence"],
                        "rag_document_id": payload["parse_metadata"].get("rag_document_id")
                        or payload["parse_metadata"].get("document_id"),
                        "rag_queries": payload["parse_metadata"].get("rag_queries") or {},
                        "rag_warnings": payload["parse_metadata"].get("rag_warnings") or [],
                    },
                )
                result = skill.run(context)
                message = {
                    "message_id": f"msg_{uuid.uuid4().hex}",
                    "session_id": session_id,
                    "analysis_id": analysis_id,
                    "seq": index + 1,
                    "role": "agent",
                    "agent_name": result.agent_name,
                    "skill_id": result.skill_id,
                    "title": result.title,
                    "summary": result.summary,
                    "content": result.content,
                    "status": result.status,
                    "provider": result.provider,
                    "model": result.model,
                    "payload_json": json.dumps(result.to_message(), ensure_ascii=False),
                    "created_at": utcnow(),
                }
                self.database.add_agent_message(message)

                prior_messages.append(
                    {
                        "agent_name": result.agent_name,
                        "label": skill.label,
                        "content": result.content,
                        "summary": result.summary,
                    }
                )
                shared_board[result.skill_id] = {
                    "summary": result.summary,
                    "status": result.status,
                    "provider": result.provider,
                    "model": result.model,
                }
                if skill_id == "orchestrator_decision":
                    shared_board["final_decision"] = result.summary
                    self.database.update_agent_session(
                        session_id,
                        decision=result.content,
                        shared_board=shared_board,
                    )
                else:
                    self.database.update_agent_session(session_id, shared_board=shared_board)

            self.database.update_agent_session(
                session_id,
                status="completed",
                progress=100,
                stage="会诊完成",
                error=None,
            )
        except Exception as exc:  # noqa: BLE001
            self.database.update_agent_session(
                session_id,
                status="failed",
                stage="会诊失败",
                error=f"{type(exc).__name__}: {exc}",
            )
            error_log = self.settings.runtime_root / f"{session_id}.error.log"
            error_log.write_text(traceback.format_exc(), encoding="utf-8")
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> dict:
        session = self.database.get_agent_session(session_id)
        if session is None:
            raise KeyError(session_id)
        messages = self.database.list_agent_messages(session_id)
        session["messages"] = messages
        session["skills"] = skill_registry.list_manifests()
        session["providers"] = llm_status()
        return session

    def list_sessions(self, analysis_id: str | None = None, limit: int = 30) -> list[dict]:
        return self.database.list_agent_sessions(analysis_id=analysis_id, limit=limit)

    def ask(
        self,
        session_id: str,
        *,
        skill_id: str,
        question: str,
        provider: str | None = None,
    ) -> dict:
        session = self.database.get_agent_session(session_id)
        if session is None:
            raise KeyError(session_id)
        payload = self._load_context_payload(session["analysis_id"])
        analysis = payload["analysis"]
        prior = self.database.list_agent_messages(session_id)
        prior_messages = [
            {
                "agent_name": item.get("agent_name"),
                "label": item.get("title"),
                "content": item.get("content"),
                "summary": item.get("summary"),
            }
            for item in prior
            if item.get("role") == "agent"
        ]
        skill = skill_registry.create(skill_id, provider=provider)
        context = SkillContext(
            analysis_id=session["analysis_id"],
            company_name=analysis["company_name"],
            stock_code=analysis["stock_code"],
            mode=analysis["mode"],
            listing_date=analysis["listing_date"],
            prediction_as_of=analysis["prediction_as_of"],
            issue_price=analysis.get("issue_price"),
            claims=payload["claims"],
            evidence=payload["evidence"],
            prediction=payload["prediction"],
            parse_metadata=payload["parse_metadata"],
            prior_messages=prior_messages,
            shared_board=session.get("shared_board") or {},
            extra={"user_question": question},
        )
        # Append free-form question to user prompt via shared board.
        context.shared_board = {
            **context.shared_board,
            "followup_question": question,
        }
        result = skill.run(context)
        seq = len(prior) + 1
        user_msg = {
            "message_id": f"msg_{uuid.uuid4().hex}",
            "session_id": session_id,
            "analysis_id": session["analysis_id"],
            "seq": seq,
            "role": "user",
            "agent_name": "USER",
            "skill_id": skill_id,
            "title": "追问",
            "summary": question[:120],
            "content": question,
            "status": "success",
            "provider": None,
            "model": None,
            "payload_json": json.dumps({"skill_id": skill_id}, ensure_ascii=False),
            "created_at": utcnow(),
        }
        agent_msg = {
            "message_id": f"msg_{uuid.uuid4().hex}",
            "session_id": session_id,
            "analysis_id": session["analysis_id"],
            "seq": seq + 1,
            "role": "agent",
            "agent_name": result.agent_name,
            "skill_id": result.skill_id,
            "title": f"{skill.label}回复",
            "summary": result.summary,
            "content": result.content,
            "status": result.status,
            "provider": result.provider,
            "model": result.model,
            "payload_json": json.dumps(result.to_message(), ensure_ascii=False),
            "created_at": utcnow(),
        }
        self.database.add_agent_message(user_msg)
        self.database.add_agent_message(agent_msg)
        self.database.update_agent_session(session_id, stage=f"{skill.label} 已回复追问")
        return self.get_session(session_id)
