"""AI Provider 抽象与实现。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ProviderResponse:
    """Provider 统一响应。"""

    content: str
    request_tokens: int | None = None
    response_tokens: int | None = None
    raw: dict[str, Any] | None = None


class AIProvider(ABC):
    """统一 Provider 抽象。"""

    def __init__(self, base_url: str | None, api_key: str, model: str, timeout: int):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ProviderResponse:
        """发送聊天请求。"""


class OpenAICompatibleProvider(AIProvider):
    """OpenAI 兼容接口 Provider。"""

    def __init__(self, base_url: str | None, api_key: str, model: str, timeout: int):
        normalized_base = (base_url or "https://api.openai.com/v1").rstrip("/")
        super().__init__(normalized_base, api_key, model, timeout)

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ProviderResponse:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 2000),
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        usage = data.get("usage") or {}
        message = ((data.get("choices") or [{}])[0].get("message") or {})
        content = str(message.get("content") or "")
        return ProviderResponse(
            content=content,
            request_tokens=usage.get("prompt_tokens"),
            response_tokens=usage.get("completion_tokens"),
            raw=data,
        )


class QwenProvider(OpenAICompatibleProvider):
    """Qwen 兼容接口 Provider。"""

    def __init__(self, base_url: str | None, api_key: str, model: str, timeout: int):
        qwen_base = (base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
        super().__init__(qwen_base, api_key, model, timeout)


class AnthropicProvider(AIProvider):
    """Anthropic Provider。"""

    def __init__(self, api_key: str, model: str, timeout: int):
        super().__init__("https://api.anthropic.com/v1", api_key, model, timeout)

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ProviderResponse:
        url = f"{self.base_url}/messages"

        system_prompt = ""
        anthropic_messages: list[dict[str, str]] = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "")
            if role == "system":
                system_prompt = content
                continue
            anthropic_messages.append(
                {
                    "role": role if role != "assistant" else "assistant",
                    "content": content,
                }
            )

        payload: dict[str, Any] = {
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
            "anthropic-version": "2023-06-01",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        usage = data.get("usage") or {}
        blocks = data.get("content") or []
        content = ""
        if blocks:
            content = str((blocks[0] or {}).get("text") or "")

        return ProviderResponse(
            content=content,
            request_tokens=usage.get("input_tokens"),
            response_tokens=usage.get("output_tokens"),
            raw=data,
        )
