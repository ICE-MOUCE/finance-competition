from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import LLMClient
from .deepseek import DeepSeekClient
from .doubao import DoubaoClient


class OfflineLLMClient:
    """Deterministic fallback so the collaboration room stays usable offline."""

    provider = "offline"
    model = "offline-synthesizer"

    def chat(self, messages, *, temperature: float = 0.2, max_tokens: int = 1800):
        from .base import LLMResponse

        user = next((item.content for item in reversed(messages) if item.role == "user"), "")
        # Keep offline output short and structured; never dump the whole prompt.
        company = "目标公司"
        for line in user.splitlines():
            if "对 " in line and "做" in line:
                company = line.strip("【】 ")
                break
        content = (
            "## 结论摘要\n"
            f"【离线合成】外部 LLM 暂不可用，已基于已落库结论生成 {company} 的可审计降级草案。\n\n"
            "## 关键发现\n"
            "- 仅使用分析阶段 claims/evidence/prediction\n"
            "- 未调用外部模型，不新增无证据事实\n"
            "- 概率与规则分只可引用系统结构化结果\n\n"
            "## 主要风险\n"
            "- 优先复核 accepted/revised 且 severity 高的条目\n"
            "- 对证据不足项标记为数据缺口\n\n"
            "## 建议\n"
            "- 配置有效 API Key 后重跑会诊\n"
            "- 补齐关键证据原文后再做最终决议\n\n"
            "## 证据引用\n"
            "- 沿用分析库 evidence_id，不伪造引用"
        )
        return LLMResponse(content=content, provider=self.provider, model=self.model)


@lru_cache(maxsize=8)
def get_llm_client(provider: str) -> LLMClient:
    name = (provider or "deepseek").strip().lower()
    if name == "deepseek":
        if not settings.deepseek_api_key:
            return OfflineLLMClient()
        return DeepSeekClient(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
        )
    if name in {"doubao", "volc", "volcengine"}:
        # Volcengine Ark chat/completions requires an API Key (Bearer),
        # not IAM AccessKey/SecretKey. Treat AK/SK-only as not ready.
        if not settings.doubao_api_key:
            return OfflineLLMClient()
        return DoubaoClient(
            api_key=settings.doubao_api_key,
            access_key_id=settings.doubao_access_key_id,
            secret_access_key=settings.doubao_secret_access_key,
            model=settings.doubao_model,
            base_url=settings.doubao_base_url,
        )
    if name == "offline":
        return OfflineLLMClient()
    raise ValueError(f"unsupported LLM provider: {provider}")


def llm_status() -> dict:
    return {
        "deepseek": {
            "configured": bool(settings.deepseek_api_key),
            "model": settings.deepseek_model,
            "ready": bool(settings.deepseek_api_key),
        },
        "doubao": {
            # Ready only when Ark API key exists. AK/SK alone cannot call chat API.
            "configured": bool(settings.doubao_api_key),
            "model": settings.doubao_model,
            "ready": bool(settings.doubao_api_key),
            "has_api_key": bool(settings.doubao_api_key),
            "has_ak_sk": bool(settings.doubao_access_key_id and settings.doubao_secret_access_key),
            "note": (
                None
                if settings.doubao_api_key
                else "需要 DOUBAO_API_KEY（方舟 API Key）；仅有 AK/SK 无法调用 chat/completions"
            ),
        },
    }

