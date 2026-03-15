"""执行插件路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .deps import get_executor_service_dep

router = APIRouter(prefix="/executors", tags=["executors"])


class ExecutorRunRequest(BaseModel):
    """执行请求。"""

    plugin_key: str = Field(..., min_length=1, description="插件标识")
    command: str = Field(..., min_length=1, description="命令文本")
    readonly: bool = Field(default=True, description="是否只读执行")
    timeout_seconds: int = Field(default=20, ge=1, le=120, description="超时时间")
    task_id: str | None = Field(default=None, description="关联任务 ID")
    operator: str = Field(default="system", description="操作人")
    approval_ticket: str = Field(default="", description="写操作审批单")


class ExecutorPluginPatchRequest(BaseModel):
    """插件配置更新请求。"""

    enabled: bool | None = Field(default=None, description="是否启用")
    write_enabled: bool | None = Field(default=None, description="是否打开写操作入口")
    approval_ticket: str = Field(default="", description="写操作审批单")


@router.get("/status")
async def get_executor_status(
    limit: int = 30,
    executor_service=Depends(get_executor_service_dep),
):
    if not executor_service:
        raise HTTPException(status_code=409, detail="执行插件服务未初始化")

    safe_limit = max(1, min(limit, 200))
    return executor_service.get_status(recent_limit=safe_limit)


@router.get("/readonly-command-packs")
async def list_executor_readonly_command_packs(
    plugin_key: str | None = None,
    executor_service=Depends(get_executor_service_dep),
):
    if not executor_service:
        raise HTTPException(status_code=409, detail="执行插件服务未初始化")

    try:
        return executor_service.list_readonly_command_packs(plugin_key=plugin_key)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "不存在" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/run")
async def run_executor(
    payload: ExecutorRunRequest,
    executor_service=Depends(get_executor_service_dep),
):
    if not executor_service:
        raise HTTPException(status_code=409, detail="执行插件服务未初始化")

    try:
        return executor_service.run(
            plugin_key=payload.plugin_key,
            command=payload.command,
            readonly=payload.readonly,
            timeout_seconds=payload.timeout_seconds,
            task_id=payload.task_id,
            operator=payload.operator,
            approval_ticket=payload.approval_ticket,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "不存在" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.patch("/plugins/{plugin_key}")
async def patch_executor_plugin(
    plugin_key: str,
    payload: ExecutorPluginPatchRequest,
    executor_service=Depends(get_executor_service_dep),
):
    if not executor_service:
        raise HTTPException(status_code=409, detail="执行插件服务未初始化")
    if payload.enabled is None and payload.write_enabled is None:
        raise HTTPException(status_code=400, detail="至少更新一个字段")

    try:
        plugin = executor_service.update_plugin(
            plugin_key=plugin_key,
            enabled=payload.enabled,
            write_enabled=payload.write_enabled,
            approval_ticket=payload.approval_ticket,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "不存在" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc

    return {
        "message": "插件配置更新成功",
        "plugin": plugin,
    }
