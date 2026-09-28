from __future__ import annotations

from pathlib import Path

from app.rag.ingest import parse_prospectus
from app.rag.mapper import map_mineru_document, map_search_response, normalize_bbox
from app.rag.retrieve import merge_parse_with_retrieval
from app.parser import ParseResult
from app.models import EvidenceObject
from app.skills import DEFAULT_SKILL_ORDER, INTERNAL_SKILL_ORDER, skill_registry
from app.skills.base import SkillContext


def _evidence(evidence_id: str, text: str, page: int = 1) -> EvidenceObject:
    return EvidenceObject(
        evidence_id=evidence_id,
        company_id="保誠",
        document_id="2021_02378_保誠",
        source_type="prospectus",
        page=page,
        section_path=["Business"],
        block_type="paragraph",
        text=text,
        bbox=(0.0, 0.0, 1.0, 1.0),
        screenshot_uri=None,
        language="zh-HK",
        content_hash="a" * 64,
        parser_version="test",
    )


def test_normalize_pixel_bbox_to_unit_square():
    bbox = normalize_bbox([371.0, 142.0, 621.0, 192.0], page_width=800, page_height=1000)
    assert all(0.0 <= value <= 1.0 for value in bbox)
    assert bbox[0] < bbox[2]
    assert bbox[1] < bbox[3]


def test_map_search_response_converts_page_and_keeps_evidence_id():
    payload = {
        "routing": {"document_id": "2021_02378_保誠", "company": "保誠"},
        "results": [
            {
                "document_id": "2021_02378_保誠",
                "company": "保誠",
                "pages": [0],
                "section": "風險因素",
                "evidence_ids": ["ev_2021_02378_保誠_p0_txt001"],
                "block_type": "text",
                "text": "Prudential plc英國保誠有限公司",
            }
        ],
    }
    mapped = map_search_response(payload, company_id="保誠")
    assert len(mapped) == 1
    item = mapped[0]
    assert item.evidence_id == "ev_2021_02378_保誠_p0_txt001"
    assert item.page == 1
    assert item.bbox == (0.0, 0.0, 1.0, 1.0)
    assert item.document_id == "2021_02378_保誠"


def test_map_mineru_document_uses_store_ids(tmp_path: Path):
    doc_dir = tmp_path / "2021_02378_保誠"
    doc_dir.mkdir()
    (doc_dir / "document.json").write_text(
        '{"document_id":"2021_02378_保誠","company":"保誠","total_pages":122,"parser_version":"3.4.3","source_file":"a.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / "evidences.json").write_text(
        """[
          {
            "evidence_id": "ev_2021_02378_保誠_p0_txt001",
            "document_id": "2021_02378_保誠",
            "company": "保誠",
            "page": 0,
            "section_path": ["封面"],
            "bbox": [371.0, 142.0, 621.0, 192.0],
            "block_type": "text",
            "text": "Prudential plc英國保誠有限公司"
          }
        ]""",
        encoding="utf-8",
    )
    parsed = map_mineru_document(doc_dir, company_id="保誠")
    assert parsed.metadata["parser_backend"] == "mineru"
    assert parsed.evidence[0].evidence_id == "ev_2021_02378_保誠_p0_txt001"
    assert parsed.evidence[0].page == 1
    assert all(0.0 <= value <= 1.0 for value in parsed.evidence[0].bbox)


def test_parse_prospectus_prefers_mineru_store(tmp_path: Path):
    pdf = tmp_path / "02378_20-09-2021_保誠_售股章程 - 股份發售.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    store = tmp_path / "evidence" / "2021_02378_保誠"
    store.mkdir(parents=True)
    (store / "document.json").write_text(
        '{"document_id":"2021_02378_保誠","company":"保誠","total_pages":2,"source_file":"02378_20-09-2021_保誠_售股章程 - 股份發售.pdf"}',
        encoding="utf-8",
    )
    (store / "evidences.json").write_text(
        '[{"evidence_id":"ev_x","document_id":"2021_02378_保誠","page":0,"bbox":[0,0,10,10],"block_type":"text","text":"客户集中度风险披露段落足够长"}]',
        encoding="utf-8",
    )
    parsed = parse_prospectus(
        pdf,
        "保誠",
        parser_backend="auto",
        mineru_root=tmp_path / "evidence",
        document_hint="2021_02378_保誠",
    )
    assert parsed.metadata["parser_backend"] == "mineru"
    assert parsed.evidence[0].evidence_id == "ev_x"


def test_merge_prefers_retrieval_over_full_parse():
    parsed = ParseResult(
        evidence=[_evidence("ev_parse", "整本解析块" * 4, page=2)],
        metadata={"document_id": "doc", "pages": 10, "parsed_pages": 10},
        data_gaps=[],
    )
    retrieved = [_evidence("ev_rag", "检索命中客户集中度", page=3)]
    merged = merge_parse_with_retrieval(parsed, retrieved, prefer_retrieval=True, max_evidence=10)
    assert [item.evidence_id for item in merged.evidence] == ["ev_rag"]
    assert merged.metadata["prefer_retrieval"] is True


def test_rag_skill_is_registered_first():
    assert DEFAULT_SKILL_ORDER == [
        "financial_risk",
        "legal_risk",
        "equity_risk",
        "business_risk",
        "market_risk",
        "nonstandard_risk",
    ]
    assert INTERNAL_SKILL_ORDER[0] == "rag_retrieval"
    assert INTERNAL_SKILL_ORDER[-1] == "orchestrator_decision"
    skill = skill_registry.create("rag_retrieval", provider="offline")
    context = SkillContext(
        analysis_id="analysis_demo",
        company_name="保誠",
        stock_code="02378.HK",
        mode="PREDICT",
        listing_date="2021-09-20",
        prediction_as_of="2021-09-01T00:00:00+08:00",
        issue_price=10.0,
        claims=[],
        evidence=[{"evidence_id": "ev_1", "page": 1, "section_path": ["Risk"], "text": "客户集中"}],
        prediction=None,
        parse_metadata={"document_id": "2021_02378_保誠"},
        extra={
            "retrieved_evidence": [{"evidence_id": "ev_1", "page": 1, "section_path": ["Risk"], "text": "客户集中"}],
            "rag_queries": {"FINANCIAL_DD_AGENT": "客户集中"},
            "rag_warnings": [],
            "rag_document_id": "2021_02378_保誠",
        },
    )
    result = skill.run(context)
    assert result.agent_name == "RAG_RETRIEVAL_AGENT"
    assert result.evidence_ids or "ev_1" in result.content
