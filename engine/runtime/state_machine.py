"""
任务状态机定义。

"""
from __future__ import annotations

from typing import Dict, Set

from .models import TaskStatus, TaskType


class TaskStateMachine:
    """任务状态机。"""

    DEFAULT_STAGE_BY_TYPE: Dict[TaskType, list[TaskStatus]] = {
        TaskType.DASHBOARD_REFRESH: [TaskStatus.PENDING, TaskStatus.COLLECTING, TaskStatus.COMPLETED],
        TaskType.INCIDENT_ANALYSIS: [TaskStatus.PENDING, TaskStatus.COLLECTING, TaskStatus.ANALYZING, TaskStatus.COMPLETED],
        TaskType.RECOMMENDATION_GENERATION: [
            TaskStatus.PENDING,
            TaskStatus.COLLECTING,
            TaskStatus.ANALYZING,
            TaskStatus.GENERATING,
            TaskStatus.WAITING_CONFIRM,
            TaskStatus.COMPLETED,
        ],
        TaskType.REPORT_GENERATION: [
            TaskStatus.PENDING,
            TaskStatus.COLLECTING,
            TaskStatus.ANALYZING,
            TaskStatus.GENERATING,
            TaskStatus.COMPLETED,
        ],
    }

    ALLOWED_TRANSITIONS: Dict[TaskStatus, Set[TaskStatus]] = {
        TaskStatus.PENDING: {TaskStatus.COLLECTING, TaskStatus.CANCELLED, TaskStatus.FAILED},
        TaskStatus.COLLECTING: {TaskStatus.ANALYZING, TaskStatus.GENERATING, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
        TaskStatus.ANALYZING: {TaskStatus.GENERATING, TaskStatus.WAITING_CONFIRM, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
        TaskStatus.GENERATING: {TaskStatus.WAITING_CONFIRM, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
        TaskStatus.WAITING_CONFIRM: {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED},
        TaskStatus.COMPLETED: set(),
        TaskStatus.FAILED: set(),
        TaskStatus.CANCELLED: set(),
    }

    @classmethod
    def can_transition(cls, current: TaskStatus, target: TaskStatus) -> bool:
        """判断状态是否允许流转。"""
        return target in cls.ALLOWED_TRANSITIONS.get(current, set())

    @classmethod
    def validate_transition(cls, current: TaskStatus, target: TaskStatus) -> None:
        """校验状态流转是否合法。"""
        if not cls.can_transition(current, target):
            raise ValueError(f"非法状态流转: {current} -> {target}")
