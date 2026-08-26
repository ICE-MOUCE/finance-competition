from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import traceback
import uuid

from .config import Settings
from .database import Database
from .model_registry import ModelRegistry
from .models import (
    AgentEnvelope,
    AnalysisCreate,
    AuditStatus,
    Mode,
    PredictionRecord,
    ToolCall,
)
from .prompts import PromptRegistry
from .rag import RagClient, RagRetriever, merge_parse_with_retrieval, parse_prospectus
from .reporting import ReportRenderer
from .agent_room import AgentRoomService
from .risk_engine import (
    RiskTaxonomy,
    audit_claims,
    build_document_features,
    build_rule_features,
    extract_candidate_claims,
)


EXPERT_AGENTS = [
    "FINANCIAL_DD_AGENT",
    "LEGAL_COMPLIANCE_AGENT",
    "EQUITY_CLAUSE_AGENT",
    "INDUSTRY_PIPELINE_AGENT",
    "MARKET_SENTIMENT_AGENT",
    "VALUATION_AGENT",
]


class AnalysisOrchestrator:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        prompts: PromptRegistry,
        taxonomy: RiskTaxonomy,
        model_registry: ModelRegistry,
    ):
        self.settings = settings
        self.database = database
        self.prompts = prompts
        self.taxonomy = taxonomy
        self.model_registry = model_registry
        self.reporter = ReportRenderer(settings.report_root)
        self.agent_room = AgentRoomService(settings, database)

    @staticmethod
    def new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def envelope(
        self,
        analysis_id: str,
        agent_name: str,
        mode: Mode,
        as_of: datetime,
        status: str,
        summary: str,
        *,
        input_refs: list[str] | None = None,
        claims=None,
        conflicts=None,
        data_gaps=None,
        tool_name: str | None = None,
        output_refs: list[str] | None = None,
    ) -> AgentEnvelope:
        tool_calls = []
        if tool_name:
            tool_calls.append(
                ToolCall(
                    tool_name=tool_name,
                    call_id=self.new_id("call"),
                    input_refs=input_refs or [],
                    output_refs=output_refs or [],
                    status="success" if status != "failed" else "failed",
                )
            )
        return AgentEnvelope(
            task_id=analysis_id,
            trace_id=f"trace_{analysis_id}",
            agent_name=agent_name,
            agent_run_id=self.new_id("run"),
            status=status,
            mode=mode,
            as_of=as_of,
            input_refs=input_refs or [],
            tool_calls=tool_calls,
            claims=claims or [],
            conflicts=conflicts or [],
            data_gaps=data_gaps or [],
            decision_summary=summary[:120],
        )

    def run(self, analysis_id: str, request: AnalysisCreate, resolved_pdf: Path) -> None:
        all_data_gaps: list[str] = []
        try:
            self.database.update_analysis(analysis_id, status="running", progress=3, stage="总控规划")
            plan = self.envelope(
                analysis_id,
                "ORCHESTRATOR_AGENT",
                request.mode,
                request.prediction_as_of,
                "success",
                "DAG 已生成；解析、抽取、六专家、审计、模型与报告门禁已启用。",
                input_refs=[str(resolved_pdf)],
                tool_name="agent_dispatch",
            )
            self.database.save_trace(analysis_id, plan)

            self.database.update_analysis(analysis_id, progress=10, stage="文档解析与证据入库")
            company_id = request.company_id or analysis_id
            parsed = parse_prospectus(
                resolved_pdf,
                company_id,
                parser_backend=self.settings.parser_backend,
                mineru_root=self.settings.mineru_evidence_root,
                max_pages=self.settings.max_pages,
                max_evidence=self.settings.max_evidence,
                document_hint=request.company_name,
            )
            all_data_gaps.extend(parsed.data_gaps)
            retrieved_evidence = []
            rag_warnings = []
            rag_queries = {}
            rag_document_id = parsed.metadata.get("document_id")
            if self.settings.rag_enabled:
                self.database.update_analysis(analysis_id, progress=22, stage="RAG 证据检索")
                retriever = RagRetriever(
                    RagClient(
                        base_url=self.settings.rag_base_url,
                        timeout_s=self.settings.rag_timeout_s,
                        ranking_profile=self.settings.rag_ranking_profile,
                    ),
                    top_k=self.settings.rag_top_k,
                )
                parser_backend = str(parsed.metadata.get("parser_backend") or "")
                rag_document_hint = None
                if parser_backend == "mineru" and parsed.metadata.get("document_id"):
                    rag_document_hint = str(parsed.metadata.get("document_id"))
                bundle = retriever.collect(
                    company_id=company_id,
                    company_name=request.company_name,
                    document_id=rag_document_hint,
                )
                retrieved_evidence = bundle.evidence
                rag_warnings = bundle.warnings
                rag_queries = bundle.queries
                rag_document_id = bundle.routed_document_id or rag_document_id
                all_data_gaps.extend(rag_warnings)
                parsed.metadata["rag_health"] = bundle.health
                parsed.metadata["rag_document_id"] = rag_document_id
                parsed.metadata["rag_query_count"] = len(rag_queries)
                parsed.metadata["rag_queries"] = rag_queries
                parsed.metadata["rag_warnings"] = rag_warnings
                parsed.metadata["retrieved_evidence_ids"] = [item.evidence_id for item in retrieved_evidence[:50]]
                self.database.save_trace(
                    analysis_id,
                    self.envelope(
                        analysis_id,
                        "RAG_RETRIEVAL_AGENT",
                        request.mode,
                        request.prediction_as_of,
                        "partial" if rag_warnings or not retrieved_evidence else "success",
                        f"RAG 检索完成，命中 {len(retrieved_evidence)} 条证据。",
                        input_refs=[str(rag_document_id or parsed.metadata.get("document_id"))],
                        data_gaps=rag_warnings,
                        tool_name="rag_search",
                        output_refs=[item.evidence_id for item in retrieved_evidence[:20]],
                    ),
                )
            working = merge_parse_with_retrieval(
                parsed,
                retrieved_evidence,
                prefer_retrieval=bool(self.settings.rag_enabled and retrieved_evidence),
                max_evidence=min(self.settings.max_evidence, self.settings.working_evidence_limit),
            )
            parsed = working
            all_data_gaps.extend(gap for gap in parsed.data_gaps if gap not in all_data_gaps)
            self.database.save_evidence(analysis_id, parsed.evidence)
            self.database.update_analysis(
                analysis_id,
                parse_metadata_json=json.dumps(parsed.metadata, ensure_ascii=False),
            )
            parser_status = "partial" if parsed.data_gaps else "success"
            parser_backend = parsed.metadata.get("parser_backend", "pymupdf")
            self.database.save_trace(
                analysis_id,
                self.envelope(
                    analysis_id,
                    "DOCUMENT_PARSER_AGENT",
                    request.mode,
                    request.prediction_as_of,
                    parser_status,
                    f"完成 {parsed.metadata.get('parsed_pages', 0)} 页解析（{parser_backend}），工作证据 {len(parsed.evidence)} 条。",
                    input_refs=[str(parsed.metadata.get("document_id"))],
                    data_gaps=parsed.data_gaps,
                    tool_name="pdf_parser" if parser_backend == "pymupdf" else "mineru_evidence_store",
                    output_refs=[item.evidence_id for item in parsed.evidence[:20]],
                ),
            )

            self.database.update_analysis(analysis_id, progress=38, stage="风险抽取")
            candidates = extract_candidate_claims(
                company_id,
                parsed.evidence,
                request.prediction_as_of,
                self.taxonomy,
            )
            self.database.save_trace(
                analysis_id,
                self.envelope(
                    analysis_id,
                    "RISK_EXTRACTION_AGENT",
                    request.mode,
                    request.prediction_as_of,
                    "success",
                    f"风险字典 {self.taxonomy.version} 生成 {len(candidates)} 条候选 claim。",
                    input_refs=[parsed.metadata["document_id"]],
                    claims=[item for item in candidates if item.owner_agent == "RISK_EXTRACTION_AGENT"],
                    tool_name="risk_taxonomy",
                    output_refs=[item.claim_id for item in candidates],
                ),
            )

            self.database.update_analysis(analysis_id, progress=52, stage="专家并行尽调")
            for agent_name in EXPERT_AGENTS:
                owned = [item for item in candidates if item.owner_agent == agent_name]
                gaps = []
                if agent_name in {"MARKET_SENTIMENT_AGENT", "VALUATION_AGENT"}:
                    gaps.append("未提供带 prediction_as_of 的外部市场/可比公司快照，仅保留招股书内候选证据。")
                    all_data_gaps.extend(gaps)
                if self.settings.rag_enabled:
                    query = rag_queries.get(agent_name)
                    if query:
                        gaps.append(f"已用 RAG 检索词先行召回证据：{query}")
                    if not retrieved_evidence:
                        gaps.append("RAG 未命中证据，专家仅基于解析库候选 claim 推理。")
                self.database.save_trace(
                    analysis_id,
                    self.envelope(
                        analysis_id,
                        agent_name,
                        request.mode,
                        request.prediction_as_of,
                        "partial" if gaps else "success",
                        f"先检索后推理：角色内候选 {len(owned)} 条，工作证据 {len(parsed.evidence)} 条。",
                        input_refs=[item.claim_id for item in owned] or [str(rag_document_id or parsed.metadata.get("document_id"))],
                        claims=owned,
                        data_gaps=gaps,
                        tool_name="rag_search" if self.settings.rag_enabled else self.prompts.get(agent_name).tools[0],
                        output_refs=[item.claim_id for item in owned] or [item.evidence_id for item in parsed.evidence[:8]],
                    ),
                )

            self.database.update_analysis(analysis_id, progress=68, stage="反驳审计")
            audited, conflicts = audit_claims(candidates, parsed.evidence, request.prediction_as_of)
            self.database.save_claims(analysis_id, audited)
            accepted = sum(item.audit_status == AuditStatus.ACCEPTED for item in audited)
            revised = sum(item.audit_status == AuditStatus.REVISED for item in audited)
            rejected = sum(item.audit_status == AuditStatus.REJECTED for item in audited)
            self.database.save_trace(
                analysis_id,
                self.envelope(
                    analysis_id,
                    "CHALLENGE_AUDIT_AGENT",
                    request.mode,
                    request.prediction_as_of,
                    "success",
                    f"审计完成：接受 {accepted}、修订 {revised}、拒绝 {rejected}。",
                    input_refs=[item.claim_id for item in candidates],
                    claims=audited,
                    conflicts=conflicts,
                    tool_name="temporal_check",
                    output_refs=[item.claim_id for item in audited],
                ),
            )

            self.database.update_analysis(analysis_id, progress=80, stage="规则与结构化模型")
            features, rule_hits, rule_score = build_rule_features(audited)
            listing_datetime = datetime.combine(
                request.listing_date,
                datetime.min.time(),
                tzinfo=request.prediction_as_of.tzinfo,
            )
            features.update(
                build_document_features(
                    (item.text for item in parsed.evidence),
                    self.taxonomy,
                    page_count=parsed.metadata["pages"],
                    listing_date=listing_datetime,
                )
            )
            features["issue_price"] = request.issue_price
            model_output = self.model_registry.predict(features, request.model_version)
            feature_material = json.dumps(features, sort_keys=True).encode("utf-8")
            feature_snapshot = "feature_" + hashlib.sha256(feature_material).hexdigest()
            eligible_ids = [
                item.claim_id for item in audited if item.audit_status in {AuditStatus.ACCEPTED, AuditStatus.REVISED}
            ]
            model_gaps = []
            if model_output is None:
                prediction = PredictionRecord(
                    stock_code=request.stock_code,
                    prediction_as_of=request.prediction_as_of,
                    model_version=None,
                    feature_snapshot_id=feature_snapshot,
                    risk_score=None,
                    risk_level="UNAVAILABLE",
                    probabilities=None,
                    rule_hits=rule_hits,
                    rule_score=rule_score,
                    top_contributors=[],
                    audited_claim_ids=eligible_ids,
                    calibration_version=None,
                    status="partial",
                )
                model_gaps.append("未发现已注册并校准的结构化模型；probabilities 按契约置为 null。")
                all_data_gaps.extend(model_gaps)
            else:
                prediction = PredictionRecord(
                    stock_code=request.stock_code,
                    prediction_as_of=request.prediction_as_of,
                    model_version=model_output["version"],
                    feature_snapshot_id=model_output["feature_snapshot_id"],
                    risk_score=model_output["risk_score"],
                    risk_level=model_output["risk_level"],
                    probabilities=model_output["probabilities"],
                    rule_hits=rule_hits,
                    rule_score=rule_score,
                    top_contributors=model_output["contributors"],
                    audited_claim_ids=eligible_ids,
                    calibration_version=model_output["calibration_version"],
                    status="success",
                )
            self.database.save_prediction(analysis_id, prediction)
            self.database.save_trace(
                analysis_id,
                self.envelope(
                    analysis_id,
                    "RISK_MODEL_AGENT",
                    request.mode,
                    request.prediction_as_of,
                    "partial" if model_gaps else "success",
                    (
                        "规则命中与模型概率已分层保存，模型与校准版本已记录。"
                        if model_output is not None
                        else "规则命中已保存；模型不可用，未生成概率。"
                    ),
                    input_refs=eligible_ids,
                    data_gaps=model_gaps,
                    tool_name="model_registry",
                    output_refs=[prediction.feature_snapshot_id],
                ),
            )

            if request.mode == Mode.EVALUATE:
                gap = "未提供冻结预测集和上市后标签快照，回测 Agent 已阻断且未改写事前结果。"
                all_data_gaps.append(gap)
                self.database.save_trace(
                    analysis_id,
                    self.envelope(
                        analysis_id,
                        "BACKTEST_EVALUATION_AGENT",
                        request.mode,
                        request.prediction_as_of,
                        "blocked",
                        gap,
                        input_refs=[prediction.feature_snapshot_id],
                        data_gaps=[gap],
                    ),
                )

            self.database.update_analysis(analysis_id, progress=92, stage="报告生成")
            analysis = {
                "analysis_id": analysis_id,
                "company_name": request.company_name,
                "company_id": request.company_id or analysis_id,
                "stock_code": request.stock_code,
                "listing_date": request.listing_date.isoformat(),
                "prediction_as_of": request.prediction_as_of.isoformat(),
                "mode": request.mode.value,
                "pdf_path": str(resolved_pdf),
            }
            report_path = self.reporter.render(
                analysis,
                prediction,
                audited,
                parsed.evidence,
                [item.model_dump(mode="json") for item in conflicts],
                all_data_gaps,
                parsed.metadata,
            )
            self.database.save_trace(
                analysis_id,
                self.envelope(
                    analysis_id,
                    "REPORT_GENERATION_AGENT",
                    request.mode,
                    request.prediction_as_of,
                    "success",
                    "报告仅使用已审计结论、规则/模型分层结果和可回跳证据生成。",
                    input_refs=eligible_ids,
                    tool_name="report_renderer",
                    output_refs=[str(report_path)],
                ),
            )
            self.database.update_analysis(
                analysis_id,
                status="completed",
                progress=100,
                stage="完成",
                report_path=str(report_path),
                error=None,
            )
            if self.settings.agent_room_auto_start:
                try:
                    session = self.agent_room.create_session(analysis_id, auto_start=True)
                    self.agent_room.run_session(session["session_id"])
                except Exception as room_exc:  # noqa: BLE001
                    # Room failure must not fail the deterministic analysis.
                    error_log = self.settings.runtime_root / f"{analysis_id}.agent_room.error.log"
                    error_log.write_text(traceback.format_exc(), encoding="utf-8")
                    self.database.update_analysis(
                        analysis_id,
                        stage="完成（会诊室启动失败）",
                        error=None,
                    )
        except Exception as exc:
            self.database.update_analysis(
                analysis_id,
                status="failed",
                stage="失败",
                error=f"{type(exc).__name__}: {exc}",
            )
            error_log = self.settings.runtime_root / f"{analysis_id}.error.log"
            error_log.write_text(traceback.format_exc(), encoding="utf-8")

