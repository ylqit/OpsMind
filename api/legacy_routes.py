"""Legacy 调试路由。

该模块只保留开发调试页所需的最小接口：
- 列出能力
- 调用能力

说明：
- 不属于主产品 API 面
- 不作为稳定集成契约
- 主要服务于本地调试、开发验证与兼容入口
"""
from __future__ import annotations

import asyncio
from importlib import import_module
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["legacy-debug"])


class DispatchRequest(BaseModel):
    """能力调用请求体。"""

    params: dict[str, Any] = Field(default_factory=dict, description="能力参数")


def _read_main_capability_registry() -> Any | None:
    """兼容旧测试与脚本，必要时回退到 main 模块读取全局注册表。"""

    try:
        main_module = import_module("main")
    except Exception:  # noqa: BLE001
        return None
    return getattr(main_module, "capability_registry", None)


def get_registry(request: Request):
    """获取能力注册表（优先 app.state，保留 main 回退兼容）。"""

    state = getattr(request.app, "state", None)
    if state is not None and hasattr(state, "capability_registry"):
        registry = getattr(state, "capability_registry")
        if registry is not None:
            return registry
    return _read_main_capability_registry()


@router.get("/capabilities")
async def list_capabilities(registry=Depends(get_registry)) -> list[dict[str, Any]]:
    """列出开发调试页可见的能力清单。"""
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
    """调用指定能力，仅用于开发调试与兼容验证。"""
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
