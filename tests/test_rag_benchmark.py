import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_rag_benchmark import rate, validate_cases


def main() -> None:
    cases = json.loads((ROOT / "evaluation" / "benchmark" / "benchmark_queries.json").read_text(encoding="utf-8"))
    validate_cases(cases)
    assert len(cases) == 60
    assert {case["category"] for case in cases} == {
        "financial_risk", "business_risk", "ownership_risk", "compliance_risk", "ipo_specific_risk"
    }
    assert rate([{"page_range_hit": True}, {"page_range_hit": None}], "page_range_hit") == {
        "rate": 1.0, "denominator": 1
    }


if __name__ == "__main__":
    main()
