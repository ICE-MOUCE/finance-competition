"""FastAPI application for Thin RAG API V1."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from src.api import deps
from src.api.schemas import (
    DocumentsResponse,
    EvidenceGetRequest,
    EvidenceGetResponse,
    HealthResponse,
    SearchRequest,
    SearchResponse,
)
from src.api.service import get_evidences, health, list_documents, search

API_DESCRIPTION = (
    "IPO-Risk-Agent Thin RAG API V1. "
    "复用 LayeredRetriever / Company Routing / term normalization。"
    "返回可审计 evidence，不生成最终法律意见。"
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="IPO-Risk-Agent Thin RAG API",
        version="v1",
        description=API_DESCRIPTION,
    )

    @app.get("/health", response_model=HealthResponse)
    def health_endpoint() -> HealthResponse:
        runtime = deps.get_runtime()
        return health(runtime)

    @app.post("/v1/search", response_model=SearchResponse)
    def search_endpoint(request: SearchRequest) -> SearchResponse:
        if not request.query or not request.query.strip():
            raise HTTPException(status_code=422, detail="query must not be empty")
        runtime = deps.get_runtime()
        return search(runtime, request)

    @app.get("/v1/documents", response_model=DocumentsResponse)
    def documents_endpoint() -> DocumentsResponse:
        runtime = deps.get_runtime()
        return list_documents(runtime)

    @app.post("/v1/evidence/get", response_model=EvidenceGetResponse)
    def evidence_get_endpoint(request: EvidenceGetRequest) -> EvidenceGetResponse:
        if not request.document_id.strip():
            raise HTTPException(status_code=422, detail="document_id must not be empty")
        runtime = deps.get_runtime()
        return get_evidences(runtime, request.document_id, request.evidence_ids)

    return app


app = create_app()
