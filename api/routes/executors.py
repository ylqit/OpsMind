"""执行插件路由。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engine.runtime.models import ArtifactKind, TaskStatus

from .deps import get_executor_service_dep, get_task_manager

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


def _resolve_trace_stage(task) -> TaskStatus:
    stage_value = getattr(task, "current_stage", None)
    if isinstance(stage_value, TaskStatus):
        return stage_value
    normalized = str(stage_value or "").strip().upper()
    if normalized in TaskStatus.__members__:
        return TaskStatus[normalized]
    return TaskStatus.ANALYZING


async def _link_execution_to_task(
    task_manager,
    executor_service,
    task_id: str,
    run_result: dict,
) -> dict:
    normalized_task_id = (task_id or "").strip()
    if not normalized_task_id:
        return {"linked": False, "reason": "task_id_empty"}
    if not task_manager:
        return {"linked": False, "reason": "task_manager_unavailable"}

    task = task_manager.get_task(normalized_task_id)
    if not task:
        return {"linked": False, "reason": "task_not_found", "task_id": normalized_task_id}

    execution = run_result.get("execution") if isinstance(run_result.get("execution"), dict) else {}
    execution_id = str(execution.get("execution_id") or "").strip() or "unknown"
    execution_status = str(execution.get("status") or "").strip() or "unknown"
    plugin_key = str(execution.get("plugin_key") or "").strip() or "unknown"
    command = str(execution.get("command") or "").strip()
    duration_ms = int(execution.get("duration_ms") or 0)
    error_code = str(execution.get("error_code") or "").strip()
    error_message = str(execution.get("error_message") or "").strip()

    # 执行结果先规整成统一证据结构，再写入任务产物，保证后续页面可追溯。
    evidence_payload = (
        executor_service.build_execution_evidence(run_result)
        if hasattr(executor_service, "build_execution_evidence")
        else {
            "source": "executor_plugin",
            "execution": execution,
            "plugin": run_result.get("plugin") if isinstance(run_result.get("plugin"), dict) else {},
        }
    )
    artifact = task_manager.artifact_store.write_text(
        task_id=normalized_task_id,
        kind=ArtifactKind.JSON,
        content=json.dumps(evidence_payload, ensure_ascii=False, indent=2),
        filename=f"executor-{execution_id}.json",
    )
    await task_manager.attach_artifact(normalized_task_id, artifact)

    action_label = "执行成功" if execution_status == "success" else "执行完成"
    trace_summary = f"执行插件命令{action_label}：{plugin_key} {command}".strip()
    if execution_status in {"error", "timeout", "rejected", "circuit_open"}:
        trace_summary = f"执行插件命令失败：{plugin_key} {command}".strip()
    # trace 仅保留关键摘要与定位字段，避免把大文本直接塞进任务流。
    await task_manager.append_trace(
        normalized_task_id,
        "collect",
        "run_executor_command",
        _resolve_trace_stage(task),
        trace_summary,
        {
            "execution_id": execution_id,
            "plugin_key": plugin_key,
            "status": execution_status,
            "command": command,
            "duration_ms": duration_ms,
            "error_code": error_code,
            "error_message": error_message,
            "artifact_id": artifact.artifact_id,
            "artifact_path": artifact.path,
        },
    )
    return {
        "linked": True,
        "task_id": normalized_task_id,
        "artifact_id": artifact.artifact_id,
        "execution_id": execution_id,
    }


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
    task_manager=Depends(get_task_manager),
):
    if not executor_service:
        raise HTTPException(status_code=409, detail="执行插件服务未初始化")

    try:
        result = executor_service.run(
            plugin_key=payload.plugin_key,
            command=payload.command,
            readonly=payload.readonly,
            timeout_seconds=payload.timeout_seconds,
            task_id=payload.task_id,
            operator=payload.operator,
            approval_ticket=payload.approval_ticket,
        )
        if payload.task_id:
            try:
                result["task_evidence"] = await _link_execution_to_task(
                    task_manager=task_manager,
                    executor_service=executor_service,
                    task_id=payload.task_id,
                    run_result=result,
                )
            except Exception as exc:  # noqa: BLE001
                result["task_evidence"] = {
                    "linked": False,
                    "reason": "link_failed",
                    "message": str(exc),
                }
        else:
            result["task_evidence"] = {"linked": False, "reason": "task_id_missing"}
        return result
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
