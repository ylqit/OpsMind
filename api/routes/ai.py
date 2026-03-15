"""AI 统一接口。"""
from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from engine.llm.client import LLMClient
from engine.llm.config import (
    LLMProviderConfig,
    LLMProviderType,
    ensure_default_provider_record,
    serialize_provider_record,
)
from engine.runtime.models import AIProviderConfigRecord

from .deps import (
    get_ai_call_log_repository_dep,
    get_ai_provider_config_repository_dep,
    get_llm_router_dep,
    get_refresh_llm_router_dep,
)

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

    provider_id: str | None = Field(default=None, description="Provider ID，可选")
    provider_name: str | None = Field(default=None, description="Provider 名称，可选")
    message: str = Field(default="请仅回复 OK", min_length=1, description="测试消息")


class AIProviderCreateRequest(BaseModel):
    """新增 Provider 请求。"""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, description="Provider 名称")
    provider_type: LLMProviderType = Field(..., alias="type", description="Provider 类型")
    api_key: str | None = Field(default=None, description="API Key")
    model: str = Field(..., min_length=1, description="模型名称")
    base_url: str | None = Field(default=None, description="API 基础地址")
    enabled: bool = Field(default=True, description="是否启用")
    is_default: bool | None = Field(default=None, description="是否设为默认")
    timeout: int = Field(default=30, ge=5, le=300, description="超时时间")
    max_retries: int = Field(default=2, ge=0, le=5, description="最大重试次数")


class AIProviderPatchRequest(BaseModel):
    """更新 Provider 请求。"""

    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, description="Provider 名称")
    provider_type: LLMProviderType | None = Field(default=None, alias="type", description="Provider 类型")
    api_key: str | None = Field(default=None, description="API Key，空字符串表示保持原值")
    model: str | None = Field(default=None, min_length=1, description="模型名称")
    base_url: str | None = Field(default=None, description="API 基础地址")
    enabled: bool | None = Field(default=None, description="是否启用")
    is_default: bool | None = Field(default=None, description="是否设为默认")
    timeout: int | None = Field(default=None, ge=5, le=300, description="超时时间")
    max_retries: int | None = Field(default=None, ge=0, le=5, description="最大重试次数")


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


def _build_client_from_record(record: AIProviderConfigRecord) -> LLMClient:
    provider_config = LLMProviderConfig(
        name=record.name,
        provider_type=LLMProviderType(record.provider_type),
        api_key=record.api_key,
        base_url=record.base_url,
        model=record.model,
        enabled=record.enabled,
        timeout=record.timeout,
        max_retries=record.max_retries,
    )
    return LLMClient(provider_config)


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


@router.get("/providers")
async def list_ai_providers(provider_repository=Depends(get_ai_provider_config_repository_dep)):
    """读取 Provider 列表。"""
    if not provider_repository:
        return {"providers": [], "default_provider": "", "default_provider_id": ""}

    providers = provider_repository.list()
    default_provider = provider_repository.get_default()
    return {
        "providers": [serialize_provider_record(item) for item in providers],
        "default_provider": default_provider.name if default_provider else "",
        "default_provider_id": default_provider.provider_id if default_provider else "",
    }


@router.get("/call-logs")
async def list_ai_call_logs(
    provider_name: str | None = None,
    status: str | None = None,
    limit: int = 100,
    call_log_repository=Depends(get_ai_call_log_repository_dep),
):
    """读取 AI 调用日志。"""
    normalized_status = (status or "").strip().lower()
    if normalized_status and normalized_status not in {"success", "error"}:
        raise HTTPException(status_code=400, detail="status 仅支持 success 或 error")

    safe_limit = max(1, min(limit, 500))
    if not call_log_repository:
        return {
            "items": [],
            "total": 0,
            "provider_name": provider_name or "",
            "status": normalized_status,
            "limit": safe_limit,
        }

    logs = call_log_repository.list(
        provider_name=provider_name,
        status=normalized_status or None,
        limit=safe_limit,
    )
    return {
        "items": [item.model_dump(mode="json") for item in logs],
        "total": len(logs),
        "provider_name": provider_name or "",
        "status": normalized_status,
        "limit": safe_limit,
    }


@router.post("/providers")
async def create_ai_provider(
    payload: AIProviderCreateRequest,
    provider_repository=Depends(get_ai_provider_config_repository_dep),
    refresh_llm_router=Depends(get_refresh_llm_router_dep),
):
    """新增 Provider 并即时生效。"""
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    normalized_name = payload.name.strip()
    normalized_model = payload.model.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Provider 名称不能为空")
    if not normalized_model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if provider_repository.get_by_name(normalized_name):
        raise HTTPException(status_code=409, detail="Provider 名称已存在")

    default_provider = provider_repository.get_default()
    should_default = payload.is_default if payload.is_default is not None else (default_provider is None and payload.enabled)
    if should_default and not payload.enabled:
        raise HTTPException(status_code=400, detail="默认 Provider 必须处于启用状态")

    record = AIProviderConfigRecord(
        name=normalized_name,
        provider_type=payload.provider_type.value,
        model=normalized_model,
        base_url=(payload.base_url or "").strip() or None,
        api_key=(payload.api_key or "").strip(),
        enabled=payload.enabled,
        is_default=should_default,
        timeout=payload.timeout,
        max_retries=payload.max_retries,
    )
    saved = provider_repository.save(record)

    ensure_default_provider_record(provider_repository)
    refresh_llm_router()

    latest = provider_repository.get(saved.provider_id)
    return {
        "message": "Provider 创建成功",
        "provider": serialize_provider_record(latest or saved),
    }


@router.post("/providers/test")
async def test_ai_provider(
    payload: AIProviderTestRequest,
    llm_router=Depends(get_llm_router_dep),
    provider_repository=Depends(get_ai_provider_config_repository_dep),
):
    """Provider 连通性测试，优先走数据库配置。"""
    started = time.perf_counter()

    target_record = None
    if provider_repository:
        if payload.provider_id:
            target_record = provider_repository.get(payload.provider_id)
        elif payload.provider_name:
            target_record = provider_repository.get_by_name(payload.provider_name)
        else:
            target_record = provider_repository.get_default()

    if target_record:
        try:
            client = _build_client_from_record(target_record)
            content = await client.chat(
                [
                    {"role": "system", "content": "你是连接测试助手，请简短作答。"},
                    {"role": "user", "content": payload.message},
                ],
                temperature=0,
                max_tokens=32,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "error",
                "provider": target_record.name,
                "error_code": _normalize_error_code(exc),
                "error_message": str(exc),
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }

        return {
            "status": "success",
            "provider": target_record.name,
            "response_preview": content[:120],
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    if not llm_router:
        raise HTTPException(status_code=409, detail="当前未启用可用的 LLM Provider")
    if payload.provider_name and payload.provider_name not in llm_router.clients:
        raise HTTPException(status_code=404, detail="Provider 不存在")

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


@router.patch("/providers/{provider_id}")
async def patch_ai_provider(
    provider_id: str,
    payload: AIProviderPatchRequest,
    provider_repository=Depends(get_ai_provider_config_repository_dep),
    refresh_llm_router=Depends(get_refresh_llm_router_dep),
):
    """更新 Provider 配置并热刷新路由。"""
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    current = provider_repository.get(provider_id)
    if not current:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    if payload.is_default is False and current.is_default:
        raise HTTPException(status_code=400, detail="默认 Provider 不能直接取消，请先设置其他默认")
    if payload.enabled is False and current.is_default and payload.is_default is not True:
        raise HTTPException(status_code=400, detail="默认 Provider 不能直接禁用，请先切换默认")

    updates: dict[str, Any] = {}

    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Provider 名称不能为空")
        duplicate = provider_repository.get_by_name(new_name)
        if duplicate and duplicate.provider_id != provider_id:
            raise HTTPException(status_code=409, detail="Provider 名称已存在")
        updates["name"] = new_name

    if payload.provider_type is not None:
        updates["provider_type"] = payload.provider_type.value
    if payload.model is not None:
        new_model = payload.model.strip()
        if not new_model:
            raise HTTPException(status_code=400, detail="模型名称不能为空")
        updates["model"] = new_model
    if payload.base_url is not None:
        updates["base_url"] = payload.base_url.strip() or None
    if payload.enabled is not None:
        updates["enabled"] = payload.enabled
    if payload.timeout is not None:
        updates["timeout"] = payload.timeout
    if payload.max_retries is not None:
        updates["max_retries"] = payload.max_retries
    if payload.api_key is not None and payload.api_key.strip():
        updates["api_key"] = payload.api_key.strip()

    updated = current
    if updates:
        updated = provider_repository.update(provider_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail="Provider 不存在")

    if payload.is_default is True:
        default_record = provider_repository.set_default(provider_id)
        if not default_record:
            raise HTTPException(status_code=400, detail="默认 Provider 必须处于启用状态")
        updated = default_record

    ensure_default_provider_record(provider_repository)
    refresh_llm_router()

    latest = provider_repository.get(provider_id)
    if not latest:
        raise HTTPException(status_code=500, detail="Provider 更新后读取失败")

    return {
        "message": "Provider 更新成功",
        "provider": serialize_provider_record(latest),
    }


@router.delete("/providers/{provider_id}")
async def delete_ai_provider(
    provider_id: str,
    provider_repository=Depends(get_ai_provider_config_repository_dep),
    refresh_llm_router=Depends(get_refresh_llm_router_dep),
):
    """删除 Provider。"""
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    current = provider_repository.get(provider_id)
    if not current:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    if provider_repository.count() <= 1:
        raise HTTPException(status_code=409, detail="至少保留一个 Provider")

    enabled_items = provider_repository.list(enabled_only=True)
    if current.is_default and len(enabled_items) <= 1:
        raise HTTPException(status_code=409, detail="至少保留一个启用状态的默认 Provider")

    deleted = provider_repository.delete(provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    ensure_default_provider_record(provider_repository)
    refresh_llm_router()
    return {"message": "Provider 删除成功"}
