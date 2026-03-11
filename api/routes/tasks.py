"""任务接口。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from .deps import get_task_manager

router = APIRouter(prefix="/tasks", tags=["tasks"])


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


@router.post("/{task_id}/approve")
async def approve_task(task_id: str, task_manager=Depends(get_task_manager)):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "WAITING_CONFIRM":
        raise HTTPException(status_code=409, detail="当前任务不处于待确认状态")
    approved = await task_manager.approve_task(task_id)
    return approved.model_dump(mode="json")


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, task_manager=Depends(get_task_manager)):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    cancelled = await task_manager.cancel_task(task_id)
    return cancelled.model_dump(mode="json")
