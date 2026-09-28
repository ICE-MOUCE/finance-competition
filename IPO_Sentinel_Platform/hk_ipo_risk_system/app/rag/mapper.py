from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Sequence

from ..models import EvidenceObject
from ..parser import ParseResult, detect_injection, detect_language, normalize_text


PARSER_VERSION = "ipo-rag-adapter-v1"
BBOX_PLACEHOLDER = (0.0, 0.0, 1.0, 1.0)
DEFAULT_EXPERT_QUERIES = {
    "FINANCIAL_DD_AGENT": "现金消耗 現金流 盈利 杠杆 槓桿 客户集中 客戶集中 关联交易 關連交易 所得款项用途 所得款項用途 偿债 償債",
    "LEGAL_COMPLIANCE_AGENT": "重大诉讼 重大訴訟 监管调查 監管 行政处罚 牌照 知识产权 知識產權 数据合规 數據 網絡安全 私隱 法律及監管合規",
    "EQUITY_CLAUSE_AGENT": "赎回权 贖回權 优先清算 反稀释 對賭 股权激励 投票權 控制权 禁售 鎖定 轉讓限制",
    "INDUSTRY_PIPELINE_AGENT": "客户依赖 供應商 分銷 管线 产能 競爭 業務模式 第三方 合營企業",
    "MARKET_SENTIMENT_AGENT": "发行窗口 認購 基石投资者 超额配售 超額配售 市场风险 市場波動 公開發售 發售股份",
    "VALUATION_AGENT": "估值 市盈率 可比公司 发行价 發售價 募集资金 所得款項",
}


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def mineru_page_to_agent_page(page_value: Any) -> int:
    try:
        value = int(page_value)
    except Exception:
        value = 0
    if value < 0:
        return 1
    return max(1, value + 1) if value < 1000 else value


def physical_page_to_agent_page(page_value: Any) -> int:
    return mineru_page_to_agent_page(page_value)


def split_section_path(section: Any) -> list[str]:
    if section is None:
        return []
    if isinstance(section, (list, tuple)):
        return [str(item).strip() for item in section if str(item).strip()]
    text = str(section).strip()
    if not text:
        return []
    return [item.strip() for item in re.split(r"\s*[>／/|]\s*", text) if item.strip()]


def map_block_type(block_type: Any) -> str:
    raw = str(block_type or "").strip().lower()
    if raw in {"table", "html_table", "table_block"}:
        return "table"
    if raw in {"figure", "image", "img"}:
        return "figure"
    if raw in {"footnote", "note"}:
        return "footnote"
    return "paragraph"


def normalize_bbox(
    bbox: Any,
    page_width: float | None = None,
    page_height: float | None = None,
) -> tuple[float, float, float, float]:
    if not bbox or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return BBOX_PLACEHOLDER
    try:
        x0, y0, x1, y1 = [float(item) for item in bbox[:4]]
    except Exception:
        return BBOX_PLACEHOLDER
    max_value = max(abs(x0), abs(y0), abs(x1), abs(y1))
    if max_value <= 1.5:
        width, height = 1.0, 1.0
    else:
        width = float(page_width or max(x1, 1.0))
        height = float(page_height or max(y1, 1.0))
    nx0 = max(0.0, min(1.0, x0 / width))
    ny0 = max(0.0, min(1.0, y0 / height))
    nx1 = max(0.0, min(1.0, x1 / width))
    ny1 = max(0.0, min(1.0, y1 / height))
    if nx0 > nx1:
        nx0, nx1 = nx1, nx0
    if ny0 > ny1:
        ny0, ny1 = ny1, ny0
    if nx0 == nx1:
        nx1 = min(1.0, nx0 + 0.01)
    if ny0 == ny1:
        ny1 = min(1.0, ny0 + 0.01)
    return (nx0, ny0, nx1, ny1)


def _result_pages(result: dict[str, Any]) -> list[int]:
    pages: list[int] = []
    for page in result.get("pages") or []:
        try:
            pages.append(int(page))
        except Exception:
            continue
    return pages


def _pick_company_id(result: dict[str, Any], routing: dict[str, Any], fallback: str | None) -> str:
    for candidate in (
        fallback,
        routing.get("company"),
        result.get("company"),
        routing.get("matched_name"),
        result.get("document_id"),
        routing.get("document_id"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return "unknown_company"


def map_search_result_to_evidence(
    result: dict[str, Any],
    *,
    company_id: str,
    routing: dict[str, Any] | None = None,
    source_details: dict[str, Any] | None = None,
) -> EvidenceObject:
    routing = routing or {}
    source = source_details or {}
    text = normalize_text(str(result.get("text") or result.get("preview") or source.get("text") or ""))
    pages = _result_pages(result)
    page = mineru_page_to_agent_page(pages[0] if pages else source.get("page") or 0)
    evidence_ids = [str(item) for item in (result.get("evidence_ids") or []) if str(item).strip()]
    document_id = str(result.get("document_id") or routing.get("document_id") or "unknown_document")
    if evidence_ids:
        evidence_id = evidence_ids[0]
    else:
        evidence_id = "rag_ev_" + sha256_text("|".join([document_id, str(pages), text]))[:16]
    return EvidenceObject(
        evidence_id=evidence_id,
        company_id=_pick_company_id(result, routing, company_id),
        document_id=document_id,
        source_type="prospectus",
        page=page,
        section_path=split_section_path(
            result.get("section")
            or (result.get("citation") or {}).get("section")
            or source.get("section_path")
        ),
        block_type=map_block_type(result.get("block_type") or source.get("block_type")),
        text=text or document_id,
        bbox=normalize_bbox(source.get("bbox")),
        screenshot_uri=f"/api/evidence/{evidence_id}/image",
        language=detect_language(text),
        ocr_used=False,
        ocr_confidence=1.0,
        source_timestamp=None,
        content_hash=sha256_text(text),
        parser_version=PARSER_VERSION,
        injection_like_text=detect_injection(text),
    )


def map_search_response(
    payload: dict[str, Any],
    *,
    company_id: str,
    source_evidences: Sequence[dict[str, Any]] | None = None,
) -> list[EvidenceObject]:
    routing = payload.get("routing") or {}
    source_by_id = {
        str(item.get("evidence_id")): item
        for item in (source_evidences or [])
        if item.get("evidence_id")
    }
    mapped: list[EvidenceObject] = []
    seen: set[str] = set()
    for result in payload.get("results") or []:
        source = None
        for evidence_id in result.get("evidence_ids") or []:
            if evidence_id in source_by_id:
                source = source_by_id[str(evidence_id)]
                break
        item = map_search_result_to_evidence(
            result,
            company_id=company_id,
            routing=routing,
            source_details=source,
        )
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        mapped.append(item)
    return mapped


def map_mineru_record(
    record: dict[str, Any],
    *,
    company_id: str,
    document_id: str,
) -> EvidenceObject | None:
    text = normalize_text(str(record.get("text") or ""))
    if len(text) < 8:
        return None
    page = mineru_page_to_agent_page(record.get("page"))
    evidence_id = str(record.get("evidence_id") or "").strip() or (
        "rag_ev_" + sha256_text("|".join([document_id, str(page), text]))[:16]
    )
    return EvidenceObject(
        evidence_id=evidence_id,
        company_id=str(record.get("company") or company_id),
        document_id=str(record.get("document_id") or document_id),
        source_type="prospectus",
        page=page,
        section_path=split_section_path(record.get("section_path")),
        block_type=map_block_type(record.get("block_type")),
        text=text,
        bbox=normalize_bbox(record.get("bbox")),
        screenshot_uri=f"/api/evidence/{evidence_id}/image",
        language=detect_language(text),
        ocr_used=False,
        ocr_confidence=1.0,
        source_timestamp=None,
        content_hash=sha256_text(text),
        parser_version=str(record.get("parser_version") or PARSER_VERSION),
        injection_like_text=detect_injection(text),
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def discover_mineru_document(root: Path, pdf_path: Path | None = None, hint: str | None = None) -> Path | None:
    if not root.exists():
        return None
    names: list[str] = []
    if hint:
        names.append(hint)
    if pdf_path is not None:
        names.extend([pdf_path.stem, pdf_path.name])
    for name in names:
        candidate = root / name
        if (candidate / "evidences.json").is_file() or (candidate / "document.json").is_file():
            return candidate
    needle = (hint or (pdf_path.stem if pdf_path else "")).replace(" ", "")
    for document in root.rglob("document.json"):
        try:
            payload = _load_json(document)
        except Exception:
            continue
        source = str(payload.get("source_file") or "")
        document_id = str(payload.get("document_id") or document.parent.name)
        if pdf_path is not None and (
            pdf_path.name in source or pdf_path.stem in source or pdf_path.stem in document_id
        ):
            return document.parent
        if needle and needle in document_id.replace(" ", ""):
            return document.parent
    return None


def map_mineru_document(
    document_dir: Path,
    *,
    company_id: str,
    max_evidence: int = 12000,
) -> ParseResult:
    document_path = document_dir / "document.json"
    evidence_path = document_dir / "evidences.json"
    document = _load_json(document_path) if document_path.is_file() else {}
    records = _load_json(evidence_path) if evidence_path.is_file() else []
    if not isinstance(records, list):
        records = []
    document_id = str(document.get("document_id") or document_dir.name)
    evidence: list[EvidenceObject] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        item = map_mineru_record(record, company_id=company_id, document_id=document_id)
        if item is None:
            continue
        evidence.append(item)
        if len(evidence) >= max_evidence:
            break
    data_gaps: list[str] = []
    if not evidence:
        data_gaps.append("MinerU evidence store is empty")
    if len(records) > len(evidence):
        data_gaps.append(f"MinerU evidence truncated to {max_evidence}")
    metadata = {
        "document_id": document_id,
        "filename": Path(str(document.get("source_file") or document_dir.name)).name,
        "pages": int(document.get("total_pages") or 0),
        "parsed_pages": int(document.get("total_pages") or 0),
        "evidence_count": len(evidence),
        "low_text_pages": [],
        "injection_count": sum(item.injection_like_text for item in evidence),
        "parser_version": str(document.get("parser_version") or PARSER_VERSION),
        "parser_backend": "mineru",
        "source_file": document.get("source_file"),
        "company": document.get("company"),
        "stock_code": document.get("stock_code"),
    }
    return ParseResult(evidence=evidence, metadata=metadata, data_gaps=data_gaps)