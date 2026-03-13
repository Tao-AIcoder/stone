"""
core/model_router.py - LLM routing layer for STONE (默行者)

Routes requests to the appropriate model based on task type, privacy mode,
and token count. Supports Ollama (local), 智谱 GLM, and 阿里云通义.
Implements fallback logic when the primary model fails.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings
from models.errors import ModelError, ModelQuotaError, ModelTimeoutError

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

OLLAMA_TIMEOUT = 120.0          # seconds
CLOUD_TIMEOUT = 60.0
MAX_TOKENS_DEFAULT = 2048

# Models
MODEL_GLM = "glm-4-plus"
MODEL_QWEN_CODER = "qwen-coder-plus"
MODEL_LOCAL = "qwen2.5:14b"


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate: ~4 chars per token for Chinese/English mixed text."""
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    return total_chars // 4


def _select_model(
    task_type: str,
    privacy_mode: str,
    privacy_sensitive: bool,
    token_estimate: int,
) -> str:
    """
    Decide which model to use.

    Rules:
    - privacy_mode=strict OR privacy_sensitive=True  -> always local
    - privacy_mode=performance                        -> prefer cloud
    - privacy_mode=balanced (default):
        - code task                                   -> qwen-coder-plus
        - heavy token load (>4000)                    -> local (cost saving)
        - else chinese/chat/analysis                  -> glm-4-plus
        - general                                     -> local
    """
    if privacy_mode == "strict" or privacy_sensitive:
        return MODEL_LOCAL

    if privacy_mode == "performance":
        if task_type == "code":
            return MODEL_QWEN_CODER
        return MODEL_GLM

    # balanced
    if task_type == "code":
        return MODEL_QWEN_CODER
    if token_estimate > 4000:
        return MODEL_LOCAL
    if task_type in ("chat", "analysis", "chinese"):
        return MODEL_GLM
    return MODEL_LOCAL


class ModelRouter:
    """
    Thin async router that wraps three LLM backends:
    - Ollama  (local, via httpx)
    - 智谱 GLM  (cloud, via zhipuai SDK)
    - 阿里云通义 (cloud, via dashscope SDK)
    """

    def __init__(self) -> None:
        self._http_client: httpx.AsyncClient | None = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=OLLAMA_TIMEOUT)
        return self._http_client

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    # ── Public API ────────────────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict[str, Any]],
        task_type: str = "chat",
        user_id: str = "default_user",
        privacy_sensitive: bool = False,
        model_override: str | None = None,
    ) -> str:
        """
        Route the chat request to the best-fit model and return the response text.
        Falls back to local model if the primary model fails.
        """
        privacy_mode = settings.privacy_mode
        token_estimate = _estimate_tokens(messages)

        primary = model_override or _select_model(
            task_type=task_type,
            privacy_mode=privacy_mode,
            privacy_sensitive=privacy_sensitive,
            token_estimate=token_estimate,
        )

        logger.debug(
            "ModelRouter: user=%s task=%s tokens≈%d selected=%s",
            user_id,
            task_type,
            token_estimate,
            primary,
        )

        try:
            return await self._call_model(primary, messages)
        except (ModelTimeoutError, ModelQuotaError, ModelError) as exc:
            logger.warning(
                "Primary model %s failed (%s), falling back to local",
                primary,
                exc.code,
            )
            if primary == MODEL_LOCAL:
                raise  # no further fallback
            try:
                return await self._call_model(MODEL_LOCAL, messages)
            except Exception as fallback_exc:
                logger.error("Fallback to local model also failed: %s", fallback_exc)
                raise ModelError(
                    message=f"所有模型均不可用。最后错误：{fallback_exc}",
                    model_id="fallback",
                ) from fallback_exc

    # ── Backend Dispatchers ────────────────────────────────────────────────────

    async def _call_model(self, model_id: str, messages: list[dict[str, Any]]) -> str:
        if model_id == MODEL_LOCAL or "ollama" in model_id.lower():
            return await self._call_ollama(model_id, messages)
        if model_id.startswith("glm"):
            return await self._call_zhipuai(model_id, messages)
        if model_id.startswith("qwen"):
            return await self._call_dashscope(model_id, messages)
        # Unknown model – try ollama as generic fallback
        logger.warning("Unknown model_id %r, attempting via Ollama", model_id)
        return await self._call_ollama(model_id, messages)

    # ── Ollama ─────────────────────────────────────────────────────────────────

    async def _call_ollama(self, model_id: str, messages: list[dict[str, Any]]) -> str:
        client = await self._get_http()
        url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": model_id,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": MAX_TOKENS_DEFAULT},
        }
        try:
            resp = await client.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(model_id=model_id, timeout_seconds=OLLAMA_TIMEOUT) from exc
        except httpx.RequestError as exc:
            raise ModelError(
                message=f"Ollama 连接失败：{exc}",
                model_id=model_id,
            ) from exc

        if resp.status_code != 200:
            raise ModelError(
                message=f"Ollama 返回错误 HTTP {resp.status_code}: {resp.text[:200]}",
                model_id=model_id,
            )

        data = resp.json()
        content: str = data.get("message", {}).get("content", "")
        if not content:
            raise ModelError(message="Ollama 返回空内容", model_id=model_id)
        return content

    # ── 智谱 GLM ──────────────────────────────────────────────────────────────

    async def _call_zhipuai(self, model_id: str, messages: list[dict[str, Any]]) -> str:
        if not settings.zhipuai_api_key:
            raise ModelError(message="ZHIPUAI_API_KEY 未配置", model_id=model_id)
        try:
            from zhipuai import ZhipuAI  # type: ignore[import]
        except ImportError as exc:
            raise ModelError(message="zhipuai SDK 未安装", model_id=model_id) from exc

        try:
            client = ZhipuAI(api_key=settings.zhipuai_api_key)
            # The zhipuai SDK is synchronous; run in thread pool to avoid blocking
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model_id,
                    messages=messages,
                    max_tokens=MAX_TOKENS_DEFAULT,
                ),
            )
            content = response.choices[0].message.content
            return content or ""
        except Exception as exc:
            err_str = str(exc).lower()
            if "quota" in err_str or "limit" in err_str or "1302" in err_str:
                raise ModelQuotaError(model_id=model_id) from exc
            if "timeout" in err_str:
                raise ModelTimeoutError(model_id=model_id, timeout_seconds=CLOUD_TIMEOUT) from exc
            raise ModelError(
                message=f"智谱 API 错误：{exc}",
                model_id=model_id,
            ) from exc

    # ── 阿里云通义 (DashScope) ────────────────────────────────────────────────

    async def _call_dashscope(self, model_id: str, messages: list[dict[str, Any]]) -> str:
        if not settings.dashscope_api_key:
            raise ModelError(message="DASHSCOPE_API_KEY 未配置", model_id=model_id)
        try:
            import dashscope  # type: ignore[import]
            from dashscope import Generation  # type: ignore[import]
        except ImportError as exc:
            raise ModelError(message="dashscope SDK 未安装", model_id=model_id) from exc

        dashscope.api_key = settings.dashscope_api_key

        try:
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: Generation.call(
                    model=model_id,
                    messages=messages,
                    result_format="message",
                    max_tokens=MAX_TOKENS_DEFAULT,
                ),
            )
            if response.status_code != 200:
                if response.status_code in (429, 403):
                    raise ModelQuotaError(model_id=model_id)
                raise ModelError(
                    message=f"DashScope 错误 {response.status_code}: {response.message}",
                    model_id=model_id,
                )
            content = response.output.choices[0].message.content
            return content or ""
        except (ModelError, ModelQuotaError):
            raise
        except Exception as exc:
            err_str = str(exc).lower()
            if "timeout" in err_str:
                raise ModelTimeoutError(model_id=model_id, timeout_seconds=CLOUD_TIMEOUT) from exc
            raise ModelError(
                message=f"DashScope API 错误：{exc}",
                model_id=model_id,
            ) from exc


__all__ = ["ModelRouter"]
