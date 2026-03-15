"""异常接口。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engine.domain.incident_evidence import normalize_incident_evidence, sort_incident_evidence
from engine.llm.structured_output import run_guarded_structured_chat
from engine.runtime.models import ArtifactKind, TaskStatus, TaskType

from .deps import (
    get_alert_store,
    get_asset_service,
    get_incident_service,
    get_llm_router_dep,
    get_recommendation_service,
    get_resource_engine,
    get_signal_service,
    get_task_manager,
    get_traffic_engine,
    resolve_access_logs,
)

router = APIRouter(prefix="/incidents", tags=["incidents"])


class IncidentAnalyzeRequest(BaseModel):
    """异常分析请求。"""

    service_key: str | None = Field(default=None, description="服务键")
    asset_id: str | None = Field(default=None, description="资产 ID")
    time_window: str = Field(default="1h", description="分析时间窗口")


class IncidentAISummaryRequest(BaseModel):
    """异常 AI 摘要请求。"""

    provider: str | None = Field(default=None, description="指定 Provider")


class IncidentAISummaryPayload(BaseModel):
    """结构化 AI 总结响应。"""

    incident_id: str
    provider: str
    summary: str
    risk_level: str = "medium"
    confidence: float = 0.5
    primary_causes: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    evidence_citations: list[str] = Field(default_factory=list)
    parse_mode: str = "fallback"
    validation_status: str = "fallback_template"
    retry_count: int = 0
    guardrail_error_code: str = ""
    guardrail_error_message: str = ""
    log_sample_count: int = 0
    recommendation_count: int = 0


class IncidentSummarySchema(BaseModel):
    """异常 AI 总结结构。"""

    summary: str = Field(..., min_length=1, max_length=800)
    risk_level: str = Field(..., pattern="^(high|medium|low)$")
    confidence: float = Field(..., ge=0.0, le=1.0)
    primary_causes: list[str] = Field(default_factory=list, max_length=6)
    recommended_actions: list[str] = Field(default_factory=list, max_length=10)
    evidence_citations: list[str] = Field(default_factory=list, max_length=10)


def _serialize_incident(incident) -> dict[str, Any]:
    payload = incident.model_dump(mode="json")
    payload["evidence_refs"] = sort_incident_evidence(
        [
            normalize_incident_evidence(
                item,
                default_service_key=str(payload.get("service_key") or ""),
                default_asset_ids=payload.get("related_asset_ids") or [],
            )
            for item in payload.get("evidence_refs") or []
            if isinstance(item, dict)
        ]
    )
    return payload


@router.get("")
async def list_incidents(
    status: str | None = None,
    severity: str | None = None,
    service_key: str | None = None,
    time_range: str | None = None,
    incident_service=Depends(get_incident_service),
):
    del time_range
    incidents = incident_service.list_incidents(status=status, severity=severity, service_key=service_key)
    return {"items": [_serialize_incident(incident) for incident in incidents], "total": len(incidents)}


def _to_string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        item_text = str(item).strip()
        if item_text:
            output.append(item_text)
        if len(output) >= limit:
            break
    return output


def _normalize_risk_level(value: Any) -> str:
    risk = str(value or "").strip().lower()
    if risk in {"high", "medium", "low"}:
        return risk
    return "medium"


def _normalize_confidence(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, score))


def _build_fallback_payload(incident, recommendations: list[Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    primary_causes = [tag.replace("_", " ") for tag in incident.reasoning_tags[:3]]
    if not primary_causes:
        primary_causes = ["需要结合更多证据进一步定位"]

    recommended_actions = [str(item).strip() for item in incident.recommended_actions[:5] if str(item).strip()]
    if not recommended_actions:
        recommended_actions = [str(item.recommendation).strip() for item in recommendations[:3] if str(item.recommendation).strip()]

    evidence_citations = []
    for sample in samples[:3]:
        evidence_citations.append(f"log:{sample.get('path') or '/'} status={sample.get('status')}")
    if not evidence_citations:
        evidence_citations = ["evidence:incident_summary"]

    severity_to_risk = {
        "critical": "high",
        "warning": "medium",
    }
    risk_level = severity_to_risk.get(str(incident.severity).lower(), "low")

    return {
        "summary": incident.summary,
        "risk_level": risk_level,
        "confidence": float(incident.confidence),
        "primary_causes": primary_causes,
        "recommended_actions": recommended_actions,
        "evidence_citations": evidence_citations,
    }


def _normalize_summary_payload(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": str(payload.get("summary") or "").strip() or fallback["summary"],
        "risk_level": _normalize_risk_level(payload.get("risk_level")),
        "confidence": _normalize_confidence(payload.get("confidence")),
        "primary_causes": _to_string_list(payload.get("primary_causes"), limit=6) or fallback["primary_causes"],
        "recommended_actions": _to_string_list(payload.get("recommended_actions"), limit=10) or fallback["recommended_actions"],
        "evidence_citations": _to_string_list(payload.get("evidence_citations"), limit=10) or fallback["evidence_citations"],
    }


@router.get("/{incident_id}")
async def get_incident_detail(
    incident_id: str,
    incident_service=Depends(get_incident_service),
    recommendation_service=Depends(get_recommendation_service),
    traffic_engine=Depends(get_traffic_engine),
):
    incident = incident_service.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")

    recommendations = recommendation_service.list_by_incident(incident_id)
    log_samples = []
    log_paths = resolve_access_logs()
    if log_paths:
        samples = traffic_engine.sample_records(
            log_paths,
            service_key=incident.service_key,
            start_time=incident.time_window_start,
            end_time=incident.time_window_end,
            limit=8,
        )
        log_samples = samples

    return {
        "incident": _serialize_incident(incident),
        "recommendations": [item.model_dump(mode="json") for item in recommendations],
        "log_samples": log_samples,
    }


@router.post("/{incident_id}/ai-summary")
async def generate_incident_ai_summary(
    incident_id: str,
    request: IncidentAISummaryRequest,
    incident_service=Depends(get_incident_service),
    recommendation_service=Depends(get_recommendation_service),
    traffic_engine=Depends(get_traffic_engine),
    llm_router=Depends(get_llm_router_dep),
):
    incident = incident_service.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")

    if not llm_router:
        raise HTTPException(status_code=409, detail="当前未启用可用的 LLM Provider")

    recommendations = recommendation_service.list_by_incident(incident_id)
    log_paths = resolve_access_logs()
    samples: list[dict[str, Any]] = []
    if log_paths:
        samples = traffic_engine.sample_records(
            log_paths,
            service_key=incident.service_key,
            start_time=incident.time_window_start,
            end_time=incident.time_window_end,
            limit=5,
        )

    sample_lines = [
        f"- {item.get('timestamp')} {item.get('method')} {item.get('path')} status={item.get('status')} latency_ms={item.get('latency_ms')} ip={item.get('client_ip')}"
        for item in samples
    ]
    recommendation_lines = [f"- {item.kind.value}: {item.recommendation}" for item in recommendations[:5]]

    fallback_payload = _build_fallback_payload(incident, recommendations, samples)
    messages = [
        {
            "role": "system",
            "content": (
                "你是运维分析助手。"
                "请严格输出 JSON 对象，字段固定为："
                "summary(string), risk_level(high|medium|low), confidence(0-1),"
                "primary_causes(string[]), recommended_actions(string[]), evidence_citations(string[])。"
                "不要输出 markdown，不要输出额外字段。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"服务: {incident.service_key}\n"
                f"时间窗: {incident.time_window_start.isoformat()} ~ {incident.time_window_end.isoformat()}\n"
                f"严重级别: {incident.severity}\n"
                f"已有摘要: {incident.summary}\n"
                f"推理标签: {', '.join(incident.reasoning_tags) or '-'}\n"
                f"推荐动作: {', '.join(incident.recommended_actions) or '-'}\n"
                f"建议草稿:\n{chr(10).join(recommendation_lines) if recommendation_lines else '-'}\n"
                f"日志样本:\n{chr(10).join(sample_lines) if sample_lines else '-'}"
            ),
        },
    ]

    guardrail_result = await run_guarded_structured_chat(
        llm_router=llm_router,
        messages=messages,
        schema_model=IncidentSummarySchema,
        fallback_payload=fallback_payload,
        provider=request.provider,
        temperature=0.1,
        max_tokens=450,
        source="incident_center",
        endpoint="incident_ai_summary",
        max_retries=1,
    )

    normalized = _normalize_summary_payload(guardrail_result.data, fallback_payload)
    result = IncidentAISummaryPayload(
        incident_id=incident.incident_id,
        provider=request.provider or llm_router.default_client_name,
        parse_mode=guardrail_result.parse_mode,
        validation_status=guardrail_result.validation_status,
        retry_count=guardrail_result.retry_count,
        guardrail_error_code=guardrail_result.error_code,
        guardrail_error_message=guardrail_result.error_message,
        log_sample_count=len(samples),
        recommendation_count=len(recommendations),
        **normalized,
    )
    return result.model_dump(mode="json")


@router.post("/analyze")
async def analyze_incident(
    request: IncidentAnalyzeRequest,
    task_manager=Depends(get_task_manager),
    asset_service=Depends(get_asset_service),
    traffic_engine=Depends(get_traffic_engine),
    resource_engine=Depends(get_resource_engine),
    incident_service=Depends(get_incident_service),
    signal_service=Depends(get_signal_service),
    alert_store=Depends(get_alert_store),
):
    service_key = request.service_key or "unknown/root"

    async def runner(task):
        await task_manager.set_stage(task.task_id, TaskStatus.COLLECTING, 15, "正在同步资产与采集流量数据")
        assets = await asset_service.sync_assets(service_key=service_key)
        related_asset_ids = [asset.asset_id for asset in assets if not request.asset_id or asset.asset_id == request.asset_id]
        log_paths = resolve_access_logs()
        traffic_summary = traffic_engine.summarize(log_paths, time_range=request.time_window, service_key=service_key)
        resource_summary = await resource_engine.summarize(service_key=service_key)
        active_alerts = await alert_store.query_alerts(status="active", limit=100)

        await task_manager.append_trace(
            task.task_id,
            "collect",
            "collect_signals",
            TaskStatus.COLLECTING,
            "已采集流量、资源和告警信号",
            {"related_asset_ids": related_asset_ids, "alert_count": len(active_alerts)},
        )
        signal_service.capture_log_summary(traffic_summary, service_key=service_key, asset_id=request.asset_id)
        signal_service.capture_resource_summary(resource_summary, service_key=service_key, asset_id=request.asset_id)
        signal_service.capture_alerts(active_alerts, service_key=service_key, asset_id=request.asset_id)

        await task_manager.set_stage(task.task_id, TaskStatus.ANALYZING, 70, "正在生成异常结论")
        incident = incident_service.build_incident(
            service_key=service_key,
            traffic_summary=traffic_summary,
            resource_summary=resource_summary,
            related_asset_ids=related_asset_ids,
            active_alerts=active_alerts,
            task_context={
                "task_id": task.task_id,
                "task_type": task.task_type.value,
                "status": task.status.value,
                "current_stage": TaskStatus.ANALYZING.value,
                "progress": 70,
                "progress_message": "正在生成异常结论",
                "trace_id": task.trace_id,
                "summary": "异常分析任务已完成信号聚合，正在汇总证据链",
            },
        )
        incident_payload = _serialize_incident(incident)
        await task_manager.append_trace(
            task.task_id,
            "analyze",
            "build_incident",
            TaskStatus.ANALYZING,
            incident.summary,
            {"incident_id": incident.incident_id, "severity": incident.severity, "confidence": incident.confidence},
        )

        artifact = task_manager.artifact_store.write_text(
            task_id=task.task_id,
            kind=ArtifactKind.JSON,
            content=json.dumps(
                {
                    "incident": incident_payload,
                    "traffic_summary": traffic_summary,
                    "resource_summary": resource_summary,
                },
                ensure_ascii=False,
                indent=2,
            ),
            filename=f"incident-{incident.incident_id}.json",
        )
        await task_manager.attach_artifact(task.task_id, artifact)
        await task_manager.event_bus.publish(
            {
                "type": "incident_updated",
                "incident": incident_payload,
                "task_id": task.task_id,
            }
        )
        return {"incident": incident_payload, "artifact": artifact.model_dump(mode="json")}

    task = await task_manager.create_task(
        task_type=TaskType.INCIDENT_ANALYSIS,
        payload=request.model_dump(),
        runner=runner,
    )
    return task.model_dump(mode="json")
