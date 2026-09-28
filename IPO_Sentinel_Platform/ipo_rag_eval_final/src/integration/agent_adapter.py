# -*- coding: utf-8 -*-
"""RAG -> Agent framework adapter (local, no monorepo merge)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.api.schemas import SearchRequest, SearchResponse
from src.api.service import RuntimeBundle, health as api_health, search as api_search
from src.integration.schema_map import (
    BBOX_PLACEHOLDER,
    OWNER_AGENT,
    PARSER_VERSION,
    EvidenceObject,
    RiskClaim,
    as_dict,
    default_limitations,
    detect_language,
    map_audit_status,
    map_block_type,
    map_confidence,
    map_risk_code,
    map_severity,
    physical_page_to_agent_page,
    sha256_text,
    split_section_path,
    stable_evidence_id,
    validate_agent_claim_dicts,
    validate_agent_evidence_dicts,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_mapping(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return dict(getattr(obj, "__dict__", {}) or {})


def _pick_company_id(result: Dict[str, Any], routing: Dict[str, Any], request_company: Optional[str]) -> str:
    for candidate in (
        request_company,
        routing.get("company"),
        result.get("company"),
        routing.get("matched_name"),
        result.get("document_id"),
        routing.get("document_id"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return "unknown_company"


def _result_pages(result: Dict[str, Any]) -> List[int]:
    pages = result.get("pages") or []
    out: List[int] = []
    for p in pages:
        try:
            out.append(int(p))
        except Exception:
            continue
    return out


def map_result_to_evidence(
    result: Dict[str, Any],
    *,
    routing: Optional[Dict[str, Any]] = None,
    request_company: Optional[str] = None,
    warnings: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Map one Thin RAG search result to peer-compatible EvidenceObject dict."""
    routing = routing or {}
    local_warnings: List[str] = []
    document_id = str(result.get("document_id") or routing.get("document_id") or "").strip()
    text = str(result.get("text") or "").strip()
    if not text:
        text = str(result.get("preview") or "").strip()
        local_warnings.append("result_text_empty_used_preview")

    pages_0 = _result_pages(result)
    physical_page = pages_0[0] if pages_0 else 0
    agent_page = physical_page_to_agent_page(physical_page)

    evidence_ids = [str(x) for x in (result.get("evidence_ids") or []) if str(x).strip()]
    if evidence_ids:
        evidence_id = evidence_ids[0]
    else:
        evidence_id = stable_evidence_id(document_id, pages_0, text)
        local_warnings.append(f"missing_evidence_id_generated:{evidence_id}")

    company_id = _pick_company_id(result, routing, request_company)
    section_path = split_section_path(result.get("section") or (result.get("citation") or {}).get("section"))
    block_type = map_block_type(result.get("block_type"))
    bbox = BBOX_PLACEHOLDER
    local_warnings.append("bbox_placeholder_used")

    evidence = EvidenceObject(
        evidence_id=evidence_id,
        company_id=company_id,
        document_id=document_id or "unknown_document",
        source_type="prospectus",
        page=agent_page,
        section_path=section_path,
        block_type=block_type,
        text=text,
        bbox=bbox,
        screenshot_uri=None,
        language=detect_language(text),
        ocr_used=False,
        ocr_confidence=1.0,
        source_timestamp=None,
        content_hash=sha256_text(text),
        parser_version=PARSER_VERSION,
        injection_like_text=False,
    )
    payload = as_dict(evidence)
    # Keep diagnostic fields outside the strict peer schema for adapter consumers.
    payload["_adapter_meta"] = {
        "physical_page_0_based": physical_page,
        "agent_page_1_based": agent_page,
        "source_rank": result.get("rank"),
        "source_score": result.get("score"),
        "source_chunk_id": result.get("chunk_id"),
        "source_evidence_ids": evidence_ids,
        "bbox_placeholder": True,
        "parser_version": PARSER_VERSION,
    }
    if warnings is not None:
        warnings.extend(local_warnings)
    return payload, local_warnings


def map_claim_to_risk_claim(
    claim: Dict[str, Any],
    *,
    bucket: str,
    data_cutoff: Optional[datetime] = None,
    fallback_evidence_ids: Optional[Sequence[str]] = None,
    warnings: Optional[List[str]] = None,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Map accepted/partial ClaimItem to peer RiskClaim dict. Rejected must not enter."""
    local_warnings: List[str] = []
    key = (bucket or "").lower()
    if key == "rejected":
        local_warnings.append("rejected_claim_skipped")
        if warnings is not None:
            warnings.extend(local_warnings)
        return None, local_warnings

    citation = claim.get("citation") or {}
    evidence_ids = [str(x) for x in (citation.get("evidence_ids") or []) if str(x).strip()]
    if not evidence_ids and fallback_evidence_ids:
        evidence_ids = [str(x) for x in fallback_evidence_ids if str(x).strip()]
        local_warnings.append("claim_evidence_ids_filled_from_results")
    if not evidence_ids:
        local_warnings.append(f"claim_skipped_no_evidence_ids:{claim.get('claim_id')}")
        if warnings is not None:
            warnings.extend(local_warnings)
        return None, local_warnings

    claim_text = str(claim.get("claim_text") or claim.get("evidence_sentence") or "").strip()
    if not claim_text:
        local_warnings.append(f"claim_skipped_empty_text:{claim.get('claim_id')}")
        if warnings is not None:
            warnings.extend(local_warnings)
        return None, local_warnings

    missing_facts = list(claim.get("missing_facts") or [])
    quantitative_facts = list(claim.get("quantitative_facts") or [])
    risk_type = claim.get("risk_type") or "other"
    limitations = default_limitations(
        bbox_placeholder=True,
        page_converted=True,
        claim_bucket=key,
        missing_facts=missing_facts,
    )
    if claim.get("support_reason"):
        limitations.append("support_reason=" + str(claim.get("support_reason"))[:180])

    risk_claim = RiskClaim(
        claim_id=str(claim.get("claim_id") or stable_evidence_id("claim", [], claim_text) ),
        risk_code=map_risk_code(risk_type, claim_text),
        claim=claim_text,
        direction="risk",
        severity=map_severity(risk_type, quantitative_facts),
        confidence=map_confidence(key),
        evidence_ids=evidence_ids,
        counter_evidence_ids=[],
        calculation_ids=[],
        applicable_windows=["1d", "5d", "20d", "60d"],
        data_cutoff=data_cutoff or _utcnow(),
        audit_status=map_audit_status(key),
        limitations=limitations,
        owner_agent=OWNER_AGENT,
        audit_reason=(
            f"mapped_from_rag_claim bucket={key} sufficiency={claim.get('sufficiency')}"
        ),
    )
    payload = as_dict(risk_claim)
    payload["_adapter_meta"] = {
        "source_bucket": key,
        "source_risk_type": risk_type,
        "quantitative_facts": quantitative_facts,
        "missing_facts": missing_facts,
        "evidence_sentence": claim.get("evidence_sentence") or "",
        "citation": citation,
        "not_peer_probability_model": True,
    }
    if warnings is not None:
        warnings.extend(local_warnings)
    return payload, local_warnings


def map_search_response_to_agent(
    response: Any,
    *,
    request_company: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert SearchResponse (or dict) into agent-consumable package."""
    raw = _as_mapping(response)
    routing = _as_mapping(raw.get("routing"))
    results = [_as_mapping(item) for item in (raw.get("results") or [])]
    mapping_warnings: List[str] = list(raw.get("warnings") or [])
    data_gaps: List[str] = [
        "bbox_unavailable_from_rag_index",
        "peer_probability_model_not_invoked",
        "peer_risk_taxonomy_not_authoritative_in_adapter",
    ]

    agent_evidences: List[Dict[str, Any]] = []
    seen_evidence_ids: set[str] = set()
    for item in results:
        evidence, warns = map_result_to_evidence(
            item,
            routing=routing,
            request_company=request_company,
        )
        mapping_warnings.extend(warns)
        eid = evidence.get("evidence_id")
        if eid in seen_evidence_ids:
            continue
        seen_evidence_ids.add(eid)
        agent_evidences.append(evidence)

    fallback_ids = [e.get("evidence_id") for e in agent_evidences if e.get("evidence_id")]

    agent_claims: List[Dict[str, Any]] = []
    seen_claim_keys: set[str] = set()
    for bucket, key in (
        ("accepted_claims", "accepted"),
        ("partial_claims", "partial"),
    ):
        for claim in raw.get(bucket) or []:
            mapped, warns = map_claim_to_risk_claim(
                _as_mapping(claim),
                bucket=key,
                fallback_evidence_ids=fallback_ids,
            )
            mapping_warnings.extend(warns)
            if mapped is None:
                continue
            dedupe_key = (
                str(mapped.get("claim") or "").strip()
                + "|"
                + ",".join(mapped.get("evidence_ids") or [])
            )
            if dedupe_key in seen_claim_keys:
                continue
            seen_claim_keys.add(dedupe_key)
            agent_claims.append(mapped)
    if len(agent_claims) > 20:
        mapping_warnings.append(f"agent_claims_truncated:{len(agent_claims)}->20")
        agent_claims = agent_claims[:20]

    # Explicitly ignore rejected claims for main list.
    rejected = raw.get("rejected_claims") or []
    if rejected:
        mapping_warnings.append(f"rejected_claims_excluded:{len(rejected)}")

    # Strict validation against mirrored peer schema (strip adapter meta first).
    strict_evidences = [{k: v for k, v in e.items() if not k.startswith("_")} for e in agent_evidences]
    strict_claims = [{k: v for k, v in c.items() if not k.startswith("_")} for c in agent_claims]
    validated_evidences = [as_dict(x) for x in validate_agent_evidence_dicts(strict_evidences)]
    validated_claims = [as_dict(x) for x in validate_agent_claim_dicts(strict_claims)]

    # Re-attach adapter meta after validation for local debugging.
    meta_by_eid = {e.get("evidence_id"): e.get("_adapter_meta") for e in agent_evidences}
    for item in validated_evidences:
        if item.get("evidence_id") in meta_by_eid:
            item["_adapter_meta"] = meta_by_eid[item["evidence_id"]]
    meta_by_cid = {c.get("claim_id"): c.get("_adapter_meta") for c in agent_claims}
    for item in validated_claims:
        if item.get("claim_id") in meta_by_cid:
            item["_adapter_meta"] = meta_by_cid[item["claim_id"]]

    pages = [int(e.get("page") or 0) for e in validated_evidences]
    page_ok = all(p >= 1 for p in pages) if pages else False
    claim_with_text = 0
    for claim in validated_claims:
        if claim.get("claim") and claim.get("evidence_ids"):
            # require corresponding evidence text if available
            if any(e.get("evidence_id") in set(claim.get("evidence_ids") or []) and e.get("text") for e in validated_evidences):
                claim_with_text += 1
            elif claim.get("claim"):
                claim_with_text += 1

    package = {
        "query": raw.get("query"),
        "routing": routing,
        "agent_evidences": validated_evidences,
        "agent_claims": validated_claims,
        "raw_rag_response": raw,
        "mapping_warnings": mapping_warnings,
        "data_gaps": data_gaps,
        "limitations": [
            "adapter_only_no_monorepo_merge",
            "page_is_1_based_converted_from_mineru_0_based",
            "bbox_placeholder_when_missing",
            "does_not_replace_peer_risk_engine_or_probability_model",
        ],
        "validation": {
            "evidence_count": len(validated_evidences),
            "claim_count": len(validated_claims),
            "all_pages_ge_1": page_ok,
            "claims_with_evidence_and_text": claim_with_text,
            "parser_version": PARSER_VERSION,
            "owner_agent": OWNER_AGENT,
        },
    }
    return package


def query_for_agent(
    runtime: RuntimeBundle,
    *,
    query: str,
    company: Optional[str] = None,
    document_id: Optional[str] = None,
    top_k: int = 5,
    enable_followup: bool = True,
    enable_claim_analysis: bool = True,
    max_followup_rounds: int = 2,
) -> Dict[str, Any]:
    """Local callable used by smoke scripts and future peer bypass integration."""
    request = SearchRequest(
        query=query,
        top_k=top_k,
        company=company,
        document_id=document_id,
        enable_followup=enable_followup,
        enable_claim_analysis=enable_claim_analysis,
        max_followup_rounds=max_followup_rounds,
    )
    response: SearchResponse = api_search(runtime, request)
    package = map_search_response_to_agent(response, request_company=company)
    health_payload = as_dict(api_health(runtime)) if runtime is not None else {}
    package["health"] = health_payload
    package["request"] = {
        "query": query,
        "company": company,
        "document_id": document_id,
        "top_k": top_k,
        "enable_followup": enable_followup,
        "enable_claim_analysis": enable_claim_analysis,
        "max_followup_rounds": max_followup_rounds,
    }
    return package
