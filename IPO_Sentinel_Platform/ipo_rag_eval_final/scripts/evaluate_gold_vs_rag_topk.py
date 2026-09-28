"""Evaluate Gold-vs-RAG Top-K ranking for baseline and P0 experiments."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.embedding import EmbeddingConfig, EmbeddingEngine  # noqa: E402
from src.retriever import LayeredRetriever, RetrieverConfig  # noqa: E402
from src.vector import VectorStore  # noqa: E402


EXPERIMENTS = {
    "baseline": {"enable_sufficiency_rerank": False, "enable_intent_multiquery": False},
    "A_sufficiency": {"enable_sufficiency_rerank": True, "enable_intent_multiquery": False},
    "B_intent": {"enable_sufficiency_rerank": False, "enable_intent_multiquery": True},
    "C_combined": {"enable_sufficiency_rerank": True, "enable_intent_multiquery": True},
    "D_section_prior": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": True,
        "enable_section_hard_prior": True,
    },
    "E_ipo_local_rerank": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": True,
        "enable_ipo_specific_rerank": True,
    },
    "G_use_of_proceeds_representation_repair": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": False,
        "enable_ipo_specific_rerank": False,
    },
    "G_plus_E": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": True,
        "enable_ipo_specific_rerank": True,
    },
    "H_answer_excerpt_rerank": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": False,
        "enable_ipo_specific_rerank": False,
        "enable_answer_excerpt_rerank": True,
    },
    "H_plus_G_plus_E": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": True,
        "enable_ipo_specific_rerank": True,
        "enable_answer_excerpt_rerank": True,
        "enable_evidence_role_rerank": False,
    },
    "I_intent_credit_competition": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": True,
        "enable_ipo_specific_rerank": False,
        "enable_answer_excerpt_rerank": False,
    },
    "I_plus_H_plus_G_plus_E": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": True,
        "enable_ipo_specific_rerank": True,
        "enable_answer_excerpt_rerank": True,
        "enable_evidence_role_rerank": False,
    },
    "J_evidence_role_only": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": False,
        "enable_ipo_specific_rerank": False,
        "enable_answer_excerpt_rerank": False,
        "enable_evidence_role_rerank": True,
    },
    "H_plus_G_plus_E_plus_Role": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": True,
        "enable_ipo_specific_rerank": True,
        "enable_answer_excerpt_rerank": True,
        "enable_evidence_role_rerank": True,
    },
    "HGE_related_party_quant": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": True,
        "enable_ipo_specific_rerank": True,
        "enable_answer_excerpt_rerank": True,
        "enable_evidence_role_rerank": True,
        "enable_related_party_quant_complement": True,
    },
    # Alias of current HGE(+Role+RPQ) profile; WC mechanism rules ride on intent/excerpt/role.
    "HGE_working_capital_mechanism": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": True,
        "enable_ipo_specific_rerank": True,
        "enable_answer_excerpt_rerank": True,
        "enable_evidence_role_rerank": True,
        "enable_related_party_quant_complement": True,
    },
    "HGE_preipo_terms_sufficiency": {
        "enable_sufficiency_rerank": False,
        "enable_intent_multiquery": True,
        "enable_ipo_specific_rerank": True,
        "enable_answer_excerpt_rerank": True,
        "enable_evidence_role_rerank": True,
        "enable_related_party_quant_complement": True,
    },
}
HARD_CASE_IDS = {
    "manual_new_董飞飞_cat_comp_004",
    "mgv1_duodian_comp_litigation_001",
    "manual_new_田歌_cat_fin_010",
    "manual_new_董飞飞_seed_bus_005",
    "manual_new_董飞飞_cat_bus_009",
    "mgv1_maogeping_comp_no_litigation_001",
    "mgv1_yunzhisheng_comp_no_litigation_001",
    "mgv1_duodian_owner_connected_tx_001",
}
TRAD = str.maketrans({
    "競": "竞", "爭": "争", "劇": "剧", "趨": "趋", "勢": "势", "壘": "垒", "遲": "迟", "難": "难", "潤": "润", "場": "场", "現": "现", "戶": "户", "觀": "观", "濟": "济", "貸": "贷", "償": "偿", "運": "运", "壘": "垒",
    "識": "识", "訊": "讯", "議": "议", "記": "记", "許": "许", "訴": "诉", "訟": "讼", "敗": "败", "獲": "获", "導": "导", "執": "执", "處": "处", 
    "項": "项", "發": "发", "業": "业", "萬": "万", "淨": "净", "額": "额", "開": "开", "銷": "销", "經": "经", "營": "营", "現": "现", "金": "金", "與": "与", "為": "为", "於": "于", "對": "对", "從": "从", "後": "后", "這": "这", "該": "该", "們": "们", "個": "个", "無": "无", "務": "务", "財": "财", "資": "资", "產": "产", "報": "报", "據": "据", "風": "风", "險": "险", "點": "点", "數": "数", "雲": "云", "聲": "声", "電": "电", "軟": "软", "車": "车", "國": "国", "歷": "历", "組": "组", "東": "东", "層": "层", "劃": "划", "計": "计", "錄": "录", "幣": "币", "億": "亿", "預": "预", "權": "权", "變": "变", "動": "动", "減": "减", "餘": "余", "負": "负", "債": "债", "許": "许", "證": "证", "監": "监", "規": "规", "採": "采", "購": "购", "總": "总", "佔": "占", "會": "会", "師": "师", "標": "标", "準": "准", "應": "应", "賬": "账", "虧": "亏", "損": "损", "約": "约", "實": "实", "際": "际", "間": "间", "關": "关", "聯": "联", "價": "价", "訴": "诉", "訟": "讼", "質": "质", "戶": "户", "舊": "旧",
    "為": "为", "與": "与", "對": "对", "業": "业", "國": "国", "們": "们",
    "於": "于", "後": "后", "來": "来", "這": "这", "還": "还", "從": "从",
    "開": "开", "關": "关", "無": "无", "產": "产", "億": "亿", "萬": "万",
    "餘": "余", "並": "并", "計": "计", "報": "报", "發": "发", "總": "总",
    "佔": "占", "經": "经", "營": "营", "現": "现", "輝": "辉", "創": "创",
    "東": "东", "車": "车", "電": "电", "風": "风", "險": "险", "繳": "缴",
    "納": "纳", "記": "记", "錄": "录", "際": "际", "係": "系", "則": "则",
    "據": "据", "應": "应", "該": "该", "會": "会", "員": "员", "責": "责",
})


def norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").translate(TRAD).lower())


def tokens_from_gold(text: str) -> List[str]:
    toks = re.findall(r"\d+(?:\.\d+)?%?|[\u4e00-\u9fff]{2,10}", text or "")
    out: List[str] = []
    seen = set()
    stop = {norm(x) for x in ["我们", "本公司", "以及", "或者", "因为", "因此", "可能", "如果"]}
    for token in toks:
        key = norm(token)
        if len(key) < 2 or key in seen or key in stop:
            continue
        seen.add(key)
        out.append(token)
        if len(out) >= 24:
            break
    return out


def coverage(text: str, gold_tokens: List[str]) -> float:
    if not gold_tokens:
        return 0.0
    haystack = norm(text)
    return sum(1 for token in gold_tokens if norm(token) in haystack) / len(gold_tokens)


def pages_overlap(result_pages: List[int], expected: List[List[int]]) -> bool:
    for page in result_pages or []:
        for pair in expected or []:
            if len(pair) != 2:
                continue
            lo, hi = sorted([int(pair[0]), int(pair[1])])
            if lo <= int(page) <= hi:
                return True
    return False


def classify_evidence(text: str) -> str:
    n = norm(text)
    has_num = bool(re.search(r"\d", text or ""))
    if any(k in n for k in ["未足额", "未完成登记", "录得", "截至", "往绩记录", "已发生", "接获", "申索", "诉讼", "冻结"]):
        return "historical_or_actual_event"
    if any(k in n for k in ["未来", "可能因", "或会", "倘", "如果", "存在风险", "无法保证"]):
        return "future_risk_with_fact" if has_num else "generic_future_risk"
    if any(k in n for k in ["已采取", "缓解", "内部控制", "措施", "改善", "转正"]):
        return "mitigation_or_improvement"
    if has_num and any(k in n for k in ["占比", "利润率", "毛利率", "现金流", "人民币", "港元", "%"]):
        return "financial_impact"
    if any(k in n for k in ["处罚", "罚款", "滞纳金", "吊销", "许可证", "牌照"]):
        return "legal_consequence"
    if any(k in n for k in ["风险因素", "可能", "或会"]):
        return "generic_risk_disclosure"
    return "other"


def query_intent(question: str) -> Dict[str, Any]:
    q = norm(question)
    return {
        "needs_quant": any(k in q for k in ["占比", "金额", "比例", "多少", "百分比", "具体"]),
        "needs_event": any(k in q for k in ["是否存在", "是否", "有无", "是否已", "是否发生"]),
        "needs_legal": any(k in q for k in ["处罚", "追缴", "诉讼", "合规", "牌照", "许可"]),
    }


def gold_fields(case: dict) -> dict:
    keywords = case.get("expected_keywords") or case.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [x for x in re.split(r"[、,，;/；\s]+", keywords) if x]
    gold_text = case.get("expected_evidence_text") or case.get("gold_text") or ""
    spans = case.get("expected_evidence_spans") or []
    quant_markers = case.get("expected_quant_markers") or []
    if not quant_markers:
        # derive percent markers from quant span or full gold text
        span_quant = " ".join(
            str(s.get("text") or "")
            for s in spans
            if str(s.get("role") or s.get("span_id") or "").startswith("span_quant")
            or "quant" in str(s.get("role") or "").lower()
        )
        source = span_quant or gold_text
        quant_markers = re.findall(r"\d+(?:\.\d+)?%", source or "")
    return {
        "gold_text": gold_text,
        "keywords": keywords,
        "phys_pages": case.get("expected_physical_page_ranges_0_based") or case.get("expected_page_ranges") or [],
        "document_ids": case.get("expected_document_ids") or [],
        "tokens": tokens_from_gold(gold_text),
        "spans": spans,
        "quant_markers": quant_markers,
    }



def _result_text_blob(result: Any) -> str:
    text = getattr(result, "text", "") or ""
    meta = getattr(result, "metadata", {}) or {}
    extra = " ".join(
        str(meta.get(k) or "")
        for k in ("text_preview", "text_for_embedding", "table_description")
    )
    return f"{text}\n{extra}"


def quant_markers_hit(text: str, markers: List[str]) -> List[str]:
    hay = norm(text)
    hits = []
    for marker in markers or []:
        m = norm(marker)
        if m and m in hay:
            hits.append(marker)
    return hits


def span_supported(text: str, span: dict) -> bool:
    span_text = str(span.get("text") or "").strip()
    if not span_text:
        return False
    toks = tokens_from_gold(span_text)
    if not toks:
        return False
    cov = coverage(text, toks)
    # looser for table rows: percent markers alone can support quant span
    markers = re.findall(r"\d+(?:\.\d+)?%", span_text)
    if markers:
        hit_n = sum(1 for m in markers if norm(m) in norm(text))
        if hit_n >= max(2, int(round(0.4 * len(markers)))):
            return True
    return cov >= 0.28


def score_result_against_gold(result: Any, gf: dict) -> dict:
    text = getattr(result, "text", "") or ""
    pages = [int(p) for p in (getattr(result, "pages", []) or []) if str(p).lstrip("-").isdigit()]
    cov = coverage(text, gf["tokens"]) if gf["tokens"] else 0.0
    haystack = norm(text)

    def keyword_in_text(keyword: str) -> bool:
        key = norm(keyword)
        if not key:
            return False
        if key in haystack:
            return True
        # soft variants for common IPO risk phrasing
        soft = {
            "流失客户": ["流失现有客户", "流失客戶", "流失現有客戶", "客户流失", "客戶流失"],
            "竞争激烈": ["竞争加剧", "日趋激烈", "更趋激烈", "竞争日趋激烈", "競爭激烈", "競爭加劇", "日趨激烈", "更趨激烈"],
            "进入壁垒低": ["进入壁垒", "进入门檻低", "進入壁壘低", "進入壁壘"],
            "延迟付款": ["延迟向我们付款", "延遲付款", "延遲向我們付款", "延迟支付"],
            "财政困难": ["財務困難", "财务困难"],
            "无法履行付款责任": ["无法向我们履行付款责任", "無法履行付款責任", "無法向我們履行付款責任"],
            "营运资金": ["營運資金", "运营资金"],
            "降价": ["降價", "降低价格", "降低價格"],
            "议价能力": ["議價能力"],
        }
        for variant in soft.get(key, soft.get(keyword, [])):
            vk = norm(variant)
            if vk and vk in haystack:
                return True
        # very light stemming: keyword contained in a longer matched token already in text
        if len(key) >= 4:
            # e.g. 流失客户 vs 流失现有客户 already handled; also accept key without 现有
            pass
        return False

    kw_hit = [k for k in gf["keywords"] if keyword_in_text(k)]
    kw_cov = (len(kw_hit) / len(gf["keywords"])) if gf["keywords"] else 0.0
    page_hit = pages_overlap(pages, gf["phys_pages"])
    kw_need = 2 if len(gf["keywords"]) >= 2 else 1
    content_hit = (
        cov >= 0.35
        or (kw_cov >= 0.5 and len(kw_hit) >= kw_need)
        or (cov >= 0.25 and page_hit)
        # near-duplicate concrete disclosure: strong coverage short of 0.35 with keyword support
        or (cov >= 0.22 and kw_cov >= 0.5 and len(kw_hit) >= 1)
    )
    return {
        "content_hit": content_hit,
        "coverage": round(cov, 4),
        "keyword_coverage": round(kw_cov, 4),
        "keyword_hit": kw_hit,
        "page_hit": page_hit,
        "pages": pages,
        "doc": getattr(result, "document_id", ""),
        "score": round(float(getattr(result, "score", 0.0) or 0.0), 6),
        "section_path": getattr(result, "section_path", []) or [],
        "preview": re.sub(r"\s+", " ", text)[:240],
        "evidence_type": classify_evidence(text),
        "chunk_id": getattr(result, "chunk_id", ""),
        "evidence_ids": getattr(result, "evidence_ids", []) or [],
    }



def is_gold_aligned(item: dict) -> bool:
    """Content-oriented Gold alignment (not page-only).

    A hit means the returned excerpt can sufficiently support the same answer as
    the human gold via keyword/core-fact coverage or evidence-text support.
    """
    if not item:
        return False
    if item.get("content_hit"):
        return True
    kw_cov = float(item.get("keyword_coverage") or 0.0)
    cov = float(item.get("coverage") or 0.0)
    kw_hit = item.get("keyword_hit") or []
    preview = norm(item.get("preview") or "")
    # Near-miss safety net: strong keyword support even if coverage threshold barely missed.
    if kw_cov >= 0.6 and cov >= 0.18 and len(kw_hit) >= 1:
        return True
    # Consequence-chain equivalence: enough answer facts even when gold page/chunk is split.
    consequence_groups = [
        ("降价", "降價", "利润减少", "利潤減少", "利润下降", "失去市场地位", "失去市場地位"),
        ("流失客户", "流失客戶", "流失现有客户", "流失現有客戶", "收入减少", "收入減少"),
        ("财政困难", "財務困難", "延迟付款", "延遲付款", "无法履行付款", "無法履行付款", "修改付款"),
        ("营运资金", "營運資金", "流失客户", "流失客戶"),
    ]
    group_hits = 0
    for group in consequence_groups:
        if any(norm(term) in preview for term in group if norm(term)):
            group_hits += 1
    if cov >= 0.22 and group_hits >= 2 and len(kw_hit) >= 1:
        return True
    if kw_cov >= 0.4 and len(kw_hit) >= 2 and group_hits >= 2:
        return True
    return False


def gold_aligned_rank(ranked: List[dict]) -> Optional[int]:
    for idx, item in enumerate(ranked, 1):
        if is_gold_aligned(item):
            return idx
    return None


def failure_reason(case: dict, ranked: List[dict], gold_rank: Optional[int]) -> str:
    intent = query_intent(case.get("question") or "")
    if not ranked:
        return "no_results"
    top = ranked[0]
    if gold_rank is None:
        if top["evidence_type"] in {"generic_future_risk", "generic_risk_disclosure"} and intent["needs_event"]:
            return "generic_risk_outranks_actual_event"
        if intent["needs_quant"] and top["coverage"] < 0.2 and not re.search(r"\d", top["preview"] or ""):
            return "quant_fact_not_ranked"
        if not top["page_hit"] and top["coverage"] < 0.2:
            return "semantic_near_miss_or_chunk_boundary"
        return "gold_not_in_topk_content"
    if gold_rank > 1:
        if top["evidence_type"] in {"generic_future_risk", "generic_risk_disclosure"}:
            return "gold_recalled_but_generic_ranked_higher"
        if intent["needs_quant"]:
            return "gold_recalled_but_quant_not_top1"
        return "gold_recalled_but_rank_low"
    if ranked[0]["content_hit"] and not ranked[0]["page_hit"]:
        return "content_hit_page_mismatch"
    return "ok"


def load_cases(paths: List[Path]) -> List[dict]:
    cases: List[dict] = []
    for path in paths:
        dataset = path.stem
        for case in json.loads(path.read_text(encoding="utf-8")):
            item = dict(case)
            item["_dataset"] = dataset
            cases.append(item)
    return cases


def interpret_case_metrics(
    gold_rank: Optional[int],
    ranked: List[dict],
    page_hit_any: bool,
) -> Dict[str, Any]:
    """Split content success from page grounding without changing R@k semantics."""
    top = ranked[0] if ranked else None
    content_hit_at = {
        1: bool(gold_rank == 1),
        3: bool(gold_rank is not None and gold_rank <= 3),
        5: bool(gold_rank is not None and gold_rank <= 5),
        10: bool(gold_rank is not None and gold_rank <= 10),
    }
    content_status = "hit" if gold_rank is not None else "miss"
    if gold_rank is None:
        page_status = "hit" if page_hit_any else ("missing" if not ranked else "missing")
        if page_hit_any:
            interpretation = "content_miss_page_hit_elsewhere"
        else:
            interpretation = "content_miss"
        page_grounded_when_content_hit = False
        page_hit_at_gold_rank = False
    else:
        gold_item = ranked[gold_rank - 1]
        page_hit_at_gold_rank = bool(gold_item.get("page_hit"))
        if page_hit_at_gold_rank:
            page_status = "hit"
            interpretation = "full_success" if gold_rank == 1 else "content_success_page_hit_not_top1"
            page_grounded_when_content_hit = True
        else:
            page_status = "mismatch"
            interpretation = "content_success_page_mismatch"
            page_grounded_when_content_hit = False
            # if another topk result has correct page, treat as multi-location-like residual
            if page_hit_any:
                interpretation = "content_success_page_mismatch"
    # top1-focused page status for residual narrative
    if top and content_status == "hit" and gold_rank == 1 and not top.get("page_hit"):
        page_status = "mismatch"
        interpretation = "content_success_page_mismatch"
        page_grounded_when_content_hit = False
    multi_location_like = bool(
        content_status == "hit"
        and page_status == "mismatch"
        and page_hit_any
    )
    return {
        "content_hit_at_1": content_hit_at[1],
        "content_hit_at_3": content_hit_at[3],
        "content_hit_at_5": content_hit_at[5],
        "content_hit_at_10": content_hit_at[10],
        "content_status": content_status,
        "page_status": page_status,
        "interpretation": interpretation,
        "page_hit_at_gold_rank": bool(page_hit_at_gold_rank) if gold_rank is not None else False,
        "page_grounded_when_content_hit": bool(page_grounded_when_content_hit),
        "multi_location_like": multi_location_like,
    }


def build_case_metric_row(
    case: dict,
    ranked: List[dict],
    document_ids: List[str],
    phys_pages: List[List[int]],
    top_k: int,
    gf: Optional[dict] = None,
) -> dict:
    """Pure metric builder used by evaluate_case and unit tests."""
    del phys_pages  # reserved for future stricter page diagnostics; page_hit already scored on ranked items
    gf = gf or gold_fields(case)
    quant_markers = list(gf.get("quant_markers") or [])
    spans = list(gf.get("spans") or [])

    def top_blob(n: int) -> str:
        parts = []
        for item in ranked[: max(int(n), 0)]:
            parts.append(str(item.get("full_text") or item.get("preview") or ""))
        return "\n".join(parts)

    def quant_hit_at(n: int) -> bool:
        if not quant_markers:
            return False
        blob = top_blob(n)
        hits = quant_markers_hit(blob, quant_markers)
        need = 2 if len(quant_markers) >= 2 else 1
        if len(hits) < need:
            return False
        # If gold includes high share ratios (>=60%), require at least one such marker.
        # This prevents soft single-customer % from counting as full related-party total-share evidence.
        def _val(marker: str):
            try:
                return float(str(marker).replace('%', '').replace('％', '').strip())
            except Exception:
                return None
        high_expected = [m for m in quant_markers if (_val(m) is not None and _val(m) >= 60.0)]
        if high_expected:
            high_hits = [m for m in hits if (_val(m) is not None and _val(m) >= 60.0)]
            if not high_hits:
                return False
        return True

    def multi_span_support_at(n: int) -> bool:
        if not spans:
            return False
        blob = top_blob(n)
        supported = [span for span in spans if span_supported(blob, span)]
        # require all configured spans loosely supported within TopN union text
        return len(supported) >= len(spans)

    gold_rank = next((i for i, item in enumerate(ranked, 1) if item["content_hit"]), None)
    aligned_rank = gold_aligned_rank(ranked)
    page_hit_any = any(item.get("page_hit") for item in ranked)
    split = interpret_case_metrics(gold_rank, ranked, page_hit_any)
    row = {
        "id": case.get("id"),
        "dataset": case.get("_dataset"),
        "category": case.get("category"),
        "question": case.get("question"),
        "document_id": document_ids[0] if document_ids else None,
        "gold_rank": gold_rank,
        "gold_aligned_rank": aligned_rank,
        "gold_aligned_at_1": aligned_rank == 1,
        "gold_aligned_at_3": aligned_rank is not None and aligned_rank <= 3,
        "gold_aligned_at_5": aligned_rank is not None and aligned_rank <= 5,
        # R@k remains content-anchored
        "recall_at_1": gold_rank == 1,
        "recall_at_3": gold_rank is not None and gold_rank <= 3,
        "recall_at_5": gold_rank is not None and gold_rank <= 5,
        "recall_at_10": gold_rank is not None and gold_rank <= 10,
        "doc_hit": any(item["doc"] in document_ids for item in ranked) if document_ids else bool(ranked),
        "page_hit_any": page_hit_any,
        # Related-party / multi-span sufficiency (optional; does not replace GA)
        "quant_hit_at_5": quant_hit_at(5),
        "quant_hit_at_10": quant_hit_at(10 if top_k is None else min(int(top_k), 10) if top_k else 10),
        "multi_span_support_at_5": multi_span_support_at(5),
        "multi_span_support_at_10": multi_span_support_at(10 if top_k is None else min(int(top_k), 10) if top_k else 10),
        "quant_markers_expected": quant_markers,
        "quant_markers_hit_top10": quant_markers_hit(top_blob(10), quant_markers),
        "top1": ranked[0] if ranked else None,
        "ranked_brief": [
            {
                "rank": i,
                "coverage": item["coverage"],
                "content_hit": item.get("content_hit"),
                "gold_aligned": is_gold_aligned(item),
                "page_hit": item["page_hit"],
                "type": item["evidence_type"],
                "pages": item["pages"],
                "score": item["score"],
                "chunk_id": item["chunk_id"],
                "preview": item["preview"],
            }
            for i, item in enumerate(ranked[:5], 1)
        ],
        **split,
    }
    row["failure_reason"] = failure_reason(case, ranked, gold_rank)
    # Keep legacy failure_reason, but expose non-failure interpretation for page residual.
    if row["interpretation"] == "content_success_page_mismatch":
        row["narrative"] = "content_success_with_page_residual_not_retrieval_failure"
    elif row["interpretation"] == "full_success":
        row["narrative"] = "full_success"
    elif row["content_status"] == "miss":
        row["narrative"] = "content_miss"
    else:
        row["narrative"] = row["interpretation"]
    # sufficiency narrative for dual-span cases
    if quant_markers:
        if row.get("quant_hit_at_10") and row.get("multi_span_support_at_10"):
            row["sufficiency_narrative"] = "narrative_plus_quant_table"
        elif row.get("content_status") == "hit" and not row.get("quant_hit_at_10"):
            row["sufficiency_narrative"] = "narrative_only_missing_quant"
        else:
            row["sufficiency_narrative"] = "quant_or_content_gap"
    return row


def evaluate_case(retriever: LayeredRetriever, case: dict, top_k: int) -> dict:
    gf = gold_fields(case)
    document_id = gf["document_ids"][0] if gf["document_ids"] else None
    filters = {"document_id": document_id} if document_id else None
    results = retriever.search(case.get("question") or "", top_k=top_k, metadata_filters=filters)
    ranked = []
    for result in results:
        item = score_result_against_gold(result, gf)
        # Keep fuller text for quant/multi-span metrics (preview alone may truncate table rows).
        full_text = re.sub(r"\s+", " ", (getattr(result, "text", "") or item.get("preview") or ""))
        item["full_text"] = full_text[:4000]
        item["preview"] = full_text[:420]
        ranked.append(item)
    return build_case_metric_row(
        case=case,
        ranked=ranked,
        document_ids=gf["document_ids"],
        phys_pages=gf["phys_pages"],
        top_k=top_k,
        gf=gf,
    )


def summarize(rows: List[dict]) -> dict:
    n = len(rows) or 1
    ranks = [row["gold_rank"] for row in rows if row["gold_rank"]]

    def rate(key: str, items: List[dict] = rows) -> float:
        denom = len(items) or 1
        return round(sum(1 for row in items if row.get(key)) / denom, 4)

    content_success_n = sum(1 for row in rows if row.get("content_status") == "hit")
    page_mismatch_n = sum(1 for row in rows if row.get("interpretation") == "content_success_page_mismatch")
    multi_location_like_count = sum(1 for row in rows if row.get("multi_location_like"))
    page_grounded_when_content_n = sum(1 for row in rows if row.get("page_grounded_when_content_hit"))

    summary = {
        "n_cases": len(rows),
        # content-anchored ranking metrics (unchanged semantics)
        "recall_at_1": rate("recall_at_1"),
        "recall_at_3": rate("recall_at_3"),
        "recall_at_5": rate("recall_at_5"),
        "recall_at_10": rate("recall_at_10"),
        "mrr": round(sum(1.0 / r for r in ranks) / n, 4) if ranks else 0.0,
        "content_hit_at_1": rate("content_hit_at_1"),
        "content_hit_at_3": rate("content_hit_at_3"),
        "content_hit_at_5": rate("content_hit_at_5"),
        "content_hit_at_10": rate("content_hit_at_10"),
        # product-facing main acceptance: Gold-aligned@K (content-oriented)
        "gold_aligned_at_1": rate("gold_aligned_at_1"),
        "gold_aligned_at_3": rate("gold_aligned_at_3"),
        "gold_aligned_at_5": rate("gold_aligned_at_5"),
        "doc_hit_rate": rate("doc_hit"),
        "page_hit_any_rate": rate("page_hit_any"),
        # independent metric split
        "content_success_rate": round(content_success_n / n, 4),
        "page_grounding_rate": rate("page_hit_any"),
        "page_grounded_when_content_hit_rate": round(
            (page_grounded_when_content_n / content_success_n) if content_success_n else 0.0,
            4,
        ),
        "content_success_page_mismatch_rate": round(page_mismatch_n / n, 4),
        "multi_location_like_count": multi_location_like_count,
        "quant_hit_at_5": rate("quant_hit_at_5"),
        "quant_hit_at_10": rate("quant_hit_at_10"),
        "multi_span_support_at_5": rate("multi_span_support_at_5"),
        "multi_span_support_at_10": rate("multi_span_support_at_10"),
        "interpretation_counts": dict(Counter(row.get("interpretation") or "unknown" for row in rows)),
        "mrr": round(sum((1.0 / row["gold_rank"]) if row["gold_rank"] else 0.0 for row in rows) / n, 4),
        "avg_gold_rank_when_recalled": round(sum(ranks) / len(ranks), 3) if ranks else None,
        "failure_reason_counts": dict(Counter(row["failure_reason"] for row in rows)),
        "metric_definitions": {
            "recall_at_k": "content_hit anchored; page mismatch does not zero out R@k",
            "gold_aligned_at_k": "content-oriented human-gold alignment; main product acceptance",
            "content_success_rate": "share of cases with any content_hit in top_k",
            "page_grounding_rate": "share of cases with any expected-page hit in top_k (independent)",
            "content_success_page_mismatch_rate": "content success where top content hit is not page-grounded",
            "multi_location_like_count": "content success + page mismatch + page_hit_any in topk (approx multi-location)",
            "quant_hit_at_k": "TopK union text hits expected percent/quant markers (related-party sufficiency)",
            "multi_span_support_at_k": "TopK union loosely supports all expected_evidence_spans when configured",
        },
        "by_dataset": {},
        "by_category": {},
    }
    for field, target in [("dataset", "by_dataset"), ("category", "by_category")]:
        groups: Dict[str, List[dict]] = defaultdict(list)
        for row in rows:
            groups[str(row.get(field) or "unknown")].append(row)
        for name, items in groups.items():
            denom = len(items) or 1
            c_success = sum(1 for row in items if row.get("content_status") == "hit")
            p_mismatch = sum(1 for row in items if row.get("interpretation") == "content_success_page_mismatch")
            summary[target][name] = {
                "n": len(items),
                "recall_at_1": rate("recall_at_1", items),
                "recall_at_3": rate("recall_at_3", items),
                "recall_at_5": rate("recall_at_5", items),
                "recall_at_10": rate("recall_at_10", items),
                "gold_aligned_at_1": rate("gold_aligned_at_1", items),
                "gold_aligned_at_3": rate("gold_aligned_at_3", items),
                "gold_aligned_at_5": rate("gold_aligned_at_5", items),
                "content_success_rate": round(c_success / denom, 4),
                "page_grounding_rate": rate("page_hit_any", items),
                "content_success_page_mismatch_rate": round(p_mismatch / denom, 4),
                "mrr": round(sum((1.0 / row["gold_rank"]) if row["gold_rank"] else 0.0 for row in items) / denom, 4),
                "top_failures": dict(Counter(row["failure_reason"] for row in items).most_common(5)),
                "top_interpretations": dict(Counter(row.get("interpretation") or "unknown" for row in items).most_common(5)),
            }
    return summary


def build_runtime(config: RetrieverConfig) -> LayeredRetriever:
    engine = EmbeddingEngine(EmbeddingConfig())
    store = VectorStore(str(ROOT / "data" / "vectors"), dimension=engine.dimension)
    return LayeredRetriever(store, engine, config, chunk_dir=str(ROOT / "data" / "chunks"))


def evaluate_experiment(cases: List[dict], name: str, top_k: int) -> dict:
    flags = EXPERIMENTS[name]
    retriever = build_runtime(RetrieverConfig(top_k=top_k, **flags))
    rows = [evaluate_case(retriever, case, top_k) for case in cases]
    hard_cases = [row for row in rows if row["id"] in HARD_CASE_IDS or str(row["id"]).endswith("cat_comp_004")]
    ipo_rows = [row for row in rows if row.get("category") == "ipo_specific_risk"]
    improved_ipo_targets = [
        row for row in rows
        if row.get("category") == "ipo_specific_risk" and any(term in norm(row.get("question") or "") for term in ["所得款项", "发售前", "preipo"])
    ]
    return {
        "flags": flags,
        "summary": summarize(rows),
        "rows": rows,
        "hard_cases": hard_cases,
        "ipo_targets": improved_ipo_targets,
        "ipo_rows": ipo_rows,
    }


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def p0_success(results: dict) -> dict:
    baseline = results["experiments"]["baseline"]["summary"]
    target_name = "D_section_prior" if "D_section_prior" in results["experiments"] else "C_combined"
    target = results["experiments"][target_name]["summary"]
    by_cat = target["by_category"]
    by_data = target["by_dataset"]
    manual_baseline = baseline["by_dataset"].get("manual_gold_v1", {}).get("recall_at_5", 0.0)
    manual_combined = by_data.get("manual_gold_v1", {}).get("recall_at_5", 0.0)
    hard = {row["id"]: row for row in results["experiments"][target_name]["hard_cases"]}
    cat_comp = next((row for key, row in hard.items() if str(key).endswith("cat_comp_004")), None)
    duodian = hard.get("mgv1_duodian_comp_litigation_001")
    checks = {
        "r1_ge_45": target["recall_at_1"] >= 0.45,
        "r3_ge_65": target["recall_at_3"] >= 0.65,
        "r5_ge_75": target["recall_at_5"] >= 0.75,
        "r10_not_down": target["recall_at_10"] >= baseline["recall_at_10"],
        "mrr_ge_55": target["mrr"] >= 0.55,
        "ipo_r5_ge_50": by_cat.get("ipo_specific_risk", {}).get("recall_at_5", 0.0) >= 0.50,
        "compliance_r5_ge_625": by_cat.get("compliance_risk", {}).get("recall_at_5", 0.0) >= 0.625,
        "manual_gold_r5_not_down_gt_3pt": manual_combined >= manual_baseline - 0.03,
        "cat_comp_rank_le_3": bool(cat_comp and cat_comp.get("gold_rank") and cat_comp["gold_rank"] <= 3),
        "duodian_litigation_top1_not_generic": bool(
            duodian and duodian.get("top1") and duodian["top1"].get("evidence_type") not in {"generic_future_risk", "generic_risk_disclosure"}
        ),
    }
    return {"passed": all(checks.values()), "target_experiment": target_name, "checks": checks}


def render_report(results: dict) -> str:
    lines = [
        "# Gold-aligned TopN V2 / Gold vs RAG Top-K Report",
        "",
        "Condition: document_id constrained, top_k=10, follow-up and claim analysis disabled.",
        "",
        "## Metric Definitions",
        "",
        "1. **R@k / MRR** = content-anchored ranking metrics. A case counts as recalled when `content_hit` appears in top-k.",
        "2. **Gold-aligned@K** = product main acceptance. Content-oriented alignment to human gold excerpt/keywords (not page-only).",
        "3. **page grounding** = independent metric (`page_hit_any` / page status). It does **not** zero out R@k or Gold-aligned@K.",
        "4. **content_hit_page_mismatch** means content success with page residual. It is **not** a retrieval failure.",
        "5. **multi_location_like** approximates prospectus summary-vs-detail repeats: content success + page mismatch + page hit elsewhere in top-k.",
        "",
        "## Main Acceptance: Gold-aligned@K",
        "",
        "| Experiment | Gold-aligned@1 | Gold-aligned@3 | Gold-aligned@5 | R@5 | MRR |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, data in results["experiments"].items():
        s = data["summary"]
        lines.append(
            f"| {name} | {pct(s.get('gold_aligned_at_1', 0.0))} | {pct(s.get('gold_aligned_at_3', 0.0))} | "
            f"{pct(s.get('gold_aligned_at_5', 0.0))} | {pct(s['recall_at_5'])} | {s['mrr']:.4f} |"
        )

    lines += [
        "",
        "## Content-anchored Ranking Metrics",
        "",
        "| Experiment | R@1 | R@3 | R@5 | R@10 | MRR | content_success | Doc hit |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, data in results["experiments"].items():
        s = data["summary"]
        lines.append(
            f"| {name} | {pct(s['recall_at_1'])} | {pct(s['recall_at_3'])} | "
            f"{pct(s['recall_at_5'])} | {pct(s['recall_at_10'])} | {s['mrr']:.4f} | "
            f"{pct(s.get('content_success_rate', s['recall_at_10']))} | {pct(s['doc_hit_rate'])} |"
        )

    lines += [
        "",
        "## Independent Page Grounding Metrics",
        "",
        "| Experiment | page_grounding_rate | page_grounded_when_content_hit | content_success_page_mismatch | multi_location_like_count |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, data in results["experiments"].items():
        s = data["summary"]
        lines.append(
            f"| {name} | {pct(s.get('page_grounding_rate', s.get('page_hit_any_rate', 0.0)))} | "
            f"{pct(s.get('page_grounded_when_content_hit_rate', 0.0))} | "
            f"{pct(s.get('content_success_page_mismatch_rate', 0.0))} | "
            f"{s.get('multi_location_like_count', 0)} |"
        )

    lines += [
        "",
        "## Interpretation Counts",
        "",
    ]
    for name, data in results["experiments"].items():
        counts = data["summary"].get("interpretation_counts") or {}
        lines.append(f"- **{name}**: `{counts}`")

    lines += [
        "",
        "## Category R@5 (content-anchored)",
        "",
        "| Experiment | business | financial | ipo | ownership | compliance |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, data in results["experiments"].items():
        cats = data["summary"]["by_category"]
        lines.append(
            f"| {name} | {pct(cats.get('business_risk', {}).get('recall_at_5', 0))} | "
            f"{pct(cats.get('financial_risk', {}).get('recall_at_5', 0))} | "
            f"{pct(cats.get('ipo_specific_risk', {}).get('recall_at_5', 0))} | "
            f"{pct(cats.get('ownership_risk', {}).get('recall_at_5', 0))} | "
            f"{pct(cats.get('compliance_risk', {}).get('recall_at_5', 0))} |"
        )

    # Highlight content_success_page_mismatch rows for the last experiment if present
    focus_name = None
    for cand in ["H_plus_G_plus_E_plus_Role", "I_plus_H_plus_G_plus_E", "H_plus_G_plus_E", "G_plus_E", "E_ipo_local_rerank", "baseline"]:
        if cand in results["experiments"]:
            focus_name = cand
            break
    if focus_name:
        lines += [
            "",
            f"## Content Success + Page Residual Cases (`{focus_name}`)",
            "",
            "These are **not** retrieval failures. They are content-success cases with independent page residual.",
            "",
            "| Case | gold_rank | content_status | page_status | interpretation | page_hit_any | multi_location_like |",
            "|---|---:|---|---|---|---:|---:|",
        ]
        for row in results["experiments"][focus_name]["rows"]:
            if row.get("interpretation") != "content_success_page_mismatch":
                continue
            lines.append(
                f"| `{row['id']}` | {row.get('gold_rank')} | {row.get('content_status')} | "
                f"{row.get('page_status')} | {row.get('interpretation')} | "
                f"{row.get('page_hit_any')} | {row.get('multi_location_like')} |"
            )

    lines += [
        "",
        "## Hard Cases",
        "",
        "| Experiment | Case | content rank | Gold-aligned rank | interpretation | Top1 type | Top1 preview |",
        "|---|---|---:|---:|---|---|---|",
    ]
    for name, data in results["experiments"].items():
        for row in data.get("hard_cases") or []:
            top1 = row.get("top1") or {}
            preview = (top1.get("preview") or "").replace("|", "/")[:120]
            lines.append(
                f"| {name} | `{row['id']}` | {row.get('gold_rank')} | {row.get('gold_aligned_rank')} | "
                f"{row.get('interpretation')} | {top1.get('evidence_type')} | {preview} |"
            )

    p0 = results.get("p0_success") or {"passed": False, "checks": {}}
    lines += ["", "## P0 Gate", ""]
    for key, value in (p0.get("checks") or {}).items():
        lines.append(f"- {key}: {'PASS' if value else 'FAIL'}")
    lines += [
        "",
        f"Overall P0 success: {'YES' if p0.get('passed') else 'NO / N/A'}",
        "",
        "## Notes",
        "",
        "- No Hybrid/BM25/cross-encoder/LLM reranker was used.",
        "- Ranking flags remain experiment-controlled; defaults stay off outside explicit experiment configs.",
        "- R@k/MRR stay content-anchored after metric split.",
        "- Gold-aligned@3 is the product main acceptance metric for human-annotation demo.",
        "- I_intent_credit_competition only adds narrow aux for customer_credit / competitive_pricing intents.",
        "- page grounding is reported independently and must not be read as retrieval failure when content already hit.",
        "- This is a 39-case ranking regression, not 568-PDF production readiness.",
    ]
    return "\n".join(lines) + "\n"



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--benchmark-paths",
        default="evaluation/benchmark/manual_gold_v1.json,evaluation/benchmark/manual_new_annotators_v1.json",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--experiments", default="baseline,A_sufficiency,B_intent,C_combined,D_section_prior,E_ipo_local_rerank")
    parser.add_argument("--results-path", default="evaluation/benchmark/gold_vs_rag_topk_results.json")
    parser.add_argument("--report-path", default="docs/rag/GOLD_VS_RAG_TOPK_REPORT.md")
    parser.add_argument("--disable-followup", action="store_true")
    parser.add_argument("--disable-claim", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = [ROOT / part.strip() for part in args.benchmark_paths.split(",") if part.strip()]
    cases = load_cases(paths)
    experiment_names = [name.strip() for name in args.experiments.split(",") if name.strip()]
    results = {
        "condition": {
            "benchmark_paths": [str(path.relative_to(ROOT)) for path in paths],
            "top_k": args.top_k,
            "followup": False,
            "claim_analysis": False,
        },
        "experiments": {},
    }
    for name in experiment_names:
        print(f"running {name} on {len(cases)} cases")
        results["experiments"][name] = evaluate_experiment(cases, name, args.top_k)
    if "baseline" in results["experiments"] and "C_combined" in results["experiments"]:
        results["p0_success"] = p0_success(results)
    else:
        results["p0_success"] = {"passed": False, "checks": {}}

    results_path = ROOT / args.results_path
    report_path = ROOT / args.report_path
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_report(results), encoding="utf-8")
    print(f"saved {results_path}")
    print(f"saved {report_path}")


if __name__ == "__main__":
    main()
