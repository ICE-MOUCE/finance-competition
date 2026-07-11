import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.retriever.layered_retriever import LayeredRetriever
from src.retriever.models import SearchResult


def test_keyword_coverage_boost_handles_traditional_chinese_text():
    retriever = LayeredRetriever.__new__(LayeredRetriever)
    results = [
        SearchResult(
            chunk_id="low",
            evidence_ids=[],
            document_id="doc",
            company="德合集團",
            pages=[1],
            section_path=["概 要"],
            block_type="text",
            score=0.6,
            text="客戶付款存在不確定性。",
        ),
        SearchResult(
            chunk_id="high",
            evidence_ids=[],
            document_id="doc",
            company="德合集團",
            pages=[2],
            section_path=["風 險 因 素"],
            block_type="text",
            score=0.6,
            text="新項目可能延後，客戶付款能力下降，應收款可收回性及減值虧損存在風險。",
        ),
    ]

    ranked = retriever._boost_keyword_coverage(
        "德合集團 新项目 延后 客户付款 应收款 可收回 减值亏损",
        results,
    )

    assert ranked[0].chunk_id == "high"
    assert ranked[0].score > ranked[1].score
