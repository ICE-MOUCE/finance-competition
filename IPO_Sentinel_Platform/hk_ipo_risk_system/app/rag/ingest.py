from __future__ import annotations

from pathlib import Path

from ..parser import ParseResult, parse_pdf
from .mapper import discover_mineru_document, map_mineru_document


def parse_prospectus(
    path: Path,
    company_id: str,
    *,
    parser_backend: str = "auto",
    mineru_root: Path | None = None,
    max_pages: int = 0,
    max_evidence: int = 12000,
    document_hint: str | None = None,
) -> ParseResult:
    backend = (parser_backend or "auto").strip().lower()
    mineru_root = Path(mineru_root) if mineru_root else None
    if backend in {"auto", "mineru"} and mineru_root is not None:
        found = discover_mineru_document(mineru_root, pdf_path=path, hint=document_hint)
        if found is not None:
            parsed = map_mineru_document(found, company_id=company_id, max_evidence=max_evidence)
            if parsed.evidence or backend == "mineru":
                parsed.metadata["source_pdf"] = str(path)
                parsed.metadata["mineru_dir"] = str(found)
                return parsed
            parsed.data_gaps.append("MinerU 产物为空，已回退 PyMuPDF")
        elif backend == "mineru":
            return ParseResult(
                evidence=[],
                metadata={
                    "document_id": path.stem,
                    "filename": path.name,
                    "pages": 0,
                    "parsed_pages": 0,
                    "evidence_count": 0,
                    "low_text_pages": [],
                    "injection_count": 0,
                    "parser_version": "mineru-missing",
                    "parser_backend": "mineru",
                },
                data_gaps=[f"未找到 MinerU 证据库: {mineru_root}"],
            )
    parsed = parse_pdf(path, company_id, max_pages=max_pages, max_evidence=max_evidence)
    parsed.metadata["parser_backend"] = "pymupdf"
    parsed.metadata["source_pdf"] = str(path)
    return parsed