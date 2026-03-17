"""执行插件路由。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engine.runtime.models import ArtifactKind, TaskStatus

from .deps import (
    get_analysis_session_repository_dep,
    get_executor_service_dep,
    get_incident_service,
    get_recommendation_service,
    get_task_manager,
)

router = APIRouter(prefix="/executors", tags=["executors"])


class ExecutorExecutionContextRequest(BaseModel):
    """执行上下文请求，默认本地执行。"""

    mode: str = Field(default="local", description="执行模式：local | remote")
    remote_kind: str = Field(default="", description="远程执行类型")
    remote_target: str = Field(default="", description="远程目标标识")
    remote_namespace: str = Field(default="", description="远程命名空间")


class ExecutorRunRequest(BaseModel):
    """执行请求。"""

    plugin_key: str = Field(..., min_length=1, description="插件标识")
    command: str = Field(..., min_length=1, description="命令文本")
    readonly: bool = Field(default=True, description="是否只读执行")
    timeout_seconds: int = Field(default=20, ge=1, le=120, description="超时时间")
    task_id: str | None = Field(default=None, description="关联任务 ID")
    operator: str = Field(default="system", description="操作人")
    approval_ticket: str = Field(default="", description="写操作审批单")
    session_id: str | None = Field(default=None, description="关联分析会话 ID")
    execution_context: ExecutorExecutionContextRequest | None = Field(default=None, description="执行上下文")


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


def _link_execution_to_analysis_session(
    analysis_session_repository,
    session_id: str,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    normalized_session_id = (session_id or "").strip()
    if not normalized_session_id:
        return {"linked": False, "reason": "session_id_empty"}
    if not analysis_session_repository:
        return {"linked": False, "reason": "analysis_session_repository_unavailable"}

    session = analysis_session_repository.get(normalized_session_id)
    if not session:
        return {"linked": False, "reason": "session_not_found", "session_id": normalized_session_id}

    execution = run_result.get("execution") if isinstance(run_result.get("execution"), dict) else {}
    execution_id = str(execution.get("execution_id") or "").strip()
    if not execution_id:
        return {"linked": False, "reason": "execution_id_missing", "session_id": normalized_session_id}

    next_ids = list(session.executor_result_ids)
    if execution_id not in next_ids:
        next_ids.append(execution_id)
    latest = analysis_session_repository.update(
        normalized_session_id,
        {"executor_result_ids": next_ids},
    )
    if not latest:
        return {"linked": False, "reason": "session_update_failed", "session_id": normalized_session_id}

    return {
        "linked": True,
        "session_id": normalized_session_id,
        "execution_id": execution_id,
        "executor_result_ids": latest.executor_result_ids,
        "service_key": latest.service_key,
        "time_range": latest.time_range,
    }


def _resolve_recommended_command_context(
    *,
    analysis_session_repository,
    incident_service,
    recommendation_service,
    session_id: str | None,
    incident_id: str | None,
    recommendation_id: str | None,
) -> dict[str, Any]:
    session = analysis_session_repository.get(session_id) if analysis_session_repository and session_id else None

    resolved_recommendation_id = str(recommendation_id or (session.recommendation_id if session else "") or "").strip()
    recommendation = None
    if recommendation_service and resolved_recommendation_id:
        recommendation = recommendation_service.repository.get(resolved_recommendation_id)

    resolved_incident_id = str(
        incident_id
        or (session.incident_id if session else "")
        or (recommendation.incident_id if recommendation else "")
        or ""
    ).strip()
    incident = incident_service.get_incident(resolved_incident_id) if incident_service and resolved_incident_id else None

    service_key = str(
        (session.service_key if session else "")
        or (incident.service_key if incident else "")
        or ""
    ).strip()
    time_range = str((session.time_range if session else "") or "1h").strip() or "1h"

    return {
        "session": session,
        "incident": incident,
        "recommendation": recommendation,
        "service_key": service_key,
        "time_range": time_range,
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


@router.get("/recommended-command-packs")
async def list_executor_recommended_command_packs(
    session_id: str | None = None,
    incident_id: str | None = None,
    recommendation_id: str | None = None,
    plugin_key: str | None = None,
    limit: int = 8,
    executor_service=Depends(get_executor_service_dep),
    analysis_session_repository=Depends(get_analysis_session_repository_dep),
    incident_service=Depends(get_incident_service),
    recommendation_service=Depends(get_recommendation_service),
):
    if not executor_service:
        raise HTTPException(status_code=409, detail="执行插件服务未初始化")

    try:
        context = _resolve_recommended_command_context(
            analysis_session_repository=analysis_session_repository,
            incident_service=incident_service,
            recommendation_service=recommendation_service,
            session_id=session_id,
            incident_id=incident_id,
            recommendation_id=recommendation_id,
        )
        return executor_service.recommend_readonly_command_packs(
            session=context["session"],
            incident=context["incident"],
            recommendation=context["recommendation"],
            service_key=context["service_key"],
            time_range=context["time_range"],
            plugin_key=plugin_key,
            limit=limit,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "不存在" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/run")
async def run_executor(
    payload: ExecutorRunRequest,
    executor_service=Depends(get_executor_service_dep),
    task_manager=Depends(get_task_manager),
    analysis_session_repository=Depends(get_analysis_session_repository_dep),
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
            execution_context=payload.execution_context.model_dump() if payload.execution_context else None,
        )
        result["evidence"] = executor_service.build_execution_evidence(result)
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
        if payload.session_id:
            result["analysis_session"] = _link_execution_to_analysis_session(
                analysis_session_repository=analysis_session_repository,
                session_id=payload.session_id,
                run_result=result,
            )
        else:
            result["analysis_session"] = {"linked": False, "reason": "session_id_missing"}
        return result
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "不存在" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.get("/executions/{execution_id}")
async def get_executor_execution(
    execution_id: str,
    executor_service=Depends(get_executor_service_dep),
):
    if not executor_service:
        raise HTTPException(status_code=409, detail="执行插件服务未初始化")
    try:
        return executor_service.get_execution_detail(execution_id)
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
