"""Pydantic request/response schemas for Thin RAG API V1."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    document_id: Optional[str] = None
    company: Optional[str] = None
    enable_followup: bool = True
    max_followup_rounds: int = Field(default=2, ge=0, le=2)
    enable_claim_analysis: bool = True
    ranking_profile: str = Field(default="default", description="default|hge; defaults stay off")


class Citation(BaseModel):
    document_id: str
    pages: List[int] = Field(default_factory=list)
    section: str = ""
    evidence_ids: List[str] = Field(default_factory=list)


class SearchResultItem(BaseModel):
    rank: int
    score: float
    document_id: str
    company: str = ""
    section: str = ""
    pages: List[int] = Field(default_factory=list)
    page_labels: List[Any] = Field(default_factory=list)
    chunk_id: str = ""
    evidence_ids: List[str] = Field(default_factory=list)
    block_type: str = ""
    text: str = ""
    preview: str = ""
    # Table presentation fields (optional; filled from chunk/evidence when available).
    # text/preview remain retrieval-oriented searchable linearization and are fallback only.
    table_html: str = ""
    table_data: Dict[str, Any] = Field(default_factory=dict)
    table_headers: List[Any] = Field(default_factory=list)
    table_rows: List[Any] = Field(default_factory=list)
    citation: Citation


class RoutingInfo(BaseModel):
    status: str
    source: str
    document_id: Optional[str] = None
    company: Optional[str] = None
    matched_name: Optional[str] = None
    candidate_document_ids: List[str] = Field(default_factory=list)


class EvidenceChainInfo(BaseModel):
    enabled: bool
    initial_support_label: str = "unknown"
    final_support_label: str = "unknown"
    followup_queries: List[str] = Field(default_factory=list)
    followup_results: List[SearchResultItem] = Field(default_factory=list)
    missing_facts: List[str] = Field(default_factory=list)
    recovered_facts: List[str] = Field(default_factory=list)
    unresolved_missing_facts: List[str] = Field(default_factory=list)




class ClaimCitation(BaseModel):
    document_id: str
    pages: List[int] = Field(default_factory=list)
    section: str = ""
    chunk_id: str = ""
    evidence_ids: List[str] = Field(default_factory=list)


class ClaimItem(BaseModel):
    claim_id: str
    claim_text: str
    answer_relevance: str
    risk_type: str = "other"
    quantitative_facts: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    evidence_sentence: str = ""
    citation: ClaimCitation
    sufficiency: str = "partial"
    missing_facts: List[str] = Field(default_factory=list)
    support_reason: str = ""

class SearchResponse(BaseModel):
    ranking_profile: str = "default"
    query: str
    routing: RoutingInfo
    results: List[SearchResultItem]
    evidence_chain: EvidenceChainInfo
    latency_ms: float
    warnings: List[str] = Field(default_factory=list)
    claims: List[ClaimItem] = Field(default_factory=list)
    accepted_claims: List[ClaimItem] = Field(default_factory=list)
    partial_claims: List[ClaimItem] = Field(default_factory=list)
    rejected_claims: List[ClaimItem] = Field(default_factory=list)
    claim_level_support: str = "disabled"
    followup_triggered_by_claims: bool = False


class HealthResponse(BaseModel):
    status: str
    vector_count: int
    model_loaded: bool
    version: str
    readiness_note: str


class DocumentSummary(BaseModel):
    document_id: str
    company: str = ""
    vector_count: int = 0


class DocumentsResponse(BaseModel):
    count: int
    documents: List[DocumentSummary]


class EvidenceGetRequest(BaseModel):
    document_id: str = Field(..., min_length=1)
    evidence_ids: List[str] = Field(default_factory=list)


class EvidenceGetResponse(BaseModel):
    document_id: str
    evidences: List[Dict[str, Any]] = Field(default_factory=list)
