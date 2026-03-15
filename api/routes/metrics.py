"""质量指标看板接口。"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from engine.runtime.models import UsageMetricsDailyRecord

from .deps import (
    get_ai_call_log_repository_dep,
    get_incident_service,
    get_recommendation_feedback_repository_dep,
    get_task_manager,
    get_usage_metrics_daily_repository_dep,
)

router = APIRouter(prefix="/metrics", tags=["metrics"])

MODEL_COST_PER_1K_TOKENS = {
    "qwen3.5-plus": 0.004,
    "qwen-plus": 0.004,
    "qwen-max": 0.02,
    "gpt-4o-mini": 0.0006,
    "gpt-4.1-mini": 0.0008,
}
DEFAULT_COST_PER_1K_TOKENS = 0.002


def _parse_day(value: str, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} 格式必须为 YYYY-MM-DD") from exc


def _resolve_time_range(
    start_date: str | None,
    end_date: str | None,
    fallback_days: int = 7,
) -> tuple[date, date, datetime, datetime]:
    today = datetime.utcnow().date()

    if start_date and end_date:
        start_day = _parse_day(start_date, "start_date")
        end_day = _parse_day(end_date, "end_date")
    elif start_date:
        start_day = _parse_day(start_date, "start_date")
        end_day = start_day + timedelta(days=fallback_days - 1)
    elif end_date:
        end_day = _parse_day(end_date, "end_date")
        start_day = end_day - timedelta(days=fallback_days - 1)
    else:
        end_day = today
        start_day = end_day - timedelta(days=fallback_days - 1)

    if start_day > end_day:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")

    start_dt = datetime.combine(start_day, datetime.min.time())
    end_dt_exclusive = datetime.combine(end_day + timedelta(days=1), datetime.min.time())
    return start_day, end_day, start_dt, end_dt_exclusive


def _status_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def _cost_per_1k_tokens(model: str) -> float:
    normalized_model = model.lower()
    for key, value in MODEL_COST_PER_1K_TOKENS.items():
        if key in normalized_model:
            return value
    return DEFAULT_COST_PER_1K_TOKENS


def _normalize_counter(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _extract_guardrail_counters(task) -> dict[str, int]:
    result_ref = task.result_ref if isinstance(task.result_ref, dict) else {}
    guardrail_summary = result_ref.get("guardrail_summary") if isinstance(result_ref, dict) else {}
    if not isinstance(guardrail_summary, dict):
        guardrail_summary = {}
    return {
        "guardrail_fallback_count": _normalize_counter(guardrail_summary.get("fallback_count")),
        "guardrail_retried_count": _normalize_counter(guardrail_summary.get("retried_count")),
        "guardrail_schema_error_count": _normalize_counter(guardrail_summary.get("schema_error_count")),
    }


def _is_timeout_error(log) -> bool:
    error_code = str(log.error_code or "").strip().upper()
    error_message = str(log.error_message or "").strip().upper()
    return "TIMEOUT" in error_code or "TIMEOUT" in error_message


def _resolve_model_version(model_name: str) -> str:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return "unknown"
    for sep in ("@", ":"):
        if sep in normalized:
            candidate = normalized.split(sep)[-1].strip()
            if candidate:
                return candidate
    matched = re.search(r"(\d+(?:\.\d+)*(?:-[a-z0-9]+)?)", normalized)
    if matched:
        return matched.group(1)
    return normalized


def _build_task_llm_context_map(logs: list[Any]) -> dict[str, dict[str, str]]:
    latest_map: dict[str, tuple[datetime, dict[str, str]]] = {}
    for item in logs:
        task_id = str(getattr(item, "task_id", "") or "").strip()
        if not task_id:
            continue
        provider_name = str(getattr(item, "provider_name", "") or "unknown").strip() or "unknown"
        model_name = str(getattr(item, "model", "") or "unknown").strip() or "unknown"
        version_name = _resolve_model_version(model_name)
        created_at = getattr(item, "created_at", None) or datetime.min
        candidate = {
            "provider_name": provider_name,
            "model": model_name,
            "version": version_name,
        }
        current = latest_map.get(task_id)
        if not current or created_at >= current[0]:
            latest_map[task_id] = (created_at, candidate)
    return {key: value[1] for key, value in latest_map.items()}


def _matches_llm_filters(
    context: dict[str, str] | None,
    *,
    provider_name: str | None,
    model: str | None,
    version: str | None,
) -> bool:
    current = context or {"provider_name": "unknown", "model": "unknown", "version": "unknown"}
    if provider_name and current.get("provider_name") != provider_name:
        return False
    if model and current.get("model") != model:
        return False
    if version and current.get("version") != version:
        return False
    return True


def _resolve_service_from_task(task, incident_service_map: dict[str, str]) -> str:
    payload = task.payload if isinstance(task.payload, dict) else {}
    service_key = str(payload.get("service_key") or "").strip()
    if service_key:
        return service_key

    incident_id = str(payload.get("incident_id") or "").strip()
    if incident_id and incident_id in incident_service_map:
        return incident_service_map[incident_id]

    return "unknown"


def _build_incident_service_map(incident_service, incident_ids: list[str]) -> dict[str, str]:
    if not incident_service or not hasattr(incident_service, "repository"):
        return {}
    repository = incident_service.repository
    if not repository or not hasattr(repository, "list_by_ids"):
        return {}

    incidents = repository.list_by_ids(incident_ids)
    service_map: dict[str, str] = {}
    for item in incidents:
        service_map[item.incident_id] = item.service_key or "unknown"
    return service_map


def _build_day_keys(start_day: date, end_day: date) -> list[str]:
    days: list[str] = []
    cursor = start_day
    while cursor <= end_day:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


@router.get("/recommendation")
async def get_recommendation_metrics(
    start_date: str | None = Query(default=None, description="起始日期，格式 YYYY-MM-DD"),
    end_date: str | None = Query(default=None, description="结束日期，格式 YYYY-MM-DD"),
    service_key: str | None = Query(default=None, description="按服务键过滤"),
    provider_name: str | None = Query(default=None, description="按 Provider 过滤"),
    model: str | None = Query(default=None, description="按模型过滤"),
    version: str | None = Query(default=None, description="按模型版本过滤"),
    task_manager=Depends(get_task_manager),
    incident_service=Depends(get_incident_service),
    feedback_repository=Depends(get_recommendation_feedback_repository_dep),
    ai_call_log_repository=Depends(get_ai_call_log_repository_dep),
):
    if not task_manager or not feedback_repository:
        raise HTTPException(status_code=409, detail="指标依赖尚未初始化")

    start_day, end_day, start_dt, end_dt_exclusive = _resolve_time_range(start_date, end_date)

    feedback_items = feedback_repository.list_by_created_range(start_dt, end_dt_exclusive)
    feedback_incident_ids = [item.incident_id for item in feedback_items if item.incident_id]
    ai_logs = ai_call_log_repository.list_by_created_range(start_dt, end_dt_exclusive) if ai_call_log_repository else []
    task_llm_context_map = _build_task_llm_context_map(ai_logs)

    task_items = task_manager.task_repository.list_by_created_range(start_dt, end_dt_exclusive)
    task_incident_ids = []
    for task in task_items:
        payload = task.payload if isinstance(task.payload, dict) else {}
        incident_id = str(payload.get("incident_id") or "").strip()
        if incident_id:
            task_incident_ids.append(incident_id)

    incident_service_map = _build_incident_service_map(
        incident_service,
        [*feedback_incident_ids, *task_incident_ids],
    )

    day_metrics: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "adopt": 0,
            "reject": 0,
            "rewrite": 0,
            "feedback_total": 0,
            "feedback_bound_task": 0,
            "feedback_unbound_task": 0,
            "task_total": 0,
            "task_success": 0,
            "task_failed": 0,
            "task_approved": 0,
            "task_duration_sum_ms": 0,
            "task_duration_count": 0,
        }
    )

    service_metrics: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "feedback_total": 0,
            "adopt": 0,
            "reject": 0,
            "rewrite": 0,
            "feedback_bound_task": 0,
            "feedback_unbound_task": 0,
            "task_total": 0,
            "task_success": 0,
            "task_failed": 0,
            "task_approved": 0,
            "task_duration_sum_ms": 0,
            "task_duration_count": 0,
        }
    )
    provider_metrics: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "feedback_total": 0,
            "adopt": 0,
            "reject": 0,
            "rewrite": 0,
            "feedback_bound_task": 0,
            "feedback_unbound_task": 0,
            "task_total": 0,
            "task_success": 0,
            "task_failed": 0,
            "task_approved": 0,
            "task_duration_sum_ms": 0,
            "task_duration_count": 0,
        }
    )
    model_metrics: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "feedback_total": 0,
            "adopt": 0,
            "reject": 0,
            "rewrite": 0,
            "feedback_bound_task": 0,
            "feedback_unbound_task": 0,
            "task_total": 0,
            "task_success": 0,
            "task_failed": 0,
            "task_approved": 0,
            "task_duration_sum_ms": 0,
            "task_duration_count": 0,
        }
    )
    version_metrics: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "feedback_total": 0,
            "adopt": 0,
            "reject": 0,
            "rewrite": 0,
            "feedback_bound_task": 0,
            "feedback_unbound_task": 0,
            "task_total": 0,
            "task_success": 0,
            "task_failed": 0,
            "task_approved": 0,
            "task_duration_sum_ms": 0,
            "task_duration_count": 0,
        }
    )

    for item in feedback_items:
        current_service = incident_service_map.get(item.incident_id, "unknown")
        if service_key and current_service != service_key:
            continue
        context = task_llm_context_map.get(str(item.task_id or "").strip())
        if not _matches_llm_filters(
            context,
            provider_name=provider_name,
            model=model,
            version=version,
        ):
            continue
        current_provider = (context or {}).get("provider_name", "unknown")
        current_model = (context or {}).get("model", "unknown")
        current_version = (context or {}).get("version", "unknown")

        day_key = item.created_at.date().isoformat()
        action = item.action.value if hasattr(item.action, "value") else str(item.action)

        day_metrics[day_key]["feedback_total"] += 1
        if action in {"adopt", "reject", "rewrite"}:
            day_metrics[day_key][action] += 1

        service_metrics[current_service]["feedback_total"] += 1
        if action in {"adopt", "reject", "rewrite"}:
            service_metrics[current_service][action] += 1
        provider_metrics[current_provider]["feedback_total"] += 1
        model_metrics[current_model]["feedback_total"] += 1
        version_metrics[current_version]["feedback_total"] += 1
        if action in {"adopt", "reject", "rewrite"}:
            provider_metrics[current_provider][action] += 1
            model_metrics[current_model][action] += 1
            version_metrics[current_version][action] += 1

        # 反馈与任务是否绑定，决定闭环链路是否完整可追踪。
        has_bound_task = bool(item.task_id and task_manager.task_repository.get(str(item.task_id)))
        if has_bound_task:
            day_metrics[day_key]["feedback_bound_task"] += 1
            service_metrics[current_service]["feedback_bound_task"] += 1
            provider_metrics[current_provider]["feedback_bound_task"] += 1
            model_metrics[current_model]["feedback_bound_task"] += 1
            version_metrics[current_version]["feedback_bound_task"] += 1
        else:
            day_metrics[day_key]["feedback_unbound_task"] += 1
            service_metrics[current_service]["feedback_unbound_task"] += 1
            provider_metrics[current_provider]["feedback_unbound_task"] += 1
            model_metrics[current_model]["feedback_unbound_task"] += 1
            version_metrics[current_version]["feedback_unbound_task"] += 1

    for task in task_items:
        current_service = _resolve_service_from_task(task, incident_service_map)
        if service_key and current_service != service_key:
            continue
        context = task_llm_context_map.get(str(task.task_id or "").strip())
        if not _matches_llm_filters(
            context,
            provider_name=provider_name,
            model=model,
            version=version,
        ):
            continue
        current_provider = (context or {}).get("provider_name", "unknown")
        current_model = (context or {}).get("model", "unknown")
        current_version = (context or {}).get("version", "unknown")

        day_key = task.created_at.date().isoformat()
        status = _status_value(task.status)

        day_metrics[day_key]["task_total"] += 1
        service_metrics[current_service]["task_total"] += 1
        provider_metrics[current_provider]["task_total"] += 1
        model_metrics[current_model]["task_total"] += 1
        version_metrics[current_version]["task_total"] += 1

        if status == "COMPLETED":
            day_metrics[day_key]["task_success"] += 1
            service_metrics[current_service]["task_success"] += 1
            provider_metrics[current_provider]["task_success"] += 1
            model_metrics[current_model]["task_success"] += 1
            version_metrics[current_version]["task_success"] += 1
        if status in {"FAILED", "CANCELLED"}:
            day_metrics[day_key]["task_failed"] += 1
            service_metrics[current_service]["task_failed"] += 1
            provider_metrics[current_provider]["task_failed"] += 1
            model_metrics[current_model]["task_failed"] += 1
            version_metrics[current_version]["task_failed"] += 1
        # recommendation 任务审批通过后，纳入质量看板统计。
        if task.approval:
            day_metrics[day_key]["task_approved"] += 1
            service_metrics[current_service]["task_approved"] += 1
            provider_metrics[current_provider]["task_approved"] += 1
            model_metrics[current_model]["task_approved"] += 1
            version_metrics[current_version]["task_approved"] += 1

        if task.completed_at:
            duration_ms = max(0, int((task.completed_at - task.created_at).total_seconds() * 1000))
            day_metrics[day_key]["task_duration_sum_ms"] += duration_ms
            day_metrics[day_key]["task_duration_count"] += 1
            service_metrics[current_service]["task_duration_sum_ms"] += duration_ms
            service_metrics[current_service]["task_duration_count"] += 1
            provider_metrics[current_provider]["task_duration_sum_ms"] += duration_ms
            provider_metrics[current_provider]["task_duration_count"] += 1
            model_metrics[current_model]["task_duration_sum_ms"] += duration_ms
            model_metrics[current_model]["task_duration_count"] += 1
            version_metrics[current_version]["task_duration_sum_ms"] += duration_ms
            version_metrics[current_version]["task_duration_count"] += 1

    trend = []
    summary = {
        "feedback_total": 0,
        "adopt": 0,
        "reject": 0,
        "rewrite": 0,
        "adopt_rate": 0.0,
        "reject_rate": 0.0,
        "rewrite_rate": 0.0,
        "feedback_bound_task": 0,
        "feedback_unbound_task": 0,
        "feedback_bound_rate": 0.0,
        "task_total": 0,
        "task_success": 0,
        "task_failed": 0,
        "task_approved": 0,
        "task_approval_rate": 0.0,
        "task_success_rate": 0.0,
        "avg_task_duration_ms": 0.0,
    }
    total_duration = 0
    total_duration_count = 0

    for day_key in _build_day_keys(start_day, end_day):
        row = day_metrics.get(day_key) or {
            "adopt": 0,
            "reject": 0,
            "rewrite": 0,
            "feedback_total": 0,
            "feedback_bound_task": 0,
            "feedback_unbound_task": 0,
            "task_total": 0,
            "task_success": 0,
            "task_failed": 0,
            "task_approved": 0,
            "task_duration_sum_ms": 0,
            "task_duration_count": 0,
        }
        feedback_total = int(row["feedback_total"])
        feedback_bound_task = int(row["feedback_bound_task"])
        task_total = int(row["task_total"])
        task_approved = int(row["task_approved"])
        task_duration_count = int(row["task_duration_count"])
        avg_task_duration = (
            round(float(row["task_duration_sum_ms"]) / task_duration_count, 2)
            if task_duration_count > 0
            else 0.0
        )

        trend.append(
            {
                "date": day_key,
                "feedback_total": feedback_total,
                "adopt": int(row["adopt"]),
                "reject": int(row["reject"]),
                "rewrite": int(row["rewrite"]),
                "adopt_rate": _safe_rate(int(row["adopt"]), feedback_total),
                "reject_rate": _safe_rate(int(row["reject"]), feedback_total),
                "rewrite_rate": _safe_rate(int(row["rewrite"]), feedback_total),
                "feedback_bound_task": feedback_bound_task,
                "feedback_unbound_task": int(row["feedback_unbound_task"]),
                "feedback_bound_rate": _safe_rate(feedback_bound_task, feedback_total),
                "task_total": task_total,
                "task_success": int(row["task_success"]),
                "task_failed": int(row["task_failed"]),
                "task_approved": task_approved,
                "task_approval_rate": _safe_rate(task_approved, task_total),
                "task_success_rate": _safe_rate(int(row["task_success"]), task_total),
                "avg_task_duration_ms": avg_task_duration,
            }
        )

        summary["feedback_total"] += feedback_total
        summary["adopt"] += int(row["adopt"])
        summary["reject"] += int(row["reject"])
        summary["rewrite"] += int(row["rewrite"])
        summary["feedback_bound_task"] += feedback_bound_task
        summary["feedback_unbound_task"] += int(row["feedback_unbound_task"])
        summary["task_total"] += task_total
        summary["task_success"] += int(row["task_success"])
        summary["task_failed"] += int(row["task_failed"])
        summary["task_approved"] += task_approved
        total_duration += int(row["task_duration_sum_ms"])
        total_duration_count += task_duration_count

    summary["adopt_rate"] = _safe_rate(summary["adopt"], summary["feedback_total"])
    summary["reject_rate"] = _safe_rate(summary["reject"], summary["feedback_total"])
    summary["rewrite_rate"] = _safe_rate(summary["rewrite"], summary["feedback_total"])
    summary["feedback_bound_rate"] = _safe_rate(summary["feedback_bound_task"], summary["feedback_total"])
    summary["task_success_rate"] = _safe_rate(summary["task_success"], summary["task_total"])
    summary["task_approval_rate"] = _safe_rate(summary["task_approved"], summary["task_total"])
    summary["avg_task_duration_ms"] = round(total_duration / total_duration_count, 2) if total_duration_count > 0 else 0.0

    def _build_recommendation_breakdown(data_map: dict[str, dict[str, Any]], key_field: str) -> list[dict[str, Any]]:
        items = []
        for key in sorted(data_map.keys()):
            row = data_map[key]
            feedback_total = int(row["feedback_total"])
            feedback_bound_task = int(row["feedback_bound_task"])
            task_total = int(row["task_total"])
            task_approved = int(row["task_approved"])
            duration_count = int(row["task_duration_count"])
            items.append(
                {
                    key_field: key,
                    "feedback_total": feedback_total,
                    "adopt": int(row["adopt"]),
                    "reject": int(row["reject"]),
                    "rewrite": int(row["rewrite"]),
                    "adopt_rate": _safe_rate(int(row["adopt"]), feedback_total),
                    "reject_rate": _safe_rate(int(row["reject"]), feedback_total),
                    "rewrite_rate": _safe_rate(int(row["rewrite"]), feedback_total),
                    "feedback_bound_task": feedback_bound_task,
                    "feedback_unbound_task": int(row["feedback_unbound_task"]),
                    "feedback_bound_rate": _safe_rate(feedback_bound_task, feedback_total),
                    "task_total": task_total,
                    "task_success": int(row["task_success"]),
                    "task_failed": int(row["task_failed"]),
                    "task_approved": task_approved,
                    "task_approval_rate": _safe_rate(task_approved, task_total),
                    "task_success_rate": _safe_rate(int(row["task_success"]), task_total),
                    "avg_task_duration_ms": (
                        round(float(row["task_duration_sum_ms"]) / duration_count, 2)
                        if duration_count > 0
                        else 0.0
                    ),
                }
            )
        items.sort(
            key=lambda item: (item["feedback_total"] + item["task_total"], str(item[key_field])),
            reverse=True,
        )
        return items

    service_breakdown = _build_recommendation_breakdown(service_metrics, "service_key")
    provider_breakdown = _build_recommendation_breakdown(provider_metrics, "provider_name")
    model_breakdown = _build_recommendation_breakdown(model_metrics, "model")
    version_breakdown = _build_recommendation_breakdown(version_metrics, "version")

    return {
        "start_date": start_day.isoformat(),
        "end_date": end_day.isoformat(),
        "service_key": service_key or "",
        "provider_name": provider_name or "",
        "model": model or "",
        "version": version or "",
        "summary": summary,
        "trend": trend,
        "service_breakdown": service_breakdown,
        "provider_breakdown": provider_breakdown,
        "model_breakdown": model_breakdown,
        "version_breakdown": version_breakdown,
    }


@router.get("/ai-usage")
async def get_ai_usage_metrics(
    start_date: str | None = Query(default=None, description="起始日期，格式 YYYY-MM-DD"),
    end_date: str | None = Query(default=None, description="结束日期，格式 YYYY-MM-DD"),
    service_key: str | None = Query(default=None, description="按服务键过滤"),
    provider_name: str | None = Query(default=None, description="按 Provider 过滤"),
    model: str | None = Query(default=None, description="按模型过滤"),
    version: str | None = Query(default=None, description="按模型版本过滤"),
    sync_daily: bool = Query(default=True, description="是否先同步 usage_metrics_daily"),
    task_manager=Depends(get_task_manager),
    incident_service=Depends(get_incident_service),
    ai_call_log_repository=Depends(get_ai_call_log_repository_dep),
    usage_metrics_daily_repository=Depends(get_usage_metrics_daily_repository_dep),
):
    if not task_manager or not ai_call_log_repository or not usage_metrics_daily_repository:
        raise HTTPException(status_code=409, detail="指标依赖尚未初始化")

    start_day, end_day, start_dt, end_dt_exclusive = _resolve_time_range(start_date, end_date)

    if sync_daily:
        logs = ai_call_log_repository.list_by_created_range(start_dt, end_dt_exclusive)
        task_ids = [item.task_id for item in logs if item.task_id]
        task_map = {}
        incident_ids: list[str] = []

        for task_id in task_ids:
            task = task_manager.task_repository.get(task_id)
            if not task:
                continue
            task_map[task_id] = task
            payload = task.payload if isinstance(task.payload, dict) else {}
            incident_id = str(payload.get("incident_id") or "").strip()
            if incident_id:
                incident_ids.append(incident_id)

        incident_service_map = _build_incident_service_map(incident_service, incident_ids)

        grouped: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(
            lambda: {
                "ai_call_total": 0,
                "ai_error_count": 0,
                "ai_success_count": 0,
                "ai_timeout_count": 0,
                "guardrail_fallback_count": 0,
                "guardrail_retried_count": 0,
                "guardrail_schema_error_count": 0,
                "latency_sum": 0.0,
                "token_sum": 0,
                "cost_sum": 0.0,
            }
        )
        task_group_key_map: dict[str, tuple[str, str, str, str]] = {}

        for log in logs:
            model_name = (log.model or "unknown").strip() or "unknown"
            if model and model_name != model:
                continue
            version_name = _resolve_model_version(model_name)
            if version and version_name != version:
                continue

            provider_label = (log.provider_name or "unknown").strip() or "unknown"
            if provider_name and provider_label != provider_name:
                continue
            day_key = log.created_at.date().isoformat()

            current_service = "all"
            if log.task_id and log.task_id in task_map:
                current_service = _resolve_service_from_task(task_map[log.task_id], incident_service_map)

            if service_key and current_service != service_key:
                continue

            key = (day_key, current_service, model_name, provider_label)
            if log.task_id:
                task_group_key_map[str(log.task_id)] = key
            grouped[key]["ai_call_total"] += 1

            status = _status_value(log.status).lower()
            if status == "error":
                grouped[key]["ai_error_count"] += 1
                if _is_timeout_error(log):
                    grouped[key]["ai_timeout_count"] += 1
            else:
                grouped[key]["ai_success_count"] += 1

            latency_ms = max(0.0, float(log.latency_ms or 0))
            grouped[key]["latency_sum"] += latency_ms

            token_count = int(log.request_tokens or 0) + int(log.response_tokens or 0)
            grouped[key]["token_sum"] += token_count
            grouped[key]["cost_sum"] += (token_count / 1000.0) * _cost_per_1k_tokens(model_name)

        # 护栏统计来自任务结果，按 task->最后一次模型分组归并，进入同一质量口径。
        for task_id, key in task_group_key_map.items():
            task = task_map.get(task_id)
            if not task:
                continue
            counters = _extract_guardrail_counters(task)
            grouped[key]["guardrail_fallback_count"] += counters["guardrail_fallback_count"]
            grouped[key]["guardrail_retried_count"] += counters["guardrail_retried_count"]
            grouped[key]["guardrail_schema_error_count"] += counters["guardrail_schema_error_count"]

        for (metric_date, current_service, model_name, provider_label), data in grouped.items():
            call_total = int(data["ai_call_total"])
            avg_latency = round(float(data["latency_sum"]) / call_total, 2) if call_total > 0 else 0.0
            usage_metrics_daily_repository.upsert(
                UsageMetricsDailyRecord(
                    metric_date=metric_date,
                    service_key=current_service,
                    model=model_name,
                    provider_name=provider_label,
                    ai_call_total=call_total,
                    ai_error_count=int(data["ai_error_count"]),
                    ai_success_count=int(data["ai_success_count"]),
                    ai_avg_latency_ms=avg_latency,
                    ai_total_tokens=int(data["token_sum"]),
                    ai_total_cost=round(float(data["cost_sum"]), 6),
                    ai_timeout_count=int(data["ai_timeout_count"]),
                    guardrail_fallback_count=int(data["guardrail_fallback_count"]),
                    guardrail_retried_count=int(data["guardrail_retried_count"]),
                    guardrail_schema_error_count=int(data["guardrail_schema_error_count"]),
                )
            )

    records = usage_metrics_daily_repository.list(
        start_date=start_day.isoformat(),
        end_date=end_day.isoformat(),
        service_key=service_key,
        model=model,
    )
    if provider_name or version:
        filtered_records = []
        for item in records:
            if provider_name and item.provider_name != provider_name:
                continue
            if version and _resolve_model_version(item.model) != version:
                continue
            filtered_records.append(item)
        records = filtered_records

    trend_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "ai_call_total": 0,
            "ai_error_count": 0,
            "ai_success_count": 0,
            "ai_timeout_count": 0,
            "guardrail_fallback_count": 0,
            "guardrail_retried_count": 0,
            "guardrail_schema_error_count": 0,
            "latency_sum": 0.0,
            "token_sum": 0,
            "cost_sum": 0.0,
        }
    )
    service_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "ai_call_total": 0,
            "ai_error_count": 0,
            "ai_success_count": 0,
            "ai_timeout_count": 0,
            "guardrail_fallback_count": 0,
            "guardrail_retried_count": 0,
            "guardrail_schema_error_count": 0,
            "latency_sum": 0.0,
            "token_sum": 0,
            "cost_sum": 0.0,
        }
    )
    model_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "ai_call_total": 0,
            "ai_error_count": 0,
            "ai_success_count": 0,
            "ai_timeout_count": 0,
            "guardrail_fallback_count": 0,
            "guardrail_retried_count": 0,
            "guardrail_schema_error_count": 0,
            "latency_sum": 0.0,
            "token_sum": 0,
            "cost_sum": 0.0,
        }
    )
    provider_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "ai_call_total": 0,
            "ai_error_count": 0,
            "ai_success_count": 0,
            "ai_timeout_count": 0,
            "guardrail_fallback_count": 0,
            "guardrail_retried_count": 0,
            "guardrail_schema_error_count": 0,
            "latency_sum": 0.0,
            "token_sum": 0,
            "cost_sum": 0.0,
        }
    )
    version_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "ai_call_total": 0,
            "ai_error_count": 0,
            "ai_success_count": 0,
            "ai_timeout_count": 0,
            "guardrail_fallback_count": 0,
            "guardrail_retried_count": 0,
            "guardrail_schema_error_count": 0,
            "latency_sum": 0.0,
            "token_sum": 0,
            "cost_sum": 0.0,
        }
    )

    summary = {
        "ai_call_total": 0,
        "ai_error_count": 0,
        "ai_success_count": 0,
        "ai_timeout_count": 0,
        "ai_error_rate": 0.0,
        "ai_timeout_rate": 0.0,
        "guardrail_fallback_count": 0,
        "guardrail_retried_count": 0,
        "guardrail_schema_error_count": 0,
        "guardrail_fallback_rate": 0.0,
        "guardrail_schema_error_rate": 0.0,
        "ai_avg_latency_ms": 0.0,
        "ai_total_tokens": 0,
        "ai_total_cost": 0.0,
        "ai_cost_per_call": 0.0,
    }
    total_latency_weighted = 0.0

    for item in records:
        version_name = _resolve_model_version(item.model)
        key_date = item.metric_date
        trend_map[key_date]["ai_call_total"] += item.ai_call_total
        trend_map[key_date]["ai_error_count"] += item.ai_error_count
        trend_map[key_date]["ai_success_count"] += item.ai_success_count
        trend_map[key_date]["ai_timeout_count"] += item.ai_timeout_count
        trend_map[key_date]["guardrail_fallback_count"] += item.guardrail_fallback_count
        trend_map[key_date]["guardrail_retried_count"] += item.guardrail_retried_count
        trend_map[key_date]["guardrail_schema_error_count"] += item.guardrail_schema_error_count
        trend_map[key_date]["latency_sum"] += item.ai_avg_latency_ms * item.ai_call_total
        trend_map[key_date]["token_sum"] += item.ai_total_tokens
        trend_map[key_date]["cost_sum"] += item.ai_total_cost

        service_map[item.service_key]["ai_call_total"] += item.ai_call_total
        service_map[item.service_key]["ai_error_count"] += item.ai_error_count
        service_map[item.service_key]["ai_success_count"] += item.ai_success_count
        service_map[item.service_key]["ai_timeout_count"] += item.ai_timeout_count
        service_map[item.service_key]["guardrail_fallback_count"] += item.guardrail_fallback_count
        service_map[item.service_key]["guardrail_retried_count"] += item.guardrail_retried_count
        service_map[item.service_key]["guardrail_schema_error_count"] += item.guardrail_schema_error_count
        service_map[item.service_key]["latency_sum"] += item.ai_avg_latency_ms * item.ai_call_total
        service_map[item.service_key]["token_sum"] += item.ai_total_tokens
        service_map[item.service_key]["cost_sum"] += item.ai_total_cost

        model_map[item.model]["ai_call_total"] += item.ai_call_total
        model_map[item.model]["ai_error_count"] += item.ai_error_count
        model_map[item.model]["ai_success_count"] += item.ai_success_count
        model_map[item.model]["ai_timeout_count"] += item.ai_timeout_count
        model_map[item.model]["guardrail_fallback_count"] += item.guardrail_fallback_count
        model_map[item.model]["guardrail_retried_count"] += item.guardrail_retried_count
        model_map[item.model]["guardrail_schema_error_count"] += item.guardrail_schema_error_count
        model_map[item.model]["latency_sum"] += item.ai_avg_latency_ms * item.ai_call_total
        model_map[item.model]["token_sum"] += item.ai_total_tokens
        model_map[item.model]["cost_sum"] += item.ai_total_cost

        provider_map[item.provider_name]["ai_call_total"] += item.ai_call_total
        provider_map[item.provider_name]["ai_error_count"] += item.ai_error_count
        provider_map[item.provider_name]["ai_success_count"] += item.ai_success_count
        provider_map[item.provider_name]["ai_timeout_count"] += item.ai_timeout_count
        provider_map[item.provider_name]["guardrail_fallback_count"] += item.guardrail_fallback_count
        provider_map[item.provider_name]["guardrail_retried_count"] += item.guardrail_retried_count
        provider_map[item.provider_name]["guardrail_schema_error_count"] += item.guardrail_schema_error_count
        provider_map[item.provider_name]["latency_sum"] += item.ai_avg_latency_ms * item.ai_call_total
        provider_map[item.provider_name]["token_sum"] += item.ai_total_tokens
        provider_map[item.provider_name]["cost_sum"] += item.ai_total_cost

        version_map[version_name]["ai_call_total"] += item.ai_call_total
        version_map[version_name]["ai_error_count"] += item.ai_error_count
        version_map[version_name]["ai_success_count"] += item.ai_success_count
        version_map[version_name]["ai_timeout_count"] += item.ai_timeout_count
        version_map[version_name]["guardrail_fallback_count"] += item.guardrail_fallback_count
        version_map[version_name]["guardrail_retried_count"] += item.guardrail_retried_count
        version_map[version_name]["guardrail_schema_error_count"] += item.guardrail_schema_error_count
        version_map[version_name]["latency_sum"] += item.ai_avg_latency_ms * item.ai_call_total
        version_map[version_name]["token_sum"] += item.ai_total_tokens
        version_map[version_name]["cost_sum"] += item.ai_total_cost

        summary["ai_call_total"] += item.ai_call_total
        summary["ai_error_count"] += item.ai_error_count
        summary["ai_success_count"] += item.ai_success_count
        summary["ai_timeout_count"] += item.ai_timeout_count
        summary["guardrail_fallback_count"] += item.guardrail_fallback_count
        summary["guardrail_retried_count"] += item.guardrail_retried_count
        summary["guardrail_schema_error_count"] += item.guardrail_schema_error_count
        summary["ai_total_tokens"] += item.ai_total_tokens
        summary["ai_total_cost"] += item.ai_total_cost
        total_latency_weighted += item.ai_avg_latency_ms * item.ai_call_total

    if summary["ai_call_total"] > 0:
        summary["ai_error_rate"] = _safe_rate(summary["ai_error_count"], summary["ai_call_total"])
        summary["ai_timeout_rate"] = _safe_rate(summary["ai_timeout_count"], summary["ai_call_total"])
        summary["guardrail_fallback_rate"] = _safe_rate(summary["guardrail_fallback_count"], summary["ai_call_total"])
        summary["guardrail_schema_error_rate"] = _safe_rate(summary["guardrail_schema_error_count"], summary["ai_call_total"])
        summary["ai_avg_latency_ms"] = round(total_latency_weighted / summary["ai_call_total"], 2)
        summary["ai_cost_per_call"] = round(summary["ai_total_cost"] / summary["ai_call_total"], 6)
    summary["ai_total_cost"] = round(summary["ai_total_cost"], 6)

    def _normalize_group(data_map: dict[str, dict[str, Any]], key_field: str) -> list[dict[str, Any]]:
        items = []
        for key, data in data_map.items():
            total = int(data["ai_call_total"])
            avg_latency = round(float(data["latency_sum"]) / total, 2) if total > 0 else 0.0
            items.append(
                {
                    key_field: key,
                    "ai_call_total": total,
                    "ai_error_count": int(data["ai_error_count"]),
                    "ai_success_count": int(data["ai_success_count"]),
                    "ai_timeout_count": int(data["ai_timeout_count"]),
                    "ai_error_rate": _safe_rate(int(data["ai_error_count"]), total),
                    "ai_timeout_rate": _safe_rate(int(data["ai_timeout_count"]), total),
                    "guardrail_fallback_count": int(data["guardrail_fallback_count"]),
                    "guardrail_retried_count": int(data["guardrail_retried_count"]),
                    "guardrail_schema_error_count": int(data["guardrail_schema_error_count"]),
                    "guardrail_fallback_rate": _safe_rate(int(data["guardrail_fallback_count"]), total),
                    "guardrail_schema_error_rate": _safe_rate(int(data["guardrail_schema_error_count"]), total),
                    "ai_avg_latency_ms": avg_latency,
                    "ai_total_tokens": int(data["token_sum"]),
                    "ai_total_cost": round(float(data["cost_sum"]), 6),
                }
            )
        items.sort(key=lambda item: (item["ai_call_total"], str(item[key_field])), reverse=True)
        return items

    trend = []
    for day_key in _build_day_keys(start_day, end_day):
        data = trend_map.get(day_key) or {
            "ai_call_total": 0,
            "ai_error_count": 0,
            "ai_success_count": 0,
            "ai_timeout_count": 0,
            "guardrail_fallback_count": 0,
            "guardrail_retried_count": 0,
            "guardrail_schema_error_count": 0,
            "latency_sum": 0.0,
            "token_sum": 0,
            "cost_sum": 0.0,
        }
        call_total = int(data["ai_call_total"])
        avg_latency = round(float(data["latency_sum"]) / call_total, 2) if call_total > 0 else 0.0
        trend.append(
            {
                "date": day_key,
                "ai_call_total": call_total,
                "ai_error_count": int(data["ai_error_count"]),
                "ai_success_count": int(data["ai_success_count"]),
                "ai_timeout_count": int(data["ai_timeout_count"]),
                "ai_error_rate": _safe_rate(int(data["ai_error_count"]), call_total),
                "ai_timeout_rate": _safe_rate(int(data["ai_timeout_count"]), call_total),
                "guardrail_fallback_count": int(data["guardrail_fallback_count"]),
                "guardrail_retried_count": int(data["guardrail_retried_count"]),
                "guardrail_schema_error_count": int(data["guardrail_schema_error_count"]),
                "guardrail_fallback_rate": _safe_rate(int(data["guardrail_fallback_count"]), call_total),
                "guardrail_schema_error_rate": _safe_rate(int(data["guardrail_schema_error_count"]), call_total),
                "ai_avg_latency_ms": avg_latency,
                "ai_total_tokens": int(data["token_sum"]),
                "ai_total_cost": round(float(data["cost_sum"]), 6),
            }
        )

    return {
        "start_date": start_day.isoformat(),
        "end_date": end_day.isoformat(),
        "service_key": service_key or "",
        "provider_name": provider_name or "",
        "model": model or "",
        "version": version or "",
        "summary": summary,
        "trend": trend,
        "service_breakdown": _normalize_group(service_map, "service_key"),
        "model_breakdown": _normalize_group(model_map, "model"),
        "provider_breakdown": _normalize_group(provider_map, "provider_name"),
        "version_breakdown": _normalize_group(version_map, "version"),
        "records_count": len(records),
    }
