"""Claim-level evidence analysis for Thin RAG API V1."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from src.api.schemas import Citation
from src.retriever.term_normalization import expand_query_with_aliases, normalize_text, term_matches

QUANT_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?%?")
SENT_SPLIT_RE = re.compile(r"(?<=[。！？；;\n])")

RISK_KEYWORDS = [
    "风险", "風險", "亏损", "虧損", "负债", "負債", "依赖", "依賴", "集中",
    "关联方", "關聯方", "制裁", "诉讼", "訴訟", "仲裁", "许可", "許可", "牌照",
    "隐私", "隱私", "数据", "數據", "所得款项", "所得款項", "募资", "募資",
    "客户", "客戶", "供应商", "供應商", "现金流", "現金流",
]

MAJOR_RISK_MARKERS = [
    "重大", "严重", "嚴重", "主要", "高度依赖", "高度依賴", "制裁", "诉讼", "訴訟",
    "净亏损", "淨虧損", "净负债", "淨負債", "集中",
]

ENTITY_HINTS = [
    "关联方", "關聯方", "客户", "客戶", "供应商", "供應商",
    "美国", "美國", "控股股东", "控股股東", "董事",
]


@dataclass
class ClaimDraft:
    claim_text: str
    evidence_sentence: str
    quantitative_facts: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    risk_type: str = "other"
    answer_relevance: str = "partial"
    sufficiency: str = "partial"
    missing_facts: List[str] = field(default_factory=list)
    support_reason: str = ""
    source_result: Any = None


@dataclass
class ClaimRecord:
    claim_id: str
    claim_text: str
    answer_relevance: str
    risk_type: str
    quantitative_facts: List[str]
    entities: List[str]
    evidence_sentence: str
    citation: Citation
    sufficiency: str
    missing_facts: List[str]
    support_reason: str
    chunk_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "answer_relevance": self.answer_relevance,
            "risk_type": self.risk_type,
            "quantitative_facts": self.quantitative_facts,
            "entities": self.entities,
            "evidence_sentence": self.evidence_sentence,
            "citation": {
                "document_id": self.citation.document_id,
                "pages": list(self.citation.pages or []),
                "section": self.citation.section,
                "chunk_id": self.chunk_id,
                "evidence_ids": list(self.citation.evidence_ids or []),
            },
            "sufficiency": self.sufficiency,
            "missing_facts": self.missing_facts,
            "support_reason": self.support_reason,
        }


def _section_text(section_path: Sequence[str]) -> str:
    return " > ".join(str(x) for x in (section_path or []) if str(x).strip())


def _result_text(result: Any) -> str:
    return str(getattr(result, "text", "") or "")


def split_sentences(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in SENT_SPLIT_RE.split(text) if p and p.strip()]
    # also split long table-like fragments by period-like separators
    refined: List[str] = []
    for part in parts:
        if len(part) > 180 and "。" not in part:
            refined.extend([x.strip() for x in re.split(r"[；;\|]", part) if x.strip()])
        else:
            refined.append(part)
    return refined or [text]


def extract_quant_facts(text: str) -> List[str]:
    return list(dict.fromkeys(QUANT_RE.findall(text or "")))


def extract_entities(text: str) -> List[str]:
    found = []
    for ent in ENTITY_HINTS:
        if ent in (text or ""):
            found.append(ent)
    return list(dict.fromkeys(found))


def infer_risk_type(query: str, sentence: str) -> str:
    blob = normalize_text(query + " " + sentence)
    if any(k in blob for k in ["亏损", "负债", "现金流", "毛利率", "流动"]):
        return "financial_risk"
    if any(k in blob for k in ["关联方", "客户", "供应商", "竞争", "制裁", "依赖"]):
        return "business_risk"
    if any(k in blob for k in ["控股", "股权", "董事", "治理", "关连"]):
        return "ownership_risk"
    if any(k in blob for k in ["诉讼", "仲裁", "许可", "牌照", "合规", "隐私", "数据", "监管"]):
        return "compliance_risk"
    if any(k in blob for k in ["所得款项", "募资", "上市", "发售", "估值", "破发"]):
        return "ipo_specific_risk"
    return "other"


def sentence_grounded(sentence: str, source_text: str) -> bool:
    sentence = (sentence or "").strip()
    source_text = source_text or ""
    if not sentence or not source_text:
        return False
    if sentence in source_text:
        return True
    # allow near-substring for lightly normalized punctuation
    compact_s = re.sub(r"\s+", "", sentence)
    compact_t = re.sub(r"\s+", "", source_text)
    if compact_s and compact_s in compact_t:
        return True
    # high-overlap token fallback
    parts = [p for p in re.split(r"[，,、\s]", sentence) if len(p) >= 6]
    return any(p in source_text for p in parts)


def query_overlap_score(query: str, sentence: str) -> float:
    q = normalize_text(query)
    s = normalize_text(sentence)
    if not q or not s:
        return 0.0
    # character bigrams for Chinese-friendly overlap
    def bigrams(text: str) -> set:
        if len(text) < 2:
            return {text} if text else set()
        return {text[i : i + 2] for i in range(len(text) - 1)}

    qb, sb = bigrams(q), bigrams(s)
    if not qb:
        return 0.0
    return len(qb & sb) / len(qb)


def classify_claim(query: str, sentence: str, quant_facts: Sequence[str]) -> Dict[str, Any]:
    overlap = query_overlap_score(query, sentence)
    has_risk = any(term_matches(sentence, k) or k in sentence for k in RISK_KEYWORDS)
    has_major = any(m in sentence or m in query for m in MAJOR_RISK_MARKERS)
    has_quant = bool(quant_facts)

    if overlap < 0.05 and not has_risk:
        return {
            "answer_relevance": "irrelevant",
            "sufficiency": "weak",
            "missing_facts": [],
            "support_reason": "与问题关联弱，且缺少风险关键词",
        }

    if has_major and not has_quant:
        missing = []
        if any(k in query + sentence for k in ["制裁", "客户", "客戶", "依赖", "依賴", "集中"]):
            missing.append("客户销售额占比或收入贡献")
        if any(k in query + sentence for k in ["亏损", "虧損", "负债", "負債", "现金", "現金"]):
            missing.append("金额/比率等量化财务事实")
        if not missing:
            missing.append("关键量化事实（金额/占比/规模）")
        return {
            "answer_relevance": "partial",
            "sufficiency": "partial",
            "missing_facts": missing,
            "support_reason": "存在定性风险描述，但缺少规模/金额/占比等量化支撑",
        }

    if has_quant and (overlap >= 0.08 or has_risk):
        return {
            "answer_relevance": "supports_answer",
            "sufficiency": "sufficient",
            "missing_facts": [],
            "support_reason": "主张可由原文句支持，并包含可核验量化事实",
        }

    if has_risk and overlap >= 0.08:
        return {
            "answer_relevance": "partial",
            "sufficiency": "partial",
            "missing_facts": ["补充关键数字或影响规模"] if has_major else [],
            "support_reason": "主张与问题相关，但证据充分性有限",
        }

    return {
        "answer_relevance": "irrelevant",
        "sufficiency": "weak",
        "missing_facts": [],
        "support_reason": "证据相关度不足",
    }


def extract_claims_rule_based(query: str, results: Sequence[Any]) -> List[ClaimRecord]:
    drafts: List[ClaimDraft] = []
    for result in results:
        text = _result_text(result)
        for sentence in split_sentences(text):
            if len(sentence) < 8:
                continue
            if not any(k in sentence for k in RISK_KEYWORDS) and not QUANT_RE.search(sentence):
                continue
            quant = extract_quant_facts(sentence)
            labels = classify_claim(query, sentence, quant)
            if labels["answer_relevance"] == "irrelevant" and not quant:
                continue
            drafts.append(
                ClaimDraft(
                    claim_text=sentence if len(sentence) <= 120 else sentence[:117] + "...",
                    evidence_sentence=sentence,
                    quantitative_facts=quant,
                    entities=extract_entities(sentence),
                    risk_type=infer_risk_type(query, sentence),
                    answer_relevance=labels["answer_relevance"],
                    sufficiency=labels["sufficiency"],
                    missing_facts=labels["missing_facts"],
                    support_reason=labels["support_reason"],
                    source_result=result,
                )
            )
    return finalize_claims(query, drafts)


def llm_config() -> Dict[str, Any]:
    enabled = os.environ.get("IPO_CLAIM_LLM_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    api_key = os.environ.get("IPO_CLAIM_LLM_API_KEY", "").strip()
    base_url = os.environ.get("IPO_CLAIM_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("IPO_CLAIM_LLM_MODEL", "gpt-4o-mini").strip()
    return {
        "enabled": enabled and bool(api_key),
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }


def extract_claims_with_llm(query: str, results: Sequence[Any]) -> List[ClaimDraft]:
    cfg = llm_config()
    if not cfg["enabled"]:
        raise RuntimeError("llm disabled or missing api key")

    evidence_blocks = []
    for idx, result in enumerate(results[:5], 1):
        evidence_blocks.append(
            {
                "index": idx,
                "document_id": getattr(result, "document_id", ""),
                "pages": list(getattr(result, "pages", []) or []),
                "section": _section_text(getattr(result, "section_path", []) or []),
                "chunk_id": getattr(result, "chunk_id", ""),
                "evidence_ids": list(getattr(result, "evidence_ids", []) or []),
                "text": _result_text(result)[:2000],
            }
        )
    prompt = {
        "query": query,
        "instructions": (
            "Extract grounded risk claims only from provided evidence. "
            "Each claim must include evidence_sentence copied from evidence text. "
            "If major risk lacks quantitative scale, mark sufficiency=partial and list missing_facts. "
            "Return pure JSON list under key claims."
        ),
        "evidence": evidence_blocks,
    }
    body = {
        "model": cfg["model"],
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "You extract grounded IPO risk claims as compact JSON only."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        url=f"{cfg['base_url']}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    data = json.loads(content)
    items = data.get("claims") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise RuntimeError("llm returned non-list claims")

    drafts: List[ClaimDraft] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        evidence_sentence = str(item.get("evidence_sentence") or "").strip()
        source = None
        for result in results:
            if sentence_grounded(evidence_sentence, _result_text(result)):
                source = result
                break
        if source is None:
            continue
        quant = list(item.get("quantitative_facts") or extract_quant_facts(evidence_sentence))
        labels = classify_claim(query, evidence_sentence, quant)
        drafts.append(
            ClaimDraft(
                claim_text=str(item.get("claim_text") or evidence_sentence)[:200],
                evidence_sentence=evidence_sentence,
                quantitative_facts=[str(x) for x in quant],
                entities=[str(x) for x in (item.get("entities") or extract_entities(evidence_sentence))],
                risk_type=str(item.get("risk_type") or infer_risk_type(query, evidence_sentence)),
                answer_relevance=str(item.get("answer_relevance") or labels["answer_relevance"]),
                sufficiency=str(item.get("sufficiency") or labels["sufficiency"]),
                missing_facts=[str(x) for x in (item.get("missing_facts") or labels["missing_facts"])],
                support_reason=str(item.get("support_reason") or labels["support_reason"]),
                source_result=source,
            )
        )
    if not drafts:
        raise RuntimeError("llm produced no grounded claims")
    return drafts


def finalize_claims(query: str, drafts: Sequence[ClaimDraft]) -> List[ClaimRecord]:
    records: List[ClaimRecord] = []
    seen = set()
    for index, draft in enumerate(drafts, 1):
        source = draft.source_result
        source_text = _result_text(source) if source is not None else ""
        sentence = (draft.evidence_sentence or "").strip()
        grounded = sentence_grounded(sentence, source_text)
        quant = list(draft.quantitative_facts or extract_quant_facts(sentence))
        labels = classify_claim(query, sentence, quant)

        answer_relevance = draft.answer_relevance or labels["answer_relevance"]
        sufficiency = draft.sufficiency or labels["sufficiency"]
        missing = list(draft.missing_facts or labels["missing_facts"])
        reason = draft.support_reason or labels["support_reason"]

        if not grounded:
            answer_relevance = "irrelevant"
            sufficiency = "weak"
            missing = []
            reason = "claim 缺少可回挂的原文句，已拒绝"
            # keep sentence for audit but mark rejected later
        else:
            # re-assert partial for major qualitative risks
            if labels["sufficiency"] == "partial":
                answer_relevance = "partial"
                sufficiency = "partial"
                missing = labels["missing_facts"] or missing
                reason = labels["support_reason"]

        key = normalize_text(sentence or draft.claim_text)
        if key in seen:
            continue
        seen.add(key)

        citation = Citation(
            document_id=str(getattr(source, "document_id", "") or ""),
            pages=list(getattr(source, "pages", []) or []),
            section=_section_text(getattr(source, "section_path", []) or []),
            evidence_ids=list(getattr(source, "evidence_ids", []) or []),
        )
        records.append(
            ClaimRecord(
                claim_id=f"c{index}",
                claim_text=(draft.claim_text or sentence)[:200],
                answer_relevance=answer_relevance,
                risk_type=draft.risk_type or infer_risk_type(query, sentence),
                quantitative_facts=quant,
                entities=list(draft.entities or extract_entities(sentence)),
                evidence_sentence=sentence,
                citation=citation,
                sufficiency=sufficiency,
                missing_facts=missing,
                support_reason=reason,
                chunk_id=str(getattr(source, "chunk_id", "") or ""),
            )
        )
    return records


def package_claims(claims: Sequence[ClaimRecord]) -> Dict[str, Any]:
    accepted = [c for c in claims if c.answer_relevance == "supports_answer" and c.sufficiency == "sufficient"]
    partial = [c for c in claims if c.answer_relevance == "partial" or c.sufficiency == "partial"]
    rejected = [
        c
        for c in claims
        if c.answer_relevance in {"irrelevant", "contradictory"} or c.sufficiency == "weak"
    ]
    # ensure no overlap priority: accepted > partial > rejected
    accepted_ids = {c.claim_id for c in accepted}
    partial = [c for c in partial if c.claim_id not in accepted_ids]
    partial_ids = {c.claim_id for c in partial}
    rejected = [c for c in rejected if c.claim_id not in accepted_ids and c.claim_id not in partial_ids]

    if accepted and not partial:
        level = "full_support"
    elif accepted and partial:
        level = "partial_support"
    elif partial:
        level = "partial_support"
    elif claims:
        level = "weak_support"
    else:
        level = "insufficient"

    return {
        "claims": [c.to_dict() for c in claims],
        "accepted_claims": [c.to_dict() for c in accepted],
        "partial_claims": [c.to_dict() for c in partial],
        "rejected_claims": [c.to_dict() for c in rejected],
        "claim_level_support": level,
        "claim_records": list(claims),
        "accepted_records": accepted,
        "partial_records": partial,
        "rejected_records": rejected,
    }


def claims_need_followup(claims: Sequence[ClaimRecord]) -> bool:
    for claim in claims:
        if claim.sufficiency == "partial" or claim.answer_relevance == "partial":
            return True
        if claim.missing_facts:
            return True
    # if no useful claims at all, also allow follow-up
    useful = [c for c in claims if c.answer_relevance in {"supports_answer", "partial"}]
    return not useful


def build_claim_followup_queries(query: str, claims: Sequence[ClaimRecord], max_rounds: int = 2) -> List[str]:
    max_rounds = max(0, min(int(max_rounds or 0), 2))
    if max_rounds <= 0:
        return []

    missing: List[str] = []
    for claim in claims:
        missing.extend(claim.missing_facts or [])
    if not missing:
        if any(k in query for k in ["制裁", "依赖", "依賴", "集中"]):
            missing = ["客户销售额占比", "收入贡献"]
        else:
            missing = ["关键量化事实", "金额或占比"]

    missing = list(dict.fromkeys(missing))
    q1 = expand_query_with_aliases(" ".join([query] + missing[:4]))
    q2 = " ".join([query, "占比", "收入", "金额", "影响规模"] + missing[:3])
    queries = [q1, q2]
    return list(dict.fromkeys(q for q in queries if q and q.strip()))[:max_rounds]


def extract_claims(query: str, results: Sequence[Any], llm_enabled: Optional[bool] = None) -> List[ClaimRecord]:
    cfg = llm_config()
    use_llm = cfg["enabled"] if llm_enabled is None else bool(llm_enabled and cfg["enabled"])
    drafts: List[ClaimDraft] = []
    if use_llm:
        try:
            drafts = extract_claims_with_llm(query, results)
        except Exception:
            drafts = []
    if not drafts:
        return extract_claims_rule_based(query, results)
    return finalize_claims(query, drafts)
