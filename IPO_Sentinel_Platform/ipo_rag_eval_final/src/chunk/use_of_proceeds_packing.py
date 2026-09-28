
"""Helpers for use-of-proceeds cross-page list/table chunk representation."""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence

UOP_SECTION_MARKERS = [
    "\u6240\u5f97\u6b3e\u9805\u7528\u9014",
    "\u6240\u5f97\u6b3e\u9879\u7528\u9014",
    "\u672a\u4f86\u8a08\u5283\u53ca\u6240\u5f97\u6b3e\u9805\u7528\u9014",
    "\u672a\u6765\u8ba1\u5212\u53ca\u6240\u5f97\u6b3e\u9879\u7528\u9014",
    "\u672a\u4f86\u8a08\u5283",
    "\u672a\u6765\u8ba1\u5212",
]
UOP_TEXT_MARKERS = [
    "\u6240\u5f97\u6b3e\u9805",
    "\u6240\u5f97\u6b3e\u9879",
    "\u6240\u5f97\u6b3e\u9805\u6de8\u984d",
    "\u6240\u5f97\u6b3e\u9879\u51c0\u989d",
    "\u52df\u96c6\u8d44\u91d1",
    "\u52df\u8cc7",
    "\u5168\u7403\u767c\u552e\u6240\u5f97\u6b3e",
    "\u5168\u7403\u767c\u552e\u6240\u5f97\u6b3e\u9805",
]
USE_VERBS = [
    "\u7528\u65bc",
    "\u7528\u4e8e",
    "\u5c07\u7528\u65bc",
    "\u5c06\u7528\u4e8e",
    "\u5206\u914d\u7528\u65bc",
    "\u5206\u914d\u7528\u4e8e",
    "\u9810\u671f\u5c07\u7528\u65bc",
    "\u9884\u671f\u5c06\u7528\u4e8e",
]
PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")
NEGATIVE_UOP_MARKERS = [
    "\u4e0a\u5e02\u958b\u652f", "\u4e0a\u5e02\u5f00\u652f", "\u5305\u92b7", "\u5305\u9500",
    "\u80a1\u606f", "\u6bdb\u5229\u7387", "\u6536\u5165", "\u71df\u6536", "\u8425\u6536",
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def section_has_uop_marker(section_path: Sequence[str] | None) -> bool:
    blob = _norm(" ".join(section_path or []))
    return any(_norm(m) in blob for m in UOP_SECTION_MARKERS)


def text_has_uop_marker(text: str) -> bool:
    blob = _norm(text)
    return any(_norm(m) in blob for m in UOP_TEXT_MARKERS + UOP_SECTION_MARKERS)


def is_allocation_bullet(text: str) -> bool:
    t = text or ""
    if not PERCENT_RE.search(t):
        return False
    # Exclude listing-expense / underwriting percent sentences.
    if any(bad in t for bad in ["上市開支", "上市开支", "包銷", "包销"]):
        return False
    if text_has_uop_marker(t):
        return any(v in t for v in USE_VERBS) or any(m in t for m in ["所得款項", "所得款项", "所得款"])
    if not any(v in t for v in USE_VERBS):
        return False
    return len(_norm(t)) <= 180


def is_uop_unit(evidence: Dict) -> bool:
    text = evidence.get("text") or evidence.get("table_description") or ""
    section = evidence.get("section_path") or []
    if section_has_uop_marker(section) and (is_allocation_bullet(text) or text_has_uop_marker(text) or len(_norm(text)) <= 20):
        return True
    if text_has_uop_marker(text):
        return True
    if is_allocation_bullet(text):
        return True
    return False


def choose_uop_section_path(evidences: Iterable[Dict]) -> List[str]:
    best: List[str] = []
    best_score = -1
    for evidence in evidences:
        section = list(evidence.get("section_path") or [])
        text = evidence.get("text") or ""
        score = 0
        if section_has_uop_marker(section):
            score += 3
        if text_has_uop_marker(text):
            score += 1
        if is_allocation_bullet(text):
            score += 1
        if score > best_score and section:
            best = section
            best_score = score
    if best_score >= 3:
        return best
    # fallback: synthesize from text header if present
    for evidence in evidences:
        text = (evidence.get("text") or "").strip()
        if text in UOP_SECTION_MARKERS or any(_norm(m) == _norm(text) for m in UOP_SECTION_MARKERS):
            return [text]
    return best


def should_flush_before_adding(
    current_evidences: List[Dict],
    next_evidence: Dict,
    current_token_count: int,
    next_tokens: int,
    max_tokens: int,
) -> bool:
    """Decide whether to close the current text chunk before appending next_evidence."""
    if not current_evidences:
        return False

    current_is_uop = any(is_uop_unit(e) for e in current_evidences)
    next_is_uop = is_uop_unit(next_evidence)
    # Allow a modest overflow inside an active use-of-proceeds allocation cluster so
    # short percent/use bullets across 1-2 pages stay together.
    effective_max = int(max_tokens * 1.35) if (current_is_uop and next_is_uop) else max_tokens
    if current_token_count + next_tokens > effective_max:
        return True

    if current_is_uop and not next_is_uop:
        # close allocation cluster before non-UOP tail text (underwriters, dividend, etc.)
        return True
    if (not current_is_uop) and next_is_uop and current_token_count >= max(40, max_tokens // 4):
        # start a fresh chunk for UOP cluster instead of appending to long finance tail
        return True
    return False


def enrich_section_path_for_chunk(evidences: List[Dict], fallback: List[str] | None = None) -> List[str]:
    chosen = choose_uop_section_path(evidences)
    if chosen:
        return chosen
    return list(fallback or [])


def collect_allocation_bullets(evidences: Sequence[Dict], pages: Sequence[int], pad: int = 1) -> List[str]:
    page_set = set(int(p) for p in pages or [])
    if not page_set:
        return []
    lo = min(page_set) - pad
    hi = max(page_set) + pad
    bullets: List[str] = []
    seen = set()
    for evidence in evidences:
        page = int(evidence.get("page") or -1)
        if page < lo or page > hi:
            continue
        raw = (evidence.get("text") or "").strip()
        if not raw or not is_allocation_bullet(raw):
            continue
        key = _norm(raw)[:180]
        if key in seen:
            continue
        seen.add(key)
        bullets.append(re.sub(r"\s+", " ", raw))
    return bullets


def build_allocation_summary(evidences: Sequence[Dict], pages: Sequence[int], existing_text: str = "", max_chars: int = 700) -> str:
    """Compact neighboring allocation bullets for searchable enrichment."""
    bullets = collect_allocation_bullets(evidences, pages, pad=1)
    if not bullets:
        return ""
    existing = _norm(existing_text)
    selected: List[str] = []
    total = 0
    for bullet in bullets:
        if _norm(bullet) in existing:
            continue
        # keep compact allocation sentences
        piece = bullet
        if len(piece) > 180:
            piece = piece[:177] + "..."
        if total + len(piece) + 1 > max_chars:
            break
        selected.append(piece)
        total += len(piece) + 1
    if not selected:
        return ""
    return " | ".join(selected)


def enrich_uop_chunk_text(text: str, evidences: Sequence[Dict], pages: Sequence[int]) -> str:
    summary = build_allocation_summary(evidences, pages, existing_text=text)
    if not summary:
        return text
    if not text:
        return summary
    return text + "\n\n[UOP allocation facts] " + summary
