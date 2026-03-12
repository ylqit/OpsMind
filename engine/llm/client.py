"""
LLM 客户端模块
支持多个 LLM Provider 的统一调用接口
"""
import time

import httpx
from typing import Dict, Any, List, Optional, AsyncGenerator, Callable
from .config import LLMProviderConfig, LLMProviderType


class LLMClient:
    """
    LLM 客户端

    提供统一的 LLM 调用接口，支持：
    - OpenAI 兼容 API
    - Anthropic API
    - 自定义 API
    """

    def __init__(self, config: LLMProviderConfig):
        self.config = config
        self.base_url = config.base_url
        self.api_key = config.api_key
        self.model = config.model
        self.timeout = config.timeout

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        发送聊天请求

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            **kwargs: 其他参数（temperature, max_tokens 等）

        Returns:
            LLM 响应内容
        """
        if self.config.provider_type == LLMProviderType.ANTHROPIC:
            return await self._chat_anthropic(messages, **kwargs)
        else:
            return await self._chat_openai_compatible(messages, **kwargs)

    async def _chat_openai_compatible(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """调用 OpenAI 兼容 API"""
        url = f"{self.base_url}/chat/completions" if self.base_url else "https://api.openai.com/v1/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 2000),
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def _chat_anthropic(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """调用 Anthropic API"""
        url = "https://api.anthropic.com/v1/messages"

        # 转换消息格式
        system_prompt = ""
        anthropic_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                anthropic_messages.append({
                    "role": msg["role"] if msg["role"] != "assistant" else "assistant",
                    "content": msg["content"]
                })

        payload = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.get("max_tokens", 2000),
            "temperature": kwargs.get("temperature", 0.7),
        }

        if system_prompt:
            payload["system"] = system_prompt

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]

    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> AsyncGenerator[str, None]:
        """流式聊天"""
        # 简化实现，非流式
        content = await self.chat(messages, **kwargs)
        yield content


class LLMRouter:
    """
    LLM 路由器

    管理多个 LLM Provider，支持：
    - 自动故障转移
    - 负载均衡
    - Provider 选择
    """

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
        """获取指定客户端"""
        client_name = name or self.default_client_name
        return self.clients.get(client_name)

    def get_enabled_clients(self) -> List[LLMClient]:
        """获取所有启用的客户端"""
        return list(self.clients.values())

    async def _notify_call_observer(self, payload: Dict[str, Any]) -> None:
        """记录 LLM 调用信息，避免日志异常中断主流程。"""
        if not self.call_observer:
            return
        try:
            result = self.call_observer(payload)
            if hasattr(result, "__await__"):
                await result
        except Exception:
            # 日志记录失败不影响主链路。
            return

    async def _chat_with_client(
        self,
        client_name: str,
        client: LLMClient,
        messages: List[Dict[str, str]],
        source: str,
        endpoint: str,
        task_id: Optional[str],
        **kwargs,
    ) -> str:
        started = time.perf_counter()
        try:
            content = await client.chat(messages, **kwargs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            await self._notify_call_observer(
                {
                    "provider_name": client_name,
                    "model": client.model,
                    "source": source,
                    "endpoint": endpoint,
                    "task_id": task_id,
                    "prompt_preview": (messages[-1].get("content", "") if messages else "")[:200],
                    "response_preview": content[:200],
                    "status": "success",
                    "error_message": "",
                    "latency_ms": latency_ms,
                }
            )
            return content
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            await self._notify_call_observer(
                {
                    "provider_name": client_name,
                    "model": client.model,
                    "source": source,
                    "endpoint": endpoint,
                    "task_id": task_id,
                    "prompt_preview": (messages[-1].get("content", "") if messages else "")[:200],
                    "response_preview": "",
                    "status": "error",
                    "error_message": str(exc)[:300],
                    "latency_ms": latency_ms,
                }
            )
            raise

    async def chat(self, messages: List[Dict[str, str]], provider: Optional[str] = None, **kwargs) -> str:
        """
        发送聊天请求（带故障转移）

        Args:
            messages: 消息列表
            provider: 指定 Provider（可选）
            **kwargs: 其他参数

        Returns:
            LLM 响应
        """
        source = str(kwargs.pop("_source", "runtime"))
        endpoint = str(kwargs.pop("_endpoint", "chat"))
        task_id_value = kwargs.pop("_task_id", None)
        task_id = str(task_id_value) if task_id_value else None

        # 尝试指定 Provider
        if provider:
            client = self.get_client(provider)
            if client:
                try:
                    return await self._chat_with_client(
                        provider,
                        client,
                        messages,
                        source,
                        endpoint,
                        task_id,
                        **kwargs,
                    )
                except Exception:
                    # 失败后尝试默认 Provider
                    pass

        # 尝试默认 Provider
        default_client = self.get_client()
        if default_client:
            try:
                return await self._chat_with_client(
                    self.default_client_name,
                    default_client,
                    messages,
                    source,
                    endpoint,
                    task_id,
                    **kwargs,
                )
            except Exception:
                pass

        # 尝试其他 Provider（故障转移）
        for name, client in self.clients.items():
            if name != self.default_client_name and name != provider:
                try:
                    return await self._chat_with_client(
                        name,
                        client,
                        messages,
                        source,
                        endpoint,
                        task_id,
                        **kwargs,
                    )
                except Exception:
                    continue

        raise RuntimeError("所有 LLM Provider 都不可用")

    def set_default(self, name: str) -> bool:
        """设置默认 Provider"""
        if name in self.clients:
            self.default_client_name = name
            return True
        return False
