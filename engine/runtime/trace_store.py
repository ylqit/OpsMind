"""
任务 trace 文件落盘。

"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .models import TaskRecord, TraceRecord


class TraceStore:
    """Trace 文件存储。"""

    def __init__(self, tasks_base_dir: Path):
        self.tasks_base_dir = tasks_base_dir
        self.tasks_base_dir.mkdir(parents=True, exist_ok=True)

    def ensure_task_dir(self, task_id: str) -> Path:
        """确保任务目录存在。"""
        task_dir = self.tasks_base_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir

    def write_state(self, task: TaskRecord) -> None:
        """写入任务状态快照。"""
        task_dir = self.ensure_task_dir(task.task_id)
        (task_dir / "state.json").write_text(task.model_dump_json(indent=2), encoding="utf-8")

    def write_result(self, task_id: str, result: Dict[str, Any]) -> None:
        """写入任务结果。"""
        task_dir = self.ensure_task_dir(task_id)
        (task_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_trace(self, record: TraceRecord) -> None:
        """追加写入 trace 记录。"""
        task_dir = self.ensure_task_dir(record.task_id)
        trace_file = task_dir / "trace.jsonl"
        with trace_file.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json())
            handle.write("\n")
