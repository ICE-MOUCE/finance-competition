"""Diagnose hard semantic near-miss cases for answer-excerpt quality."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]


HARD_IDS = [
    "manual_new_田歌_cat_fin_010",
    "manual_new_董飞飞_seed_bus_005",
    "manual_new_董飞飞_cat_bus_009",
    "mgv1_maogeping_comp_no_litigation_001",
    "mgv1_yunzhisheng_comp_no_litigation_001",
    "mgv1_duodian_owner_connected_tx_001",
]


def load_cases() -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for path in [
        ROOT / "evaluation/benchmark/manual_gold_v1.json",
        ROOT / "evaluation/benchmark/manual_new_annotators_v1.json",
    ]:
        for case in json.loads(path.read_text(encoding="utf-8")):
            out[case["id"]] = case
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results",
        default=str(ROOT / "evaluation/benchmark/hard_near_miss_excerpt_v1_results.json"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "evaluation/benchmark/hard_near_miss_excerpt_v1_diagnosis.json"),
    )
    args = parser.parse_args()
    results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    cases = load_cases()
    exps = results.get("experiments") or {}
    diagnosis: Dict[str, Any] = {"experiments": {}, "hard_ids": HARD_IDS}
    for exp_name, ed in exps.items():
        rows = {r["id"]: r for r in ed.get("rows") or []}
        items = []
        for hid in HARD_IDS:
            row = rows.get(hid)
            case = cases.get(hid) or {}
            if not row:
                continue
            items.append(
                {
                    "case_id": hid,
                    "question": case.get("question") or row.get("question"),
                    "gold_rank": row.get("gold_rank"),
                    "recall_at_5": row.get("recall_at_5"),
                    "content_status": row.get("content_status"),
                    "page_status": row.get("page_status"),
                    "interpretation": row.get("interpretation"),
                    "failure_reason": row.get("failure_reason"),
                    "top1_preview": ((row.get("top1") or {}).get("preview") or "")[:200],
                    "top1_pages": (row.get("top1") or {}).get("pages"),
                    "ranked_brief": row.get("ranked_brief") or [],
                    "expected_keywords": case.get("expected_keywords"),
                    "gold_preview": ((case.get("expected_evidence_text") or "")[:200]),
                }
            )
        hit5 = sum(1 for x in items if x.get("recall_at_5"))
        diagnosis["experiments"][exp_name] = {
            "summary": ed.get("summary"),
            "hard_hit_at_5": hit5,
            "hard_total": len(items),
            "cases": items,
        }
    Path(args.out).write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
