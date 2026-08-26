from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Mode(StrEnum):
    PREDICT = "PREDICT"
    EVALUATE = "EVALUATE"


class AuditStatus(StrEnum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REVISED = "revised"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class EvidenceObject(StrictModel):
    evidence_id: str
    company_id: str
    document_id: str
    source_type: Literal["prospectus", "allotment_result", "market_data", "news", "model_output"]
    page: int = Field(ge=1)
    section_path: list[str] = Field(default_factory=list)
    block_type: Literal["paragraph", "table", "figure", "footnote"]
    text: str
    bbox: tuple[float, float, float, float]
    screenshot_uri: str | None = None
    language: Literal["zh-HK", "zh-CN", "en", "mixed"]
    ocr_used: bool = False
    ocr_confidence: float = Field(default=1.0, ge=0, le=1)
    source_timestamp: datetime | None = None
    content_hash: str
    parser_version: str
    injection_like_text: bool = False

    @field_validator("bbox")
    @classmethod
    def bbox_is_normalized(cls, value: tuple[float, float, float, float]):
        if any(item < 0 or item > 1 for item in value):
            raise ValueError("bbox values must be normalized to [0, 1]")
        if value[0] > value[2] or value[1] > value[3]:
            raise ValueError("bbox coordinates are inverted")
        return value


class CalculationInput(StrictModel):
    name: str
    value: float
    unit: str
    evidence_id: str | None = None
    calculation_id: str | None = None


class CalculationRecord(StrictModel):
    calculation_id: str
    metric: str
    formula: str
    inputs: list[CalculationInput]
    result: float | None
    result_unit: str
    tool_version: str


class RiskClaim(StrictModel):
    claim_id: str
    risk_code: str
    claim: str
    direction: Literal["risk", "mitigant", "neutral"] = "risk"
    severity: int = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str]
    counter_evidence_ids: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)
    applicable_windows: list[Literal["1d", "5d", "20d", "60d"]] = Field(default_factory=lambda: ["1d", "5d", "20d", "60d"])
    data_cutoff: datetime
    audit_status: AuditStatus = AuditStatus.CANDIDATE
    limitations: list[str] = Field(default_factory=list)
    owner_agent: str
    audit_reason: str | None = None


class ToolCall(StrictModel):
    tool_name: str
    call_id: str
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    status: Literal["success", "failed"]


class ConflictTicket(StrictModel):
    conflict_id: str
    type: Literal["evidence", "numeric", "definition", "temporal", "cross_domain", "model"]
    claim_ids: list[str] = Field(default_factory=list)
    issue: str
    required_checks: list[str]
    owner_agent: str
    status: Literal["open", "resolved", "escalated"] = "open"
    resolution: str | None = None


class AgentEnvelope(StrictModel):
    schema_version: str = "1.0"
    task_id: str
    trace_id: str
    agent_name: str
    agent_run_id: str
    status: Literal["success", "partial", "blocked", "failed"]
    mode: Mode
    as_of: datetime
    input_refs: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    claims: list[RiskClaim] = Field(default_factory=list)
    calculations: list[CalculationRecord] = Field(default_factory=list)
    conflicts: list[ConflictTicket] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    decision_summary: str = Field(max_length=120)
    next_actions: list[str] = Field(default_factory=list)


class Probabilities(StrictModel):
    p_1d_break: float = Field(ge=0, le=1)
    p_5d_drop: float = Field(ge=0, le=1)
    p_20d_drop: float = Field(ge=0, le=1)
    p_60d_drop: float = Field(ge=0, le=1)


class Contributor(StrictModel):
    feature: str
    value: float
    contribution: float


class PredictionRecord(StrictModel):
    stock_code: str
    prediction_as_of: datetime
    model_version: str | None
    feature_snapshot_id: str
    risk_score: float | None = Field(default=None, ge=0, le=100)
    risk_level: str
    probabilities: Probabilities | None
    rule_hits: list[str] = Field(default_factory=list)
    rule_score: float = Field(ge=0, le=100)
    top_contributors: list[Contributor] = Field(default_factory=list)
    audited_claim_ids: list[str] = Field(default_factory=list)
    calibration_version: str | None
    status: Literal["success", "partial", "blocked"]

    @model_validator(mode="after")
    def probability_provenance(self):
        if self.probabilities is not None and (not self.model_version or not self.calibration_version):
            raise ValueError("probabilities require model_version and calibration_version")
        if self.probabilities is None and self.risk_score is not None:
            raise ValueError("risk_score must be null when probabilities are unavailable")
        return self


class AnalysisCreate(StrictModel):
    company_name: str = Field(min_length=1, max_length=120)
    stock_code: str = Field(min_length=1, max_length=20)
    listing_date: date
    issue_price: float = Field(gt=0)
    prediction_as_of: datetime
    pdf_path: str
    mode: Mode = Mode.PREDICT
    company_id: str | None = None
    model_version: str | None = None

    @field_validator("stock_code")
    @classmethod
    def normalize_stock_code(cls, value: str):
        value = value.strip().upper()
        if value.isdigit():
            value = f"{value.zfill(5)}.HK"
        return value


class AnalysisSummary(StrictModel):
    analysis_id: str
    company_name: str
    stock_code: str
    status: str
    progress: int = Field(ge=0, le=100)
    stage: str
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    report_url: str | None = None
    prediction: PredictionRecord | None = None
    claim_counts: dict[str, int] = Field(default_factory=dict)
    evidence_count: int = 0
    injection_count: int = 0


class DatasetItem(StrictModel):
    path: str
    filename: str
    year: int | None
    size_bytes: int
