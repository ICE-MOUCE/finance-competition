from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from src.chunk.store import ChunkStore
from src.evidence.store import EvidenceStore

TRAD = str.maketrans(
    {
        "項": "项",
        "發": "发",
        "業": "业",
        "國": "国",
        "與": "与",
        "為": "为",
        "於": "于",
        "後": "后",
        "來": "来",
        "們": "们",
        "這": "这",
        "還": "还",
        "對": "对",
        "開": "开",
        "關": "关",
        "將": "将",
        "經": "经",
        "營": "营",
        "運": "运",
        "資": "资",
        "產": "产",
        "員": "员",
        "報": "报",
        "據": "据",
        "億": "亿",
        "萬": "万",
        "餘": "余",
        "並": "并",
        "從": "从",
        "時": "时",
        "會": "会",
        "個": "个",
        "麼": "么",
        "應": "应",
        "當": "当",
        "無": "无",
        "與": "与",
        "該": "该",
        "長": "长",
        "現": "现",
        "點": "点",
        "數": "数",
        "華": "华",
        "東": "东",
        "車": "车",
        "電": "电",
        "網": "网",
        "聯": "联",
        "總": "总",
        "額": "额",
        "費": "费",
        "務": "务",
        "際": "际",
        "專": "专",
        "門": "门",
        "區": "区",
        "廣": "广",
        "價": "价",
        "錢": "钱",
        "銷": "销",
        "購": "购",
        "買": "买",
        "賣": "卖",
        "損": "损",
        "虧": "亏",
        "潤": "润",
        "稅": "税",
        "債": "债",
        "權": "权",
        "責": "责",
        "險": "险",
        "證": "证",
        "監": "监",
        "審": "审",
        "計": "计",
        "劃": "划",
        "設": "设",
        "備": "备",
        "術": "术",
        "術": "术",
        "研": "研",
        "發": "发",
        "開": "开",
        "發": "发",
    }
)


def norm(text: str) -> str:
    text = (text or "").translate(TRAD).lower()
    text = re.sub(r"\s+", "", text)
    return text


def tokens_from_gold(text: str) -> List[str]:
    raw = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9%\.]+", text or "")
    out: List[str] = []
    seen = set()
    for tok in raw:
        t = norm(tok)
        if len(t) < 2 or t in seen:
            continue
        seen.add(t)
        out.append(tok)
        if len(out) >= 24:
            break
    return out


def coverage(text: str, gold_tokens: Sequence[str]) -> float:
    if not gold_tokens:
        return 0.0
    hay = norm(text)
    return sum(1 for tok in gold_tokens if norm(tok) in hay) / len(gold_tokens)


def pages_overlap(result_pages: Sequence[int], expected: Sequence[Sequence[int]]) -> bool:
    for page in result_pages or []:
        for pair in expected or []:
            if len(pair) != 2:
                continue
            lo, hi = sorted([int(pair[0]), int(pair[1])])
            if lo <= int(page) <= hi:
                return True
    return False


def flatten_ranges(ranges: Sequence[Sequence[int]]) -> List[int]:
    pages: List[int] = []
    for pair in ranges or []:
        if len(pair) != 2:
            continue
        lo, hi = sorted([int(pair[0]), int(pair[1])])
        pages.extend(range(lo, hi + 1))
    return pages


def nearest_delta(expected_ranges: Sequence[Sequence[int]], returned_pages: Sequence[int]) -> Optional[Dict[str, int]]:
    expected_pages = flatten_ranges(expected_ranges)
    clean = [int(p) for p in returned_pages or []]
    if not expected_pages or not clean:
        return None
    best = None
    for e in expected_pages:
        for r in clean:
            d = abs(r - e)
            cand = (d, r - e, e, r)
            if best is None or cand < best:
                best = cand
    assert best is not None
    return {"abs_delta": best[0], "signed_delta": best[1], "expected_page": best[2], "returned_page": best[3]}


def load_cases() -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for path in [
        ROOT / "evaluation/benchmark/manual_gold_v1.json",
        ROOT / "evaluation/benchmark/manual_new_annotators_v1.json",
    ]:
        data = json.loads(path.read_text(encoding="utf-8"))
        cases = data if isinstance(data, list) else data.get("cases") or []
        for case in cases:
            cid = case.get("id") or case.get("case_id")
            if cid:
                case = dict(case)
                case["_dataset"] = path.name
                out[cid] = case
    return out


def load_chunk_map(document_id: str, cache: Dict[str, Dict[str, dict]]) -> Dict[str, dict]:
    if document_id in cache:
        return cache[document_id]
    store = ChunkStore()
    chunks = store.load(document_id) or []
    mapping: Dict[str, dict] = {}
    for ch in chunks:
        if isinstance(ch, dict):
            mapping[ch.get("chunk_id") or ""] = ch
        else:
            mapping[getattr(ch, "chunk_id", "")] = ch.__dict__
    cache[document_id] = mapping
    return mapping


def evidence_pages_for_chunk(chunk: dict, evidence_cache: Dict[str, Dict[str, dict]]) -> List[int]:
    doc = chunk.get("document_id") or ""
    if doc not in evidence_cache:
        estore = EvidenceStore()
        evidence_cache[doc] = estore.load_document(doc) or {}
    emap = evidence_cache[doc]
    pages: List[int] = []
    for eid in chunk.get("evidence_ids") or []:
        ev = emap.get(eid) or {}
        page = ev.get("page")
        if page is None:
            continue
        try:
            pages.append(int(page))
        except Exception:
            continue
    return sorted(set(pages))


def text_supports_answer(text: str, case: dict) -> Dict[str, Any]:
    gold_text = case.get("expected_evidence_text") or case.get("gold_text") or ""
    keywords = case.get("expected_keywords") or case.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [x for x in re.split(r"[、,，;/；\s]+", keywords) if x]
    toks = tokens_from_gold(gold_text)
    cov = coverage(text, toks) if toks else 0.0
    hay = norm(text)
    kw_hit = [k for k in keywords if norm(k) and norm(k) in hay]
    kw_cov = (len(kw_hit) / len(keywords)) if keywords else 0.0
    supports = cov >= 0.25 or (kw_cov >= 0.5 and len(kw_hit) >= 1) or (len(kw_hit) >= 2)
    return {
        "supports_answer": supports,
        "coverage": round(cov, 4),
        "keyword_coverage": round(kw_cov, 4),
        "keyword_hit": kw_hit,
    }



def classify_case(
    case: dict,
    row: dict,
    chunk: Optional[dict],
    evidence_pages: List[int],
) -> Dict[str, Any]:
    expected = case.get("expected_physical_page_ranges_0_based") or case.get("expected_page_ranges") or []
    top1 = row.get("top1") or {}
    hit_pages = [int(p) for p in (top1.get("pages") or [])]
    full_text = (chunk or {}).get("text") or top1.get("preview") or ""
    support = text_supports_answer(full_text, case)
    # fallback to evaluator's own content metrics if preview/chunk truncated oddly
    if not support["supports_answer"]:
        cov = float(top1.get("coverage") or 0.0)
        kw = float(top1.get("keyword_coverage") or 0.0)
        kw_hit = top1.get("keyword_hit") or []
        if cov >= 0.25 or (kw >= 0.5 and len(kw_hit) >= 1) or top1.get("content_hit"):
            support = {
                "supports_answer": True,
                "coverage": round(cov, 4),
                "keyword_coverage": round(kw, 4),
                "keyword_hit": kw_hit,
                "support_source": "evaluator_top1_metrics",
            }
        else:
            support["support_source"] = "full_text"
    else:
        support["support_source"] = "full_text"

    delta = nearest_delta(expected, hit_pages)
    page_hit_any = bool(row.get("page_hit_any"))
    cross_page = len(set(hit_pages)) > 1
    has_uop_enrichment = "[UOP allocation facts]" in full_text
    evidence_span_wider = False
    if evidence_pages and hit_pages:
        evidence_span_wider = (max(evidence_pages) - min(evidence_pages)) > (max(hit_pages) - min(hit_pages))

    alt_page_hits = [b for b in (row.get("ranked_brief") or []) if b.get("page_hit")]
    strong_alt = any((b.get("coverage") or 0) >= 0.2 or (b.get("rank") or 99) <= 5 for b in alt_page_hits)

    # Prospectus often repeats same fact in 概要 and later detailed chapter.
    # Require evidence that a page-correct candidate exists in topk, or top1 itself is clearly
    # the same allocation/ownership/financial fact family with strong support.
    multi_location = False
    strong_support = (
        float(support.get("coverage") or 0) >= 0.35
        or float(support.get("keyword_coverage") or 0) >= 0.6
        or float(top1.get("coverage") or 0) >= 0.35
        or (float(top1.get("keyword_coverage") or 0) >= 0.5 and len(top1.get("keyword_hit") or []) >= 2)
    )
    if support["supports_answer"] and page_hit_any and strong_support:
        multi_location = True
    elif support["supports_answer"] and page_hit_any and strong_alt:
        multi_location = True
    elif support["supports_answer"] and page_hit_any and delta and delta["abs_delta"] >= 8:
        # weaker content but correct page also recalled -> still multi-location residual
        multi_location = True

    packing_span = False
    if has_uop_enrichment and evidence_pages and pages_overlap(evidence_pages, expected) and not pages_overlap(hit_pages, expected):
        packing_span = True
    if cross_page and evidence_pages and pages_overlap(evidence_pages, expected) and not pages_overlap(hit_pages, expected):
        packing_span = True
    if (
        support["supports_answer"]
        and delta
        and delta["abs_delta"] <= 2
        and not pages_overlap(hit_pages, expected)
        and cross_page
    ):
        packing_span = True

    labels = case.get("expected_page_labels") or []
    gold_basis = False
    if labels and hit_pages and pages_overlap(hit_pages, labels) and not pages_overlap(hit_pages, expected):
        gold_basis = True

    evaluator_strict = False
    if support["supports_answer"] and page_hit_any and not top1.get("page_hit"):
        evaluator_strict = True
    if support["supports_answer"] and delta and delta["abs_delta"] <= 2 and not pages_overlap(hit_pages, expected):
        # adjacent page, same section neighborhood
        evaluator_strict = True

    true_error = False
    if not support["supports_answer"] and not page_hit_any:
        true_error = True
    elif not support["supports_answer"] and delta and delta["abs_delta"] >= 50 and not strong_alt:
        true_error = True
    elif support["supports_answer"] and not page_hit_any and delta and delta["abs_delta"] >= 20 and not strong_alt:
        # content-ish hit on far pages, and no page-correct candidate in topk
        true_error = True
    elif support["supports_answer"] and not strong_support and delta and delta["abs_delta"] >= 50 and not page_hit_any:
        true_error = True

    # single primary root cause with explicit priority
    if packing_span:
        root = "B_chunk_page_span_too_wide"
    elif gold_basis:
        root = "C_gold_page_basis_issue"
    elif multi_location and support["supports_answer"]:
        # multi-location is the dominant prospectus residual; evaluator-strict is secondary label
        root = "A_multi_location_disclosure"
    elif evaluator_strict and support["supports_answer"]:
        root = "D_evaluator_page_match_too_strict"
    elif true_error:
        root = "E_true_page_grounding_error"
    elif support["supports_answer"] and page_hit_any:
        root = "A_multi_location_disclosure"
    elif support["supports_answer"]:
        root = "D_evaluator_page_match_too_strict"
    else:
        root = "E_true_page_grounding_error"

    ranking_success = bool(row.get("gold_rank") == 1 or row.get("recall_at_1"))
    page_fail_only = bool(support["supports_answer"] and ranking_success)

    return {
        "root_cause": root,
        "supports_answer": support["supports_answer"],
        "support_metrics": support,
        "nearest_delta": delta,
        "cross_page_chunk": cross_page,
        "has_uop_enrichment": has_uop_enrichment,
        "page_hit_any_in_topk": page_hit_any,
        "evidence_pages": evidence_pages,
        "ranking_success": ranking_success,
        "page_grounding_fail_only": page_fail_only,
        "signals": {
            "multi_location": multi_location,
            "packing_span": packing_span,
            "gold_basis": gold_basis,
            "evaluator_strict": evaluator_strict,
            "true_error": true_error,
            "strong_alt_page_hit": strong_alt,
            "evidence_span_wider_than_chunk_pages": evidence_span_wider,
            "alt_page_hit_count_in_brief": len(alt_page_hits),
        },
    }



def main() -> None:
    parser = argparse.ArgumentParser(description="Audit content_hit_page_mismatch residuals")
    parser.add_argument(
        "--results",
        default=str(ROOT / "evaluation/benchmark/use_of_proceeds_crosspage_repair_v1_results.json"),
    )
    parser.add_argument("--experiment", default="G_plus_E")
    parser.add_argument(
        "--out-json",
        default=str(ROOT / "evaluation/benchmark/page_grounding_residual_v1.json"),
    )
    parser.add_argument(
        "--out-md",
        default=str(ROOT / "docs/rag/PAGE_GROUNDING_RESIDUAL_V1.md"),
    )
    args = parser.parse_args()

    results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    if args.experiment not in results["experiments"]:
        raise SystemExit(f"experiment not found: {args.experiment}")
    exp = results["experiments"][args.experiment]
    cases = load_cases()

    mismatch_rows = [r for r in exp["rows"] if r.get("failure_reason") == "content_hit_page_mismatch"]
    # also include requested focus ids even if not mismatch in this experiment
    focus_ids = [
        "mgv1_yunzhisheng_ipo_use_proceeds_001",
        "manual_ts_yideng_fin_001",
        "manual_ts_yideng_ipo_001",
        "manual_ch_duodian_bus_001",
        "mgv1_leapmotor_fin_loss_001",
        "mgv1_duodian_owner_controller_001",
        "mgv1_yunzhisheng_owner_controller_001",
        "mgv1_youran_owner_controller_connected_001",
        "manual_new_董飞飞_cat_fin_010",
        "manual_new_董飞飞_seed_bus_002",
    ]
    by_id = {r["id"]: r for r in exp["rows"]}
    selected_ids = []
    for cid in [r["id"] for r in mismatch_rows] + focus_ids:
        if cid not in selected_ids and cid in by_id:
            selected_ids.append(cid)

    chunk_cache: Dict[str, Dict[str, dict]] = {}
    evidence_cache: Dict[str, Dict[str, dict]] = {}
    diagnostics: List[dict] = []

    for cid in selected_ids:
        row = by_id[cid]
        case = cases.get(cid) or {}
        top1 = row.get("top1") or {}
        doc_id = top1.get("doc") or row.get("document_id") or ""
        chunk_id = top1.get("chunk_id") or ""
        chunk = None
        evidence_pages: List[int] = []
        if doc_id and chunk_id:
            cmap = load_chunk_map(doc_id, chunk_cache)
            chunk = cmap.get(chunk_id)
            if chunk:
                evidence_pages = evidence_pages_for_chunk(chunk, evidence_cache)

        expected_phys = case.get("expected_physical_page_ranges_0_based") or case.get("expected_page_ranges") or []
        expected_labels = case.get("expected_page_labels") or []
        expected_raw = case.get("expected_page_ranges") or []
        hit_pages = [int(p) for p in (top1.get("pages") or [])]
        classification = classify_case(case, row, chunk, evidence_pages)

        # compare alternative page-correct candidates
        alt = []
        for b in row.get("ranked_brief") or []:
            if b.get("page_hit"):
                alt.append(
                    {
                        "rank": b.get("rank"),
                        "pages": b.get("pages"),
                        "coverage": b.get("coverage"),
                        "chunk_id": b.get("chunk_id"),
                        "preview": (b.get("preview") or "")[:180],
                    }
                )

        item = {
            "case_id": cid,
            "experiment": args.experiment,
            "dataset": row.get("dataset") or case.get("_dataset"),
            "category": row.get("category") or case.get("category"),
            "question": row.get("question") or case.get("question"),
            "document_id": doc_id,
            "failure_reason": row.get("failure_reason"),
            "is_content_hit_page_mismatch": row.get("failure_reason") == "content_hit_page_mismatch",
            "gold_rank": row.get("gold_rank"),
            "recall_at_1": row.get("recall_at_1"),
            "recall_at_5": row.get("recall_at_5"),
            "page_hit_any": row.get("page_hit_any"),
            "expected_physical_page_ranges_0_based": expected_phys,
            "expected_page_ranges": expected_raw,
            "expected_page_labels": expected_labels,
            "expected_keywords": case.get("expected_keywords") or case.get("keywords") or [],
            "gold_preview": ((case.get("expected_evidence_text") or case.get("gold_text") or "")[:240]),
            "hit_chunk_id": chunk_id,
            "hit_pages": hit_pages,
            "hit_section_path": top1.get("section_path") or (chunk or {}).get("section_path") or [],
            "hit_preview": top1.get("preview") or "",
            "hit_coverage": top1.get("coverage"),
            "hit_keyword_coverage": top1.get("keyword_coverage"),
            "hit_keyword_hit": top1.get("keyword_hit") or [],
            "hit_page_hit": top1.get("page_hit"),
            "chunk_text_preview": ((chunk or {}).get("text") or "")[:320],
            "chunk_pages_field": (chunk or {}).get("pages") or [],
            "evidence_ids": (chunk or {}).get("evidence_ids") or top1.get("evidence_ids") or [],
            "evidence_pages": evidence_pages,
            "alternative_page_hit_candidates": alt,
            "classification": classification,
            "metric_accounting": {
                "count_as_ranking_or_sufficiency_success": bool(
                    classification["supports_answer"] and (row.get("gold_rank") is not None)
                ),
                "count_as_page_grounding_fail_only": classification["page_grounding_fail_only"],
                "should_not_zero_out_content_hit": bool(
                    classification["supports_answer"] and row.get("failure_reason") == "content_hit_page_mismatch"
                ),
            },
            "code_change_needed": classification["root_cause"]
            in {
                "B_chunk_page_span_too_wide",
                "D_evaluator_page_match_too_strict",
                "E_true_page_grounding_error",
            },
            "minimal_fix_layer": {
                "A_multi_location_disclosure": "no_code_metric_split_or_gold_multi_location_annotation",
                "B_chunk_page_span_too_wide": "chunk_pages_recording_or_primary_page_span",
                "C_gold_page_basis_issue": "gold_page_review_checklist_only",
                "D_evaluator_page_match_too_strict": "evaluator_metric_split_page_vs_content",
                "E_true_page_grounding_error": "retrieval_or_chunk_page_grounding_minifix",
            }[classification["root_cause"]],
        }
        diagnostics.append(item)

    mismatch_only = [d for d in diagnostics if d["is_content_hit_page_mismatch"]]
    root_counts = Counter(d["classification"]["root_cause"] for d in mismatch_only)
    multi_n = root_counts.get("A_multi_location_disclosure", 0)
    pack_n = root_counts.get("B_chunk_page_span_too_wide", 0)
    gold_n = root_counts.get("C_gold_page_basis_issue", 0)
    eval_n = root_counts.get("D_evaluator_page_match_too_strict", 0)
    true_n = root_counts.get("E_true_page_grounding_error", 0)
    total = len(mismatch_only) or 1

    # decide single next step
    acceptable_multi = multi_n
    page_only = sum(1 for d in mismatch_only if d["metric_accounting"]["count_as_page_grounding_fail_only"])
    content_success_n = sum(1 for d in mismatch_only if d["classification"]["supports_answer"])
    # If most mismatches are still content-successful, do not open retrieval fix first.
    if content_success_n >= (total + 1) // 2 and (multi_n + eval_n + page_only) >= true_n:
        next_step = "evaluator_metric_split"
        next_step_detail = (
            "主因不是检索没找到证据，而是 content 已命中后仍被 page mismatch 叙事否掉。"
            "唯一下一步只改评估口径：把 content/sufficiency 与 page grounding 拆成独立指标；"
            "R@k 继续按 content_hit，page grounding 单独报告，不再用 content_hit_page_mismatch 掩盖 sufficiency 成功。"
        )
        recommend_code = True
    elif pack_n > 0 and pack_n >= max(multi_n, gold_n, eval_n, true_n):
        next_step = "chunk_pages_recording"
        next_step_detail = "主因是 packing 后 pages 记录过宽或未保留 primary page。下一步只修 chunk pages 记录方式。"
        recommend_code = True
    elif gold_n > 0 and gold_n >= max(multi_n, pack_n, eval_n, true_n):
        next_step = "gold_page_review"
        next_step_detail = "主因是 gold 页码口径/映射。下一步只出 gold 页码复核清单，不改 retrieval。"
        recommend_code = False
    elif true_n > 0 and true_n >= (total + 1) // 2:
        next_step = "true_grounding_minifix"
        next_step_detail = "主因是真正 page grounding 漂移。下一步再开最小修复任务。"
        recommend_code = True
    else:
        next_step = "evaluator_metric_split"
        next_step_detail = "默认将 page grounding 独立计量，避免低估已召回证据。"
        recommend_code = True

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_results": str(Path(args.results)),
        "experiment": args.experiment,
        "n_cases": exp["summary"].get("n_cases"),
        "page_mismatch_total": len(mismatch_only),
        "page_hit_any_rate": exp["summary"].get("page_hit_any_rate"),
        "failure_reason_counts": exp["summary"].get("failure_reason_counts"),
        "root_cause_counts": {
            "A_multi_location_disclosure": multi_n,
            "B_chunk_page_span_too_wide": pack_n,
            "C_gold_page_basis_issue": gold_n,
            "D_evaluator_page_match_too_strict": eval_n,
            "E_true_page_grounding_error": true_n,
        },
        "ratios": {
            "acceptable_multi_location": round(multi_n / total, 4),
            "packing_page_span": round(pack_n / total, 4),
            "true_page_grounding_error": round(true_n / total, 4),
            "page_grounding_fail_only": round(page_only / total, 4),
        },
        "impact_on_hard_metrics": {
            "content_or_sufficiency_underestimated": page_only > 0,
            "page_grounding_should_be_independent_metric": True,
            "g_plus_e_content_success_if_page_split": {
                "current_ok": exp["summary"]["failure_reason_counts"].get("ok", 0),
                "page_mismatch": len(mismatch_only),
                "ok_plus_page_mismatch": exp["summary"]["failure_reason_counts"].get("ok", 0) + len(mismatch_only),
                "note": "R@k already counts content_hit; failure_reason label currently over-penalizes interpretation.",
            },
        },
        "recommend_code_change": recommend_code,
        "single_next_step": next_step,
        "single_next_step_detail": next_step_detail,
        "diagnostics": diagnostics,
    }

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # markdown report
    lines: List[str] = []
    lines.append("# Page Grounding Residual V1")
    lines.append("")
    lines.append(f"> Generated at: {payload['generated_at']}")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append("- 只审计 `content_hit_page_mismatch` residual，不改 ranking，不打开 ranking flags，不改 Gold 答案。")
    lines.append(f"- 源结果：`{args.results}`")
    lines.append(f"- 实验：`{args.experiment}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- page mismatch 总数：**{payload['page_mismatch_total']}**")
    lines.append(
        "- root cause 统计：A/B/C/D/E = "
        f"{multi_n}/{pack_n}/{gold_n}/{eval_n}/{true_n}"
    )
    lines.append(f"- 可接受 multi-location 比例：**{payload['ratios']['acceptable_multi_location']:.2%}**")
    lines.append(f"- packing page span 比例：**{payload['ratios']['packing_page_span']:.2%}**")
    lines.append(f"- 真正 page grounding error 比例：**{payload['ratios']['true_page_grounding_error']:.2%}**")
    lines.append(f"- page-fail-only（内容已成功）比例：**{payload['ratios']['page_grounding_fail_only']:.2%}**")
    lines.append("")
    lines.append("## Impact on G+E Interpretation")
    lines.append("")
    lines.append(
        f"- 当前 failure_reason ok={exp['summary']['failure_reason_counts'].get('ok', 0)}，"
        f"content_hit_page_mismatch={len(mismatch_only)}。"
    )
    lines.append(
        "- 重要：`evaluate_gold_vs_rag_topk.py` 的 R@k / MRR 已按 **content_hit** 计算，"
        "不会因为 page mismatch 把 R@k 直接打成 0。"
    )
    lines.append(
        "- 但 `failure_reason=content_hit_page_mismatch` 会在解读时造成“失败感”，"
        "容易低估证据片段召回 / sufficiency。"
    )
    lines.append("- 建议把 page grounding 作为独立指标，而不是用它否掉 content success 的叙事。")
    lines.append("")
    lines.append("## Case Table")
    lines.append("")
    lines.append(
        "| case_id | expected phys pages | hit pages | supports | root cause | page_hit_any | ranking success | page-fail-only | minimal fix layer |"
    )
    lines.append("|---|---|---|---:|---|---:|---:|---:|---|")
    for d in diagnostics:
        if not d["is_content_hit_page_mismatch"] and d["case_id"] not in focus_ids:
            continue
        c = d["classification"]
        lines.append(
            "| `{cid}` | {exp} | {hit} | {sup} | {root} | {pha} | {rs} | {pfo} | {layer} |".format(
                cid=d["case_id"],
                exp=d["expected_physical_page_ranges_0_based"],
                hit=d["hit_pages"],
                sup=c["supports_answer"],
                root=c["root_cause"],
                pha=d["page_hit_any"],
                rs=c["ranking_success"],
                pfo=c["page_grounding_fail_only"],
                layer=d["minimal_fix_layer"],
            )
        )
    lines.append("")
    lines.append("## Per-case Notes")
    lines.append("")
    for d in diagnostics:
        if not d["is_content_hit_page_mismatch"] and d["case_id"] != "manual_ts_yideng_ipo_001":
            # still include focus non-mismatch briefly
            if d["case_id"] not in focus_ids:
                continue
        c = d["classification"]
        lines.append(f"### `{d['case_id']}`")
        lines.append("")
        lines.append(f"- question: {d['question']}")
        lines.append(f"- document_id: `{d['document_id']}`")
        lines.append(f"- expected_physical_page_ranges_0_based: `{d['expected_physical_page_ranges_0_based']}`")
        lines.append(f"- expected_page_labels: `{d['expected_page_labels']}`")
        lines.append(f"- hit pages: `{d['hit_pages']}` / chunk_id=`{d['hit_chunk_id']}`")
        lines.append(f"- evidence_pages: `{d['evidence_pages']}`")
        lines.append(
            f"- text supports answer: **{c['supports_answer']}** "
            f"(cov={c['support_metrics']['coverage']}, kw={c['support_metrics']['keyword_coverage']}, hits={c['support_metrics']['keyword_hit']})"
        )
        lines.append(f"- nearest delta: `{c['nearest_delta']}`")
        lines.append(f"- root cause: **{c['root_cause']}**")
        lines.append(
            f"- accounting: ranking/sufficiency success={d['metric_accounting']['count_as_ranking_or_sufficiency_success']}, "
            f"page-fail-only={d['metric_accounting']['count_as_page_grounding_fail_only']}"
        )
        lines.append(f"- minimal fix layer: `{d['minimal_fix_layer']}`")
        if d["alternative_page_hit_candidates"]:
            lines.append(f"- alternative page-hit candidates in top brief: `{d['alternative_page_hit_candidates'][:3]}`")
        lines.append(f"- hit preview: {d['hit_preview'][:180]}")
        lines.append("")

    lines.append("## Decision")
    lines.append("")
    lines.append(f"- 是否建议改代码：**{'是' if recommend_code else '否'}**")
    lines.append(f"- 唯一下一步：**{next_step}**")
    lines.append(f"- 说明：{next_step_detail}")
    lines.append("- 不建议现在改 ranking，不建议 Hybrid/BM25/CE/LLM reranker，不建议默认打开 flags。")
    lines.append("")
    lines.append("## Verification Notes")
    lines.append("")
    lines.append("- 本报告为只读诊断产物。")
    lines.append("- 未修改 Gold，未修改 Retriever 默认行为。")
    lines.append("")

    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"saved {out_json}")
    print(f"saved {out_md}")
    print("mismatch", len(mismatch_only))
    print("roots", dict(root_counts))
    print("next", next_step)


if __name__ == "__main__":
    main()
