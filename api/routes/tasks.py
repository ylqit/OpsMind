"""任务接口。"""
from __future__ import annotations

import json
import mimetypes
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .deps import get_ai_writeback_repository_dep, get_task_manager

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskApproveRequest(BaseModel):
    """任务确认请求。"""

    approved_by: str = Field(default="operator", description="确认人")
    approval_note: str = Field(default="", description="确认备注")


def _status_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _read_trace_preview(task_id: str, task_manager, limit: int = 20) -> list[dict]:
    task_dir = task_manager.trace_store.tasks_base_dir / task_id
    trace_file = task_dir / "trace.jsonl"
    if not trace_file.exists():
        return []
    lines = trace_file.read_text(encoding="utf-8").splitlines()[-limit:]
    preview = []
    for line in lines:
        try:
            preview.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return preview


# 将失败任务聚合成可读诊断，给前端直接渲染，不要求用户再手工拼接 trace。
def _build_failure_diagnosis(task, trace_preview: list[dict], artifacts: list[Any]) -> dict[str, Any]:
    error = task.error
    status = _status_value(task.status)

    stage_counter = Counter(str(item.get("stage") or "unknown") for item in trace_preview)
    last_trace = trace_preview[-1] if trace_preview else None
    last_observation = (last_trace or {}).get("observation") if isinstance(last_trace, dict) else {}
    if not isinstance(last_observation, dict):
        last_observation = {}

    error_code = error.error_code if error else "TASK_CANCELLED"
    error_message = error.error_message if error else "任务被取消或提前终止"
    failed_stage = _status_value(error.failed_stage) if error and error.failed_stage else _status_value(task.current_stage)

    message_lower = error_message.lower()
    possible_causes: list[str] = []
    suggested_actions: list[str] = []
    retryable = True

    if status == "CANCELLED":
        possible_causes.append("任务被手动取消，未继续执行后续步骤。")
        suggested_actions.append("如果仍需结果，可重新发起同类型任务并保持任务窗口在线。")
        retryable = True

    if "timeout" in message_lower or "timed out" in message_lower or "超时" in error_message:
        possible_causes.append("外部依赖响应超时，任务在等待数据源返回时失败。")
        suggested_actions.append("检查 Prometheus、日志文件或外部 API 的可达性与响应时间。")
        suggested_actions.append("缩短时间窗后重试，确认是否为数据量过大导致超时。")

    if any(keyword in message_lower for keyword in ["connection", "connect", "refused", "dns", "network"]):
        possible_causes.append("网络链路异常或目标服务不可达。")
        suggested_actions.append("检查网络连通性、DNS 解析和目标服务端口状态。")

    if any(keyword in message_lower for keyword in ["permission", "forbidden", "denied", "unauthorized"]):
        possible_causes.append("权限或鉴权配置不足，任务无权访问目标资源。")
        suggested_actions.append("核对凭据、角色权限和 API Key 是否可用。")
        retryable = False

    if any(keyword in message_lower for keyword in ["not found", "missing", "404"]):
        possible_causes.append("依赖资源不存在或路径配置错误。")
        suggested_actions.append("检查 service_key、资产 ID、日志路径与数据源配置。")

    if error_code == "TASK_RUNNER_ERROR":
        possible_causes.append("任务执行器在运行阶段抛出异常，需结合 trace 定位具体步骤。")
        suggested_actions.append("优先查看 Trace 最后一条记录，定位失败动作与输入参数。")

    if failed_stage == "COLLECTING":
        suggested_actions.append("优先检查数据源配置与采集链路是否正常。")
    elif failed_stage == "ANALYZING":
        suggested_actions.append("检查分析规则输入是否完整，并核对异常样本格式。")
    elif failed_stage == "GENERATING":
        suggested_actions.append("检查生成模板、参数映射和产物写入目录权限。")

    if not possible_causes:
        possible_causes.append("未匹配到明确模式，建议结合 trace 与错误堆栈继续排查。")
    if not suggested_actions:
        suggested_actions.append("先查看任务 trace 与最近产物，再按失败阶段逐层回放执行链路。")

    artifact_hints = [
        f"{artifact.kind}: {Path(artifact.path).name}"
        for artifact in artifacts[:6]
    ]

    return {
        "task_id": task.task_id,
        "status": status,
        "retryable": retryable,
        "error": {
            "error_code": error_code,
            "error_message": error_message,
            "failed_stage": failed_stage,
        },
        "trace_stats": {
            "total_steps": len(trace_preview),
            "stages": dict(stage_counter),
            "last_step": {
                "step": str((last_trace or {}).get("step") or "-"),
                "action": str((last_trace or {}).get("action") or "-"),
                "stage": str((last_trace or {}).get("stage") or "-"),
                "summary": str(last_observation.get("summary") or "-"),
                "created_at": str((last_trace or {}).get("created_at") or "-"),
            } if last_trace else None,
        },
        "artifact_count": len(artifacts),
        "artifact_hints": artifact_hints,
        "possible_causes": list(dict.fromkeys(possible_causes))[:6],
        "suggested_actions": list(dict.fromkeys(suggested_actions))[:8],
    }


# 按类型和关键词做轻量筛选，便于前端在任务内快速检索目标产物。
def _filter_artifacts(artifacts: list[Any], kind: str | None = None, query: str | None = None) -> list[Any]:
    filtered = artifacts
    normalized_kind = (kind or "").strip().lower()
    normalized_query = (query or "").strip().lower()

    if normalized_kind:
        filtered = [artifact for artifact in filtered if str(artifact.kind).lower() == normalized_kind]

    if normalized_query:
        filtered = [
            artifact
            for artifact in filtered
            if normalized_query in str(artifact.path).lower()
            or normalized_query in str(artifact.preview).lower()
            or normalized_query in str(artifact.kind).lower()
        ]

    return filtered


# 分组结果直接携带分组内条目，前端无需二次聚合。
def _group_artifacts(artifacts: list[Any], group_by: str) -> list[dict[str, Any]]:
    if group_by == "none":
        return []

    grouped: dict[str, list[Any]] = defaultdict(list)
    for artifact in artifacts:
        key = str(artifact.kind or "unknown")
        grouped[key].append(artifact)

    groups = []
    for group_key in sorted(grouped.keys()):
        items = grouped[group_key]
        groups.append(
            {
                "group_key": group_key,
                "count": len(items),
                "items": [item.model_dump(mode="json") for item in items],
            }
        )
    return groups


def _require_artifact(task_id: str, artifact_id: str, task_manager):
    artifact = task_manager.artifact_repository.get(task_id, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="产物不存在")
    path = Path(artifact.path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="产物文件不存在")
    return artifact, path


@router.get("")
async def list_tasks(
    task_type: str | None = None,
    status: str | None = None,
    task_manager=Depends(get_task_manager),
):
    tasks = task_manager.list_tasks(task_type=task_type, status=status)
    return {"items": [task.model_dump(mode="json") for task in tasks], "total": len(tasks)}


@router.get("/{task_id}")
async def get_task_detail(
    task_id: str,
    task_manager=Depends(get_task_manager),
    writeback_repository=Depends(get_ai_writeback_repository_dep),
):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    trace_preview = _read_trace_preview(task_id, task_manager)
    artifacts = task_manager.list_artifacts(task_id)
    status = _status_value(task.status)
    failure_diagnosis = None
    if status in {"FAILED", "CANCELLED"}:
        failure_diagnosis = _build_failure_diagnosis(task, trace_preview, artifacts)
    return {
        "task": task.model_dump(mode="json"),
        "trace_preview": trace_preview,
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
        "failure_diagnosis": failure_diagnosis,
        "assistant_writebacks": [item.model_dump(mode="json") for item in (writeback_repository.list_by_task(task_id) if writeback_repository else [])],
    }


@router.get("/{task_id}/diagnosis")
async def get_task_diagnosis(task_id: str, task_manager=Depends(get_task_manager)):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    status = _status_value(task.status)
    if status not in {"FAILED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="仅失败或取消任务支持诊断")

    trace_preview = _read_trace_preview(task_id, task_manager, limit=80)
    artifacts = task_manager.list_artifacts(task_id)
    return _build_failure_diagnosis(task, trace_preview, artifacts)


@router.get("/{task_id}/artifacts")
async def list_task_artifacts(
    task_id: str,
    kind: str | None = None,
    query: str | None = None,
    group_by: str = "kind",
    task_manager=Depends(get_task_manager),
):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if group_by not in {"kind", "none"}:
        raise HTTPException(status_code=400, detail="group_by 仅支持 kind 或 none")

    artifacts = task_manager.list_artifacts(task_id)
    filtered_artifacts = _filter_artifacts(artifacts, kind=kind, query=query)
    grouped = _group_artifacts(filtered_artifacts, group_by=group_by)

    return {
        "items": [artifact.model_dump(mode="json") for artifact in filtered_artifacts],
        "total": len(artifacts),
        "filtered": len(filtered_artifacts),
        "kind": kind or "",
        "query": query or "",
        "group_by": group_by,
        "groups": grouped,
    }


@router.get("/{task_id}/artifacts/{artifact_id}")
async def get_task_artifact(task_id: str, artifact_id: str, task_manager=Depends(get_task_manager)):
    artifact, path = _require_artifact(task_id, artifact_id, task_manager)
    return {
        "artifact": artifact.model_dump(mode="json"),
        "filename": path.name,
        "download_url": f"/api/tasks/{task_id}/artifacts/{artifact_id}/download",
        "content_url": f"/api/tasks/{task_id}/artifacts/{artifact_id}/content",
    }


@router.get("/{task_id}/artifacts/{artifact_id}/content")
async def get_task_artifact_content(task_id: str, artifact_id: str, task_manager=Depends(get_task_manager)):
    artifact, path = _require_artifact(task_id, artifact_id, task_manager)
    content = path.read_text(encoding="utf-8")
    return {
        "artifact": artifact.model_dump(mode="json"),
        "filename": path.name,
        "content": content,
        "content_type": mimetypes.guess_type(path.name)[0] or "text/plain",
    }


@router.get("/{task_id}/artifacts/{artifact_id}/download")
async def download_task_artifact(task_id: str, artifact_id: str, task_manager=Depends(get_task_manager)):
    _, path = _require_artifact(task_id, artifact_id, task_manager)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.post("/{task_id}/approve")
async def approve_task(
    task_id: str,
    request: TaskApproveRequest | None = Body(default=None),
    task_manager=Depends(get_task_manager),
):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "WAITING_CONFIRM":
        raise HTTPException(status_code=409, detail="当前任务不处于待确认状态")
    approve_request = request or TaskApproveRequest()
    approved = await task_manager.approve_task(
        task_id,
        approved_by=approve_request.approved_by,
        approval_note=approve_request.approval_note,
    )
    return approved.model_dump(mode="json")


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, task_manager=Depends(get_task_manager)):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    cancelled = await task_manager.cancel_task(task_id)
    return cancelled.model_dump(mode="json")
