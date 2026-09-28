"""Thin RAG API service: wraps existing retriever runtime."""
from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.api.schemas import (
    Citation,
    ClaimCitation,
    ClaimItem,
    DocumentSummary,
    DocumentsResponse,
    EvidenceChainInfo,
    EvidenceGetResponse,
    HealthResponse,
    RoutingInfo,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from src.api.claim_analysis import (
    build_claim_followup_queries,
    claims_need_followup,
    extract_claims,
    package_claims,
)
from src.embedding import EmbeddingConfig, EmbeddingEngine
from src.evidence.store import EvidenceStore
from src.retriever import LayeredRetriever, RetrieverConfig, build_retriever_config, normalize_ranking_profile
from src.retriever.company_routing import CompanyRouter
from src.retriever.term_normalization import expand_query_with_aliases, term_matches
from src.vector import VectorStore

API_VERSION = "thin-rag-api-v1"
READINESS_NOTE = (
    "Thin RAG API 原型：基于本地向量索引与 LayeredRetriever。"
    "25-case development set 的 chain support / evidence fragment recall 已通过；"
    "section grounding 约 80%，不代表 568 份招股书生产就绪，也不代表可直接租服务器上线。"
)

CORE_FACT_TERMS = [
    "净亏损",
    "净负债",
    "经营活动所用现金",
    "许可证",
    "数据",
    "隐私",
    "诉讼",
    "董事确认",
    "所得款项",
    "募资",
]


@dataclass
class RuntimeBundle:
    embedding_engine: EmbeddingEngine
    vector_store: VectorStore
    retriever: LayeredRetriever
    evidence_store: EvidenceStore
    version: str = API_VERSION
    model_loaded: bool = True
    vector_count: int = 0


def build_runtime(vector_dir: str, chunk_dir: str, evidence_dir: str) -> RuntimeBundle:
    engine = EmbeddingEngine(EmbeddingConfig())
    store = VectorStore(vector_dir, dimension=engine.dimension)
    retriever = LayeredRetriever(
        store,
        engine,
        build_retriever_config(profile="default", top_k=5),
        chunk_dir=chunk_dir,
    )
    evidence_store = EvidenceStore(evidence_dir)
    stats = store.get_stats() if hasattr(store, "get_stats") else {}
    vector_count = int(stats.get("total_vectors") or len(getattr(store, "documents", []) or []))
    return RuntimeBundle(
        embedding_engine=engine,
        vector_store=store,
        retriever=retriever,
        evidence_store=evidence_store,
        version=API_VERSION,
        model_loaded=True,
        vector_count=vector_count,
    )


def _section_text(section_path: Sequence[str]) -> str:
    return " > ".join(str(item) for item in (section_path or []) if str(item).strip())


def _preview(text: str, max_chars: int = 180) -> str:
    text = text or ""
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def _page_labels(metadata: Dict[str, Any]) -> List[Any]:
    if not isinstance(metadata, dict):
        return []
    labels = metadata.get("page_labels")
    if isinstance(labels, list):
        return labels
    return []



def _chunk_cache_get(runtime: Optional[RuntimeBundle], document_id: str, chunk_id: str) -> Dict[str, Any]:
    """Load one chunk dict from retriever cache or chunk_dir; never raises."""
    if not runtime or not document_id or not chunk_id:
        return {}
    retriever = getattr(runtime, "retriever", None)
    if retriever is not None and hasattr(retriever, "_get_chunk"):
        try:
            chunk = retriever._get_chunk(document_id, chunk_id) or {}
            if isinstance(chunk, dict) and chunk:
                return chunk
        except Exception:
            pass
    chunk_dir = getattr(retriever, "chunk_dir", None) if retriever is not None else None
    if chunk_dir is None:
        return {}
    try:
        path = Path(chunk_dir) / document_id / "chunks.json"
        if not path.exists():
            return {}
        import json

        chunks = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(chunks, list):
            return {}
        for item in chunks:
            if isinstance(item, dict) and item.get("chunk_id") == chunk_id:
                return item
    except Exception:
        return {}
    return {}


def _normalize_table_payload(
    table_html: Any = "",
    table_data: Any = None,
    table_headers: Any = None,
    table_rows: Any = None,
) -> Dict[str, Any]:
    """Normalize optional table presentation fields for API/Agent consumers."""
    html = str(table_html or "").strip()
    data: Dict[str, Any] = table_data if isinstance(table_data, dict) else {}
    headers = list(table_headers) if isinstance(table_headers, list) else []
    rows = list(table_rows) if isinstance(table_rows, list) else []
    if not headers and isinstance(data.get("headers"), list):
        headers = list(data.get("headers") or [])
    if not rows and isinstance(data.get("rows"), list):
        rows = list(data.get("rows") or [])
    if data and (headers or rows):
        data = {
            "headers": headers,
            "rows": rows,
            "row_count": int(data.get("row_count") or len(rows) or 0),
            "col_count": int(
                data.get("col_count")
                or (len(headers) if headers else (len(rows[0]) if rows and isinstance(rows[0], list) else 0))
            ),
        }
    elif headers or rows:
        data = {
            "headers": headers,
            "rows": rows,
            "row_count": len(rows),
            "col_count": len(headers) if headers else (len(rows[0]) if rows and isinstance(rows[0], list) else 0),
        }
    else:
        data = {}
    return {
        "table_html": html,
        "table_data": data,
        "table_headers": headers,
        "table_rows": rows,
    }


def enrich_table_fields(result: Any, runtime: Optional[RuntimeBundle] = None) -> Dict[str, Any]:
    """Backfill table_html/table_data for table blocks from result -> chunk -> evidence.

    Presentation only: does not change score/ranking.
    """
    metadata = getattr(result, "metadata", None) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    direct = _normalize_table_payload(
        table_html=getattr(result, "table_html", None) or metadata.get("table_html"),
        table_data=getattr(result, "table_data", None) or metadata.get("table_data"),
        table_headers=getattr(result, "table_headers", None) or metadata.get("table_headers"),
        table_rows=getattr(result, "table_rows", None) or metadata.get("table_rows"),
    )
    if direct["table_html"] or direct["table_rows"] or direct["table_headers"]:
        return direct

    document_id = getattr(result, "document_id", "") or ""
    chunk_id = getattr(result, "chunk_id", "") or ""

    chunk = _chunk_cache_get(runtime, document_id, chunk_id)
    if chunk:
        from_chunk = _normalize_table_payload(
            table_html=chunk.get("table_html"),
            table_data=chunk.get("table_data"),
        )
        if from_chunk["table_html"] or from_chunk["table_rows"] or from_chunk["table_headers"]:
            return from_chunk

    evidence_ids = list(getattr(result, "evidence_ids", None) or metadata.get("evidence_ids") or [])
    store = getattr(runtime, "evidence_store", None) if runtime is not None else None
    if store is not None and document_id and evidence_ids:
        try:
            if hasattr(store, "get_many"):
                evidences = store.get_many(document_id, evidence_ids) or []
            else:
                evidences = []
                for eid in evidence_ids:
                    try:
                        evidences.append(store.get(document_id, eid))
                    except Exception:
                        continue
        except Exception:
            evidences = []
        for ev in evidences:
            if not isinstance(ev, dict):
                continue
            from_ev = _normalize_table_payload(
                table_html=ev.get("table_html"),
                table_data=ev.get("table_data"),
            )
            if from_ev["table_html"] or from_ev["table_rows"] or from_ev["table_headers"]:
                return from_ev

    return _normalize_table_payload()


def result_to_item(result: Any, rank: int, runtime: Optional[RuntimeBundle] = None) -> SearchResultItem:
    metadata = getattr(result, "metadata", None) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    document_id = getattr(result, "document_id", "") or ""
    pages = list(getattr(result, "pages", None) or [])
    section = _section_text(getattr(result, "section_path", None) or [])
    evidence_ids = list(getattr(result, "evidence_ids", None) or metadata.get("evidence_ids") or [])
    text = getattr(result, "text", "") or ""
    table_fields = enrich_table_fields(result, runtime)
    return SearchResultItem(
        rank=rank,
        score=float(getattr(result, "score", 0.0) or 0.0),
        document_id=document_id,
        company=getattr(result, "company", "") or "",
        section=section,
        pages=pages,
        page_labels=_page_labels(metadata),
        chunk_id=getattr(result, "chunk_id", "") or "",
        evidence_ids=evidence_ids,
        block_type=getattr(result, "block_type", "") or "",
        text=text,
        preview=_preview(text),
        table_html=table_fields.get("table_html") or "",
        table_data=table_fields.get("table_data") or {},
        table_headers=list(table_fields.get("table_headers") or []),
        table_rows=list(table_fields.get("table_rows") or []),
        citation=Citation(
            document_id=document_id,
            pages=pages,
            section=section,
            evidence_ids=evidence_ids,
        ),
    )


def extract_query_fact_terms(query: str) -> List[str]:
    terms: List[str] = []
    for term in CORE_FACT_TERMS:
        if term_matches(query, term) or term in query:
            terms.append(term)
    terms.extend(re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?%?", query or ""))
    unique: List[str] = []
    seen = set()
    for term in terms:
        key = term.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(key)
    return unique[:24]


def matched_terms(texts: Sequence[str], terms: Sequence[str]) -> List[str]:
    joined = "\n".join(texts)
    return [term for term in terms if term_matches(joined, term)]


def support_label(coverage: float, has_results: bool) -> str:
    if not has_results:
        return "unknown"
    if coverage >= 0.6:
        return "full_support"
    if coverage >= 0.3:
        return "partial_support"
    if coverage > 0:
        return "weak_support"
    return "unknown"


def build_followup_queries(query: str, unresolved: Sequence[str], max_rounds: int) -> List[str]:
    if max_rounds <= 0 or not unresolved:
        return []
    queries: List[str] = []
    raw = " ".join([query] + list(unresolved)[:8])
    queries.append(expand_query_with_aliases(raw))
    if max_rounds >= 2:
        queries.append(raw)
    # de-duplicate while preserving order
    return list(dict.fromkeys(q for q in queries if q and q.strip()))[:max_rounds]


def extract_routing(results: Sequence[Any], request: SearchRequest, runtime: RuntimeBundle) -> RoutingInfo:
    metadata_filters: Dict[str, str] = {}
    if request.document_id:
        metadata_filters["document_id"] = request.document_id
    if request.company:
        metadata_filters["company"] = request.company

    # Prefer explicit live router decision when available.
    try:
        runtime.retriever._refresh_routing_catalog()  # noqa: SLF001 - reuse production router
        decision = runtime.retriever._resolve_route(request.query, metadata_filters or None)  # noqa: SLF001
        company = request.company
        if decision.document_id and not company:
            for doc in runtime.vector_store.documents:
                doc_id = getattr(doc, "document_id", None) or (doc.get("document_id") if isinstance(doc, dict) else "")
                if doc_id == decision.document_id:
                    company = getattr(doc, "company", None) or (doc.get("company") if isinstance(doc, dict) else "") or company
                    break
        return RoutingInfo(
            status=decision.status,
            source=decision.source,
            document_id=decision.document_id,
            company=company,
            matched_name=decision.matched_name,
            candidate_document_ids=list(decision.candidate_document_ids or []),
        )
    except Exception:
        pass

    if results:
        first = results[0]
        metadata = getattr(first, "metadata", None) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        return RoutingInfo(
            status=str(metadata.get("routing_status") or ("matched" if request.document_id or request.company else "unknown")),
            source=str(metadata.get("routing_source") or ("document_id" if request.document_id else "company" if request.company else "query")),
            document_id=getattr(first, "document_id", None),
            company=getattr(first, "company", None),
            matched_name=metadata.get("matched_name"),
            candidate_document_ids=list(metadata.get("candidate_document_ids") or []),
        )

    if request.document_id:
        return RoutingInfo(status="matched", source="document_id", document_id=request.document_id, company=request.company)
    if request.company:
        return RoutingInfo(status="matched", source="company", company=request.company)
    return RoutingInfo(status="no_match", source="global_fallback")




def _claim_item_from_dict(data: dict) -> ClaimItem:
    citation = data.get("citation") or {}
    return ClaimItem(
        claim_id=str(data.get("claim_id") or ""),
        claim_text=str(data.get("claim_text") or ""),
        answer_relevance=str(data.get("answer_relevance") or "irrelevant"),
        risk_type=str(data.get("risk_type") or "other"),
        quantitative_facts=[str(x) for x in (data.get("quantitative_facts") or [])],
        entities=[str(x) for x in (data.get("entities") or [])],
        evidence_sentence=str(data.get("evidence_sentence") or ""),
        citation=ClaimCitation(
            document_id=str(citation.get("document_id") or ""),
            pages=list(citation.get("pages") or []),
            section=str(citation.get("section") or ""),
            chunk_id=str(citation.get("chunk_id") or ""),
            evidence_ids=[str(x) for x in (citation.get("evidence_ids") or [])],
        ),
        sufficiency=str(data.get("sufficiency") or "weak"),
        missing_facts=[str(x) for x in (data.get("missing_facts") or [])],
        support_reason=str(data.get("support_reason") or ""),
    )


def search(runtime: RuntimeBundle, request: SearchRequest) -> SearchResponse:
    import os

    profile = normalize_ranking_profile(
        getattr(request, "ranking_profile", None) or os.getenv("IPO_RAG_RANKING_PROFILE") or "default"
    )
    base_top_k = int(getattr(request, "top_k", None) or getattr(runtime.retriever.config, "top_k", 5) or 5)
    profile_cfg = build_retriever_config(profile=profile, top_k=base_top_k)
    old_cfg = runtime.retriever.config
    runtime.retriever.config = profile_cfg
    try:
        response = _search_with_profile(runtime, request)
        # pydantic v1/v2 compatible echo
        try:
            if hasattr(response, "model_copy"):
                return response.model_copy(update={"ranking_profile": profile})
            return response.copy(update={"ranking_profile": profile})
        except Exception:
            try:
                response.ranking_profile = profile
            except Exception:
                pass
            return response
    finally:
        runtime.retriever.config = old_cfg


def _search_with_profile(runtime: RuntimeBundle, request: SearchRequest) -> SearchResponse:
    started = time.perf_counter()
    warnings: List[str] = []

    metadata_filters: Dict[str, str] = {}
    if request.document_id:
        metadata_filters["document_id"] = request.document_id
    if request.company:
        metadata_filters["company"] = request.company

    initial_results = runtime.retriever.search(
        request.query,
        layer="all",
        top_k=request.top_k,
        metadata_filters=metadata_filters or None,
    )
    required_terms = extract_query_fact_terms(request.query)
    initial_texts = [getattr(item, "text", "") or "" for item in initial_results]
    initial_hits = matched_terms(initial_texts, required_terms)
    initial_unresolved = [term for term in required_terms if term not in initial_hits]
    coverage = (len(initial_hits) / len(required_terms)) if required_terms else (1.0 if initial_results else 0.0)
    initial_label = support_label(coverage, bool(initial_results))

    claim_enabled = bool(getattr(request, "enable_claim_analysis", True))
    claim_records = []
    packaged = {
        "claims": [],
        "accepted_claims": [],
        "partial_claims": [],
        "rejected_claims": [],
        "claim_level_support": "disabled",
        "claim_records": [],
        "partial_records": [],
    }
    if claim_enabled:
        try:
            claim_records = extract_claims(request.query, initial_results, llm_enabled=None)
            packaged = package_claims(claim_records)
        except Exception as exc:  # pragma: no cover
            warnings.append(f"claim analysis failed: {exc}")
            claim_records = []
            packaged = {
                "claims": [],
                "accepted_claims": [],
                "partial_claims": [],
                "rejected_claims": [],
                "claim_level_support": "insufficient",
                "claim_records": [],
                "partial_records": [],
            }

    followup_queries: List[str] = []
    followup_raw: List[Any] = []
    recovered: List[str] = []
    final_hits = list(initial_hits)
    final_unresolved = list(initial_unresolved)
    final_label = initial_label
    followup_triggered_by_claims = False

    should_followup = False
    if request.enable_followup:
        if claim_enabled:
            followup_triggered_by_claims = claims_need_followup(packaged.get("claim_records") or claim_records)
            should_followup = followup_triggered_by_claims or initial_label in {"partial_support", "weak_support", "unknown"}
        else:
            should_followup = initial_label in {"partial_support", "weak_support", "unknown"}
    else:
        warnings.append("followup disabled by request")

    if should_followup:
        if claim_enabled and (packaged.get("claim_records") or claim_records):
            followup_queries = build_claim_followup_queries(
                request.query,
                packaged.get("claim_records") or claim_records,
                max_rounds=request.max_followup_rounds,
            )
            if not followup_queries:
                followup_queries = build_followup_queries(
                    request.query,
                    initial_unresolved or required_terms,
                    request.max_followup_rounds,
                )
        else:
            followup_queries = build_followup_queries(
                request.query,
                initial_unresolved or required_terms,
                request.max_followup_rounds,
            )

        seen_chunk_ids = {getattr(item, "chunk_id", "") for item in initial_results}
        for query in followup_queries:
            results = runtime.retriever.search(
                query,
                layer="all",
                top_k=request.top_k,
                metadata_filters=metadata_filters or None,
            )
            for result in results:
                chunk_id = getattr(result, "chunk_id", "")
                if chunk_id and chunk_id in seen_chunk_ids:
                    continue
                if chunk_id:
                    seen_chunk_ids.add(chunk_id)
                followup_raw.append(result)

        all_results_for_claims = list(initial_results) + list(followup_raw)
        all_texts = initial_texts + [getattr(item, "text", "") or "" for item in followup_raw]
        final_hits = matched_terms(all_texts, required_terms)
        final_unresolved = [term for term in required_terms if term not in final_hits]
        recovered = [term for term in final_hits if term not in initial_hits]
        final_coverage = (len(final_hits) / len(required_terms)) if required_terms else (1.0 if all_results_for_claims else 0.0)
        final_label = support_label(final_coverage, bool(all_results_for_claims))

        if claim_enabled:
            try:
                claim_records = extract_claims(request.query, all_results_for_claims, llm_enabled=None)
                packaged = package_claims(claim_records)
            except Exception as exc:  # pragma: no cover
                warnings.append(f"claim re-analysis failed: {exc}")

    merged: List[Any] = []
    seen = set()
    for item in list(initial_results) + list(followup_raw):
        key = getattr(item, "chunk_id", None) or id(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    merged = merged[: request.top_k]

    result_items = [result_to_item(item, rank=index, runtime=runtime) for index, item in enumerate(merged, start=1)]
    followup_items = [result_to_item(item, rank=index, runtime=runtime) for index, item in enumerate(followup_raw, start=1)]
    routing = extract_routing(initial_results or merged, request, runtime)

    if not result_items:
        warnings.append("no retrieval results")

    if not claim_enabled:
        claim_level_support = "disabled"
        claim_items: List[ClaimItem] = []
        accepted_items: List[ClaimItem] = []
        partial_items: List[ClaimItem] = []
        rejected_items: List[ClaimItem] = []
        followup_triggered_by_claims = False
    else:
        claim_level_support = str(packaged.get("claim_level_support") or "insufficient")
        claim_items = [_claim_item_from_dict(x) for x in packaged.get("claims") or []]
        accepted_items = [_claim_item_from_dict(x) for x in packaged.get("accepted_claims") or []]
        partial_items = [_claim_item_from_dict(x) for x in packaged.get("partial_claims") or []]
        rejected_items = [_claim_item_from_dict(x) for x in packaged.get("rejected_claims") or []]

    latency_ms = (time.perf_counter() - started) * 1000.0
    return SearchResponse(
        ranking_profile=getattr(request, "ranking_profile", "default") or "default",
        query=request.query,
        routing=routing,
        results=result_items,
        evidence_chain=EvidenceChainInfo(
            enabled=bool(request.enable_followup),
            initial_support_label=initial_label,
            final_support_label=final_label,
            followup_queries=followup_queries,
            followup_results=followup_items,
            missing_facts=list(initial_unresolved),
            recovered_facts=recovered,
            unresolved_missing_facts=list(final_unresolved),
        ),
        latency_ms=round(latency_ms, 2),
        warnings=warnings,
        claims=claim_items,
        accepted_claims=accepted_items,
        partial_claims=partial_items,
        rejected_claims=rejected_items,
        claim_level_support=claim_level_support,
        followup_triggered_by_claims=bool(followup_triggered_by_claims),
    )


def health(runtime: RuntimeBundle) -> HealthResponse:
    stats = runtime.vector_store.get_stats() if hasattr(runtime.vector_store, "get_stats") else {}
    vector_count = int(stats.get("total_vectors") or runtime.vector_count or len(getattr(runtime.vector_store, "documents", []) or []))
    return HealthResponse(
        status="ok",
        vector_count=vector_count,
        model_loaded=bool(runtime.model_loaded),
        version=runtime.version,
        readiness_note=READINESS_NOTE,
    )


def list_documents(runtime: RuntimeBundle) -> DocumentsResponse:
    counter: Counter[str] = Counter()
    company_map: Dict[str, str] = {}
    for doc in getattr(runtime.vector_store, "documents", []) or []:
        if isinstance(doc, dict):
            document_id = str(doc.get("document_id") or "")
            company = str(doc.get("company") or "")
        else:
            document_id = str(getattr(doc, "document_id", "") or "")
            company = str(getattr(doc, "company", "") or "")
        if not document_id:
            continue
        counter[document_id] += 1
        if company and document_id not in company_map:
            company_map[document_id] = company
    documents = [
        DocumentSummary(document_id=doc_id, company=company_map.get(doc_id, ""), vector_count=count)
        for doc_id, count in sorted(counter.items())
    ]
    return DocumentsResponse(count=len(documents), documents=documents)


def get_evidences(runtime: RuntimeBundle, document_id: str, evidence_ids: Sequence[str]) -> EvidenceGetResponse:
    evidences = runtime.evidence_store.get_many(document_id, list(evidence_ids or []))
    return EvidenceGetResponse(document_id=document_id, evidences=evidences)
