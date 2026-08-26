from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import PROJECT_ROOT
from .models import AuditStatus, EvidenceObject, PredictionRecord, RiskClaim


SECTION_BY_AGENT = {
    "FINANCIAL_DD_AGENT": "财务穿透",
    "LEGAL_COMPLIANCE_AGENT": "法务与合规",
    "EQUITY_CLAUSE_AGENT": "股权与非标条款",
    "INDUSTRY_PIPELINE_AGENT": "行业与商业化",
    "MARKET_SENTIMENT_AGENT": "市场情绪",
    "VALUATION_AGENT": "估值",
    "RISK_EXTRACTION_AGENT": "文本与披露信号",
}

SECTION_EVIDENCE_HINTS = {
    "财务穿透": ("現金", "现金", "負債", "负债", "保費", "借款", "所得款", "資本", "盈利", "虧損"),
    "法务与合规": ("訴訟", "诉讼", "監管", "监管", "合規", "合规", "牌照", "網絡安全", "私隱", "數據", "彌償"),
    "股权与非标条款": ("投票權", "贖回", "優先", "禁售", "鎖定", "轉讓限制", "控股", "股權"),
    "行业与商业化": ("分銷", "客戶", "供應", "業務", "競爭", "合營", "產品", "第三方"),
    "市场情绪": ("發售", "認購", "配售", "市場", "基石", "超額", "申請認購"),
    "估值": ("估值", "發售價", "市盈", "可比", "倍數", "定價"),
    "文本与披露信号": ("可能無法", "不能保證", "重大不利", "無法量化", "或會"),
    "其他": (),
}



def _section_evidence(evidence: list[EvidenceObject], hints: tuple[str, ...], limit: int = 3) -> list[EvidenceObject]:
    if not hints:
        return []
    scored: list[tuple[int, EvidenceObject]] = []
    for item in evidence:
        blob = f"{' '.join(item.section_path)} {item.text}"
        score = sum(hint in blob for hint in hints)
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1].page, len(pair[1].text)))
    seen: set[str] = set()
    out: list[EvidenceObject] = []
    for _, item in scored:
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        out.append(item)
        if len(out) >= limit:
            break
    return out


class ReportRenderer:
    def __init__(self, output_root: Path):
        self.output_root = output_root
        self.environment = Environment(
            loader=FileSystemLoader(PROJECT_ROOT / "app" / "templates"),
            autoescape=select_autoescape(["html"]),
        )

    def render(
        self,
        analysis: dict,
        prediction: PredictionRecord,
        claims: list[RiskClaim],
        evidence: list[EvidenceObject],
        conflicts: list[dict],
        data_gaps: list[str],
        parse_metadata: dict,
    ) -> Path:
        evidence_by_id = {item.evidence_id: item for item in evidence}
        eligible = [
            item for item in claims if item.audit_status in {AuditStatus.ACCEPTED, AuditStatus.REVISED}
        ]
        eligible.sort(key=lambda item: (-item.severity, -item.confidence))
        sections: dict[str, list[dict]] = {
            name: []
            for name in (
                "财务穿透",
                "法务与合规",
                "股权与非标条款",
                "行业与商业化",
                "市场情绪",
                "估值",
                "文本与披露信号",
                "其他",
            )
        }
        for claim in eligible:
            excerpts = [evidence_by_id[item] for item in claim.evidence_ids if item in evidence_by_id]
            counters = [evidence_by_id[item] for item in claim.counter_evidence_ids if item in evidence_by_id]
            sections[SECTION_BY_AGENT.get(claim.owner_agent, "其他")].append(
                {"claim": claim, "evidence": excerpts, "counters": counters}
            )
        section_evidence = {
            name: _section_evidence(evidence, hints)
            for name, hints in SECTION_EVIDENCE_HINTS.items()
        }
        template = self.environment.get_template("report.html")
        html = template.render(
            analysis=analysis,
            prediction=prediction,
            sections=sections,
            section_evidence=section_evidence,
            top_claims=eligible[:8],
            evidence_by_id=evidence_by_id,
            conflicts=conflicts,
            data_gaps=sorted(set(data_gaps)),
            parse_metadata=parse_metadata,
            generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        path = self.output_root / f"{analysis['analysis_id']}.html"
        path.write_text(html, encoding="utf-8")
        return path
