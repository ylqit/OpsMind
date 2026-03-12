"""任务接口。"""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .deps import get_task_manager

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskApproveRequest(BaseModel):
    """任务确认请求。"""

    approved_by: str = Field(default="operator", description="确认人")
    approval_note: str = Field(default="", description="确认备注")


def _read_trace_preview(task_id: str, task_manager) -> list[dict]:
    task_dir = task_manager.trace_store.tasks_base_dir / task_id
    trace_file = task_dir / "trace.jsonl"
    if not trace_file.exists():
        return []
    lines = trace_file.read_text(encoding="utf-8").splitlines()[-20:]
    preview = []
    for line in lines:
        try:
            preview.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return preview


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
async def get_task_detail(task_id: str, task_manager=Depends(get_task_manager)):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    artifacts = task_manager.list_artifacts(task_id)
    return {
        "task": task.model_dump(mode="json"),
        "trace_preview": _read_trace_preview(task_id, task_manager),
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
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
