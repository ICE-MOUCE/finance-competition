from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import math
from pathlib import Path
from typing import Iterable

import yaml

from .config import PROJECT_ROOT
from .models import AuditStatus, ConflictTicket, EvidenceObject, RiskClaim


GENERIC_RISK_MARKERS = (
    "可能",
    "或会",
    "无法保证",
    "不能保证",
    "may ",
    "might ",
    "could ",
    "cannot assure",
    "we cannot guarantee",
)
ACTUAL_EVENT_MARKERS = (
    "已收到",
    "收到监管",
    "已发生",
    "正在调查",
    "已涉及诉讼",
    "已涉及訴訟",
    "目前涉及诉讼",
    "目前涉及訴訟",
    "正在进行诉讼",
    "正在進行訴訟",
    "已涉及仲裁",
    "已牽涉訴訟",
    "被起诉",
    "被起訴",
    "已受到处罚",
    "已受到處罰",
    "已被罚款",
    "已被罰款",
    "被罚款人民币",
    "被罰款人民幣",
    "被罚款港币",
    "被罰款港幣",
    "作为原告",
    "作為原告",
    "作为被告",
    "作為被告",
    "于往绩记录期发生",
    "during the track record period, we incurred",
    "pending litigation",
    "is under investigation",
    "has been investigated",
    "was fined",
)
STRONG_EVENT_REQUIRED = {
    "LEGAL_LITIGATION",
    "LEGAL_REGULATORY",
}


class RiskTaxonomy:
    def __init__(self, path: Path | None = None):
        path = path or PROJECT_ROOT / "config" / "risk_taxonomy.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.version = payload["version"]
        self.risks: dict[str, dict] = payload["risks"]


def _claim_text(label: str, excerpt: str) -> str:
    snippet = " ".join((excerpt or "").split())
    if len(snippet) > 180:
        snippet = snippet[:180].rstrip() + "…"
    if snippet:
        return f"{label}：{snippet}"
    return f"发现与“{label}”相关的招股书披露，需结合上下文与反证复核。"


def _claim_id(company_id: str, code: str, evidence_ids: list[str]) -> str:
    value = "|".join([company_id, code, *sorted(evidence_ids)])
    return "claim_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def extract_candidate_claims(
    company_id: str,
    evidence: list[EvidenceObject],
    prediction_as_of: datetime,
    taxonomy: RiskTaxonomy,
    max_claims: int = 30,
) -> list[RiskClaim]:
    claims: list[RiskClaim] = []
    searchable = [(item, item.text.casefold()) for item in evidence if not item.injection_like_text]
    for code, definition in taxonomy.risks.items():
        keywords = [str(item).casefold() for item in definition.get("keywords", [])]
        mitigants = [str(item).casefold() for item in definition.get("mitigants", [])]
        hits: list[tuple[int, EvidenceObject]] = []
        counter_hits: list[tuple[int, EvidenceObject]] = []
        for item, lowered in searchable:
            counter_count = sum(keyword in lowered for keyword in mitigants)
            if counter_count:
                counter_hits.append((counter_count, item))
            lacks_required_event = (
                code in STRONG_EVENT_REQUIRED
                and not any(marker in lowered for marker in ACTUAL_EVENT_MARKERS)
            )
            # A sentence that explicitly states absence, termination or mitigation
            # is counter-evidence, not supporting evidence for the same risk.
            # Prospectus risk-factor language often uses 可能/或會; do not drop
            # keyword hits for that reason. Legal codes still need an actual event.
            hit_count = 0 if counter_count or lacks_required_event else sum(keyword in lowered for keyword in keywords)
            if hit_count:
                hits.append((hit_count, item))
        if not hits:
            continue
        hits.sort(key=lambda pair: (-pair[0], pair[1].page, len(pair[1].text)))
        counter_hits.sort(key=lambda pair: (-pair[0], pair[1].page))
        selected = [item for _, item in hits[:3]]
        selected_counters = [item for _, item in counter_hits[:2]]
        confidence = min(0.90, 0.56 + 0.10 * len(selected))
        confidence = min(confidence, *(item.ocr_confidence for item in selected))
        limitations = []
        if len(selected) == 1:
            limitations.append("仅命中单一证据块，需审计上下文与一般性风险模板")
        claims.append(
            RiskClaim(
                claim_id=_claim_id(company_id, code, [item.evidence_id for item in selected]),
                risk_code=code,
                claim=_claim_text(definition["label"], selected[0].text),
                direction="risk",
                severity=int(definition["severity"]),
                confidence=confidence,
                evidence_ids=[item.evidence_id for item in selected],
                counter_evidence_ids=[item.evidence_id for item in selected_counters],
                data_cutoff=prediction_as_of,
                audit_status=AuditStatus.CANDIDATE,
                limitations=limitations,
                owner_agent=str(definition["owner"]),
            )
        )
    claims.sort(key=lambda item: (-item.severity, -item.confidence, item.risk_code))
    return claims[:max_claims]


def audit_claims(
    claims: list[RiskClaim],
    evidence: Iterable[EvidenceObject],
    prediction_as_of: datetime,
) -> tuple[list[RiskClaim], list[ConflictTicket]]:
    evidence_by_id = {item.evidence_id: item for item in evidence}
    audited: list[RiskClaim] = []
    conflicts: list[ConflictTicket] = []
    for original in claims:
        claim = original.model_copy(deep=True)
        supporting = [evidence_by_id[item] for item in claim.evidence_ids if item in evidence_by_id]
        counters = [evidence_by_id[item] for item in claim.counter_evidence_ids if item in evidence_by_id]
        if not claim.evidence_ids or not supporting:
            claim.audit_status = AuditStatus.REJECTED
            claim.audit_reason = "无有效 evidence_id 支持，审计拒绝。"
        elif any(item.source_timestamp and item.source_timestamp > prediction_as_of for item in supporting):
            claim.audit_status = AuditStatus.REJECTED
            claim.audit_reason = "证据晚于 prediction_as_of，触发时点泄漏门禁。"
            conflicts.append(
                ConflictTicket(
                    conflict_id=f"conflict_temporal_{claim.claim_id}",
                    type="temporal",
                    claim_ids=[claim.claim_id],
                    issue="PREDICT 证据包含 prediction_as_of 之后的数据",
                    required_checks=["检查数据快照时间", "重建事前数据视图"],
                    owner_agent="CHALLENGE_AUDIT_AGENT",
                )
            )
        elif any(item.ocr_used and item.ocr_confidence < 0.92 for item in supporting):
            claim.audit_status = AuditStatus.ESCALATED
            claim.confidence = min(claim.confidence, 0.60)
            claim.audit_reason = "关键证据来自低置信 OCR，保留候选并升级人工复核。"
        elif counters:
            claim.audit_status = AuditStatus.REVISED
            claim.severity = max(1, claim.severity - 2)
            claim.audit_reason = "支持性披露成立，但检出缓释或终止证据，已下调严重度。"
        elif claim.severity >= 7 and len(supporting) < 2:
            claim.audit_status = AuditStatus.REVISED
            claim.severity = 6
            claim.confidence = min(claim.confidence, 0.66)
            claim.audit_reason = "重大风险仅有单一证据块，降级为中等风险并要求人工抽查。"
        else:
            claim.audit_status = AuditStatus.ACCEPTED
            claim.audit_reason = "证据引用、时点和基本上下文检查通过。"
        audited.append(claim)
    return audited, conflicts


def detect_numeric_unit_conflict(units: Iterable[str]) -> bool:
    normalized = {item.strip().casefold() for item in units if item.strip()}
    scales = {
        "元": 1,
        "千元": 1_000,
        "百万元": 1_000_000,
        "million": 1_000_000,
        "thousand": 1_000,
    }
    present = {value for key, value in scales.items() if any(key in unit for unit in normalized)}
    return len(present) > 1


def comparable_quality(count: int) -> str:
    if count < 3:
        return "low"
    if count < 5:
        return "medium"
    return "high"


def build_document_features(
    texts: Iterable[str],
    taxonomy: RiskTaxonomy,
    *,
    page_count: int,
    listing_date: datetime | None = None,
) -> dict[str, float]:
    normalized = [text.casefold() for text in texts if text and text.strip()]
    denominator = max(1, len(normalized))
    features: dict[str, float] = {
        "document_block_count_log": math.log1p(denominator),
        "document_page_count_log": math.log1p(max(1, page_count)),
    }
    for code, definition in taxonomy.risks.items():
        keywords = [str(item).casefold() for item in definition.get("keywords", [])]
        mitigants = [str(item).casefold() for item in definition.get("mitigants", [])]
        hits = 0
        counters = 0
        for text in normalized:
            has_counter = any(marker in text for marker in mitigants)
            counters += int(has_counter)
            is_text_signal = code.startswith("TEXT_")
            generic = (
                not is_text_signal
                and any(marker in text for marker in GENERIC_RISK_MARKERS)
                and not any(marker in text for marker in ACTUAL_EVENT_MARKERS)
            )
            lacks_event = code in STRONG_EVENT_REQUIRED and not any(
                marker in text for marker in ACTUAL_EVENT_MARKERS
            )
            if not has_counter and not generic and not lacks_event and any(
                keyword in text for keyword in keywords
            ):
                hits += 1
        prefix = code.casefold()
        features[f"lex_{prefix}_rate"] = hits * 1000.0 / denominator
        features[f"lex_{prefix}_mitigant_rate"] = counters * 1000.0 / denominator
    if listing_date is not None:
        month_angle = 2 * math.pi * (listing_date.month - 1) / 12
        features["listing_year"] = float(listing_date.year)
        features["listing_month_sin"] = math.sin(month_angle)
        features["listing_month_cos"] = math.cos(month_angle)
    return features


def build_rule_features(claims: list[RiskClaim]) -> tuple[dict[str, float], list[str], float]:
    eligible = [item for item in claims if item.audit_status in {AuditStatus.ACCEPTED, AuditStatus.REVISED}]
    domains: dict[str, list[RiskClaim]] = defaultdict(list)
    for claim in eligible:
        domains[claim.risk_code.split("_", 1)[0]].append(claim)
    features: dict[str, float] = {}
    for prefix in ["FIN", "LEGAL", "EQUITY", "BIZ", "TEXT", "VAL", "MKT"]:
        items = domains.get(prefix, [])
        features[f"{prefix.lower()}_max_severity"] = max((item.severity for item in items), default=0) / 10
        features[f"{prefix.lower()}_claim_count"] = float(len(items))
    features["accepted_claim_count"] = float(sum(item.audit_status == AuditStatus.ACCEPTED for item in eligible))
    features["revised_claim_count"] = float(sum(item.audit_status == AuditStatus.REVISED for item in eligible))
    features["mean_confidence"] = sum(item.confidence for item in eligible) / len(eligible) if eligible else 0.0
    rule_hits = [item.risk_code for item in eligible if item.severity >= 6]
    weighted = sum(item.severity * item.confidence for item in eligible)
    rule_score = min(100.0, round(weighted * 4.0, 2))
    return features, sorted(set(rule_hits)), rule_score
