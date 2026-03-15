"""LLM 客户端与路由器。"""
from __future__ import annotations

import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

import httpx

from .config import (
    LLMProviderConfig,
    LLMProviderType,
    is_openai_compatible_provider_type,
    resolve_provider_base_url,
)
from .providers import AnthropicProvider, OpenAICompatibleProvider, ProviderResponse, QwenProvider


class LLMClient:
    """统一 LLM 客户端。"""

    def __init__(self, config: LLMProviderConfig):
        self.config = config
        self.base_url = config.base_url
        self.api_key = config.api_key
        self.model = config.model
        self.timeout = config.timeout
        self.provider = self._build_provider()

    def _build_provider(self):
        """根据配置构建对应 Provider 实现。"""
        if self.config.provider_type == LLMProviderType.ANTHROPIC:
            return AnthropicProvider(api_key=self.api_key, model=self.model, timeout=self.timeout)
        if self.config.provider_type == LLMProviderType.QWEN:
            # Qwen 使用专用 Provider，保留其官方兼容网关默认值逻辑。
            return QwenProvider(
                base_url=resolve_provider_base_url(self.config.provider_type, self.base_url),
                api_key=self.api_key,
                model=self.model,
                timeout=self.timeout,
            )
        if is_openai_compatible_provider_type(self.config.provider_type):
            # 所有 OpenAI 兼容协议统一走该分支。
            return OpenAICompatibleProvider(
                base_url=resolve_provider_base_url(self.config.provider_type, self.base_url),
                api_key=self.api_key,
                model=self.model,
                timeout=self.timeout,
            )
        return OpenAICompatibleProvider(base_url=self.base_url, api_key=self.api_key, model=self.model, timeout=self.timeout)

    async def chat_with_meta(self, messages: List[Dict[str, str]], **kwargs: Any) -> ProviderResponse:
        """返回带 token 元数据的响应。"""
        return await self.provider.chat(messages, **kwargs)

    async def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        """发送聊天请求，仅返回文本。"""
        response = await self.chat_with_meta(messages, **kwargs)
        return response.content

    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs: Any) -> AsyncGenerator[str, None]:
        """流式聊天（当前为非流式兼容实现）。"""
        content = await self.chat(messages, **kwargs)
        yield content


class LLMRouter:
    """LLM 路由器，支持重试、超时与 fallback。"""

    def __init__(
        self,
        clients: Dict[str, LLMClient],
        default_client_name: str = "openai",
        call_observer: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        self.clients = clients
        self.default_client_name = default_client_name
        self.fallback_order = list(clients.keys())
        self.call_observer = call_observer

    def get_client(self, name: Optional[str] = None) -> Optional[LLMClient]:
        """获取指定客户端。"""
        client_name = name or self.default_client_name
        return self.clients.get(client_name)

    def get_enabled_clients(self) -> List[LLMClient]:
        """获取所有启用客户端。"""
        return list(self.clients.values())

    async def _notify_call_observer(self, payload: Dict[str, Any]) -> None:
        """记录调用日志，异常不影响主流程。"""
        if not self.call_observer:
            return
        try:
            result = self.call_observer(payload)
            if hasattr(result, "__await__"):
                await result
        except Exception:
            return

    @staticmethod
    def _extract_error_code(error: Exception) -> str:
        """把异常映射成稳定错误码。"""
        if isinstance(error, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TimeoutException, TimeoutError)):
            return "AI_TIMEOUT"
        if isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code if error.response is not None else 0
            return f"AI_HTTP_{status_code}"
        if isinstance(error, httpx.RequestError):
            return "AI_NETWORK_ERROR"
        if isinstance(error, ValueError):
            return "AI_VALIDATION_ERROR"
        if isinstance(error, RuntimeError):
            return "AI_RUNTIME_ERROR"
        return "AI_UNKNOWN_ERROR"

    @staticmethod
    def _build_prompt_preview(messages: List[Dict[str, str]]) -> str:
        if not messages:
            return ""
        return str(messages[-1].get("content", ""))[:200]

    async def _chat_with_client_once(
        self,
        client_name: str,
        client: LLMClient,
        messages: List[Dict[str, str]],
        source: str,
        endpoint: str,
        task_id: Optional[str],
        attempt: int,
        **kwargs: Any,
    ) -> ProviderResponse:
        started = time.perf_counter()
        prompt_preview = self._build_prompt_preview(messages)
        try:
            response = await client.chat_with_meta(messages, **kwargs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            await self._notify_call_observer(
                {
                    "provider_name": client_name,
                    "model": client.model,
                    "source": source,
                    "endpoint": endpoint,
                    "task_id": task_id,
                    "prompt_preview": prompt_preview,
                    "response_preview": response.content[:200],
                    "status": "success",
                    "error_code": "",
                    "error_message": "",
                    "latency_ms": latency_ms,
                    "request_tokens": response.request_tokens,
                    "response_tokens": response.response_tokens,
                    "attempt": attempt,
                }
            )
            return response
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            await self._notify_call_observer(
                {
                    "provider_name": client_name,
                    "model": client.model,
                    "source": source,
                    "endpoint": endpoint,
                    "task_id": task_id,
                    "prompt_preview": prompt_preview,
                    "response_preview": "",
                    "status": "error",
                    "error_code": self._extract_error_code(exc),
                    "error_message": str(exc)[:300],
                    "latency_ms": latency_ms,
                    "request_tokens": None,
                    "response_tokens": None,
                    "attempt": attempt,
                }
            )
            raise

    async def _chat_with_retry(
        self,
        client_name: str,
        client: LLMClient,
        messages: List[Dict[str, str]],
        source: str,
        endpoint: str,
        task_id: Optional[str],
        **kwargs: Any,
    ) -> ProviderResponse:
        max_retries = max(0, int(client.config.max_retries or 0))
        last_error: Exception | None = None
        for attempt in range(1, max_retries + 2):
            try:
                return await self._chat_with_client_once(
                    client_name,
                    client,
                    messages,
                    source,
                    endpoint,
                    task_id,
                    attempt,
                    **kwargs,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt > max_retries:
                    break
        if last_error:
            raise last_error
        raise RuntimeError("LLM 请求失败")

    def _build_candidate_order(self, provider: Optional[str]) -> list[str]:
        """构建路由候选顺序：指定 -> 默认 -> 其他。"""
        ordered: list[str] = []

        def add(name: Optional[str]) -> None:
            if name and name in self.clients and name not in ordered:
                ordered.append(name)

        add(provider)
        add(self.default_client_name)
        for name in self.fallback_order:
            add(name)
        for name in self.clients.keys():
            add(name)
        return ordered

    async def chat(self, messages: List[Dict[str, str]], provider: Optional[str] = None, **kwargs: Any) -> str:
        """发送聊天请求（重试 + fallback）。"""
        source = str(kwargs.pop("_source", "runtime"))
        endpoint = str(kwargs.pop("_endpoint", "chat"))
        task_id_value = kwargs.pop("_task_id", None)
        task_id = str(task_id_value) if task_id_value else None

        candidate_order = self._build_candidate_order(provider)
        if not candidate_order:
            raise RuntimeError("当前没有可用 LLM Provider")

        last_error: Exception | None = None
        for client_name in candidate_order:
            client = self.clients.get(client_name)
            if not client:
                continue
            try:
                response = await self._chat_with_retry(
                    client_name,
                    client,
                    messages,
                    source,
                    endpoint,
                    task_id,
                    **kwargs,
                )
                return response.content
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

        if last_error:
            raise RuntimeError(f"所有 LLM Provider 都不可用: {last_error}") from last_error
        raise RuntimeError("所有 LLM Provider 都不可用")

    def set_default(self, name: str) -> bool:
        """设置默认 Provider。"""
        if name in self.clients:
            self.default_client_name = name
            return True
        return False
