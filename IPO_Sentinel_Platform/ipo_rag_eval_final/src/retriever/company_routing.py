"""Company/document routing helpers for Retriever candidate generation."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set

try:  # Optional dependency in some local environments; keep production import safe.
    from opencc import OpenCC  # type: ignore
except Exception:  # pragma: no cover - environment dependent
    OpenCC = None

_OPENCC = OpenCC("t2s") if OpenCC else None
_FALLBACK_TRANSLATION = str.maketrans({
    # Keep a compact offline t2s map for HK IPO company/document names when opencc is absent.
    "軟": "软",
    "體": "体",
    "點": "点",
    "數": "数",
    "據": "据",
    "華": "华",
    "國": "国",
    "際": "际",
    "開": "开",
    "發": "发",
    "電": "电",
    "車": "车",
    "雲": "云",
    "聲": "声",
    "優": "优",
    "業": "业",
    "聯": "联",
    "營": "营",
    "醫": "医",
    "藥": "药",
    "貿": "贸",
    "買": "买",
    "賣": "卖",
    "產": "产",
    "資": "资",
    "訊": "讯",
    "達": "达",
    "東": "东",
    "長": "长",
    "萬": "万",
    "輝": "辉",
    "創": "创",
    "視": "视",
    "傳": "传",
    "務": "务",
    "團": "团",
    "設": "设",
    "嶺": "岭",
    "時": "时",
    "凱": "凯",
    "萊": "莱",
    "潤": "润",
    "偉": "伟",
    "溫": "温",
    "豬": "猪",
    "術": "术",
    "爾": "尔",
    "顯": "显",
    "線": "线",
    "網": "网",
    "經": "经",
    "總": "总",
    "與": "与",
    "為": "为",
    "於": "于",
    "對": "对",
    "從": "从",
    "後": "后",
    "當": "当",
    "還": "还",
    "這": "这",
    "說": "说",
    "無": "无",
    "擊": "击",
    "億": "亿",
    "價": "价",
    "質": "质",
    "損": "损",
    "餘": "余",
    "幣": "币",
    "帳": "账",
    "戶": "户",
    "關": "关",
    "係": "系",
    "們": "们",
    "個": "个",
    "兩": "两",
    "並": "并",
    "態": "态",
    "報": "报",
    "應": "应",
    "懷": "怀",
    "態": "态",
})


@dataclass(frozen=True)
class RouteDecision:
    status: str
    source: str
    document_id: Optional[str] = None
    matched_name: Optional[str] = None
    candidate_document_ids: List[str] = None

    def __post_init__(self) -> None:
        if self.candidate_document_ids is None:
            object.__setattr__(self, "candidate_document_ids", [])


@dataclass(frozen=True)
class CompanyCatalogEntry:
    normalized_name: str
    names: List[str]
    document_ids: List[str]


def _get_value(item: Any, key: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        if key in item:
            return item.get(key, default)
        metadata = item.get("metadata") or {}
        if isinstance(metadata, dict):
            return metadata.get(key, default)
        return default
    value = getattr(item, key, default)
    if value != default:
        return value
    metadata = getattr(item, "metadata", {}) or {}
    if isinstance(metadata, dict):
        return metadata.get(key, default)
    return default


def normalize_for_company_match(text: Any) -> str:
    value = str(text or "")
    if _OPENCC:
        value = _OPENCC.convert(value)
    else:
        value = value.translate(_FALLBACK_TRANSLATION)
    value = value.lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value)


def _company_aliases(document_id: str, company: str) -> Set[str]:
    aliases = {company}
    parts = str(document_id or "").split("_", 2)
    if len(parts) == 3:
        aliases.add(parts[2])
    return {alias for alias in aliases if alias}


def build_company_catalog(vector_documents: Iterable[Any]) -> List[CompanyCatalogEntry]:
    by_name: Dict[str, Dict[str, Set[str]]] = {}
    for doc in vector_documents:
        document_id = str(_get_value(doc, "document_id", "") or "")
        if not document_id:
            continue
        company = str(_get_value(doc, "company", "") or "")
        for alias in _company_aliases(document_id, company):
            normalized = normalize_for_company_match(alias)
            if len(normalized) < 2:
                continue
            entry = by_name.setdefault(normalized, {"names": set(), "document_ids": set()})
            entry["names"].add(alias)
            entry["document_ids"].add(document_id)
    return [
        CompanyCatalogEntry(
            normalized_name=name,
            names=sorted(value["names"]),
            document_ids=sorted(value["document_ids"]),
        )
        for name, value in sorted(by_name.items(), key=lambda item: (-len(item[0]), item[0]))
    ]


def build_document_row_id_map(vector_documents: Iterable[Any]) -> Dict[str, List[int]]:
    mapping: Dict[str, List[int]] = defaultdict(list)
    for row_id, doc in enumerate(vector_documents):
        document_id = str(_get_value(doc, "document_id", "") or "")
        if document_id:
            mapping[document_id].append(row_id)
    return dict(mapping)


class CompanyRouter:
    """Exact company/document router built only from VectorStore documents."""

    def __init__(self, vector_documents: Iterable[Any]):
        docs = list(vector_documents)
        self.catalog = build_company_catalog(docs)
        self.document_ids = {
            str(_get_value(doc, "document_id", "") or "")
            for doc in docs
            if _get_value(doc, "document_id", "")
        }

    def resolve(self, query: str, metadata_filters: Optional[Dict[str, str]] = None) -> RouteDecision:
        filters = metadata_filters or {}
        document_id = filters.get("document_id")
        if document_id:
            if document_id in self.document_ids:
                return RouteDecision("matched", "document_id", document_id=document_id, candidate_document_ids=[document_id])
            return RouteDecision("no_match", "global_fallback")

        company = filters.get("company")
        if company:
            return self._resolve_company_text(company, source="company")

        return self._resolve_company_text(query, source="query")

    def _resolve_company_text(self, text: str, source: str) -> RouteDecision:
        normalized_text = normalize_for_company_match(text)
        if not normalized_text:
            return RouteDecision("no_match", "global_fallback")
        matches = [entry for entry in self.catalog if entry.normalized_name in normalized_text]
        if not matches:
            return RouteDecision("no_match", "global_fallback")
        longest = len(matches[0].normalized_name)
        longest_matches = [entry for entry in matches if len(entry.normalized_name) == longest]
        candidate_ids = sorted({doc_id for entry in longest_matches for doc_id in entry.document_ids})
        if len(longest_matches) != 1 or len(candidate_ids) != 1:
            matched_name = longest_matches[0].names[0] if longest_matches and longest_matches[0].names else None
            return RouteDecision("ambiguous", "global_fallback", matched_name=matched_name, candidate_document_ids=candidate_ids)
        selected = longest_matches[0]
        return RouteDecision(
            "matched",
            source,
            document_id=candidate_ids[0],
            matched_name=selected.names[0] if selected.names else selected.normalized_name,
            candidate_document_ids=candidate_ids,
        )

