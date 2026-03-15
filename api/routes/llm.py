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
from engine.llm.config import serialize_provider_record
from engine.runtime.models import AICallLog

from .ai import (
    AIProviderCreateRequest,
    AIProviderPatchRequest,
    create_ai_provider,
    delete_ai_provider,
    list_ai_providers,
    patch_ai_provider,
)
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
    payload = await list_ai_providers(provider_repository=provider_repository)
    providers = payload.get("providers", [])
    payload["total"] = len(providers)
    return payload


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
    return serialize_provider_record(provider)


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
    ai_payload = AIProviderCreateRequest.model_validate(
        {
            "name": payload.name,
            "type": payload.type,
            "api_key": payload.api_key,
            "model": payload.model,
            "base_url": payload.base_url,
            "enabled": payload.enabled,
            "is_default": payload.is_default,
            "timeout": payload.timeout,
            "max_retries": payload.max_retries,
        }
    )
    result = await create_ai_provider(
        ai_payload,
        provider_repository=provider_repository,
        refresh_llm_router=refresh_llm_router,
    )
    if not result.get("default_provider"):
        default_provider = provider_repository.get_default() if provider_repository else None
        result["default_provider"] = default_provider.name if default_provider else ""
    return result


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

    if (
        payload.name is None
        and payload.type is None
        and payload.api_key is None
        and payload.model is None
        and payload.base_url is None
        and payload.enabled is None
        and payload.timeout is None
        and payload.max_retries is None
    ):
        return {
            "message": "Provider 无需更新",
            "provider": serialize_provider_record(current),
        }

    ai_payload = AIProviderPatchRequest.model_validate(
        {
            "name": payload.name,
            "type": payload.type,
            "api_key": payload.api_key,
            "model": payload.model,
            "base_url": payload.base_url,
            "enabled": payload.enabled,
            "timeout": payload.timeout,
            "max_retries": payload.max_retries,
        }
    )
    return await patch_ai_provider(
        current.provider_id,
        ai_payload,
        provider_repository=provider_repository,
        refresh_llm_router=refresh_llm_router,
    )


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
    await delete_ai_provider(
        current.provider_id,
        provider_repository=provider_repository,
        refresh_llm_router=refresh_llm_router,
    )
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

    await patch_ai_provider(
        provider.provider_id,
        AIProviderPatchRequest(is_default=True),
        provider_repository=provider_repository,
        refresh_llm_router=refresh_llm_router,
    )
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
