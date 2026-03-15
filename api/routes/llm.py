"""LLM 兼容接口。

说明：
- `/api/ai/*` 是当前主产品入口。
- `/api/llm/*` 仅保留为兼容层，内部统一复用 AI Provider 仓储与运行时路由。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engine.llm.config import LLMProviderType
from engine.runtime.models import AICallLog
from engine.runtime.models import AIProviderConfigRecord

from .deps import (
    get_ai_call_log_repository_dep,
    get_ai_provider_config_repository_dep,
    get_llm_router_dep,
    get_refresh_llm_router_dep,
)

router = APIRouter(prefix="/llm", tags=["llm"])


class ProviderUpsertRequest(BaseModel):
    """新增 Provider 请求。"""

    name: str = Field(..., min_length=1, description="Provider 名称")
    type: LLMProviderType = Field(..., description="Provider 类型")
    api_key: str | None = Field(default=None, description="API Key")
    model: str = Field(..., min_length=1, description="模型名称")
    base_url: str | None = Field(default=None, description="API 基础地址")
    enabled: bool = Field(default=True, description="是否启用")
    is_default: bool | None = Field(default=None, description="是否设为默认")
    timeout: int = Field(default=30, ge=5, le=300, description="超时时间")
    max_retries: int = Field(default=2, ge=0, le=5, description="最大重试次数")


class ProviderUpdateRequest(BaseModel):
    """更新 Provider 请求。"""

    name: str | None = Field(default=None, min_length=1, description="Provider 名称")
    type: LLMProviderType | None = Field(default=None, description="Provider 类型")
    api_key: str | None = Field(default=None, description="API Key，空字符串表示保持不变")
    model: str | None = Field(default=None, description="模型名称")
    base_url: str | None = Field(default=None, description="API 基础地址")
    enabled: bool | None = Field(default=None, description="是否启用")
    timeout: int | None = Field(default=None, ge=5, le=300, description="超时时间")
    max_retries: int | None = Field(default=None, ge=0, le=5, description="最大重试次数")


class DefaultProviderRequest(BaseModel):
    """设置默认 Provider 请求。"""

    provider_name: str = Field(..., min_length=1, description="Provider 名称")


class AnalyzeRequest(BaseModel):
    """LLM 分析兼容请求。"""

    messages: list[dict[str, str]] = Field(..., min_length=1, description="消息列表")
    provider: str | None = Field(default=None, description="指定 Provider")
    temperature: float = Field(default=0.7, description="温度参数")
    max_tokens: int = Field(default=2000, ge=1, le=8192, description="最大输出 token")


def _serialize_provider(record: AIProviderConfigRecord) -> dict[str, Any]:
    return {
        "provider_id": record.provider_id,
        "name": record.name,
        "type": record.provider_type,
        "model": record.model,
        "base_url": record.base_url,
        "enabled": record.enabled,
        "timeout": record.timeout,
        "max_retries": record.max_retries,
        "api_key_configured": bool(record.api_key),
        "is_default": record.is_default,
    }


def _ensure_default_provider(provider_repository) -> None:
    """保证始终存在一个可用默认 Provider。"""
    default_provider = provider_repository.get_default()
    if default_provider and default_provider.enabled:
        return

    enabled_items = provider_repository.list(enabled_only=True)
    if enabled_items:
        provider_repository.set_default(enabled_items[0].provider_id)


def _record_call_log(call_log_repository, payload: dict[str, Any]) -> None:
    """兼容层补充测试调用日志。"""
    if not call_log_repository:
        return

    status = str(payload.get("status") or "success").lower()
    try:
        call_log_repository.save(
            AICallLog(
                provider_name=str(payload.get("provider_name") or "unknown"),
                model=str(payload.get("model") or "unknown"),
                source=str(payload.get("source") or "llm_compat_route"),
                endpoint=str(payload.get("endpoint") or "provider_test"),
                task_id=None,
                prompt_preview=str(payload.get("prompt_preview") or "")[:200],
                response_preview=str(payload.get("response_preview") or "")[:200],
                status="error" if status == "error" else "success",
                error_code=str(payload.get("error_code") or "")[:120],
                error_message=str(payload.get("error_message") or "")[:500],
                latency_ms=max(0, int(payload.get("latency_ms") or 0)),
                request_tokens=None,
                response_tokens=None,
            )
        )
    except Exception:
        return


@router.get("/providers", deprecated=True)
async def list_providers(provider_repository=Depends(get_ai_provider_config_repository_dep)):
    """列出 Provider，兼容旧路径。"""
    if not provider_repository:
        return {
            "providers": [],
            "default_provider": "",
            "default_provider_id": "",
            "total": 0,
        }

    providers = provider_repository.list()
    default_provider = provider_repository.get_default()
    return {
        "providers": [_serialize_provider(provider) for provider in providers],
        "default_provider": default_provider.name if default_provider else "",
        "default_provider_id": default_provider.provider_id if default_provider else "",
        "total": len(providers),
    }


@router.get("/providers/{provider_name}", deprecated=True)
async def get_provider(
    provider_name: str,
    provider_repository=Depends(get_ai_provider_config_repository_dep),
):
    """按名称读取单个 Provider。"""
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    provider = provider_repository.get_by_name(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    return _serialize_provider(provider)


@router.get("/call-logs", deprecated=True)
async def list_call_logs(
    provider_name: str | None = None,
    status: str | None = None,
    limit: int = 100,
    call_log_repository=Depends(get_ai_call_log_repository_dep),
):
    """读取调用日志，兼容旧路径。"""
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


@router.post("/providers", deprecated=True)
async def create_provider(
    payload: ProviderUpsertRequest,
    provider_repository=Depends(get_ai_provider_config_repository_dep),
    refresh_llm_router=Depends(get_refresh_llm_router_dep),
):
    """创建 Provider，兼容旧路径。"""
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    normalized_name = payload.name.strip()
    normalized_model = payload.model.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Provider 名称不能为空")
    if not normalized_model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if provider_repository.get_by_name(normalized_name):
        raise HTTPException(status_code=409, detail="Provider 已存在")

    should_default = payload.is_default if payload.is_default is not None else (
        provider_repository.get_default() is None and payload.enabled
    )
    if should_default and not payload.enabled:
        raise HTTPException(status_code=400, detail="默认 Provider 必须处于启用状态")

    record = AIProviderConfigRecord(
        name=normalized_name,
        provider_type=payload.type.value,
        api_key=(payload.api_key or "").strip(),
        base_url=(payload.base_url or "").strip() or None,
        model=normalized_model,
        enabled=payload.enabled,
        is_default=should_default,
        timeout=payload.timeout,
        max_retries=payload.max_retries,
    )
    saved = provider_repository.save(record)
    _ensure_default_provider(provider_repository)
    refresh_llm_router()

    latest = provider_repository.get(saved.provider_id)
    return {
        "message": "Provider 添加成功",
        "provider": _serialize_provider(latest or saved),
        "default_provider": (provider_repository.get_default().name if provider_repository.get_default() else ""),
    }


@router.put("/providers/{provider_name}", deprecated=True)
async def update_provider(
    provider_name: str,
    payload: ProviderUpdateRequest,
    provider_repository=Depends(get_ai_provider_config_repository_dep),
    refresh_llm_router=Depends(get_refresh_llm_router_dep),
):
    """按名称更新 Provider，兼容旧路径。"""
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    current = provider_repository.get_by_name(provider_name)
    if not current:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    updates: dict[str, Any] = {}
    if payload.type is not None:
        updates["provider_type"] = payload.type.value
    if payload.model is not None:
        model_name = payload.model.strip()
        if not model_name:
            raise HTTPException(status_code=400, detail="模型名称不能为空")
        updates["model"] = model_name
    if payload.base_url is not None:
        updates["base_url"] = payload.base_url.strip() or None
    if payload.enabled is not None:
        if current.is_default and not payload.enabled:
            raise HTTPException(status_code=400, detail="默认 Provider 不能直接禁用，请先切换默认")
        updates["enabled"] = payload.enabled
    if payload.timeout is not None:
        updates["timeout"] = payload.timeout
    if payload.max_retries is not None:
        updates["max_retries"] = payload.max_retries
    if payload.api_key is not None and payload.api_key.strip():
        updates["api_key"] = payload.api_key.strip()
    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Provider 名称不能为空")
        duplicate = provider_repository.get_by_name(new_name)
        if duplicate and duplicate.provider_id != current.provider_id:
            raise HTTPException(status_code=409, detail="Provider 名称已存在")
        updates["name"] = new_name

    if not updates:
        return {
            "message": "Provider 无需更新",
            "provider": _serialize_provider(current),
        }

    updated = provider_repository.update(current.provider_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    _ensure_default_provider(provider_repository)
    refresh_llm_router()

    latest = provider_repository.get(current.provider_id)
    if not latest:
        raise HTTPException(status_code=500, detail="Provider 更新后读取失败")
    return {
        "message": "Provider 更新成功",
        "provider": _serialize_provider(latest),
    }


@router.delete("/providers/{provider_name}", deprecated=True)
async def delete_provider(
    provider_name: str,
    provider_repository=Depends(get_ai_provider_config_repository_dep),
    refresh_llm_router=Depends(get_refresh_llm_router_dep),
):
    """按名称删除 Provider，兼容旧路径。"""
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    current = provider_repository.get_by_name(provider_name)
    if not current:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    if provider_repository.count() <= 1:
        raise HTTPException(status_code=409, detail="至少保留一个 Provider")

    enabled_items = provider_repository.list(enabled_only=True)
    if current.is_default and len(enabled_items) <= 1:
        raise HTTPException(status_code=409, detail="至少保留一个启用状态的默认 Provider")

    deleted = provider_repository.delete(current.provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    _ensure_default_provider(provider_repository)
    refresh_llm_router()
    latest_default = provider_repository.get_default()
    return {
        "message": "Provider 删除成功",
        "default_provider": latest_default.name if latest_default else "",
    }


@router.post("/default-provider", deprecated=True)
async def set_default_provider(
    payload: DefaultProviderRequest,
    provider_repository=Depends(get_ai_provider_config_repository_dep),
    refresh_llm_router=Depends(get_refresh_llm_router_dep),
):
    """设置默认 Provider，兼容旧路径。"""
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    provider = provider_repository.get_by_name(payload.provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    default_record = provider_repository.set_default(provider.provider_id)
    if not default_record:
        raise HTTPException(status_code=400, detail="默认 Provider 必须处于启用状态")

    refresh_llm_router()
    return {
        "message": "默认 Provider 设置成功",
        "default_provider": payload.provider_name,
    }


@router.post("/providers/{provider_name}/test", deprecated=True)
async def test_provider(
    provider_name: str,
    llm_router=Depends(get_llm_router_dep),
    provider_repository=Depends(get_ai_provider_config_repository_dep),
    call_log_repository=Depends(get_ai_call_log_repository_dep),
):
    """测试 Provider 连通性，兼容旧路径。"""
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    provider = provider_repository.get_by_name(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    if not llm_router:
        return {
            "status": "error",
            "message": "当前未启用可用的 LLM Provider",
        }

    try:
        content = await llm_router.chat(
            [
                {"role": "system", "content": "你是连接测试助手，请简短作答。"},
                {"role": "user", "content": "请仅回复 OK"},
            ],
            provider=provider_name,
            temperature=0,
            max_tokens=32,
            _source="llm_compat_route",
            _endpoint="provider_test",
        )
    except Exception as exc:  # noqa: BLE001
        _record_call_log(
            call_log_repository,
            {
                "provider_name": provider.name,
                "model": provider.model,
                "source": "llm_compat_route",
                "endpoint": "provider_test",
                "prompt_preview": "请仅回复 OK",
                "response_preview": "",
                "status": "error",
                "error_message": str(exc),
                "latency_ms": 0,
            },
        )
        return {
            "status": "error",
            "message": f"连接测试失败：{exc}",
        }

    _record_call_log(
        call_log_repository,
        {
            "provider_name": provider.name,
            "model": provider.model,
            "source": "llm_compat_route",
            "endpoint": "provider_test",
            "prompt_preview": "请仅回复 OK",
            "response_preview": content,
            "status": "success",
            "error_message": "",
            "latency_ms": 0,
        },
    )
    return {
        "status": "success",
        "message": "连接测试成功",
        "response_preview": content[:120],
    }


@router.post("/analyze", deprecated=True)
async def analyze(
    payload: AnalyzeRequest,
    llm_router=Depends(get_llm_router_dep),
):
    """兼容旧的 LLM 分析接口。"""
    if not llm_router:
        raise HTTPException(status_code=500, detail="没有可用的 LLM Provider")
    if payload.provider and payload.provider not in llm_router.clients:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    try:
        response = await llm_router.chat(
            payload.messages,
            provider=payload.provider,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            _source="llm_compat_route",
            _endpoint="analyze",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"LLM 调用失败：{exc}") from exc

    return {
        "content": response,
        "provider": payload.provider or llm_router.default_client_name,
    }
