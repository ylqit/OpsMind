"""AI 统一接口。"""
from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .deps import get_llm_router_dep

router = APIRouter(prefix="/ai", tags=["ai"])


class AIChatMessage(BaseModel):
    """聊天消息。"""

    role: Literal["system", "user", "assistant"] = Field(..., description="消息角色")
    content: str = Field(..., min_length=1, description="消息内容")


class AIChatRequest(BaseModel):
    """统一 AI 聊天请求。"""

    messages: list[AIChatMessage] = Field(..., min_length=1, description="消息列表")
    provider: str | None = Field(default=None, description="指定 Provider，可选")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="采样温度")
    max_tokens: int = Field(default=1000, ge=1, le=8192, description="最大输出 token")
    task_id: str | None = Field(default=None, description="关联任务 ID，可选")


class AIProviderTestRequest(BaseModel):
    """Provider 连通性测试请求。"""

    provider_name: str | None = Field(default=None, description="Provider 名称，空则测默认 Provider")
    message: str = Field(default="请仅回复 OK", min_length=1, description="测试消息")


def _normalize_error_code(error: Exception) -> str:
    text = str(error).lower()
    if "timeout" in text or "timed out" in text:
        return "AI_TIMEOUT"
    if "http" in text and "5" in text:
        return "AI_HTTP_5XX"
    if "http" in text and "4" in text:
        return "AI_HTTP_4XX"
    if "network" in text or "connect" in text:
        return "AI_NETWORK_ERROR"
    return "AI_RUNTIME_ERROR"


@router.post("/chat")
async def chat_with_ai(
    payload: AIChatRequest,
    llm_router=Depends(get_llm_router_dep),
):
    """统一聊天入口，支持 Provider 指定、重试与 fallback。"""
    if not llm_router:
        raise HTTPException(status_code=409, detail="当前未启用可用的 LLM Provider")
    if payload.provider and payload.provider not in llm_router.clients:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    started = time.perf_counter()
    try:
        content = await llm_router.chat(
            [item.model_dump() for item in payload.messages],
            provider=payload.provider,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            _source="ai_route",
            _endpoint="chat",
            _task_id=payload.task_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": _normalize_error_code(exc),
                "error_message": str(exc),
            },
        ) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "status": "success",
        "content": content,
        "provider": payload.provider or llm_router.default_client_name,
        "task_id": payload.task_id,
        "latency_ms": latency_ms,
    }


@router.post("/providers/test")
async def test_ai_provider(
    payload: AIProviderTestRequest,
    llm_router=Depends(get_llm_router_dep),
):
    """Provider 连通性测试，走统一路由逻辑。"""
    if not llm_router:
        raise HTTPException(status_code=409, detail="当前未启用可用的 LLM Provider")
    if payload.provider_name and payload.provider_name not in llm_router.clients:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    started = time.perf_counter()
    try:
        content = await llm_router.chat(
            [
                {"role": "system", "content": "你是连接测试助手，请简短作答。"},
                {"role": "user", "content": payload.message},
            ],
            provider=payload.provider_name,
            temperature=0,
            max_tokens=32,
            _source="ai_route",
            _endpoint="provider_test",
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "provider": payload.provider_name or llm_router.default_client_name,
            "error_code": _normalize_error_code(exc),
            "error_message": str(exc),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    return {
        "status": "success",
        "provider": payload.provider_name or llm_router.default_client_name,
        "response_preview": content[:120],
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
