"""LLM Provider 配置与连通性接口。"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engine.llm.client import LLMClient
from engine.llm.config import LLMConfigManager, LLMProviderConfig, LLMProviderType
from engine.runtime.models import AICallLog

from .deps import get_ai_call_log_repository_dep, get_llm_config_manager_dep

router = APIRouter(prefix="/llm", tags=["llm"])


class ProviderUpsertRequest(BaseModel):
    """新增 Provider 请求。"""

    name: str = Field(..., min_length=1, description="Provider 名称")
    type: LLMProviderType = Field(..., description="Provider 类型")
    api_key: str | None = Field(default=None, description="API Key")
    model: str = Field(..., min_length=1, description="模型名称")
    base_url: str | None = Field(default=None, description="API 基础地址")
    enabled: bool = Field(default=True, description="是否启用")
    timeout: int = Field(default=30, ge=5, le=300, description="超时时间")
    max_retries: int = Field(default=2, ge=0, le=5, description="最大重试次数")


class ProviderUpdateRequest(BaseModel):
    """更新 Provider 请求。"""

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


def _load_config(manager: LLMConfigManager):
    """读取配置，避免路由层直接操作文件。"""
    return manager.load_config()


def _serialize_provider(provider: LLMProviderConfig) -> dict[str, Any]:
    """序列化 Provider，避免返回敏感信息。"""
    return {
        "name": provider.name,
        "type": provider.provider_type.value,
        "model": provider.model,
        "base_url": provider.base_url,
        "enabled": provider.enabled,
        "timeout": provider.timeout,
        "max_retries": provider.max_retries,
        "api_key_configured": bool(provider.api_key),
    }


def _record_call_log(call_log_repository, payload: dict[str, Any]) -> None:
    """写入 LLM 调用日志，失败时不影响主流程。"""
    if not call_log_repository:
        return

    status = str(payload.get("status") or "success").lower()
    try:
        call_log_repository.save(
            AICallLog(
                provider_name=str(payload.get("provider_name") or "unknown"),
                model=str(payload.get("model") or "unknown"),
                source=str(payload.get("source") or "llm_route"),
                endpoint=str(payload.get("endpoint") or "test"),
                task_id=str(payload.get("task_id")) if payload.get("task_id") else None,
                prompt_preview=str(payload.get("prompt_preview") or "")[:200],
                response_preview=str(payload.get("response_preview") or "")[:200],
                status="error" if status == "error" else "success",
                error_message=str(payload.get("error_message") or "")[:500],
                latency_ms=max(0, int(payload.get("latency_ms") or 0)),
                request_tokens=int(payload["request_tokens"]) if payload.get("request_tokens") is not None else None,
                response_tokens=int(payload["response_tokens"]) if payload.get("response_tokens") is not None else None,
            )
        )
    except Exception:
        return


@router.get("/providers")
async def list_providers(manager: LLMConfigManager = Depends(get_llm_config_manager_dep)):
    config = _load_config(manager)
    return {
        "providers": [_serialize_provider(provider) for provider in config.providers],
        "default_provider": config.default_provider,
    }


@router.get("/call-logs")
async def list_call_logs(
    provider_name: str | None = None,
    status: str | None = None,
    limit: int = 100,
    call_log_repository=Depends(get_ai_call_log_repository_dep),
):
    normalized_status = (status or "").strip().lower()
    if normalized_status and normalized_status not in {"success", "error"}:
        raise HTTPException(status_code=400, detail="status 仅支持 success 或 error")

    if not call_log_repository:
        return {
            "items": [],
            "total": 0,
            "provider_name": provider_name or "",
            "status": normalized_status,
            "limit": max(1, min(limit, 500)),
        }

    logs = call_log_repository.list(
        provider_name=provider_name,
        status=normalized_status or None,
        limit=limit,
    )
    return {
        "items": [item.model_dump(mode="json") for item in logs],
        "total": len(logs),
        "provider_name": provider_name or "",
        "status": normalized_status,
        "limit": max(1, min(limit, 500)),
    }


@router.post("/providers")
async def create_provider(payload: ProviderUpsertRequest, manager: LLMConfigManager = Depends(get_llm_config_manager_dep)):
    config = _load_config(manager)
    if config.get_provider(payload.name):
        raise HTTPException(status_code=409, detail="Provider 已存在")

    provider = LLMProviderConfig(
        name=payload.name,
        provider_type=payload.type,
        api_key=(payload.api_key or "").strip(),
        base_url=(payload.base_url or "").strip() or None,
        model=payload.model.strip(),
        enabled=payload.enabled,
        timeout=payload.timeout,
        max_retries=payload.max_retries,
    )
    manager.add_provider(provider)

    return {
        "message": "Provider 添加成功",
        "provider": _serialize_provider(provider),
        "default_provider": manager.config.default_provider if manager.config else config.default_provider,
    }


@router.put("/providers/{provider_name}")
async def update_provider(
    provider_name: str,
    payload: ProviderUpdateRequest,
    manager: LLMConfigManager = Depends(get_llm_config_manager_dep),
):
    config = _load_config(manager)
    provider = config.get_provider(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    updates: dict[str, Any] = {}
    if payload.type is not None:
        updates["provider_type"] = payload.type
    if payload.model is not None and payload.model.strip():
        updates["model"] = payload.model.strip()
    if payload.base_url is not None:
        updates["base_url"] = payload.base_url.strip() or None
    if payload.enabled is not None:
        updates["enabled"] = payload.enabled
    if payload.timeout is not None:
        updates["timeout"] = payload.timeout
    if payload.max_retries is not None:
        updates["max_retries"] = payload.max_retries
    # 编辑场景下前端通常传空字符串，表示保持原值，避免误覆盖已有密钥。
    if payload.api_key is not None and payload.api_key.strip():
        updates["api_key"] = payload.api_key.strip()

    if not updates:
        return {
            "message": "Provider 无需更新",
            "provider": _serialize_provider(provider),
        }

    manager.update_provider(provider_name, updates)
    latest = manager.load_config().get_provider(provider_name)
    if not latest:
        raise HTTPException(status_code=500, detail="Provider 更新后读取失败")

    return {
        "message": "Provider 更新成功",
        "provider": _serialize_provider(latest),
    }


@router.delete("/providers/{provider_name}")
async def delete_provider(provider_name: str, manager: LLMConfigManager = Depends(get_llm_config_manager_dep)):
    config = _load_config(manager)
    target = config.get_provider(provider_name)
    if not target:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    if len(config.providers) <= 1:
        raise HTTPException(status_code=409, detail="至少保留一个 Provider")

    if config.default_provider == provider_name:
        fallback = next((provider.name for provider in config.providers if provider.name != provider_name), None)
        if not fallback:
            raise HTTPException(status_code=409, detail="默认 Provider 无法删除")
        manager.set_default_provider(fallback)

    manager.remove_provider(provider_name)
    latest = manager.load_config()
    return {
        "message": "Provider 删除成功",
        "default_provider": latest.default_provider,
    }


@router.post("/default-provider")
async def set_default_provider(payload: DefaultProviderRequest, manager: LLMConfigManager = Depends(get_llm_config_manager_dep)):
    config = _load_config(manager)
    if not config.get_provider(payload.provider_name):
        raise HTTPException(status_code=404, detail="Provider 不存在")

    manager.set_default_provider(payload.provider_name)
    return {
        "message": "默认 Provider 设置成功",
        "default_provider": payload.provider_name,
    }


@router.post("/providers/{provider_name}/test")
async def test_provider_connection(
    provider_name: str,
    manager: LLMConfigManager = Depends(get_llm_config_manager_dep),
    call_log_repository=Depends(get_ai_call_log_repository_dep),
):
    config = _load_config(manager)
    provider = config.get_provider(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    prompt_preview = "请回复 OK"
    if not provider.api_key and provider.provider_type != LLMProviderType.CUSTOM:
        _record_call_log(
            call_log_repository,
            {
                "provider_name": provider.name,
                "model": provider.model,
                "source": "llm_route",
                "endpoint": "provider_test",
                "prompt_preview": prompt_preview,
                "response_preview": "",
                "status": "error",
                "error_message": "API Key 未配置",
                "latency_ms": 0,
            },
        )
        return {
            "status": "error",
            "message": "API Key 未配置，无法测试连接",
        }

    client = LLMClient(provider)
    started = time.perf_counter()
    try:
        content = await client.chat(
            [
                {"role": "system", "content": "你是连接测试助手，请只返回一个词。"},
                {"role": "user", "content": prompt_preview},
            ],
            temperature=0,
            max_tokens=16,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        _record_call_log(
            call_log_repository,
            {
                "provider_name": provider.name,
                "model": provider.model,
                "source": "llm_route",
                "endpoint": "provider_test",
                "prompt_preview": prompt_preview,
                "response_preview": content,
                "status": "success",
                "error_message": "",
                "latency_ms": latency_ms,
            },
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.perf_counter() - started) * 1000)
        _record_call_log(
            call_log_repository,
            {
                "provider_name": provider.name,
                "model": provider.model,
                "source": "llm_route",
                "endpoint": "provider_test",
                "prompt_preview": prompt_preview,
                "response_preview": "",
                "status": "error",
                "error_message": str(exc),
                "latency_ms": latency_ms,
            },
        )
        return {
            "status": "error",
            "message": f"连接测试失败：{exc}",
        }

    return {
        "status": "success",
        "message": "连接测试成功",
        "response_preview": content[:120],
    }
