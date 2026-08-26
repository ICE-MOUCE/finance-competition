from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import EvidenceObject, RiskClaim


@pytest.fixture
def as_of():
    return datetime(2025, 1, 1, tzinfo=timezone.utc)


def make_evidence(
    evidence_id: str = "ev_1",
    text: str = "公司存在现金流压力。",
    *,
    timestamp=None,
    ocr_used: bool = False,
    ocr_confidence: float = 1.0,
):
    return EvidenceObject(
        evidence_id=evidence_id,
        company_id="company_1",
        document_id="doc_1",
        source_type="prospectus",
        page=1,
        section_path=["Risk Factors"],
        block_type="paragraph",
        text=text,
        bbox=(0.1, 0.1, 0.9, 0.2),
        language="zh-CN",
        ocr_used=ocr_used,
        ocr_confidence=ocr_confidence,
        source_timestamp=timestamp,
        content_hash="a" * 64,
        parser_version="test",
    )


def make_claim(as_of, evidence_ids=None, counter_ids=None, **updates):
    payload = dict(
        claim_id="claim_1",
        risk_code="FIN_RUNWAY",
        claim="现金续航较短",
        direction="risk",
        severity=8,
        confidence=0.85,
        evidence_ids=["ev_1"] if evidence_ids is None else evidence_ids,
        counter_evidence_ids=[] if counter_ids is None else counter_ids,
        data_cutoff=as_of,
        owner_agent="FINANCIAL_DD_AGENT",
    )
    payload.update(updates)
    return RiskClaim(**payload)

