import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.evaluate_gold_rag import evaluate_risk_extraction
from src.retriever.models import SearchResult


def test_risk_extraction_metric_scores_keyword_coverage_from_returned_evidence():
    case = {
        "id": "case_001",
        "risk_element": "供应商材料短缺、延误交付或材料缺陷可能导致项目无法按时完成及赔偿客户。",
    }
    results = [
        SearchResult(
            chunk_id="chunk_001",
            evidence_ids=["ev_001"],
            document_id="doc",
            company="company",
            pages=[49],
            section_path=["风险因素"],
            block_type="text",
            score=0.9,
            text="若供应商出现材料短缺、延误交付或材料缺陷，本集团可能无法按时完成项目并须赔偿客户。",
        )
    ]

    row = evaluate_risk_extraction(case, results)

    assert row["risk_element_hit"] is True
    assert row["keyword_coverage"] >= 0.8
    assert "供应商" in row["matched_keywords"]


def test_risk_extraction_metric_fails_when_returned_text_lacks_core_terms():
    case = {
        "id": "case_002",
        "risk_element": "经营活动现金流出增加，存在现金流消耗压力。",
    }
    results = [
        SearchResult(
            chunk_id="chunk_002",
            evidence_ids=["ev_002"],
            document_id="doc",
            company="company",
            pages=[10],
            section_path=["概要"],
            block_type="text",
            score=0.8,
            text="公司主要介绍董事和历史沿革。",
        )
    ]

    row = evaluate_risk_extraction(case, results)

    assert row["risk_element_hit"] is False
    assert row["keyword_coverage"] < 0.8


def test_risk_extraction_metric_accepts_financial_synonyms():
    case = {
        "id": "case_003",
        "risk_element": "最大客户及五大客户收入占比较高，存在客户集中度风险。",
    }
    results = [
        SearchResult(
            chunk_id="chunk_003",
            evidence_ids=["ev_003"],
            document_id="doc",
            company="company",
            pages=[88],
            section_path=["客户"],
            block_type="text",
            score=0.9,
            text="最大客户及五大客户的收益占比集中，若主要客户减少订单，业务可能受到影响。",
        )
    ]

    row = evaluate_risk_extraction(case, results)

    assert row["risk_element_hit"] is True
    assert "收入占比" in row["matched_keywords"]


if __name__ == "__main__":
    test_risk_extraction_metric_scores_keyword_coverage_from_returned_evidence()
    test_risk_extraction_metric_fails_when_returned_text_lacks_core_terms()
    test_risk_extraction_metric_accepts_financial_synonyms()
