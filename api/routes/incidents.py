"""异常接口。"""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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
    log_sample_count: int = 0
    recommendation_count: int = 0


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
    return {"items": [incident.model_dump(mode="json") for incident in incidents], "total": len(incidents)}


# 把原始访问记录压成详情页可读样本，避免前端处理复杂日志字段。
def _format_log_sample(record: dict[str, Any]) -> dict[str, Any]:
    geo = record.get("geo") or {}
    ua = record.get("ua") or {}
    return {
        "timestamp": record.get("timestamp"),
        "method": record.get("method") or "GET",
        "path": record.get("path") or "/",
        "status": int(record.get("status") or 0),
        "latency_ms": round(float(record.get("request_time") or 0.0) * 1000, 2),
        "client_ip": record.get("remote_addr") or "-",
        "geo_label": "/".join(
            [str(item) for item in [geo.get("country"), geo.get("region"), geo.get("city")] if item],
        )
        or "unknown",
        "user_agent": record.get("user_agent") or "Unknown",
        "browser": ua.get("browser") or "Unknown",
        "os": ua.get("os") or "Unknown",
        "device": ua.get("device") or "Unknown",
        "service_key": record.get("service_key") or "unknown/root",
    }


def _extract_json_payload(text: str) -> dict[str, Any] | None:
    """从模型输出提取 JSON，兼容 fenced code block 与纯文本包裹。"""
    text = (text or "").strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


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


def _build_fallback_payload(incident, recommendations: list[Any], samples: list[dict[str, Any]], summary_text: str) -> dict[str, Any]:
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
        "summary": summary_text.strip() or incident.summary,
        "risk_level": risk_level,
        "confidence": float(incident.confidence),
        "primary_causes": primary_causes,
        "recommended_actions": recommended_actions,
        "evidence_citations": evidence_citations,
    }


def _build_structured_payload(
    incident,
    recommendations: list[Any],
    samples: list[dict[str, Any]],
    llm_text: str,
) -> tuple[dict[str, Any], str]:
    """规范化模型输出，保证前端拿到稳定结构。"""
    parsed = _extract_json_payload(llm_text)
    fallback = _build_fallback_payload(incident, recommendations, samples, llm_text)

    if not parsed:
        return fallback, "text_fallback"

    summary = str(parsed.get("summary") or "").strip() or fallback["summary"]
    primary_causes = _to_string_list(parsed.get("primary_causes"), limit=5) or fallback["primary_causes"]
    recommended_actions = _to_string_list(parsed.get("recommended_actions"), limit=8) or fallback["recommended_actions"]
    evidence_citations = _to_string_list(parsed.get("evidence_citations"), limit=8) or fallback["evidence_citations"]

    payload = {
        "summary": summary,
        "risk_level": _normalize_risk_level(parsed.get("risk_level")),
        "confidence": _normalize_confidence(parsed.get("confidence")),
        "primary_causes": primary_causes,
        "recommended_actions": recommended_actions,
        "evidence_citations": evidence_citations,
    }
    return payload, "json"


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
        log_samples = [_format_log_sample(item) for item in samples]

    return {
        "incident": incident.model_dump(mode="json"),
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
        f"- {item.get('timestamp')} {item.get('method')} {item.get('path')} status={item.get('status')} rt={item.get('request_time')}"
        for item in samples
    ]
    recommendation_lines = [f"- {item.kind.value}: {item.recommendation}" for item in recommendations[:5]]

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

    try:
        llm_text = await llm_router.chat(
            messages,
            provider=request.provider,
            temperature=0.1,
            max_tokens=450,
            _source="incident_center",
            _endpoint="incident_ai_summary",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"AI 摘要生成失败：{exc}") from exc

    normalized, parse_mode = _build_structured_payload(incident, recommendations, samples, llm_text)

    result = IncidentAISummaryPayload(
        incident_id=incident.incident_id,
        provider=request.provider or llm_router.default_client_name,
        parse_mode=parse_mode,
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
        )
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
                    "incident": incident.model_dump(mode="json"),
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
                "incident": incident.model_dump(mode="json"),
                "task_id": task.task_id,
            }
        )
        return {"incident": incident.model_dump(mode="json"), "artifact": artifact.model_dump(mode="json")}

    task = await task_manager.create_task(
        task_type=TaskType.INCIDENT_ANALYSIS,
        payload=request.model_dump(),
        runner=runner,
    )
    return task.model_dump(mode="json")
