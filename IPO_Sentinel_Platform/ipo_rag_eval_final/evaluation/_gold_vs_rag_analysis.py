# -*- coding: utf-8 -*-
"""Read-only Gold vs RAG Top-K systematic error analysis."""
from __future__ import annotations

import json
import math
import re
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(r"E:\WorkSpace\IPO-Risk-Agent")
OUT_DIR = ROOT / "docs" / "rag"
BENCH = ROOT / "evaluation" / "benchmark"
API = "http://127.0.0.1:8000/v1/search"

TRAD = str.maketrans({
    "為": "为", "與": "与", "對": "对", "業": "业", "國": "国", "們": "们",
    "於": "于", "後": "后", "來": "来", "這": "这", "還": "还", "從": "从",
    "開": "开", "關": "关", "無": "无", "產": "产", "億": "亿", "萬": "万",
    "餘": "余", "並": "并", "計": "计", "報": "报", "發": "发", "總": "总",
    "佔": "占", "經": "经", "營": "营", "現": "现", "輝": "辉", "創": "创",
    "東": "东", "車": "车", "電": "电", "風": "风", "險": "险", "繳": "缴",
    "納": "纳", "記": "记", "錄": "录", "險": "险", "際": "际", "係": "系",
    "則": "则", "據": "据", "應": "应", "該": "该", "會": "会", "員": "员",
    "責": "责", "險": "险", "際": "际",
})


def norm(s: str) -> str:
    s = (s or "").translate(TRAD).lower()
    s = re.sub(r"\s+", "", s)
    return s


def tokens_from_gold(text: str) -> list[str]:
    if not text:
        return []
    toks = re.findall(r"\d+(?:\.\d+)?%?|[\u4e00-\u9fff]{2,10}", text)
    # keep informative tokens
    out = []
    seen = set()
    for t in toks:
        nt = norm(t)
        if len(nt) < 2 or nt in seen:
            continue
        if nt in {"我们", "本公司", "以及", "或者", "因为", "因此", "可能", "如果", "以及"}:
            continue
        seen.add(nt)
        out.append(t)
        if len(out) >= 24:
            break
    return out


def coverage(text: str, gold_tokens: list[str]) -> float:
    if not gold_tokens:
        return 0.0
    nt = norm(text)
    hit = sum(1 for t in gold_tokens if norm(t) in nt)
    return hit / len(gold_tokens)


def pages_overlap(result_pages: list[int], expected: list[list[int]] | None) -> bool:
    if not result_pages or not expected:
        return False
    for p in result_pages:
        for a, b in expected:
            lo, hi = (a, b) if a <= b else (b, a)
            if lo <= int(p) <= hi:
                return True
    return False


def classify_evidence(text: str) -> str:
    t = text or ""
    n = norm(t)
    has_num = bool(re.search(r"\d", t))
    if any(k in n for k in ["未足额", "未完成登记", "录得", "截至", "往绩记录期", "已发生", "接获", "申索", "诉讼"]):
        if any(k in n for k in ["可能", "或会", "风险", "不确定"]):
            if has_num or any(k in n for k in ["未足额", "未完成", "接获", "申索"]):
                return "historical_or_actual_event"
        else:
            return "historical_or_actual_event"
    if any(k in n for k in ["未来", "可能因", "或会", "倘", "如果", "存在风险", "无法保证"]):
        if has_num:
            return "future_risk_with_fact"
        return "generic_future_risk"
    if any(k in n for k in ["已采取", "缓解", "内部控制", "措施", "改善", "转正"]):
        return "mitigation_or_improvement"
    if has_num and any(k in n for k in ["占比", "利润率", "毛利率", "现金流", "人民币", "港元", "%"]):
        return "financial_impact"
    if any(k in n for k in ["处罚", "罚款", "滞纳金", "吊销", "许可证", "牌照"]):
        return "legal_consequence"
    if any(k in n for k in ["风险因素", "可能", "或会"]):
        return "generic_risk_disclosure"
    return "other"


def query_intent(question: str) -> dict[str, Any]:
    q = question or ""
    n = norm(q)
    temporal = []
    if any(k in n for k in ["已发生", "往绩", "历史", "是否存在", "未足额", "未完成"]):
        temporal.append("historical_or_actual")
    if any(k in n for k in ["未来", "可能", "会否", "是否会", "是否可能"]):
        temporal.append("future")
    if any(k in n for k in ["当前", "现在", "目前", "最新"]):
        temporal.append("current")
    if not temporal:
        temporal = ["unspecified"]
    needs_quant = any(k in n for k in ["占比", "金额", "比例", "多少", "百分比", "具体"])
    needs_event = any(k in n for k in ["是否存在", "是否", "有无", "是否已", "是否发生"])
    needs_legal = any(k in n for k in ["处罚", "追缴", "诉讼", "合规", "牌照", "许可"])
    return {
        "temporal": temporal,
        "needs_quant": needs_quant,
        "needs_event": needs_event,
        "needs_legal": needs_legal,
    }


def search(query: str, document_id: str | None, company: str | None = None, top_k: int = 10) -> dict:
    body = {
        "query": query,
        "top_k": top_k,
        "enable_followup": False,
        "enable_claim_analysis": False,
    }
    if document_id:
        body["document_id"] = document_id
    if company:
        body["company"] = company
    req = urllib.request.Request(
        API,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_cases() -> list[dict]:
    cases = []
    # Manual Gold V1
    p1 = BENCH / "manual_gold_v1.json"
    if p1.exists():
        for c in json.loads(p1.read_text(encoding="utf-8")):
            c = dict(c)
            c["_dataset"] = "manual_gold_v1"
            cases.append(c)
    # New annotators
    p2 = BENCH / "manual_new_annotators_v1.json"
    if p2.exists():
        for c in json.loads(p2.read_text(encoding="utf-8")):
            c = dict(c)
            c["_dataset"] = "manual_new_annotators_v1"
            cases.append(c)
    return cases


def gold_fields(case: dict) -> dict:
    gold_text = case.get("expected_evidence_text") or case.get("gold_text") or ""
    keywords = case.get("expected_keywords") or case.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [x for x in re.split(r"[、,，;/；\s]+", keywords) if x]
    phys = case.get("expected_physical_page_ranges_0_based") or case.get("expected_page_ranges") or []
    docs = case.get("expected_document_ids") or []
    sections = case.get("expected_sections") or []
    return {
        "gold_text": gold_text,
        "keywords": keywords,
        "phys_pages": phys,
        "document_ids": docs,
        "sections": sections,
        "tokens": tokens_from_gold(gold_text),
    }


def score_result_against_gold(item: dict, gf: dict) -> dict:
    text = item.get("text") or ""
    pages = []
    for p in item.get("pages") or []:
        try:
            pages.append(int(p))
        except Exception:
            pass
    cov = coverage(text, gf["tokens"]) if gf["tokens"] else 0.0
    # keyword coverage
    nt = norm(text)
    kw = gf["keywords"]
    kw_hit = [k for k in kw if norm(k) and norm(k) in nt]
    kw_cov = (len(kw_hit) / len(kw)) if kw else 0.0
    page_hit = pages_overlap(pages, gf["phys_pages"])
    # gold hit definition: strong content support
    content_hit = cov >= 0.35 or (kw_cov >= 0.5 and len(kw_hit) >= 2) or (cov >= 0.25 and page_hit)
    # stronger exactish
    exactish = cov >= 0.55
    return {
        "content_hit": content_hit,
        "exactish": exactish,
        "coverage": round(cov, 4),
        "keyword_coverage": round(kw_cov, 4),
        "keyword_hit": kw_hit,
        "page_hit": page_hit,
        "pages": pages,
        "doc": item.get("document_id"),
        "score": item.get("score"),
        "section_path": item.get("section_path") or [],
        "preview": re.sub(r"\s+", " ", text)[:220],
        "evidence_type": classify_evidence(text),
    }


def failure_reason(case: dict, gf: dict, ranked: list[dict], gold_rank: int | None) -> str:
    q = case.get("question") or ""
    intent = query_intent(q)
    if not ranked:
        return "no_results"
    if gold_rank is None:
        # inspect top wrong
        top = ranked[0]
        top_type = top["evidence_type"]
        if top_type in {"generic_future_risk", "generic_risk_disclosure"} and intent["needs_event"]:
            return "generic_risk_outranks_actual_event"
        if intent["needs_quant"] and top["coverage"] < 0.2 and not re.search(r"\d", top["preview"] or ""):
            return "quant_fact_not_ranked"
        if top["doc"] not in (gf["document_ids"] or [top["doc"]]):
            return "wrong_document"
        if top["page_hit"] is False and top["coverage"] < 0.2:
            return "semantic_near_miss_or_chunk_boundary"
        return "gold_not_in_topk_content"
    if gold_rank > 1:
        top = ranked[0]
        if top["evidence_type"] in {"generic_future_risk", "generic_risk_disclosure"}:
            return "gold_recalled_but_generic_ranked_higher"
        if intent["needs_quant"] and classify_evidence(gf["gold_text"]) in {"financial_impact", "historical_or_actual_event"}:
            return "gold_recalled_but_quant_not_top1"
        return "gold_recalled_but_rank_low"
    # rank1 but maybe page miss only
    if ranked[0]["content_hit"] and not ranked[0]["page_hit"]:
        return "content_hit_page_mismatch"
    return "ok"


def analyze() -> dict:
    cases = load_cases()
    print("loaded cases", len(cases))
    rows = []
    for idx, case in enumerate(cases, 1):
        gf = gold_fields(case)
        did = (gf["document_ids"][0] if gf["document_ids"] else None)
        company = None
        cos = case.get("expected_companies") or []
        if cos:
            # prefer short traditional-like if available later; keep None to avoid filter issues
            company = None
        try:
            data = search(case.get("question") or "", document_id=did, company=company, top_k=10)
            results = data.get("results") or []
            routing = data.get("routing")
            warn = data.get("warnings")
        except Exception as e:
            results, routing, warn = [], None, [str(e)]
        ranked = [score_result_against_gold(item, gf) for item in results]
        gold_rank = None
        for i, r in enumerate(ranked, 1):
            if r["content_hit"]:
                gold_rank = i
                break
        doc_hit = any((r["doc"] in gf["document_ids"]) for r in ranked) if gf["document_ids"] else bool(ranked)
        page_hit_any = any(r["page_hit"] for r in ranked)
        reason = failure_reason(case, gf, ranked, gold_rank)
        intent = query_intent(case.get("question") or "")
        gold_type = classify_evidence(gf["gold_text"])
        row = {
            "id": case.get("id"),
            "dataset": case.get("_dataset"),
            "annotator": case.get("annotator"),
            "category": case.get("category"),
            "question": case.get("question"),
            "document_id": did,
            "intent": intent,
            "gold_type": gold_type,
            "gold_preview": re.sub(r"\s+", " ", gf["gold_text"])[:240],
            "gold_keywords": gf["keywords"],
            "expected_phys_pages": gf["phys_pages"],
            "n_results": len(ranked),
            "doc_hit": doc_hit,
            "gold_rank": gold_rank,
            "recall_at_1": gold_rank == 1,
            "recall_at_3": gold_rank is not None and gold_rank <= 3,
            "recall_at_5": gold_rank is not None and gold_rank <= 5,
            "recall_at_10": gold_rank is not None and gold_rank <= 10,
            "page_hit_any": page_hit_any,
            "top1": ranked[0] if ranked else None,
            "top3_types": [r["evidence_type"] for r in ranked[:3]],
            "failure_reason": reason,
            "routing": routing,
            "warnings": warn,
            "ranked_brief": [
                {
                    "rank": i,
                    "coverage": r["coverage"],
                    "page_hit": r["page_hit"],
                    "type": r["evidence_type"],
                    "pages": r["pages"],
                    "preview": r["preview"],
                }
                for i, r in enumerate(ranked[:5], 1)
            ],
        }
        rows.append(row)
        print(
            f"[{idx}/{len(cases)}] {row['id']} rank={gold_rank} reason={reason} "
            f"r@1={row['recall_at_1']} r@5={row['recall_at_5']}"
        )

    n = len(rows) or 1
    def rate(key):
        return round(sum(1 for r in rows if r[key]) / n, 4)

    ranks = [r["gold_rank"] for r in rows if r["gold_rank"] is not None]
    mrr = round(sum(1.0 / r["gold_rank"] for r in rows if r["gold_rank"]) / n, 4)
    summary = {
        "n_cases": len(rows),
        "datasets": dict(Counter(r["dataset"] for r in rows)),
        "recall_at_1": rate("recall_at_1"),
        "recall_at_3": rate("recall_at_3"),
        "recall_at_5": rate("recall_at_5"),
        "recall_at_10": rate("recall_at_10"),
        "doc_hit_rate": rate("doc_hit"),
        "page_hit_any_rate": rate("page_hit_any"),
        "mrr": mrr,
        "avg_gold_rank_when_recalled": round(sum(ranks) / len(ranks), 3) if ranks else None,
        "failure_reason_counts": dict(Counter(r["failure_reason"] for r in rows)),
        "gold_type_counts": dict(Counter(r["gold_type"] for r in rows)),
        "by_dataset": {},
        "by_category": {},
    }
    for field, bucket in [("dataset", "by_dataset"), ("category", "by_category")]:
        groups = defaultdict(list)
        for r in rows:
            groups[str(r.get(field) or "unknown")].append(r)
        for g, items in groups.items():
            m = len(items) or 1
            summary[bucket][g] = {
                "n": len(items),
                "recall_at_1": round(sum(1 for x in items if x["recall_at_1"]) / m, 4),
                "recall_at_5": round(sum(1 for x in items if x["recall_at_5"]) / m, 4),
                "recall_at_10": round(sum(1 for x in items if x["recall_at_10"]) / m, 4),
                "mrr": round(sum((1.0 / x["gold_rank"]) if x["gold_rank"] else 0.0 for x in items) / m, 4),
                "top_failures": dict(Counter(x["failure_reason"] for x in items).most_common(5)),
            }

    # pick representative hard cases
    hard = [r for r in rows if r["failure_reason"] not in {"ok", "content_hit_page_mismatch"}]
    hard_sorted = sorted(hard, key=lambda x: (x["gold_rank"] is not None, x["gold_rank"] or 99))

    out = {
        "summary": summary,
        "rows": rows,
        "hard_cases": hard_sorted[:20],
        "architecture_snapshot": {
            "dense": "BAAI/bge-small-zh-v1.5 via EmbeddingEngine",
            "sparse_bm25": False,
            "hybrid": False,
            "cross_encoder_reranker": False,
            "llm_reranker": False,
            "company_routing": True,
            "term_normalization_aliases": True,
            "section_aware_boost": True,
            "table_fact_boost_requires_query_numbers": True,
            "quantitative_intent_boost": True,
            "evidence_sufficiency_layer_in_retriever": False,
            "temporal_status_field": False,
            "parent_child_retrieval": False,
        },
    }
    BENCH.mkdir(parents=True, exist_ok=True)
    path = BENCH / "gold_vs_rag_topk_error_analysis.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return out


if __name__ == "__main__":
    analyze()
