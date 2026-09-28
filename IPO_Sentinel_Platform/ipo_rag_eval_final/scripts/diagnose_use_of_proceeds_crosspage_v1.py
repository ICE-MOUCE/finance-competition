
"""Diagnose use-of-proceeds cross-page list/table representation failures."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_gold_vs_rag_topk import gold_fields, score_result_against_gold  # noqa: E402
from types import SimpleNamespace  # noqa: E402

CASE_IDS = {
    "mgv1_yunzhisheng_ipo_use_proceeds_001",
    "mgv1_maogeping_ipo_use_proceeds_001",
    "mgv1_leapmotor_ipo_use_proceeds_001",
    "manual_ts_yideng_ipo_001",
}

UOP_MARKERS = [
    "\u6240\u5f97\u6b3e\u9805\u7528\u9014",  # ??????
    "\u6240\u5f97\u6b3e\u9879\u7528\u9014",  # ??????
    "\u672a\u4f86\u8a08\u5283\u53ca\u6240\u5f97\u6b3e\u9805\u7528\u9014",
    "\u672a\u6765\u8ba1\u5212\u53ca\u6240\u5f97\u6b3e\u9879\u7528\u9014",
    "\u6240\u5f97\u6b3e\u9805\u6de8\u984d",
    "\u6240\u5f97\u6b3e\u9879\u51c0\u989d",
    "\u52df\u96c6\u8d44\u91d1",
    "\u52df\u8cc7",
]
USE_VERBS = [
    "\u7528\u65bc",  # ??
    "\u7528\u4e8e",  # ??
    "\u5206\u914d",
    "\u9810\u671f\u5c07",
    "\u9884\u671f\u5c06",
]
ALLOC_RE = re.compile(r"\d+(?:\.\d+)?\s*%")


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def find_doc_dir(base: Path, document_id: str) -> Path:
    direct = base / document_id
    if direct.exists():
        return direct
    code = "_".join(document_id.split("_")[:2])
    for p in base.iterdir():
        if p.is_dir() and code in p.name:
            return p
    raise FileNotFoundError(f"{document_id} not under {base}")


def page_window(ranges: list[list[int]], pad: int = 2) -> set[int]:
    pages: set[int] = set()
    for pair in ranges or []:
        if len(pair) != 2:
            continue
        lo, hi = sorted(int(x) for x in pair)
        pages.update(range(lo - pad, hi + pad + 1))
    return pages


def section_is_uop(section_path: list[str] | None) -> bool:
    blob = norm(" ".join(section_path or []))
    return any(norm(m) in blob for m in UOP_MARKERS)


def text_is_uopish(section_path: list[str] | None, text: str) -> bool:
    blob = norm(" ".join(section_path or []) + " " + (text or ""))
    if any(norm(m) in blob for m in UOP_MARKERS):
        return True
    if ALLOC_RE.search(text or "") and (
        "\u6240\u5f97\u6b3e" in (text or "")
        or "\u52df" in (text or "")
        or any(v in (text or "") for v in USE_VERBS)
    ):
        return True
    return False


def load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in [
        ROOT / "evaluation/benchmark/manual_gold_v1.json",
        ROOT / "evaluation/benchmark/manual_new_annotators_v1.json",
    ]:
        for case in json.loads(path.read_text(encoding="utf-8")):
            cid = case.get("id") or ""
            if cid in CASE_IDS or (cid.endswith("ipo_005") and "ipo" in cid):
                item = dict(case)
                item["_dataset"] = path.stem
                cases.append(item)
    return cases


def load_rank_snapshot() -> dict[str, dict[str, Any]]:
    path = ROOT / "evaluation/benchmark/ipo_specific_rerank_v1_results.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for exp_name, exp in data.get("experiments", {}).items():
        for row in exp.get("rows", []):
            out.setdefault(row["id"], {})[exp_name] = {
                "gold_rank": row.get("gold_rank"),
                "failure_reason": row.get("failure_reason"),
            }
    return out


def analyze_case(case: dict[str, Any], ranks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    gf = gold_fields(case)
    document_id = (gf["document_ids"] or [None])[0]
    if not document_id:
        raise ValueError(case.get("id"))
    evidence_dir = find_doc_dir(ROOT / "data/evidence", document_id)
    chunk_dir = find_doc_dir(ROOT / "data/chunks", document_id)
    evidences = json.loads((evidence_dir / "evidences.json").read_text(encoding="utf-8"))
    chunks = json.loads((chunk_dir / "chunks.json").read_text(encoding="utf-8"))
    window = page_window(gf["phys_pages"], pad=2)

    near_evidences = [e for e in evidences if e.get("page") in window]
    uop_evidences = []
    short_alloc_frags = 0
    section_lag = 0
    for e in near_evidences:
        text = e.get("text") or e.get("table_description") or ""
        sec = e.get("section_path") or []
        if not text_is_uopish(sec, text):
            continue
        item = {
            "evidence_id": e.get("evidence_id"),
            "page": e.get("page"),
            "block_type": e.get("block_type"),
            "section_path": sec,
            "text_len": len(text),
            "preview": re.sub(r"\s+", " ", text)[:180],
            "has_percent": bool(ALLOC_RE.search(text)),
            "has_use_verb": any(v in text for v in USE_VERBS),
            "section_is_uop": section_is_uop(sec),
        }
        uop_evidences.append(item)
        if item["has_percent"] and item["text_len"] < 90:
            short_alloc_frags += 1
        if item["has_percent"] and not item["section_is_uop"]:
            section_lag += 1

    scored_chunks = []
    for c in chunks:
        text = c.get("text") or c.get("table_description") or ""
        pages = c.get("pages") or []
        if not (set(pages) & window or text_is_uopish(c.get("section_path"), text)):
            continue
        scored = score_result_against_gold(
            SimpleNamespace(
                text=text,
                pages=pages,
                document_id=c.get("document_id", document_id),
                score=0.0,
                section_path=c.get("section_path") or [],
                chunk_id=c.get("chunk_id"),
                evidence_ids=c.get("evidence_ids") or [],
            ),
            gf,
        )
        scored_chunks.append(
            {
                "chunk_id": c.get("chunk_id"),
                "pages": pages,
                "section_path": c.get("section_path") or [],
                "text_len": len(text),
                "n_evidence_ids": len(c.get("evidence_ids") or []),
                "content_hit": scored["content_hit"],
                "coverage": scored["coverage"],
                "keyword_coverage": scored["keyword_coverage"],
                "keyword_hit": scored["keyword_hit"],
                "page_hit": scored["page_hit"],
                "preview": re.sub(r"\s+", " ", text)[:200],
            }
        )
    scored_chunks.sort(key=lambda x: (x["content_hit"], x["coverage"], x["keyword_coverage"]), reverse=True)

    pack_texts = []
    pack_pages: set[int] = set()
    pack_eids = []
    for e in evidences:
        if e.get("page") not in window or e.get("block_type") != "text":
            continue
        text = e.get("text") or ""
        if text_is_uopish(e.get("section_path"), text):
            pack_texts.append(text)
            pack_pages.add(int(e.get("page") or 0))
            pack_eids.append(e.get("evidence_id"))
    parent_text = " ".join(pack_texts)
    parent_score = None
    if parent_text:
        parent_score = score_result_against_gold(
            SimpleNamespace(
                text=parent_text,
                pages=sorted(pack_pages),
                document_id=document_id,
                score=0.0,
                section_path=["\u672a\u4f86\u8a08\u5283\u53ca\u6240\u5f97\u6b3e\u9805\u7528\u9014"],
                chunk_id="simulated_parent_uop",
                evidence_ids=pack_eids,
            ),
            gf,
        )

    mechanisms = []
    if section_lag:
        mechanisms.append("section_path_lag_on_allocation_bullets")
    if short_alloc_frags:
        mechanisms.append("short_list_bullet_fragments")
    if scored_chunks and not any(c["content_hit"] for c in scored_chunks):
        mechanisms.append("no_single_chunk_content_hit")
    if parent_score and not parent_score["content_hit"]:
        mechanisms.append("parent_pack_still_misses_evaluator_content_hit")
    gold_text = case.get("expected_evidence_text") or ""
    if any(k in gold_text for k in ["GPU", "\u55ae\u50f9", "\u4f30\u8a08\u7e3d\u6210\u672c", "\u76f8\u95dc\u8a08\u7b97\u80fd\u529b"]):
        mechanisms.append("gold_text_contaminated_by_adjacent_table_header")

    if "gold_text_contaminated_by_adjacent_table_header" in mechanisms and (
        parent_score is None or not parent_score["content_hit"]
    ):
        root_cause = "evaluation_gold_or_norm_residual_plus_fragmentation"
    elif section_lag and short_alloc_frags:
        root_cause = "section_label_lag_and_list_fragmentation"
    elif short_alloc_frags:
        root_cause = "list_fragmentation"
    elif section_lag:
        root_cause = "section_label_lag"
    elif scored_chunks and any(c["content_hit"] for c in scored_chunks):
        root_cause = "representation_ok_ranking_or_other"
    else:
        root_cause = "chunk_boundary_issue"

    return {
        "case_id": case.get("id"),
        "dataset": case.get("_dataset"),
        "document_id": document_id,
        "question": case.get("question"),
        "expected_pages": gf["phys_pages"],
        "keywords": gf["keywords"],
        "gold_preview": re.sub(r"\s+", " ", gold_text)[:240],
        "rank_snapshot": ranks.get(case.get("id"), {}),
        "near_evidence_count": len(near_evidences),
        "near_evidence_types": dict(Counter(e.get("block_type") for e in near_evidences)),
        "uop_evidence_count": len(uop_evidences),
        "short_alloc_frags": short_alloc_frags,
        "section_lag_alloc_count": section_lag,
        "uop_evidences_sample": uop_evidences[:12],
        "nearby_chunks": scored_chunks[:12],
        "best_existing_chunk": scored_chunks[0] if scored_chunks else None,
        "simulated_parent_pack": {
            "n_evidences": len(pack_eids),
            "pages": sorted(pack_pages),
            "text_len": len(parent_text),
            "score": parent_score,
            "preview": re.sub(r"\s+", " ", parent_text)[:240],
        },
        "mechanisms": mechanisms,
        "root_cause": root_cause,
        "recommended_fix_type": (
            "chunk_representation_repair"
            if root_cause
            in {
                "section_label_lag_and_list_fragmentation",
                "list_fragmentation",
                "section_label_lag",
                "chunk_boundary_issue",
            }
            else "no_code_gold_or_evaluator_review"
        ),
    }


def main() -> None:
    ranks = load_rank_snapshot()
    rows = [analyze_case(case, ranks) for case in load_cases()]
    summary = {
        "n_cases": len(rows),
        "root_cause_counts": dict(Counter(r["root_cause"] for r in rows)),
        "recommended_fix_counts": dict(Counter(r["recommended_fix_type"] for r in rows)),
        "yunzhisheng": next((r for r in rows if r["case_id"] == "mgv1_yunzhisheng_ipo_use_proceeds_001"), None),
        "parent_pack_helps_any": any(
            ((r.get("simulated_parent_pack") or {}).get("score") or {}).get("content_hit")
            and not ((r.get("best_existing_chunk") or {}).get("content_hit"))
            for r in rows
        ),
    }
    out = {
        "summary": summary,
        "rows": rows,
        "design_implication": {
            "preferred_primary_fix": "P0B_section_aware_list_enrichment_plus_section_path_carry",
            "why_not_only_local_script": "Need generic trigger on use-of-proceeds allocation bullets and section lag, not document whitelist.",
            "yunzhisheng_blocker": (
                "Packed allocation text still may miss evaluator content_hit because Gold text is contaminated by GPU table headers "
                "and evaluator TRAD map misses \u9805->\u9879 for keyword \u6240\u5f97\u6b3e\u9879."
            ),
        },
    }
    json_path = ROOT / "evaluation/benchmark/use_of_proceeds_crosspage_diagnosis_v1.json"
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {json_path}")
    print("root_cause_counts", summary["root_cause_counts"])
    y = summary["yunzhisheng"]
    if y:
        print(
            "yunzhisheng",
            y["root_cause"],
            "best_hit",
            (y.get("best_existing_chunk") or {}).get("content_hit"),
            "parent_hit",
            ((y.get("simulated_parent_pack") or {}).get("score") or {}).get("content_hit"),
            "mechanisms",
            y["mechanisms"],
        )


if __name__ == "__main__":
    main()
