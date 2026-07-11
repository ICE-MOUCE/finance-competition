#!/usr/bin/env python3
"""Smoke test for the current LayeredRetriever."""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.embedding import EmbeddingConfig, EmbeddingEngine
from src.retriever import LayeredRetriever, RetrieverConfig
from src.vector import VectorStore


VECTOR_DIR = ROOT / "data" / "vectors"


def main() -> None:
    engine = EmbeddingEngine(EmbeddingConfig())
    store = VectorStore(str(VECTOR_DIR), dimension=engine.dimension)
    retriever = LayeredRetriever(store, engine, RetrieverConfig())

    stats = store.get_stats()
    print(f"vectors: {stats['total_vectors']}")
    print(f"dimension: {stats['dimension']}")

    cases = [
        {"query": "现金流风险", "layer": "financial"},
        {"query": "监管合规", "layer": "legal"},
        {"query": "股权集中", "layer": "governance"},
    ]

    rows = []
    for case in cases:
        start = time.time()
        results = retriever.search(case["query"], layer=case["layer"], top_k=5)
        elapsed = time.time() - start
        print(f"{case['layer']}: {len(results)} results in {elapsed:.3f}s")
        rows.append(
            {
                **case,
                "elapsed": round(elapsed, 3),
                "count": len(results),
                "results": [result.to_dict() for result in results],
            }
        )

    report = {
        "test_cases": rows,
        "summary": {
            "total_queries": len(cases),
            "all_returned_results": all(row["count"] > 0 for row in rows),
        },
    }
    output = VECTOR_DIR / "retriever_test_results.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    assert report["summary"]["all_returned_results"], "Retriever returned no results for at least one smoke query."


if __name__ == "__main__":
    main()
