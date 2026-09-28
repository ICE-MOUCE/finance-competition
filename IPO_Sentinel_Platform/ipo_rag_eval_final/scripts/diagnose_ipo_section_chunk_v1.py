"""Diagnose IPO-specific section/chunk failures without changing retrieval logic."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_gold_vs_rag_topk import (  # noqa: E402
    build_runtime,
    coverage,
    gold_fields,
    norm,
    pages_overlap,
    score_result_against_gold,
)
from src.retriever import RetrieverConfig  # noqa: E402
from src.retriever.models import SearchResult  # noqa: E402
from src.retriever.query_intent import build_intent_queries, infer_query_intent  # noqa: E402
from src.retriever.term_normalization import normalize_text  # noqa: E402


TARGET_CASE_IDS = [
    "manual_ts_yideng_ipo_001",
    "mgv1_duodian_ipo_preipo_001",
    "mgv1_maogeping_ipo_use_proceeds_001",
    "mgv1_leapmotor_ipo_use_proceeds_001",
    "mgv1_yunzhisheng_ipo_use_proceeds_001",
    "manual_new_董飞飞_cat_ipo_002",
    "manual_new_董飞飞_cat_ipo_004",
    "manual_new_董飞飞_cat_ipo_005",
]

EXPERIMENTS = {
    "baseline": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": False,
        "enable_section_hard_prior": False,
    },
    "B_intent": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": True,
        "enable_section_hard_prior": False,
    },
    "D_section_prior": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": True,
        "enable_section_hard_prior": True,
    },
}

REQUIRED_CASE_FIELDS = {
    "case_id",
    "document_id",
    "question",
    "expected_pages",
    "gold_preview",
    "gold_keywords",
    "gold_evidence_in_evidence_store",
    "gold_chunk_exists",
    "gold_vector_document_exists",
    "baseline_rank",
    "b_intent_rank",
    "d_section_prior_rank",
    "topk_content_hit",
    "hit_chunk_section_path",
    "gold_chunk_section_path",
    "section_label_match",
    "chunk_boundary_diagnosis",
    "representation_diagnosis",
    "final_root_cause",
    "recommended_fix_type",
}


def load_cases(paths: Iterable[Path]) -> List[dict]:
    out: List[dict] = []
    for path in paths:
        dataset = path.stem
        for case in json.loads(path.read_text(encoding="utf-8")):
            item = dict(case)
            item["_dataset"] = dataset
            if item.get("id") in TARGET_CASE_IDS:
                out.append(item)
    order = {case_id: index for index, case_id in enumerate(TARGET_CASE_IDS)}
    return sorted(out, key=lambda item: order.get(item.get("id"), 999))


def text_for_chunk(chunk: dict) -> str:
    if not chunk:
        return ""
    if chunk.get("block_type") == "table":
        return chunk.get("table_description", "") or chunk.get("text", "")
    if chunk.get("block_type") == "image":
        return chunk.get("image_description", "") or chunk.get("image_caption", "")
    return chunk.get("text", "") or chunk.get("table_description", "")


def item_match(item: dict, gf: dict, text: str, pages: List[int]) -> dict:
    haystack = norm(text)
    kw_hit = [kw for kw in gf["keywords"] if norm(kw) and norm(kw) in haystack]
    kw_cov = len(kw_hit) / len(gf["keywords"]) if gf["keywords"] else 0.0
    cov = coverage(text, gf["tokens"]) if gf["tokens"] else 0.0
    page_hit = pages_overlap(pages, gf["phys_pages"])
    content_hit = cov >= 0.35 or (kw_cov >= 0.5 and len(kw_hit) >= 2) or (cov >= 0.25 and page_hit)
    return {
        "content_hit": content_hit,
        "coverage": round(cov, 4),
        "keyword_coverage": round(kw_cov, 4),
        "keyword_hit": kw_hit[:12],
        "page_hit": page_hit,
        "pages": pages,
        "score": round(cov + kw_cov + (0.15 if page_hit else 0.0), 4),
        "preview": " ".join((text or "").split())[:260],
    }


def best_item_match(items: Iterable[dict], gf: dict, kind: str) -> dict:
    best: Optional[dict] = None
    for item in items:
        if kind == "chunk":
            text = text_for_chunk(item)
            pages = [int(p) for p in item.get("pages", []) if str(p).lstrip("-").isdigit()]
            item_id = item.get("chunk_id", "")
            section_path = item.get("section_path", []) or []
        else:
            text = item.get("text", "") or item.get("table_description", "")
            page = item.get("page")
            pages = [int(page)] if str(page).lstrip("-").isdigit() else []
            item_id = item.get("evidence_id", "")
            section_path = item.get("section_path", []) or []
        match = item_match(item, gf, text, pages)
        match.update({
            "id": item_id,
            "section_path": section_path,
            "block_type": item.get("block_type", ""),
        })
        if best is None or match["score"] > best["score"]:
            best = match
    return best or {
        "id": "",
        "content_hit": False,
        "coverage": 0.0,
        "keyword_coverage": 0.0,
        "keyword_hit": [],
        "page_hit": False,
        "pages": [],
        "score": 0.0,
        "section_path": [],
        "block_type": "",
        "preview": "",
    }


def item_pages(item: dict, kind: str) -> List[int]:
    pages = item.get("pages", []) if kind == "chunk" else [item.get("page")]
    return [int(p) for p in pages if str(p).lstrip("-").isdigit()]


def expected_page_items(items: Iterable[dict], gf: dict, kind: str) -> List[dict]:
    if not gf["phys_pages"]:
        return list(items)
    return [item for item in items if pages_overlap(item_pages(item, kind), gf["phys_pages"])]


def aggregate_expected_page_match(items: Iterable[dict], gf: dict, kind: str) -> dict:
    texts: List[str] = []
    pages_seen = set()
    for item in items:
        pages = item.get("pages", []) if kind == "chunk" else [item.get("page")]
        clean_pages = [int(p) for p in pages if str(p).lstrip("-").isdigit()]
        if gf["phys_pages"] and not pages_overlap(clean_pages, gf["phys_pages"]):
            continue
        pages_seen.update(clean_pages)
        texts.append(text_for_chunk(item) if kind == "chunk" else (item.get("text", "") or ""))
    text = "\n".join(texts)
    return item_match({}, gf, text, sorted(pages_seen)) if text else item_match({}, gf, "", [])


def load_artifacts(document_id: str) -> dict:
    chunks_path = ROOT / "data" / "chunks" / document_id / "chunks.json"
    evidence_path = ROOT / "data" / "evidence" / document_id / "evidences.json"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path.exists() else []
    evidences = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.exists() else []
    return {"chunks": chunks, "evidences": evidences}


def build_vector_index() -> dict:
    path = ROOT / "data" / "vectors" / "documents.json"
    docs = json.loads(path.read_text(encoding="utf-8"))
    by_chunk = {doc.get("chunk_id") or doc.get("id"): doc for doc in docs}
    by_doc: Dict[str, List[dict]] = defaultdict(list)
    for doc in docs:
        by_doc[doc.get("document_id", "")].append(doc)
    return {"by_chunk": by_chunk, "by_doc": by_doc, "total": len(docs)}


def infer_ipo_subtype(case: dict) -> str:
    q = normalize_text(case.get("question") or "")
    if any(term in q for term in ["发售价", "發售價", "交易价格", "交易價格", "流动性", "流動性", "波动", "波動"]):
        return "share_price_volatility"
    if any(term in q for term in ["发售前投资", "發售前投資", "招股前投资", "招股前投資", "preipo", "特殊权利", "特殊權利"]):
        return "pre_ipo"
    if any(term in q for term in ["所得款项", "所得款項", "募集资金", "募集資金", "募资", "募資", "用途"]):
        return "use_of_proceeds"
    return "ipo_other"


def section_label_match(subtype: str, section_path: List[str], text: str = "") -> bool:
    section = normalize_text(" ".join(str(x) for x in (section_path or [])))
    body = normalize_text(text or "")[:1000]
    combined = section + " " + body
    if subtype == "use_of_proceeds":
        return any(term in combined for term in [
            "未来计划及所得款项用途",
            "未來計劃及所得款項用途",
            "所得款项用途",
            "所得款項用途",
            "所得款项净额",
            "所得款項淨額",
        ])
    if subtype == "pre_ipo":
        return any(term in combined for term in [
            "首次公开发售前投资",
            "首次公開發售前投資",
            "发售前投资",
            "發售前投資",
            "preipo",
            "历史及重组",
            "歷史及重組",
        ])
    if subtype == "share_price_volatility":
        return any(term in combined for term in ["风险因素", "風險因素", "发售价", "發售價", "股份", "流动性", "流動性", "波动", "波動"])
    return False


def search_experiment(retriever: Any, case: dict, gf: dict, gold_chunk_id: str, top_k: int = 50) -> dict:
    document_id = gf["document_ids"][0] if gf["document_ids"] else None
    filters = {"document_id": document_id} if document_id else None
    results = retriever.search(case.get("question") or "", top_k=top_k, metadata_filters=filters)
    ranked = [score_result_against_gold(result, gf) for result in results]
    first_hit = next((dict(item, rank=i) for i, item in enumerate(ranked, 1) if item["content_hit"]), None)
    page_hit_rank = next((i for i, item in enumerate(ranked, 1) if item["content_hit"] and item["page_hit"]), None)
    exact_gold_rank = next(
        (i for i, result in enumerate(results, 1) if gold_chunk_id and result.chunk_id == gold_chunk_id),
        None,
    )
    return {
        "rank": first_hit["rank"] if first_hit else None,
        "exact_gold_chunk_rank": exact_gold_rank,
        "page_grounded_rank": page_hit_rank,
        "top10": bool(first_hit and first_hit["rank"] <= 10),
        "top20": bool(first_hit and first_hit["rank"] <= 20),
        "top50": bool(first_hit and first_hit["rank"] <= 50),
        "first_hit": first_hit,
        "top1": ranked[0] if ranked else None,
    }


def raw_dense_diagnosis(retriever: Any, case: dict, gf: dict, gold_chunk_id: str, top_k: int = 50) -> dict:
    document_id = gf["document_ids"][0] if gf["document_ids"] else None
    filters = {"document_id": document_id} if document_id else None
    query = case.get("question") or ""
    query_embedding = retriever.embedding_engine.embed_text(query)
    route = retriever._resolve_route(query, filters)
    raw_results, _ = retriever._search_raw_candidates(query_embedding, top_k, "all", route, filters)
    ranked = []
    exact_gold_rank = None
    for i, raw in enumerate(raw_results, 1):
        if gold_chunk_id and raw.get("chunk_id") == gold_chunk_id:
            exact_gold_rank = i
            break
    for raw in raw_results[: max(top_k, 200)]:
        chunk = retriever._get_chunk(raw.get("document_id", ""), raw.get("chunk_id", ""))
        text = retriever._get_chunk_text(raw, chunk)
        metadata = dict(raw.get("metadata", {}))
        if chunk:
            metadata["evidence_ids"] = chunk.get("evidence_ids", [])
        result = SearchResult(
            chunk_id=raw.get("chunk_id", ""),
            evidence_ids=metadata.get("evidence_ids", []),
            document_id=raw.get("document_id", ""),
            company=raw.get("company", ""),
            pages=raw.get("pages", []),
            section_path=raw.get("section_path", []),
            block_type=raw.get("block_type", ""),
            score=raw.get("score", 0.0),
            text=text,
            metadata=metadata,
        )
        ranked.append(score_result_against_gold(result, gf))
    first_hit = next((dict(item, rank=i) for i, item in enumerate(ranked, 1) if item["content_hit"]), None)
    return {
        "rank": first_hit["rank"] if first_hit else None,
        "exact_gold_chunk_rank": exact_gold_rank,
        "top10": bool(first_hit and first_hit["rank"] <= 10),
        "top20": bool(first_hit and first_hit["rank"] <= 20),
        "top50": bool(first_hit and first_hit["rank"] <= 50),
        "first_hit": first_hit,
        "candidate_count": len(raw_results),
    }


def diagnose_boundary(evidence_present: bool, chunk_present: bool, evidence_agg: dict, chunk_agg: dict) -> str:
    if chunk_present:
        return "gold facts preserved in a retrievable chunk"
    if evidence_present and chunk_agg["coverage"] >= 0.25:
        return "gold facts appear split across expected-page chunks"
    if evidence_present:
        return "evidence store has gold facts but no single chunk reaches content-hit threshold"
    if evidence_agg["coverage"] > 0 or evidence_agg["keyword_coverage"] > 0:
        return "evidence store has weak partial overlap only"
    return "gold facts not located in evidence store text"


def diagnose_representation(evidence_present: bool, chunk_present: bool, vector_present: bool, vector_text_hit: bool) -> str:
    if not evidence_present:
        return "evidence_text_missing_or_too_fragmented"
    if not chunk_present:
        return "evidence_to_chunk_representation_loss"
    if not vector_present:
        return "chunk_not_found_in_vector_documents"
    if not vector_text_hit:
        return "chunk_vectorized_but_vector_preview_does_not_show_full_gold_text"
    return "evidence_chunk_vector_chain_present"


def classify_root_cause(
    evidence_present: bool,
    chunk_present: bool,
    vector_present: bool,
    dense: dict,
    baseline: dict,
    b_intent: dict,
    section_match: bool,
) -> str:
    baseline_rank = baseline.get("rank")
    b_rank = b_intent.get("rank")
    baseline_exact = baseline.get("exact_gold_chunk_rank")
    b_exact = b_intent.get("exact_gold_chunk_rank")
    if not evidence_present and not chunk_present:
        return "vector_missing"
    if evidence_present and not chunk_present:
        return "chunk_boundary_issue"
    if chunk_present and not vector_present:
        return "vector_missing"
    if not section_match:
        return "section_label_issue"
    if (baseline_exact is None and b_exact is not None) or (
        baseline_exact and b_exact and baseline_exact - b_exact >= 3
    ) or (baseline_rank is None and b_rank is not None) or (
        baseline_rank and b_rank and baseline_rank - b_rank >= 3
    ):
        return "query_intent_gap"
    if baseline_exact is None and b_exact is None and (
        dense.get("exact_gold_chunk_rank") is None or dense.get("exact_gold_chunk_rank", 10**9) > 50
    ):
        return "candidate_missing"
    if (baseline_exact is not None and baseline_exact > 5) or baseline_rank is None or baseline_rank > 5:
        return "ranking_issue"
    first_hit = baseline.get("first_hit")
    if first_hit and not first_hit.get("page_hit") and baseline.get("page_grounded_rank") is None:
        return "evaluation_page_mismatch"
    return "ranking_issue"


def recommend_fix(root_cause: str) -> str:
    return {
        "candidate_missing": "query_intent_terms",
        "vector_missing": "chunk_representation_repair",
        "chunk_boundary_issue": "chunk_representation_repair",
        "section_label_issue": "section_label_repair",
        "query_intent_gap": "query_intent_terms",
        "ranking_issue": "rerank_feature",
        "gold_ambiguous": "no_code_gold_review",
        "evaluation_page_mismatch": "no_code_gold_review",
    }.get(root_cause, "no_code_gold_review")


def diagnose_case(case: dict, retrievers: dict, vector_index: dict) -> dict:
    gf = gold_fields(case)
    document_id = gf["document_ids"][0] if gf["document_ids"] else ""
    artifacts = load_artifacts(document_id)
    chunks = artifacts["chunks"]
    evidences = artifacts["evidences"]
    subtype = infer_ipo_subtype(case)

    best_evidence_any = best_item_match(evidences, gf, "evidence")
    best_chunk_any = best_item_match(chunks, gf, "chunk")
    best_evidence = best_item_match(expected_page_items(evidences, gf, "evidence"), gf, "evidence")
    best_chunk = best_item_match(expected_page_items(chunks, gf, "chunk"), gf, "chunk")
    evidence_agg = aggregate_expected_page_match(evidences, gf, "evidence")
    chunk_agg = aggregate_expected_page_match(chunks, gf, "chunk")
    evidence_present = bool(best_evidence["content_hit"] or evidence_agg["content_hit"])
    chunk_present = bool(best_chunk["content_hit"] or chunk_agg["content_hit"])
    gold_chunk_id = best_chunk.get("id") if best_chunk.get("score", 0.0) > 0 else ""

    vector_doc = vector_index["by_chunk"].get(gold_chunk_id) if gold_chunk_id else None
    vector_present = bool(chunk_present and vector_doc)
    vector_text = ""
    if vector_doc:
        meta = vector_doc.get("metadata", {}) or {}
        vector_text = " ".join([
            meta.get("text_preview", "") or "",
            meta.get("text_for_embedding", "") or "",
        ])
    vector_match = item_match({}, gf, vector_text, vector_doc.get("pages", []) if vector_doc else [])
    vector_text_hit = bool(vector_match["content_hit"])

    experiments = {
        name: search_experiment(retriever, case, gf, gold_chunk_id, top_k=50)
        for name, retriever in retrievers.items()
    }
    dense = raw_dense_diagnosis(retrievers["baseline"], case, gf, gold_chunk_id, top_k=50)
    baseline = experiments["baseline"]
    b_intent = experiments["B_intent"]
    d_section = experiments["D_section_prior"]

    first_hit = baseline.get("first_hit") or b_intent.get("first_hit") or d_section.get("first_hit") or {}
    first_hit_section = first_hit.get("section_path", []) or []
    gold_section = best_chunk.get("section_path", []) or []
    gold_text = next((text_for_chunk(chunk) for chunk in chunks if chunk.get("chunk_id") == gold_chunk_id), "")
    section_match = section_label_match(subtype, gold_section, gold_text)
    root = classify_root_cause(
        evidence_present,
        chunk_present,
        vector_present,
        dense,
        baseline,
        b_intent,
        section_match,
    )

    return {
        "case_id": case.get("id"),
        "dataset": case.get("_dataset"),
        "ipo_subtype": subtype,
        "document_id": document_id,
        "question": case.get("question"),
        "expected_pages": gf["phys_pages"],
        "expected_sections": case.get("expected_sections") or [],
        "gold_preview": " ".join((gf["gold_text"] or "").split())[:320],
        "gold_keywords": gf["keywords"],
        "gold_evidence_in_evidence_store": evidence_present,
        "gold_chunk_exists": chunk_present,
        "gold_vector_document_exists": vector_present,
        "vector_text_content_hit": vector_text_hit,
        "dense_raw_rank": dense.get("rank"),
        "baseline_rank": baseline.get("rank"),
        "b_intent_rank": b_intent.get("rank"),
        "d_section_prior_rank": d_section.get("rank"),
        "topk_content_hit": {
            name: {
                "top10": data["top10"],
                "top20": data["top20"],
                "top50": data["top50"],
                "rank": data["rank"],
                "exact_gold_chunk_rank": data["exact_gold_chunk_rank"],
                "page_grounded_rank": data["page_grounded_rank"],
            }
            for name, data in experiments.items()
        },
        "dense_candidate_hit": {
            "top10": dense["top10"],
            "top20": dense["top20"],
            "top50": dense["top50"],
            "rank": dense["rank"],
            "exact_gold_chunk_rank": dense["exact_gold_chunk_rank"],
            "candidate_count": dense["candidate_count"],
        },
        "hit_chunk_section_path": first_hit_section,
        "gold_chunk_id": gold_chunk_id,
        "gold_chunk_section_path": gold_section,
        "gold_chunk_pages": best_chunk.get("pages", []),
        "gold_chunk_block_type": best_chunk.get("block_type", ""),
        "section_label_match": section_match,
        "query_intent": infer_query_intent(case.get("question") or ""),
        "intent_aux_queries": build_intent_queries(case.get("question") or "", 2),
        "best_evidence_match": best_evidence,
        "best_chunk_match": best_chunk,
        "best_evidence_match_any_page": best_evidence_any,
        "best_chunk_match_any_page": best_chunk_any,
        "expected_page_evidence_aggregate": evidence_agg,
        "expected_page_chunk_aggregate": chunk_agg,
        "chunk_boundary_diagnosis": diagnose_boundary(evidence_present, chunk_present, evidence_agg, chunk_agg),
        "representation_diagnosis": diagnose_representation(evidence_present, chunk_present, vector_present, vector_text_hit),
        "final_root_cause": root,
        "recommended_fix_type": recommend_fix(root),
    }


def summarize(cases: List[dict]) -> dict:
    by_root = Counter(case["final_root_cause"] for case in cases)
    by_subtype: Dict[str, Counter] = defaultdict(Counter)
    by_fix = Counter(case["recommended_fix_type"] for case in cases)
    for case in cases:
        by_subtype[case["ipo_subtype"]][case["final_root_cause"]] += 1
    query_intent_worth = any(case["final_root_cause"] in {"query_intent_gap", "candidate_missing"} for case in cases)
    representation_needed = any(case["final_root_cause"] in {"chunk_boundary_issue", "section_label_issue", "vector_missing"} for case in cases)
    if by_root:
        top_root, _ = by_root.most_common(1)[0]
    else:
        top_root = "unknown"
    next_step = {
        "section_label_issue": "section_label_repair",
        "chunk_boundary_issue": "chunk_representation_repair",
        "vector_missing": "chunk_representation_repair",
        "candidate_missing": "query_intent_terms",
        "query_intent_gap": "query_intent_terms",
        "ranking_issue": "rerank_feature",
        "evaluation_page_mismatch": "no_code_gold_review",
    }.get(top_root, "no_code_gold_review")
    return {
        "n_cases": len(cases),
        "root_cause_counts": dict(by_root),
        "recommended_fix_counts": dict(by_fix),
        "by_ipo_subtype_root_cause": {key: dict(value) for key, value in by_subtype.items()},
        "worth_continuing_query_intent": query_intent_worth,
        "needs_chunk_or_section_expression_repair": representation_needed,
        "hybrid_bm25_reranker_still_blocked": True,
        "single_next_step": next_step,
    }


def render_report(results: dict) -> str:
    summary = results["summary"]
    lines = [
        "# IPO Section/Chunk Diagnosis V1",
        "",
        "Scope: 8 IPO-specific Gold-vs-RAG cases. This is diagnosis only: no Retriever ranking logic, Gold labels, vector index, Hybrid/BM25, cross-encoder, or LLM reranker was changed.",
        "",
        "## Summary",
        "",
        f"- Total cases: {summary['n_cases']}",
        f"- Root cause counts: `{summary['root_cause_counts']}`",
        f"- Recommended fix counts: `{summary['recommended_fix_counts']}`",
        f"- Worth continuing query_intent: {'yes' if summary['worth_continuing_query_intent'] else 'no'}",
        f"- Needs chunk/section expression repair: {'yes' if summary['needs_chunk_or_section_expression_repair'] else 'no'}",
        f"- Hybrid/BM25/reranker still blocked: {'yes' if summary['hybrid_bm25_reranker_still_blocked'] else 'no'}",
        f"- Single next step: `{summary['single_next_step']}`",
        "",
        "## Subtype Breakdown",
        "",
        "| IPO subtype | Root causes |",
        "|---|---|",
    ]
    for subtype, counts in summary["by_ipo_subtype_root_cause"].items():
        lines.append(f"| {subtype} | `{counts}` |")
    lines += [
        "",
        "## Case Diagnosis",
        "",
        "| Case | Subtype | Baseline | B_intent | D_prior | Dense raw | Artifact chain | Gold section | Root cause | Recommended fix |",
        "|---|---|---:|---:|---:|---:|---|---|---|---|",
    ]
    for case in results["cases"]:
        artifact = (
            f"E:{'Y' if case['gold_evidence_in_evidence_store'] else 'N'} "
            f"C:{'Y' if case['gold_chunk_exists'] else 'N'} "
            f"V:{'Y' if case['gold_vector_document_exists'] else 'N'}"
        )
        section = " / ".join(case["gold_chunk_section_path"])[:60]
        lines.append(
            f"| `{case['case_id']}` | {case['ipo_subtype']} | {case['baseline_rank']} | "
            f"{case['b_intent_rank']} | {case['d_section_prior_rank']} | {case['dense_raw_rank']} | "
            f"{artifact} | {section} | {case['final_root_cause']} | {case['recommended_fix_type']} |"
        )
    lines += [
        "",
        "## Detailed Findings",
        "",
    ]
    for case in results["cases"]:
        lines += [
            f"### {case['case_id']}",
            "",
            f"- Question: {case['question']}",
            f"- Document: `{case['document_id']}`",
            f"- Expected pages: `{case['expected_pages']}`",
            f"- Gold keywords: `{case['gold_keywords']}`",
            f"- Content hit Top10/20/50: `{case['topk_content_hit']}`",
            f"- Dense candidate hit: `{case['dense_candidate_hit']}`",
            f"- Gold chunk: `{case['gold_chunk_id']}` pages `{case['gold_chunk_pages']}`, section `{case['gold_chunk_section_path']}`",
            f"- Hit chunk section: `{case['hit_chunk_section_path']}`",
            f"- Section label match: `{case['section_label_match']}`",
            f"- Query intent: `{case['query_intent']}`",
            f"- Aux queries: `{case['intent_aux_queries']}`",
            f"- Chunk boundary diagnosis: {case['chunk_boundary_diagnosis']}",
            f"- Representation diagnosis: {case['representation_diagnosis']}",
            f"- Final root cause: `{case['final_root_cause']}`",
            f"- Recommended fix type: `{case['recommended_fix_type']}`",
            "",
        ]
    lines += [
        "## Decision",
        "",
        "- Do not enable new ranking flags from this diagnosis.",
        "- Do not move to Hybrid/BM25/cross-encoder/reranker from the current evidence.",
        "- The next implementation should follow the single next step above and stay benchmarked against the same 39-case / IPO subset.",
    ]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--benchmark-paths",
        default="evaluation/benchmark/manual_gold_v1.json,evaluation/benchmark/manual_new_annotators_v1.json",
    )
    parser.add_argument("--json-path", default="evaluation/benchmark/ipo_section_chunk_diagnosis_v1.json")
    parser.add_argument("--report-path", default="docs/rag/IPO_SECTION_CHUNK_DIAGNOSIS_V1.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = [ROOT / part.strip() for part in args.benchmark_paths.split(",") if part.strip()]
    cases = load_cases(paths)
    if len(cases) != len(TARGET_CASE_IDS):
        found = {case.get("id") for case in cases}
        missing = [case_id for case_id in TARGET_CASE_IDS if case_id not in found]
        raise RuntimeError(f"Expected {len(TARGET_CASE_IDS)} IPO cases, found {len(cases)}; missing={missing}")

    retrievers = {
        name: build_runtime(RetrieverConfig(top_k=50, **flags))
        for name, flags in EXPERIMENTS.items()
    }
    vector_index = build_vector_index()
    diagnosed = [diagnose_case(case, retrievers, vector_index) for case in cases]
    results = {
        "condition": {
            "scope": "IPO-specific section/chunk diagnosis only",
            "benchmark_paths": [str(path.relative_to(ROOT)) for path in paths],
            "target_case_ids": TARGET_CASE_IDS,
            "ranking_logic_changed": False,
            "gold_dataset_changed": False,
            "hybrid_bm25_reranker_used": False,
            "ranking_flags_default_enabled": False,
            "vector_document_count": vector_index["total"],
        },
        "summary": summarize(diagnosed),
        "cases": diagnosed,
    }

    json_path = ROOT / args.json_path
    report_path = ROOT / args.report_path
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_report(results), encoding="utf-8")
    print(f"saved {json_path}")
    print(f"saved {report_path}")
    print(f"root_cause_counts={results['summary']['root_cause_counts']}")


if __name__ == "__main__":
    main()
