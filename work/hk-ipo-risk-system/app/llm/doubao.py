from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .base import ChatMessage, LLMResponse


class DoubaoClient:
    """Volcengine Ark OpenAI-compatible client for Doubao models.

    Prefer DOUBAO_API_KEY (Ark API Key). Access Key / Secret are retained for
    ops metadata and future signed OpenAPI integrations.
    """

    provider = "doubao"

    def __init__(
        self,
        api_key: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        model: str = "doubao-pro-32k",
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        timeout: int = 90,
    ):
        self.api_key = (api_key or "").strip() or None
        self.access_key_id = (access_key_id or "").strip() or None
        self.secret_access_key = (secret_access_key or "").strip() or None
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if not self.api_key and not (self.access_key_id and self.secret_access_key):
            raise ValueError("Doubao requires DOUBAO_API_KEY or AK/SK pair")

    def _auth_header(self) -> str:
        if self.api_key:
            return f"Bearer {self.api_key}"
        # Fallback used by some internal Ark setups that accept secret as bearer.
        return f"Bearer {self.secret_access_key}"

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1800,
    ) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": self._auth_header(),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Doubao HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Doubao network error: {exc.reason}") from exc

        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage") or {}
        return LLMResponse(
            content=content,
            provider=self.provider,
            model=body.get("model", self.model),
            usage=usage,
            raw=body,
        )
