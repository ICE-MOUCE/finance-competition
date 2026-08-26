from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx


class RagClientError(RuntimeError):
    pass


@dataclass
class RagClient:
    base_url: str
    timeout_s: float = 30.0
    ranking_profile: str = 'hge'

    def _url(self, path: str) -> str:
        return urljoin(self.base_url.rstrip('/') + '/', path.lstrip('/'))

    def health(self) -> dict[str, Any]:
        try:
            response = httpx.get(self._url('/health'), timeout=self.timeout_s)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise RagClientError(f'RAG health failed: {exc}') from exc

    def documents(self) -> dict[str, Any]:
        try:
            response = httpx.get(self._url('/v1/documents'), timeout=self.timeout_s)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise RagClientError(f'RAG documents failed: {exc}') from exc

    def search(
        self,
        query: str,
        *,
        company: str | None = None,
        document_id: str | None = None,
        top_k: int = 8,
        enable_followup: bool = True,
        ranking_profile: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            'query': query,
            'top_k': top_k,
            'enable_followup': enable_followup,
            'enable_claim_analysis': True,
            'ranking_profile': ranking_profile or self.ranking_profile,
        }
        if company:
            payload['company'] = company
        if document_id:
            payload['document_id'] = document_id
        try:
            response = httpx.post(
                self._url('/v1/search'),
                json=payload,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise RagClientError(f'RAG search failed: {exc}') from exc

    def get_evidence(self, document_id: str, evidence_ids: list[str]) -> list[dict[str, Any]]:
        if not document_id or not evidence_ids:
            return []
        try:
            response = httpx.post(
                self._url('/v1/evidence/get'),
                json={'document_id': document_id, 'evidence_ids': evidence_ids},
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            payload = response.json()
            return list(payload.get('evidences') or [])
        except Exception:
            return []
