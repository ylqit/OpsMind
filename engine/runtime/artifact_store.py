"""
Artifact 存储。

负责把大文本、草稿、报告等内容外部化到文件系统，并返回统一引用。
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .models import ArtifactKind, ArtifactRef, utc_now


class ArtifactStore:
    """任务产物文件存储。"""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def ensure_task_dirs(self, task_id: str) -> Path:
        """确保任务目录存在。"""
        task_dir = self.base_dir / task_id / "artifacts"
        task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir

    def write_text(self, task_id: str, kind: ArtifactKind, content: str, filename: str, preview_limit: int = 240) -> ArtifactRef:
        """写入文本产物并返回引用。"""
        task_dir = self.ensure_task_dirs(task_id)
        artifact_id = f"artifact_{uuid4().hex[:12]}"
        file_path = task_dir / filename
        file_path.write_text(content, encoding="utf-8")
        return ArtifactRef(
            artifact_id=artifact_id,
            task_id=task_id,
            kind=kind.value,
            path=str(file_path),
            preview=content[:preview_limit],
            size_bytes=len(content.encode("utf-8")),
            created_at=utc_now(),
        )

    def read_text(self, artifact: ArtifactRef) -> str:
        """读取文本产物内容。"""
        return Path(artifact.path).read_text(encoding="utf-8")
