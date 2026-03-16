"""Legacy 调试路由。

该模块只保留能力调试工作台所需的最小接口：
- 列出能力
- 调用能力
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class DispatchRequest(BaseModel):
    """能力调用请求体。"""

    params: dict[str, Any] = Field(default_factory=dict, description="能力参数")


def get_registry():
    """获取能力注册表（依赖注入）。"""
    from main import capability_registry

    return capability_registry


@router.get("/capabilities")
async def list_capabilities(registry=Depends(get_registry)) -> list[dict[str, Any]]:
    """列出所有可调试能力。"""
    if not registry:
        return []

    return [
        {
            "name": cap.metadata.name,
            "description": cap.metadata.description,
            "tags": cap.metadata.tags,
            "requires_confirmation": cap.metadata.requires_confirmation,
            "schema": cap.to_openai_tool(),
        }
        for cap in registry._capabilities.values()
    ]


@router.post("/capabilities/{name}/dispatch")
async def dispatch_capability(
    name: str,
    request: DispatchRequest,
    registry=Depends(get_registry),
) -> dict[str, Any]:
    """调用指定能力。"""
    if not registry:
        raise HTTPException(status_code=503, detail="能力注册表尚未初始化")

    capability = registry.get(name)
    if not capability:
        raise HTTPException(status_code=404, detail=f"能力 '{name}' 不存在")

    try:
        result = await asyncio.wait_for(capability.dispatch(**request.params), timeout=60)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return result.to_dict()

