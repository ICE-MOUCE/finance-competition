"""Related-party quantitative sufficiency helpers.

Generic IPO pattern (no company/case whitelist):
- detect related-party revenue dependence questions
- complementary-retrieve same-document table/quant chunks
- light rerank: promote 关联方/关连方 + revenue-share percentage sequences;
  demote bare related-party narrative without quant.
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence, Set

from .models import SearchResult
from .term_normalization import normalize_text

RELATED_PARTY_DEPENDENCE_QUERY_TERMS = (
    "关联方",
    "關聯方",
    "关连方",
    "關連方",
    "关连人士",
    "關連人士",
    "关联客户",
    "關聯客戶",
)

DEPENDENCE_QUERY_TERMS = (
    "依赖",
    "依賴",
    "重大依赖",
    "重大依賴",
    "收入依赖",
    "收益依赖",
    "客户收入",
    "客戶收入",
    "收益贡献",
    "收益貢獻",
    "收入贡献",
    "收入貢獻",
    "占比",
    "集中",
)

RELATED_PARTY_TEXT_TERMS = (
    "关联方",
    "關聯方",
    "关连方",
    "關連方",
    "关连人士",
    "關連人士",
    "其他关联方",
    "其他關聯方",
)

REVENUE_SHARE_TERMS = (
    "收益",
    "收入",
    "贡献",
    "貢獻",
    "占比",
    "百分比",
    "占总",
    "佔總",
    "占总收益",
    "佔總收益",
    "收益贡献",
    "收益貢獻",
)

PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")
BARE_RATIO_RE = re.compile(r"(?<!\d)(?:[1-9]?\d\.\d)(?!\d)")


def is_related_party_dependence_query(query: str) -> bool:
    q = normalize_text(query or "")
    if not q:
        return False
    has_rp = any(normalize_text(t) in q for t in RELATED_PARTY_DEPENDENCE_QUERY_TERMS)
    if not has_rp:
        return False
    has_dep = any(normalize_text(t) in q for t in DEPENDENCE_QUERY_TERMS)
    has_customer_rev = any(
        normalize_text(t) in q for t in ("客户", "客戶", "收入", "收益", "重大")
    )
    return bool(has_dep or has_customer_rev)


def _blob(result: SearchResult) -> str:
    meta = result.metadata or {}
    parts = [
        result.text or "",
        " ".join(result.section_path or []),
        str(meta.get("text_preview") or ""),
        str(meta.get("text_for_embedding") or ""),
        str(meta.get("table_description") or ""),
    ]
    return "\n".join(parts)


def percent_values(text: str) -> List[float]:
    vals: List[float] = []
    for m in PERCENT_RE.findall(text or ""):
        try:
            vals.append(float(m.replace("%", "").strip()))
        except ValueError:
            continue
    return vals


def has_percent_sequence(text: str, min_count: int = 3) -> bool:
    vals = percent_values(text)
    if len(vals) >= min_count:
        return True
    bare = BARE_RATIO_RE.findall(text or "")
    return len(bare) >= min_count and ("%" in (text or "") or "％" in (text or ""))


def related_party_quant_signal(result: SearchResult) -> float:
    """0-1: primary quant table/fact for related-party revenue dependence."""
    raw = _blob(result)
    if not raw.strip():
        return 0.0
    n = normalize_text(raw)
    has_rp = any(normalize_text(t) in n for t in RELATED_PARTY_TEXT_TERMS)
    if not has_rp:
        return 0.0
    rev_hits = sum(1 for t in REVENUE_SHARE_TERMS if normalize_text(t) in n)
    pct_seq = has_percent_sequence(raw, min_count=3)
    pct_n = len(percent_values(raw))
    table_like = (
        result.block_type == "table"
        or "表格" in raw
        or "|" in raw
        or str((result.metadata or {}).get("source") or "").startswith("table")
    )
    if not pct_seq and not (pct_n >= 2 and rev_hits >= 1 and table_like):
        if pct_n >= 1 and rev_hits >= 1 and has_rp:
            score = 0.25 + (0.1 if table_like else 0.0)
            return max(0.0, min(score, 1.0))
        return 0.0
    score = 0.35
    score += min(pct_n, 5) * 0.08
    score += min(rev_hits, 4) * 0.06
    if table_like:
        score += 0.2
    if "独立客户" in raw or "獨立客戶" in raw:
        score += 0.05
    return max(0.0, min(score, 1.0))


def is_weak_related_party_narrative(result: SearchResult) -> bool:
    raw = _blob(result)
    n = normalize_text(raw)
    if not any(normalize_text(t) in n for t in RELATED_PARTY_TEXT_TERMS):
        return False
    if related_party_quant_signal(result) >= 0.45:
        return False
    soft = any(
        normalize_text(t) in n
        for t in (
            "密切的业务关系",
            "密切的業務關係",
            "大量的业务交易",
            "大量的業務交易",
            "进行了大量",
            "進行了大量",
            "保持业务关系",
            "保持業務關係",
        )
    )
    pct_n = len(percent_values(raw))
    return soft and pct_n < 2


def build_related_party_quant_queries(query: str, max_queries: int = 2) -> List[str]:
    base = [
        f"{query} 关联方 收益贡献 占比 百分比 表格",
        f"{query} 關聯方 收益貢獻 佔比 獨立客戶 表格",
    ]
    out: List[str] = []
    seen: Set[str] = set()
    for q in base:
        key = normalize_text(q)
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
        if len(out) >= max(0, int(max_queries)):
            break
    return out


def merge_complementary_results(
    primary: Sequence[SearchResult],
    extra: Sequence[SearchResult],
    *,
    top_k: int,
) -> List[SearchResult]:
    merged: Dict[str, SearchResult] = {}
    order: List[str] = []

    def _key(r: SearchResult) -> str:
        return r.chunk_id or f"{r.document_id}:{','.join(map(str, r.pages or []))}:{hash((r.text or '')[:120])}"

    # Lift complementary quant/table candidates slightly on ingest so they are
    # not truncated away before rerank when dense head is narrative-heavy.
    boosted_extra = []
    for r in extra:
        signal = related_party_quant_signal(r)
        if signal:
            r.score = float(r.score or 0.0) + 0.35 * signal
            meta = dict(r.metadata or {})
            meta["related_party_quant_complement"] = True
            meta["related_party_quant_signal"] = round(signal, 4)
            r.metadata = meta
        boosted_extra.append(r)

    for src in (primary, boosted_extra):
        for r in src:
            k = _key(r)
            if k not in merged:
                merged[k] = r
                order.append(k)
                continue
            if float(r.score or 0.0) > float(merged[k].score or 0.0):
                old_meta = dict(merged[k].metadata or {})
                new_meta = dict(r.metadata or {})
                if old_meta.get("related_party_quant_complement") or new_meta.get(
                    "related_party_quant_complement"
                ):
                    new_meta["related_party_quant_complement"] = True
                r.metadata = new_meta
                merged[k] = r
            else:
                meta = dict(merged[k].metadata or {})
                if (r.metadata or {}).get("related_party_quant_complement"):
                    meta["related_party_quant_complement"] = True
                merged[k].metadata = meta

    ranked = sorted(
        order,
        key=lambda k: (float(merged[k].score or 0.0), -order.index(k)),
        reverse=True,
    )
    return [merged[k] for k in ranked[: max(int(top_k), 1)]]


def rerank_related_party_quant(query: str, results: Sequence[SearchResult]) -> List[SearchResult]:
    """Small additive rerank; only for related-party dependence questions."""
    if not results or not is_related_party_dependence_query(query):
        return list(results)

    scored = []
    for idx, result in enumerate(results):
        score = float(result.score or 0.0)
        signal = related_party_quant_signal(result)
        if signal:
            # Conservative but enough to outrank summary soft-match (~1.0-1.1) when signal high.
            score += 0.45 * signal
            if signal >= 0.6:
                score += 0.12
            meta = dict(result.metadata or {})
            meta["related_party_quant_signal"] = round(signal, 4)
            result.metadata = meta
        if is_weak_related_party_narrative(result):
            score -= 0.18
            meta = dict(result.metadata or {})
            meta["related_party_weak_narrative_penalty"] = True
            result.metadata = meta
        result.score = score
        scored.append((score, -idx, result))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored]