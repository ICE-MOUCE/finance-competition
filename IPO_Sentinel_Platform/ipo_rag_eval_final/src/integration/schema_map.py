# -*- coding: utf-8 -*-
"""Agent-side schema mirror + mapping helpers for hk_ipo_risk_system.

This module deliberately mirrors the *required fields* of the peer repo's
EvidenceObject / RiskClaim so we can validate locally without installing the
peer monorepo. It is not a probability model and does not invent taxonomy codes.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator


PARSER_VERSION = "ipo-rag-adapter-v1"
BBOX_PLACEHOLDER: Tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
OWNER_AGENT = "RAG_RETRIEVAL_ADAPTER"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuditStatus(str, Enum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REVISED = "revised"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class EvidenceObject(StrictModel):
    """Mirror of peer EvidenceObject (required fields only)."""

    evidence_id: str
    company_id: str
    document_id: str
    source_type: Literal["prospectus", "allotment_result", "market_data", "news", "model_output"]
    page: int = Field(ge=1)
    section_path: List[str] = Field(default_factory=list)
    block_type: Literal["paragraph", "table", "figure", "footnote"]
    text: str
    bbox: Tuple[float, float, float, float]
    screenshot_uri: Optional[str] = None
    language: Literal["zh-HK", "zh-CN", "en", "mixed"]
    ocr_used: bool = False
    ocr_confidence: float = Field(default=1.0, ge=0, le=1)
    source_timestamp: Optional[datetime] = None
    content_hash: str
    parser_version: str
    injection_like_text: bool = False

    @field_validator("bbox")
    @classmethod
    def bbox_is_normalized(cls, value: Tuple[float, float, float, float]):
        if any(item < 0 or item > 1 for item in value):
            raise ValueError("bbox values must be normalized to [0, 1]")
        if value[0] > value[2] or value[1] > value[3]:
            raise ValueError("bbox coordinates are inverted")
        return value


class RiskClaim(StrictModel):
    """Mirror of peer RiskClaim (required fields only)."""

    claim_id: str
    risk_code: str
    claim: str
    direction: Literal["risk", "mitigant", "neutral"] = "risk"
    severity: int = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: List[str]
    counter_evidence_ids: List[str] = Field(default_factory=list)
    calculation_ids: List[str] = Field(default_factory=list)
    applicable_windows: List[Literal["1d", "5d", "20d", "60d"]] = Field(
        default_factory=lambda: ["1d", "5d", "20d", "60d"]
    )
    data_cutoff: datetime
    audit_status: AuditStatus = AuditStatus.CANDIDATE
    limitations: List[str] = Field(default_factory=list)
    owner_agent: str
    audit_reason: Optional[str] = None


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def physical_page_to_agent_page(page_0_based: Any) -> int:
    """Convert MinerU 0-based physical page to peer 1-based page."""
    try:
        value = int(page_0_based)
    except Exception:
        value = 0
    return max(1, value + 1)


def split_section_path(section: Any) -> List[str]:
    if section is None:
        return []
    if isinstance(section, (list, tuple)):
        return [str(x).strip() for x in section if str(x).strip()]
    text = str(section).strip()
    if not text:
        return []
    parts = re.split(r"\s*[>／/|]\s*", text)
    return [p.strip() for p in parts if p.strip()]


def map_block_type(block_type: Any) -> Literal["paragraph", "table", "figure", "footnote"]:
    raw = str(block_type or "").strip().lower()
    if raw in {"table", "html_table", "table_block"}:
        return "table"
    if raw in {"figure", "image", "img"}:
        return "figure"
    if raw in {"footnote", "note"}:
        return "footnote"
    # text / paragraph / unknown -> paragraph
    return "paragraph"


def detect_language(text: str) -> Literal["zh-HK", "zh-CN", "en", "mixed"]:
    sample = text or ""
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", sample))
    has_latin = bool(re.search(r"[A-Za-z]", sample))
    trad_markers = set("國語數據關聯獨戶採購總額佔淨擴發雲務現壓為負們戶應證監務財報")
    simp_markers = set("国语数据关联独户采购总额占净扩发云务现压为负们户应证监务财报")
    trad_hits = sum(1 for ch in sample if ch in trad_markers)
    simp_hits = sum(1 for ch in sample if ch in simp_markers)
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        if trad_hits > simp_hits + 2:
            return "zh-HK"
        return "zh-CN"
    if has_latin:
        return "en"
    return "zh-CN"


def stable_evidence_id(document_id: str, pages: Sequence[Any], text: str) -> str:
    joined_pages = ",".join(str(p) for p in pages)
    digest = sha256_text(f"{document_id}|{joined_pages}|{text}")[:16]
    return f"rag_ev_{digest}"


def map_risk_code(risk_type: Any, claim_text: str = "") -> str:
    """Explainable placeholder codes only. Not peer taxonomy authority."""
    rt = str(risk_type or "").lower()
    blob = f"{rt} {claim_text}"
    if any(k in blob for k in ("关联方", "關聯方", "客户集中", "客戶集中", "concentration", "依赖", "依賴")):
        if "financial" in rt:
            return "RAG_FIN_CONCENTRATION"
        return "RAG_BUS_CONCENTRATION"
    if "financial" in rt or any(k in blob for k in ("亏损", "虧損", "现金流", "現金流", "负债", "負債")):
        return "RAG_FIN_GENERIC"
    if "compliance" in rt or any(k in blob for k in ("许可", "許可", "诉讼", "訴訟", "合规", "合規")):
        return "RAG_COMP_GENERIC"
    if "ownership" in rt or any(k in blob for k in ("股权", "股權", "控股", "治理")):
        return "RAG_OWN_GENERIC"
    if "ipo" in rt or any(k in blob for k in ("募资", "募資", "所得款项", "所得款項")):
        return "RAG_IPO_GENERIC"
    if "business" in rt:
        return "RAG_BUS_GENERIC"
    return "RAG_OTHER_GENERIC"


def map_severity(risk_type: Any, quantitative_facts: Sequence[str] | None = None) -> int:
    rt = str(risk_type or "").lower()
    base = {
        "financial_risk": 7,
        "business_risk": 6,
        "compliance_risk": 6,
        "ownership_risk": 5,
        "ipo_specific_risk": 5,
    }.get(rt, 4)
    if quantitative_facts:
        base = min(8, base + 1)
    return max(4, min(8, base))


def map_confidence(bucket: str) -> float:
    key = (bucket or "").lower()
    if key == "accepted":
        return 0.8
    if key == "partial":
        return 0.6
    return 0.5


def map_audit_status(bucket: str) -> AuditStatus:
    key = (bucket or "").lower()
    if key == "accepted":
        return AuditStatus.ACCEPTED
    if key == "partial":
        return AuditStatus.CANDIDATE
    return AuditStatus.CANDIDATE


def default_limitations(
    *,
    bbox_placeholder: bool,
    page_converted: bool,
    claim_bucket: Optional[str] = None,
    missing_facts: Optional[Sequence[str]] = None,
) -> List[str]:
    notes = [
        "source=ipo-rag-adapter-v1",
        "not_peer_probability_model",
        "risk_code_is_placeholder_not_taxonomy_authority",
    ]
    if page_converted:
        notes.append("page_converted_from_0_based_physical_page")
    if bbox_placeholder:
        notes.append("bbox_placeholder=(0,0,1,1)")
    if claim_bucket == "partial":
        notes.append("claim_sufficiency=partial")
    if missing_facts:
        notes.append("missing_facts=" + ",".join(str(x) for x in missing_facts[:8]))
    return notes


def as_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def validate_agent_evidence_dicts(items: Iterable[Dict[str, Any]]) -> List[EvidenceObject]:
    return [EvidenceObject.model_validate(item) for item in items]


def validate_agent_claim_dicts(items: Iterable[Dict[str, Any]]) -> List[RiskClaim]:
    return [RiskClaim.model_validate(item) for item in items]
