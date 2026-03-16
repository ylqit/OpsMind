"""
任务管理器。

负责创建任务、驱动状态流转、写入 trace 和结果，并广播任务事件。
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional

from engine.runtime.artifact_store import ArtifactStore
from engine.runtime.errors import normalize_task_exception
from engine.runtime.event_bus import EventBus
from engine.runtime.models import (
    Observation,
    ObservationKind,
    TaskApproval,
    TaskError,
    TaskRecord,
    TaskStatus,
    TaskType,
    TraceRecord,
)
from engine.runtime.state_machine import TaskStateMachine
from engine.runtime.time_utils import utc_now
from engine.runtime.trace_store import TraceStore
from engine.storage.repositories import ArtifactRepository, TaskRepository


TaskRunner = Callable[[TaskRecord], Awaitable[Dict[str, Any]]]


class TaskManager:
    """任务管理器。"""

    def __init__(self, task_repository: TaskRepository, artifact_repository: ArtifactRepository, trace_store: TraceStore, artifact_store: ArtifactStore, event_bus: EventBus):
        self.task_repository = task_repository
        self.artifact_repository = artifact_repository
        self.trace_store = trace_store
        self.artifact_store = artifact_store
        self.event_bus = event_bus
        self._running_tasks: Dict[str, asyncio.Task] = {}

    def list_tasks(self, task_type: Optional[str] = None, status: Optional[str] = None) -> list[TaskRecord]:
        return self.task_repository.list(task_type=task_type, status=status)

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self.task_repository.get(task_id)

    def list_artifacts(self, task_id: str):
        return self.artifact_repository.list_by_task(task_id)

    async def create_task(self, task_type: TaskType, payload: Dict[str, Any], runner: TaskRunner) -> TaskRecord:
        task = TaskRecord(task_type=task_type, payload=payload)
        # 先落库和写初始状态，再启动后台协程，保证任务一创建就能被页面与恢复逻辑感知到。
        self.task_repository.save(task)
        self.trace_store.write_state(task)
        await self._publish("task_created", task)
        self._running_tasks[task.task_id] = asyncio.create_task(self._run_task(task.task_id, runner))
        return task

    async def approve_task(self, task_id: str, approved_by: str = "operator", approval_note: str = "") -> TaskRecord:
        task = self._require_task(task_id)
        TaskStateMachine.validate_transition(task.status, TaskStatus.COMPLETED)
        approval = TaskApproval(approved_by=approved_by.strip() or "operator", approval_note=approval_note.strip())
        task.status = TaskStatus.COMPLETED
        task.current_stage = TaskStatus.COMPLETED
        task.progress = 100
        task.progress_message = f"建议稿已确认，确认人：{approval.approved_by}"
        task.approval = approval
        task.completed_at = utc_now()
        task.updated_at = utc_now()
        self.task_repository.save(task)
        self.trace_store.write_state(task)
        self.trace_store.write_result(
            task_id,
            {
                "approved": True,
                "message": "建议稿已人工确认",
                "approval": approval.model_dump(mode="json"),
            },
        )
        # 审批动作追加进 trace，便于前端在任务详情里串联完整审计链路。
        await self.append_trace(
            task_id,
            "confirm",
            "approve_recommendation",
            TaskStatus.COMPLETED,
            f"建议稿已确认，确认人：{approval.approved_by}",
            {
                "approved_by": approval.approved_by,
                "approval_note": approval.approval_note,
                "approved_at": approval.approved_at.isoformat(),
            },
        )
        await self._publish("task_completed", task, extra={"approval": approval.model_dump(mode="json")})
        return task

    async def cancel_task(self, task_id: str) -> TaskRecord:
        task = self._require_task(task_id)
        if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            return task
        if TaskStateMachine.can_transition(task.status, TaskStatus.CANCELLED):
            task.status = TaskStatus.CANCELLED
            task.current_stage = TaskStatus.CANCELLED
            task.updated_at = utc_now()
            self.task_repository.save(task)
            self.trace_store.write_state(task)
            await self._publish("task_failed", task, extra={"message": "任务已取消"})
        running = self._running_tasks.pop(task_id, None)
        if running:
            running.cancel()
        return task

    async def set_stage(self, task_id: str, stage: TaskStatus, progress: int, message: str) -> TaskRecord:
        task = self._require_task(task_id)
        if task.status != stage:
            TaskStateMachine.validate_transition(task.status, stage)
        task.status = stage
        task.current_stage = stage
        task.progress = progress
        task.progress_message = message
        task.updated_at = utc_now()
        self.task_repository.save(task)
        self.trace_store.write_state(task)
        await self._publish("task_stage_changed", task, extra={"message": message})
        return task

    async def append_trace(self, task_id: str, step: str, action: str, stage: TaskStatus, summary: str, data: Optional[Dict[str, Any]] = None) -> None:
        task = self._require_task(task_id)
        record = TraceRecord(
            trace_id=task.trace_id,
            task_id=task_id,
            step=step,
            action=action,
            stage=stage,
            observation=Observation(kind=ObservationKind.INLINE, summary=summary, data=data),
        )
        self.trace_store.append_trace(record)
        # WebSocket 只广播轻量摘要，详细 trace 仍以文件和详情接口为准。
        await self._publish("task_progress", task, extra={"step": step, "action": action, "summary": summary, "data": data or {}})

    async def attach_artifact(self, task_id: str, artifact_ref) -> None:
        self.artifact_repository.save(artifact_ref)
        task = self._require_task(task_id)
        await self._publish("task_artifact_ready", task, extra={"artifact": artifact_ref.model_dump(mode="json")})

    async def wait_for_confirm(self, task_id: str, result_ref: Dict[str, Any]) -> TaskRecord:
        task = self._require_task(task_id)
        TaskStateMachine.validate_transition(task.status, TaskStatus.WAITING_CONFIRM)
        task.status = TaskStatus.WAITING_CONFIRM
        task.current_stage = TaskStatus.WAITING_CONFIRM
        task.progress = max(task.progress, 90)
        task.result_ref = result_ref
        task.progress_message = "建议稿已生成，等待人工确认"
        task.updated_at = utc_now()
        self.task_repository.save(task)
        self.trace_store.write_state(task)
        await self._publish("task_waiting_confirm", task)
        return task

    async def complete_task(self, task_id: str, result: Dict[str, Any]) -> TaskRecord:
        task = self._require_task(task_id)
        if task.status != TaskStatus.WAITING_CONFIRM:
            TaskStateMachine.validate_transition(task.status, TaskStatus.COMPLETED)
        task.status = TaskStatus.COMPLETED
        task.current_stage = TaskStatus.COMPLETED
        task.progress = 100
        task.result_ref = result
        task.progress_message = "任务执行完成"
        task.completed_at = utc_now()
        task.updated_at = utc_now()
        self.task_repository.save(task)
        self.trace_store.write_state(task)
        self.trace_store.write_result(task_id, result)
        await self._publish("task_completed", task)
        return task

    async def fail_task(self, task_id: str, error_code: str, error_message: str, failed_stage: TaskStatus) -> TaskRecord:
        task = self._require_task(task_id)
        if task.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.COMPLETED}:
            TaskStateMachine.validate_transition(task.status, TaskStatus.FAILED)
        task.status = TaskStatus.FAILED
        task.current_stage = TaskStatus.FAILED
        task.error = TaskError(error_code=error_code, error_message=error_message, failed_stage=failed_stage)
        task.progress_message = error_message
        task.updated_at = utc_now()
        self.task_repository.save(task)
        self.trace_store.write_state(task)
        await self._publish("task_failed", task, extra={"error": task.error.model_dump(mode="json")})
        return task

    async def _run_task(self, task_id: str, runner: TaskRunner) -> None:
        try:
            task = self._require_task(task_id)
            result = await runner(task)
            latest = self.get_task(task_id)
            # 建议稿进入人工确认后，后台协程不再覆盖最终状态，由审批动作闭环完成。
            if latest and latest.status not in {TaskStatus.WAITING_CONFIRM, TaskStatus.COMPLETED}:
                await self.complete_task(task_id, result)
        except asyncio.CancelledError:
            await self.cancel_task(task_id)
        except Exception as exc:
            latest = self.get_task(task_id)
            normalized = normalize_task_exception(exc, latest.current_stage if latest else TaskStatus.FAILED)
            await self.fail_task(
                task_id=task_id,
                error_code=normalized.error_code,
                error_message=normalized.error_message,
                failed_stage=normalized.failed_stage,
            )
        finally:
            self._running_tasks.pop(task_id, None)

    async def _publish(self, event_type: str, task: TaskRecord, extra: Optional[Dict[str, Any]] = None) -> None:
        # 统一任务事件载荷，前端任务中心、异常中心和建议中心都消费同一份结构。
        payload = {
            "type": event_type,
            "task_id": task.task_id,
            "task_type": task.task_type.value,
            "status": task.status.value,
            "current_stage": task.current_stage.value,
            "progress": task.progress,
            "progress_message": task.progress_message,
            "updated_at": task.updated_at.isoformat(),
        }
        if task.approval:
            payload["approval"] = task.approval.model_dump(mode="json")
        if extra:
            payload.update(extra)
        await self.event_bus.publish(payload)

    def _require_task(self, task_id: str) -> TaskRecord:
        task = self.task_repository.get(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")
        return task
