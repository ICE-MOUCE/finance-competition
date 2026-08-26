from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Iterable

from .models import EvidenceObject


PARSER_VERSION = "pymupdf-block-parser-1.0"
INJECTION_PATTERNS = (
    "ignore previous",
    "ignore all previous",
    "忽略之前",
    "忽略系统提示",
    "system prompt",
    "泄露提示词",
    "输出密钥",
    "reveal your prompt",
    "call this tool",
)
SECTION_HINTS = {
    "risk factors": "Risk Factors",
    "風險因素": "Risk Factors",
    "风险因素": "Risk Factors",
    "financial information": "Financial Information",
    "財務資料": "Financial Information",
    "财务资料": "Financial Information",
    "business": "Business",
    "業務": "Business",
    "history and corporate structure": "History and Corporate Structure",
    "歷史、發展及公司架構": "History and Corporate Structure",
    "future plans and use of proceeds": "Future Plans and Use of Proceeds",
    "未來計劃及所得款項用途": "Future Plans and Use of Proceeds",
    "substantial shareholders": "Substantial Shareholders",
    "主要股東": "Substantial Shareholders",
    "appendix": "Appendices",
    "附錄": "Appendices",
}


@dataclass
class ParseResult:
    evidence: list[EvidenceObject]
    metadata: dict
    data_gaps: list[str]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\u00a0", " ").split())


def detect_language(text: str) -> str:
    cjk = sum("\u3400" <= char <= "\u9fff" for char in text)
    ascii_letters = sum(char.isascii() and char.isalpha() for char in text)
    traditional = sum(char in "風險財務業務發展與為後於會權證據" for char in text)
    if cjk and ascii_letters:
        return "mixed"
    if cjk:
        return "zh-HK" if traditional else "zh-CN"
    return "en"


def detect_injection(text: str) -> bool:
    lowered = text.casefold()
    return any(pattern in lowered for pattern in INJECTION_PATTERNS)


def detect_section(text: str, current: str) -> str:
    lowered = text.casefold()
    if len(text) <= 120:
        for hint, section in SECTION_HINTS.items():
            if hint.casefold() in lowered:
                return section
    return current


def stable_evidence_id(
    company_id: str,
    document_id: str,
    page: int,
    bbox: tuple[float, float, float, float],
    text: str,
) -> str:
    material = "|".join(
        [company_id, document_id, str(page), *(f"{value:.5f}" for value in bbox), text]
    )
    return "ev_" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def parse_pdf(path: Path, company_id: str, max_pages: int = 0, max_evidence: int = 12000) -> ParseResult:
    import fitz

    document_id = file_sha256(path)
    document = fitz.open(path)
    if document.needs_pass:
        raise ValueError("PDF is encrypted and requires a password")
    total_pages = document.page_count
    page_limit = min(total_pages, max_pages) if max_pages else total_pages
    evidence: list[EvidenceObject] = []
    low_text_pages: list[int] = []
    section = "Front Matter"
    for page_index in range(page_limit):
        page = document.load_page(page_index)
        page_text = normalize_text(page.get_text("text"))
        if len(page_text) < 40:
            low_text_pages.append(page_index + 1)
        blocks = page.get_text("blocks", sort=True)
        for block in blocks:
            if len(evidence) >= max_evidence:
                break
            if int(block[6]) != 0:
                continue
            text = normalize_text(str(block[4]))
            if len(text) < 8:
                continue
            section = detect_section(text, section)
            rect = page.rect
            bbox = (
                max(0.0, min(1.0, float(block[0]) / rect.width)),
                max(0.0, min(1.0, float(block[1]) / rect.height)),
                max(0.0, min(1.0, float(block[2]) / rect.width)),
                max(0.0, min(1.0, float(block[3]) / rect.height)),
            )
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            evidence_id = stable_evidence_id(company_id, document_id, page_index + 1, bbox, text)
            evidence.append(
                EvidenceObject(
                    evidence_id=evidence_id,
                    company_id=company_id,
                    document_id=document_id,
                    source_type="prospectus",
                    page=page_index + 1,
                    section_path=[section],
                    block_type="paragraph",
                    text=text,
                    bbox=bbox,
                    screenshot_uri=f"/api/evidence/{evidence_id}/image",
                    language=detect_language(text),
                    ocr_used=False,
                    ocr_confidence=1.0,
                    source_timestamp=None,
                    content_hash=content_hash,
                    parser_version=PARSER_VERSION,
                    injection_like_text=detect_injection(text),
                )
            )
        if len(evidence) >= max_evidence:
            break
    document.close()
    data_gaps = []
    if low_text_pages:
        preview = ", ".join(map(str, low_text_pages[:20]))
        data_gaps.append(f"文本层不足页面需 OCR/人工复核: {preview}")
    if len(evidence) >= max_evidence:
        data_gaps.append(f"证据块达到运行上限 {max_evidence}，后续块未入库")
    if page_limit < total_pages:
        data_gaps.append(f"仅解析前 {page_limit}/{total_pages} 页")
    metadata = {
        "document_id": document_id,
        "filename": path.name,
        "pages": total_pages,
        "parsed_pages": page_limit,
        "evidence_count": len(evidence),
        "low_text_pages": low_text_pages,
        "injection_count": sum(item.injection_like_text for item in evidence),
        "parser_version": PARSER_VERSION,
    }
    return ParseResult(evidence=evidence, metadata=metadata, data_gaps=data_gaps)


def render_evidence_image(pdf_path: Path, page_number: int, bbox: Iterable[float]) -> bytes:
    import fitz

    document = fitz.open(pdf_path)
    page = document.load_page(page_number - 1)
    x0, y0, x1, y1 = list(bbox)
    rect = page.rect
    clip = fitz.Rect(x0 * rect.width, y0 * rect.height, x1 * rect.width, y1 * rect.height)
    margin = 12
    clip = fitz.Rect(
        max(rect.x0, clip.x0 - margin),
        max(rect.y0, clip.y0 - margin),
        min(rect.x1, clip.x1 + margin),
        min(rect.y1, clip.y1 + margin),
    )
    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7), clip=clip, alpha=False)
    output = pixmap.tobytes("png")
    document.close()
    return output

