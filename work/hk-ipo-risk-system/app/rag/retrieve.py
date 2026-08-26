from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import EvidenceObject
from ..parser import ParseResult
from .client import RagClient, RagClientError
from .mapper import DEFAULT_EXPERT_QUERIES, map_search_response


@dataclass
class RetrievalBundle:
    evidence: list[EvidenceObject]
    queries: dict[str, str]
    warnings: list[str] = field(default_factory=list)
    health: dict[str, Any] = field(default_factory=dict)
    documents: list[dict[str, Any]] = field(default_factory=list)
    routed_document_id: str | None = None
    raw_responses: list[dict[str, Any]] = field(default_factory=list)


class RagRetriever:
    def __init__(self, client: RagClient, top_k: int = 8):
        self.client = client
        self.top_k = top_k

    @staticmethod
    def _match_document_id(
        documents: list[dict[str, Any]],
        *,
        company_name: str | None,
        company_id: str | None,
        document_id: str | None,
    ) -> str | None:
        ids = [str(item.get("document_id") or "") for item in documents]
        if document_id and document_id in ids:
            return document_id
        needles = [str(item).strip() for item in (company_name, company_id) if str(item or "").strip()]
        for item in documents:
            blob = f"{item.get('document_id') or ''} {item.get('company') or ''}"
            if any(needle and needle in blob for needle in needles):
                return str(item.get("document_id") or "") or None
        return None

    def collect(
        self,
        *,
        company_id: str,
        company_name: str | None = None,
        document_id: str | None = None,
        extra_queries: dict[str, str] | None = None,
    ) -> RetrievalBundle:
        warnings: list[str] = []
        health: dict[str, Any] = {}
        documents: list[dict[str, Any]] = []
        try:
            health = self.client.health()
        except RagClientError as exc:
            warnings.append(str(exc))
        try:
            payload = self.client.documents()
            documents = list(payload.get("documents") or [])
        except RagClientError as exc:
            warnings.append(str(exc))

        queries = dict(DEFAULT_EXPERT_QUERIES)
        if extra_queries:
            queries.update(extra_queries)

        matched_document_id = self._match_document_id(
            documents,
            company_name=company_name,
            company_id=company_id,
            document_id=document_id,
        )
        if (company_name or company_id or document_id) and not matched_document_id:
            warnings.append(
                f"RAG 索引未覆盖当前公司/文档（company={company_name or company_id}, document_id={document_id}），已回退解析库，避免串用其他招股书证据。"
            )
            return RetrievalBundle(
                evidence=[],
                queries=queries,
                warnings=warnings,
                health=health,
                documents=documents,
                routed_document_id=None,
            )

        routed_document_id = matched_document_id
        evidence: list[EvidenceObject] = []
        seen: set[str] = set()
        raw_responses: list[dict[str, Any]] = []
        for agent_name, query in queries.items():
            try:
                response = self.client.search(
                    query,
                    company=company_name or company_id,
                    document_id=routed_document_id,
                    top_k=self.top_k,
                )
            except RagClientError as exc:
                warnings.append(f"{agent_name}: {exc}")
                continue
            raw_responses.append({"agent_name": agent_name, "query": query, "response": response})
            routing = response.get("routing") or {}
            routed_document_id = routed_document_id or routing.get("document_id")
            warnings.extend(str(item) for item in (response.get("warnings") or []) if item)
            source_ids: list[str] = []
            for result in response.get("results") or []:
                source_ids.extend(str(item) for item in (result.get("evidence_ids") or []) if item)
            source_details = []
            if routed_document_id and source_ids:
                source_details = self.client.get_evidence(str(routed_document_id), list(dict.fromkeys(source_ids)))
            mapped = map_search_response(
                response,
                company_id=company_id,
                source_evidences=source_details,
            )
            for item in mapped:
                if item.evidence_id in seen:
                    continue
                seen.add(item.evidence_id)
                evidence.append(item)
        return RetrievalBundle(
            evidence=evidence,
            queries=queries,
            warnings=warnings,
            health=health,
            documents=documents,
            routed_document_id=routed_document_id,
            raw_responses=raw_responses,
        )


def merge_parse_with_retrieval(
    parsed: ParseResult,
    retrieved: list[EvidenceObject],
    *,
    prefer_retrieval: bool,
    max_evidence: int,
) -> ParseResult:
    merged: list[EvidenceObject] = []
    seen: set[str] = set()
    if prefer_retrieval and retrieved:
        source = retrieved
    else:
        source = list(parsed.evidence)
        existing = {row.evidence_id for row in source}
        for item in retrieved:
            if item.evidence_id not in existing:
                source.append(item)
                existing.add(item.evidence_id)
    for item in source:
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        merged.append(item)
        if len(merged) >= max_evidence:
            break
    metadata = dict(parsed.metadata)
    metadata["retrieved_evidence_count"] = len(retrieved)
    metadata["working_evidence_count"] = len(merged)
    metadata["prefer_retrieval"] = bool(prefer_retrieval and retrieved)
    data_gaps = list(parsed.data_gaps)
    if prefer_retrieval and retrieved:
        data_gaps.append("专家尽调仅使用 RAG 检索证据，未把整本招股书塞入上下文。")
    elif not retrieved:
        data_gaps.append("RAG 未返回可用证据，已回退解析库。")
    return ParseResult(evidence=merged, metadata=metadata, data_gaps=data_gaps)
