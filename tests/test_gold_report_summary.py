#!/usr/bin/env python3
"""Self-checks for Gold evaluation report helpers."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_gold_rag import build_ui_summary


def main() -> None:
    report = {
        "gold_count": 9,
        "summary": {
            "top5": {
                "exact_evidence_recall": 0.8889,
                "page_recall": 0.8889,
                "failed_exact_cases": ["gold_001"],
            },
            "top10": {
                "exact_evidence_recall": 1.0,
                "page_recall": 1.0,
                "failed_exact_cases": [],
            },
        },
    }

    summary = build_ui_summary(report)

    assert summary["gold_count"] == 9
    assert summary["top5_exact"] == "88.89%"
    assert summary["top10_exact"] == "100.00%"
    assert summary["top5_hits"] == "8/9"
    assert summary["top10_hits"] == "9/9"
    assert summary["target_met"] is True


if __name__ == "__main__":
    main()
