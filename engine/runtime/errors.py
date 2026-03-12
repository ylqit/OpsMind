"""任务执行错误标准化。"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from engine.runtime.models import TaskStatus


@dataclass
class NormalizedTaskError:
    """标准化后的任务错误。"""

    error_code: str
    error_message: str
    failed_stage: TaskStatus


class TaskExecutionError(Exception):
    """业务侧可显式抛出的任务错误。"""

    def __init__(self, error_code: str, error_message: str, failed_stage: TaskStatus | None = None):
        super().__init__(error_message)
        self.error_code = error_code
        self.error_message = error_message
        self.failed_stage = failed_stage


def normalize_task_exception(exc: Exception, default_stage: TaskStatus) -> NormalizedTaskError:
    """把异常统一映射到可审计的任务错误结构。"""
    if isinstance(exc, TaskExecutionError):
        return NormalizedTaskError(
            error_code=str(exc.error_code or "TASK_EXECUTION_ERROR"),
            error_message=str(exc.error_message or "任务执行失败"),
            failed_stage=exc.failed_stage or default_stage,
        )

    if isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout)):
        return NormalizedTaskError(
            error_code="TASK_TIMEOUT",
            error_message=str(exc) or "任务执行超时",
            failed_stage=default_stage,
        )

    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code if exc.response is not None else 0
        return NormalizedTaskError(
            error_code=f"TASK_HTTP_{status_code}",
            error_message=str(exc),
            failed_stage=default_stage,
        )

    if isinstance(exc, ValueError):
        return NormalizedTaskError(
            error_code="TASK_VALIDATION_ERROR",
            error_message=str(exc) or "任务输入或中间结果校验失败",
            failed_stage=default_stage,
        )

    if isinstance(exc, RuntimeError):
        return NormalizedTaskError(
            error_code="TASK_RUNTIME_ERROR",
            error_message=str(exc) or "任务运行失败",
            failed_stage=default_stage,
        )

    return NormalizedTaskError(
        error_code="TASK_UNKNOWN_ERROR",
        error_message=str(exc) or "任务未知异常",
        failed_stage=default_stage,
    )
