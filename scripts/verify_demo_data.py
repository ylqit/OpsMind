"""opsMind 演示数据校验脚本。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# 允许从 scripts 目录直接执行：python scripts/verify_demo_data.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.storage.repositories import (  # noqa: E402
    AICallLogRepository,
    ArtifactRepository,
    AssetRepository,
    IncidentRepository,
    RecommendationFeedbackRepository,
    RecommendationRepository,
    SignalRepository,
    TaskRepository,
    UsageMetricsDailyRepository,
)
from engine.storage.sqlite import SQLiteDatabase  # noqa: E402
from scripts.seed_demo_data import (  # noqa: E402
    INCIDENT_ID,
    RECOMMENDATION_ID,
    SERVICE_KEY,
    TASK_ID,
)
from settings import RuntimeConfig  # noqa: E402


def _read_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def collect_demo_verification(config: RuntimeConfig) -> dict[str, Any]:
    """汇总当前演示数据是否完整，便于本地和 CI 做快速校验。"""
    config.ensure_directories()
    sqlite_path = config.sqlite_path or (config.data_dir / "opsmind.db")
    seed_log_path = (config.raw_log_dir or (config.data_dir / "raw_logs")) / "access.seed.log"
    task_dir = (config.tasks_dir or (config.data_dir / "tasks")) / TASK_ID

    db = SQLiteDatabase(sqlite_path)
    db.initialize()

    task_repository = TaskRepository(db)
    artifact_repository = ArtifactRepository(db)
    asset_repository = AssetRepository(db)
    signal_repository = SignalRepository(db)
    incident_repository = IncidentRepository(db)
    recommendation_repository = RecommendationRepository(db)
    feedback_repository = RecommendationFeedbackRepository(db)
    ai_call_log_repository = AICallLogRepository(db)
    metrics_repository = UsageMetricsDailyRepository(db)

    task = task_repository.get(TASK_ID)
    incident = incident_repository.get(INCIDENT_ID)
    recommendation = recommendation_repository.get(RECOMMENDATION_ID)
    artifacts = artifact_repository.list_by_task(TASK_ID)
    assets = asset_repository.list(service_key=SERVICE_KEY)
    signals = signal_repository.list(service_key=SERVICE_KEY)
    feedback_items = feedback_repository.list_by_recommendation(RECOMMENDATION_ID)
    ai_calls = ai_call_log_repository.list(provider_name="seed-provider", limit=10)

    metrics_date = task.created_at.date().isoformat() if task else ""
    metrics = (
        metrics_repository.list(
            start_date=metrics_date,
            end_date=metrics_date,
            service_key=SERVICE_KEY,
            model="seed-model",
        )
        if metrics_date
        else []
    )

    state_path = task_dir / "state.json"
    trace_path = task_dir / "trace.jsonl"
    artifact_entries: list[dict[str, Any]] = []
    missing_artifact_paths: list[str] = []
    for artifact in artifacts:
        artifact_path = Path(artifact.path)
        exists = artifact_path.exists() and artifact_path.stat().st_size > 0
        if not exists:
            missing_artifact_paths.append(str(artifact_path))
        artifact_entries.append(
            {
                "artifact_id": artifact.artifact_id,
                "kind": artifact.kind,
                "exists": exists,
                "size_bytes": artifact.size_bytes,
                "path": str(artifact_path),
            }
        )

    checks = {
        "sqlite_exists": sqlite_path.exists(),
        "seed_log_exists": seed_log_path.exists(),
        "task_exists": task is not None,
        "incident_exists": incident is not None,
        "recommendation_exists": recommendation is not None,
        "state_file_exists": state_path.exists(),
        "trace_file_exists": trace_path.exists(),
        "artifacts_ready": bool(artifacts) and not missing_artifact_paths,
        "ai_call_log_exists": bool(ai_calls),
        "metrics_exists": bool(metrics),
    }

    issues: list[str] = []
    if not checks["seed_log_exists"]:
        issues.append("缺少演示日志文件 access.seed.log")
    elif _read_line_count(seed_log_path) <= 0:
        issues.append("演示日志文件为空")

    if not checks["task_exists"]:
        issues.append(f"缺少任务 {TASK_ID}")
    if not checks["incident_exists"]:
        issues.append(f"缺少异常 {INCIDENT_ID}")
    if not checks["recommendation_exists"]:
        issues.append(f"缺少建议 {RECOMMENDATION_ID}")
    if not checks["state_file_exists"]:
        issues.append("缺少任务 state.json")
    if not checks["trace_file_exists"]:
        issues.append("缺少任务 trace.jsonl")
    if missing_artifact_paths:
        issues.append(f"存在缺失的 artifact 文件：{', '.join(missing_artifact_paths)}")
    if not checks["ai_call_log_exists"]:
        issues.append("缺少 AI 调用日志样本")
    if not checks["metrics_exists"]:
        issues.append("缺少 usage_metrics_daily 样本")

    ok = all(checks.values()) and not issues
    return {
        "ok": ok,
        "service_key": SERVICE_KEY,
        "sqlite_path": str(sqlite_path),
        "seed_log_path": str(seed_log_path),
        "task_dir": str(task_dir),
        "checks": checks,
        "counts": {
            "log_lines": _read_line_count(seed_log_path),
            "assets": len(assets),
            "signals": len(signals),
            "artifacts": len(artifacts),
            "feedback_items": len(feedback_items),
            "ai_call_logs": len(ai_calls),
            "usage_metrics": len(metrics),
        },
        "artifacts": artifact_entries,
        "issues": issues,
    }


def main() -> None:
    config = RuntimeConfig.load_from_env()
    summary = collect_demo_verification(config)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
