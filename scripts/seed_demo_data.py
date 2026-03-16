"""opsMind 演示数据初始化脚本。"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from difflib import unified_diff
from pathlib import Path
from typing import Iterable

# 允许从 scripts 目录直接执行：python scripts/seed_demo_data.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.runtime.models import (
    AICallLog,
    AICallLogStatus,
    ArtifactRef,
    Asset,
    AssetType,
    Incident,
    IncidentStatus,
    Recommendation,
    RecommendationFeedback,
    RecommendationFeedbackAction,
    RecommendationKind,
    Signal,
    SignalType,
    TaskRecord,
    TaskStatus,
    TaskType,
    UsageMetricsDailyRecord,
)
from engine.storage.repositories import (
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
from engine.storage.sqlite import SQLiteDatabase
from settings import RuntimeConfig

TASK_ID = "task_seed_001"
TRACE_ID = "trace_seed_001"
INCIDENT_ID = "incident_seed_001"
RECOMMENDATION_ID = "rec_seed_001"
FEEDBACK_ID = "feedback_seed_001"
ASSET_HOST_ID = "asset_seed_host_001"
ASSET_CONTAINER_ID = "asset_seed_container_001"
SIGNAL_CPU_ID = "signal_seed_cpu_001"
SIGNAL_LOG_ID = "signal_seed_log_001"
SERVICE_KEY = "seed/demo-service"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _bool_env(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _format_access_line(
    ts: datetime,
    path: str,
    status: int,
    remote_addr: str,
    request_time: float,
    user_agent: str,
) -> str:
    timestamp = ts.astimezone(timezone.utc).strftime("%d/%b/%Y:%H:%M:%S +0000")
    return (
        f'{remote_addr} - - [{timestamp}] '
        f'"GET {path} HTTP/1.1" {status} 512 "-" "{user_agent}" {request_time:.3f}'
    )


def ensure_access_log(seed_log_path: Path, reset: bool) -> None:
    if seed_log_path.exists() and not reset:
        return

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    lines: list[str] = []
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127.0.0.0 Safari/537.36"

    for index in range(90):
        ts = now - timedelta(minutes=89 - index)
        status = 200
        path = "/api/orders"
        request_time = 0.08 + (index % 6) * 0.01
        remote_addr = f"10.0.0.{(index % 24) + 1}"

        # 每隔一段时间注入 5xx 和高延迟，便于流量/异常页面直接展示热点。
        if 58 <= index <= 74 and index % 4 == 0:
            status = 502
            path = "/api/pay"
            request_time = 0.24 + (index % 3) * 0.06

        lines.append(_format_access_line(ts, path, status, remote_addr, request_time, ua))

    _write_text(seed_log_path, "\n".join(lines) + "\n")


def _build_manifest_files(task_dir: Path) -> tuple[ArtifactRef, ArtifactRef, ArtifactRef, ArtifactRef]:
    # 同时生成基线、建议稿、diff 和 metadata，保证建议中心三视图在演示环境里完整可见。
    baseline_content = (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: demo-service\n"
        "spec:\n"
        "  replicas: 1\n"
        "  template:\n"
        "    spec:\n"
        "      containers:\n"
        "      - name: demo-service\n"
        "        image: nginx:latest\n"
        "        resources:\n"
        "          requests:\n"
        "            cpu: 100m\n"
        "            memory: 128Mi\n"
        "          limits:\n"
        "            cpu: 500m\n"
        "            memory: 512Mi\n"
    )
    recommended_content = (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: demo-service\n"
        "spec:\n"
        "  replicas: 2\n"
        "  template:\n"
        "    spec:\n"
        "      containers:\n"
        "      - name: demo-service\n"
        "        image: nginx:latest\n"
        "        resources:\n"
        "          requests:\n"
        "            cpu: 300m\n"
        "            memory: 256Mi\n"
        "          limits:\n"
        "            cpu: 1000m\n"
        "            memory: 1Gi\n"
    )
    diff_content = "\n".join(
        unified_diff(
            baseline_content.splitlines(),
            recommended_content.splitlines(),
            fromfile="demo-service-baseline.yaml",
            tofile="demo-service-recommended.yaml",
            lineterm="",
        )
    ) + "\n"

    metadata_content = json.dumps(
        {
            "schema_version": "v1",
            "generated_at": _utc_now().isoformat() + "Z",
            "baseline": {
                "filename": "demo-service-baseline.yaml",
                "line_count": 18,
                "document_count": 1,
                "resource_types": [{"kind": "Deployment", "count": 1}],
            },
            "recommended": {
                "filename": "demo-service-recommended.yaml",
                "line_count": 18,
                "document_count": 1,
                "resource_types": [{"kind": "Deployment", "count": 1}],
            },
            "diff": {
                "filename": "demo-service-changes.diff",
                "added_lines": 5,
                "removed_lines": 5,
                "hunk_count": 2,
                "total_changed_lines": 10,
                "change_level": "medium",
            },
            "risk_rules": ["scale_replicas_cap_4", "manifest_requires_manual_review"],
            "risk_summary": {
                "level": "medium",
                "score": 4,
                "review_required": True,
                "highlights": ["涉及副本与资源配额调整"],
            },
        },
        ensure_ascii=False,
        indent=2,
    )

    baseline_path = task_dir / "artifacts" / "demo-service-baseline.yaml"
    recommended_path = task_dir / "artifacts" / "demo-service-recommended.yaml"
    diff_path = task_dir / "artifacts" / "demo-service-changes.diff"
    meta_path = task_dir / "artifacts" / "demo-service-manifest-meta.json"

    _write_text(baseline_path, baseline_content)
    _write_text(recommended_path, recommended_content)
    _write_text(diff_path, diff_content)
    _write_text(meta_path, metadata_content + "\n")

    now = _utc_now()
    return (
        ArtifactRef(
            artifact_id="artifact_seed_baseline_001",
            task_id=TASK_ID,
            kind="manifest",
            path=str(baseline_path),
            preview="demo-service 基线 YAML",
            size_bytes=baseline_path.stat().st_size,
            created_at=now,
        ),
        ArtifactRef(
            artifact_id="artifact_seed_recommended_001",
            task_id=TASK_ID,
            kind="manifest",
            path=str(recommended_path),
            preview="demo-service 建议 YAML",
            size_bytes=recommended_path.stat().st_size,
            created_at=now,
        ),
        ArtifactRef(
            artifact_id="artifact_seed_diff_001",
            task_id=TASK_ID,
            kind="diff",
            path=str(diff_path),
            preview="新增 5 行，删除 5 行，变更块 2 处",
            size_bytes=diff_path.stat().st_size,
            created_at=now,
        ),
        ArtifactRef(
            artifact_id="artifact_seed_meta_001",
            task_id=TASK_ID,
            kind="json",
            path=str(meta_path),
            preview="manifest 元数据",
            size_bytes=meta_path.stat().st_size,
            created_at=now,
        ),
    )


def _write_trace_files(task_dir: Path, created_at: datetime) -> None:
    state_payload = {
        "task_id": TASK_ID,
        "task_type": TaskType.RECOMMENDATION_GENERATION.value,
        "status": TaskStatus.WAITING_CONFIRM.value,
        "current_stage": TaskStatus.WAITING_CONFIRM.value,
        "progress": 90,
        "progress_message": "建议草稿已生成，等待人工确认",
        "trace_id": TRACE_ID,
        "payload": {"incident_id": INCIDENT_ID, "service_key": SERVICE_KEY},
        "result_ref": {
            "incident_id": INCIDENT_ID,
            "recommendations": [{"recommendation_id": RECOMMENDATION_ID, "kind": RecommendationKind.MANIFEST_DRAFT.value}],
            "guardrail_summary": {
                "total": 1,
                "fallback_count": 0,
                "retried_count": 1,
                "schema_error_count": 0,
                "has_degraded": False,
            },
        },
        "created_at": created_at.isoformat(),
        "updated_at": created_at.isoformat(),
        "completed_at": None,
    }
    _write_text(task_dir / "state.json", json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n")

    trace_records: Iterable[dict[str, object]] = (
        {
            "trace_id": TRACE_ID,
            "task_id": TASK_ID,
            "step": "collect",
            "action": "collect_incident_context",
            "stage": TaskStatus.COLLECTING.value,
            "observation": {"kind": "inline", "summary": "已完成 incident 上下文采集"},
            "created_at": created_at.isoformat(),
        },
        {
            "trace_id": TRACE_ID,
            "task_id": TASK_ID,
            "step": "generate",
            "action": "generate_recommendation",
            "stage": TaskStatus.GENERATING.value,
            "observation": {"kind": "inline", "summary": "已生成推荐草稿与差异文件"},
            "created_at": (created_at + timedelta(seconds=8)).isoformat(),
        },
    )
    trace_content = "\n".join(json.dumps(item, ensure_ascii=False) for item in trace_records) + "\n"
    _write_text(task_dir / "trace.jsonl", trace_content)


def seed_sqlite(config: RuntimeConfig, reset: bool) -> bool:
    db = SQLiteDatabase(config.sqlite_path or (config.data_dir / "opsmind.db"))
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

    if not reset and task_repository.get(TASK_ID) and incident_repository.get(INCIDENT_ID) and recommendation_repository.get(RECOMMENDATION_ID):
        return False

    task_dir = (config.tasks_dir or (config.data_dir / "tasks")) / TASK_ID
    if reset and task_dir.exists():
        shutil.rmtree(task_dir, ignore_errors=True)

    created_at = _utc_now().replace(microsecond=0)
    now = _utc_now()

    assets = [
        Asset(
            asset_id=ASSET_HOST_ID,
            asset_type=AssetType.HOST,
            name="seed-host",
            service_key=SERVICE_KEY,
            health_status="healthy",
            labels={"env": "seed", "role": "host"},
            source_refs={"source": "seed"},
            created_at=created_at,
            updated_at=created_at,
        ),
        Asset(
            asset_id=ASSET_CONTAINER_ID,
            asset_type=AssetType.CONTAINER,
            name="demo-service-1",
            service_key=SERVICE_KEY,
            health_status="warning",
            labels={"env": "seed", "role": "container"},
            source_refs={"source": "seed"},
            created_at=created_at,
            updated_at=created_at,
        ),
    ]
    for asset in assets:
        asset_repository.save(asset)

    signals = [
        Signal(
            signal_id=SIGNAL_CPU_ID,
            signal_type=SignalType.METRIC,
            timestamp=now - timedelta(minutes=12),
            asset_id=ASSET_CONTAINER_ID,
            service_key=SERVICE_KEY,
            severity="warning",
            payload={"metric": "cpu_usage", "value": 86, "unit": "%"},
            source="seed",
            created_at=created_at,
        ),
        Signal(
            signal_id=SIGNAL_LOG_ID,
            signal_type=SignalType.LOG,
            timestamp=now - timedelta(minutes=10),
            asset_id=ASSET_CONTAINER_ID,
            service_key=SERVICE_KEY,
            severity="warning",
            payload={"status": 502, "path": "/api/pay", "latency_ms": 280},
            source="seed",
            created_at=created_at,
        ),
    ]
    for signal in signals:
        signal_repository.save(signal)

    incident = Incident(
        incident_id=INCIDENT_ID,
        title="入口 5xx 波动（演示数据）",
        severity="warning",
        status=IncidentStatus.OPEN,
        time_window_start=now - timedelta(hours=1),
        time_window_end=now,
        service_key=SERVICE_KEY,
        related_asset_ids=[ASSET_CONTAINER_ID],
        evidence_refs=[
            {
                "evidence_id": "ev_seed_log_001",
                "layer": "traffic",
                "type": "log",
                "source_type": "log_snippet",
                "title": "/api/pay 错误样本",
                "summary": "在 10 分钟窗口内出现多次 502。",
                "metric": "5xx_rate",
                "value": 6.4,
                "unit": "%",
                "priority": 90,
                "signal_strength": "high",
                "source_ref": {
                    "service_key": SERVICE_KEY,
                    "path": "/api/pay",
                    "status": 502,
                    "timestamp": (now - timedelta(minutes=10)).isoformat(),
                },
                "tags": ["seed", "traffic"],
            },
            {
                "evidence_id": "ev_seed_cpu_001",
                "layer": "resource",
                "type": "metric",
                "source_type": "metric_snapshot",
                "title": "容器 CPU 偏高",
                "summary": "demo-service-1 CPU 使用率在高峰期达到 86%。",
                "metric": "cpu_usage",
                "value": 86,
                "unit": "%",
                "priority": 82,
                "signal_strength": "medium",
                "source_ref": {
                    "service_key": SERVICE_KEY,
                    "asset_ids": [ASSET_CONTAINER_ID],
                    "timestamp": (now - timedelta(minutes=12)).isoformat(),
                },
                "tags": ["seed", "resource"],
            },
        ],
        summary="入口错误率与资源压力同时上升，建议先扩容并观察错误率回落情况。",
        confidence=0.78,
        recommended_actions=["先扩容 1 个副本", "观察 10 分钟错误率变化", "必要时追加入口限流"],
        reasoning_tags=["traffic_spike", "resource_bottleneck"],
        created_at=created_at,
        updated_at=created_at,
    )
    incident_repository.save(incident)

    task = TaskRecord(
        task_id=TASK_ID,
        task_type=TaskType.RECOMMENDATION_GENERATION,
        status=TaskStatus.WAITING_CONFIRM,
        current_stage=TaskStatus.WAITING_CONFIRM,
        progress=90,
        progress_message="建议草稿已生成，等待人工确认",
        trace_id=TRACE_ID,
        payload={"incident_id": INCIDENT_ID, "service_key": SERVICE_KEY},
        result_ref={
            "incident_id": INCIDENT_ID,
            "recommendations": [{"recommendation_id": RECOMMENDATION_ID, "kind": RecommendationKind.MANIFEST_DRAFT.value}],
            "guardrail_summary": {
                "total": 1,
                "fallback_count": 0,
                "retried_count": 1,
                "schema_error_count": 0,
                "has_degraded": False,
            },
        },
        created_at=created_at,
        updated_at=created_at,
    )
    task_repository.save(task)
    _write_trace_files(task_dir, created_at)

    artifacts = _build_manifest_files(task_dir)
    for artifact in artifacts:
        artifact_repository.save(artifact)

    recommendation = Recommendation(
        recommendation_id=RECOMMENDATION_ID,
        incident_id=INCIDENT_ID,
        target_asset_id=ASSET_CONTAINER_ID,
        kind=RecommendationKind.MANIFEST_DRAFT,
        confidence=0.82,
        observation="高峰时段 5xx 与 CPU 压力同步上升。",
        recommendation="建议副本数从 1 调整到 2，并提升 requests/limits 后观察 10 分钟。",
        risk_note="该草稿仅用于评审，应用前需人工确认并保留回滚方案。",
        artifact_refs=[artifact.model_dump(mode="json") for artifact in artifacts],
        created_at=created_at,
        updated_at=created_at,
    )
    recommendation_repository.save(recommendation)

    feedback_repository.save(
        RecommendationFeedback(
            feedback_id=FEEDBACK_ID,
            recommendation_id=RECOMMENDATION_ID,
            incident_id=INCIDENT_ID,
            task_id=TASK_ID,
            action=RecommendationFeedbackAction.ADOPT,
            reason_code="seed_demo",
            comment="演示数据：该建议可用于评审链路展示。",
            operator="seed-bot",
            created_at=created_at,
        )
    )

    ai_call_log_repository.save(
        AICallLog(
            call_id="llm_call_seed_001",
            provider_name="seed-provider",
            model="seed-model",
            source="seed",
            endpoint="recommendation_generation",
            task_id=TASK_ID,
            prompt_preview="seed prompt",
            response_preview="seed response",
            status=AICallLogStatus.SUCCESS,
            latency_ms=1200,
            request_tokens=300,
            response_tokens=180,
            created_at=created_at,
        )
    )

    metrics_repository.upsert(
        UsageMetricsDailyRecord(
            metric_date=created_at.date().isoformat(),
            service_key=SERVICE_KEY,
            model="seed-model",
            provider_name="seed-provider",
            ai_call_total=1,
            ai_error_count=0,
            ai_success_count=1,
            ai_avg_latency_ms=1200.0,
            ai_total_tokens=480,
            ai_total_cost=0.01,
            ai_timeout_count=0,
            guardrail_fallback_count=0,
            guardrail_retried_count=1,
            guardrail_schema_error_count=0,
            updated_at=created_at,
        )
    )

    return True


def main() -> None:
    config = RuntimeConfig.load_from_env()
    config.ensure_directories()

    enable_seed = _bool_env("ENABLE_SEED", True)
    if not enable_seed:
        print("[seed] ENABLE_SEED=false，跳过演示数据初始化。")
        return

    reset = _bool_env("SEED_RESET", False)
    seed_log_path = (config.raw_log_dir or (config.data_dir / "raw_logs")) / "access.seed.log"
    ensure_access_log(seed_log_path, reset=reset)

    inserted = seed_sqlite(config, reset=reset)
    if inserted:
        print(f"[seed] 演示数据已写入：{config.sqlite_path}")
        print(f"[seed] 日志样本已准备：{seed_log_path}")
    else:
        print("[seed] 检测到已有演示数据，保持现状。")


if __name__ == "__main__":
    main()
