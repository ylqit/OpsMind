"""异常接口。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engine.domain.incident_evidence import normalize_incident_evidence, sort_incident_evidence, summarize_incident_evidence
from engine.llm.structured_output import run_guarded_scenario_chat
from engine.runtime.models import ArtifactKind, Claim, TaskStatus, TaskType

from .deps import (
    get_alert_store,
    get_ai_writeback_repository_dep,
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
    claims: list[dict[str, Any]] = Field(default_factory=list)
    role_views: dict[str, dict[str, Any]] = Field(default_factory=dict)
    parse_mode: str = "fallback"
    validation_status: str = "fallback_template"
    retry_count: int = 0
    guardrail_error_code: str = ""
    guardrail_error_message: str = ""
    log_sample_count: int = 0
    recommendation_count: int = 0


class IncidentRoleViewSchema(BaseModel):
    """异常总结中的单视角结构。"""

    headline: str = Field(..., min_length=1, max_length=300)
    key_findings: list[str] = Field(default_factory=list, max_length=6)
    actions: list[str] = Field(default_factory=list, max_length=6)


class IncidentRoleViewsSchema(BaseModel):
    """异常总结中的多视角结构。"""

    traffic: IncidentRoleViewSchema | None = None
    resource: IncidentRoleViewSchema | None = None
    risk: IncidentRoleViewSchema | None = None


class IncidentSummarySchema(BaseModel):
    """异常 AI 总结结构。"""

    summary: str = Field(..., min_length=1, max_length=800)
    risk_level: str = Field(..., pattern="^(high|medium|low)$")
    confidence: float = Field(..., ge=0.0, le=1.0)
    primary_causes: list[str] = Field(default_factory=list, max_length=6)
    recommended_actions: list[str] = Field(default_factory=list, max_length=10)
    evidence_citations: list[str] = Field(default_factory=list, max_length=10)
    role_views: IncidentRoleViewsSchema | None = None


def _collect_evidence_ids(items: list[dict[str, Any]], limit: int = 3) -> list[str]:
    evidence_ids: list[str] = []
    for item in items:
        evidence_id = str(item.get("evidence_id") or "").strip()
        if not evidence_id or evidence_id in evidence_ids:
            continue
        evidence_ids.append(evidence_id)
        if len(evidence_ids) >= limit:
            break
    return evidence_ids


def _build_claim(
    *,
    claim_id: str,
    kind: str,
    statement: str,
    evidence_ids: list[str],
    confidence: float,
    limitations: list[str],
    title: str = "",
    source: str = "incident",
    next_step: str | None = None,
) -> dict[str, Any] | None:
    normalized_statement = str(statement).strip()
    if not normalized_statement:
        return None
    claim = Claim.model_validate(
        {
            "claim_id": claim_id,
            "kind": kind,
            "statement": normalized_statement,
            "evidence_ids": [item for item in evidence_ids if item],
            "confidence": confidence,
            "limitations": [item for item in limitations if str(item).strip()],
            "title": title,
            "source": source,
            "next_step": str(next_step).strip() or None if next_step is not None else None,
        }
    )
    return claim.model_dump(mode="python")


def _build_claim_limitations(
    *,
    evidence_refs: list[dict[str, Any]],
    evidence_summary: dict[str, Any] | None = None,
    risk_level: str | None = None,
) -> list[str]:
    layer_counts = (evidence_summary or {}).get("layers")
    if not isinstance(layer_counts, dict):
        layer_counts = {}

    limitations: list[str] = []
    if len(evidence_refs) < 2:
        limitations.append("当前证据数量有限，结论需要继续验证。")
    if not layer_counts.get("traffic"):
        limitations.append("缺少流量侧证据，入口行为判断可信度有限。")
    if not layer_counts.get("resource"):
        limitations.append("缺少资源侧证据，容量与瓶颈判断仍需补充。")
    if risk_level == "high":
        limitations.append("当前风险较高，执行前需要准备回滚与观察窗口。")

    deduplicated: list[str] = []
    for item in limitations:
        if item not in deduplicated:
            deduplicated.append(item)
    return deduplicated[:3]


def _build_incident_claims(incident_payload: dict[str, Any], evidence_summary: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_refs = [item for item in incident_payload.get("evidence_refs") or [] if isinstance(item, dict)]
    highlight_ids = _collect_evidence_ids(evidence_summary.get("highlights") or [], limit=3)
    default_evidence_ids = highlight_ids or _collect_evidence_ids(evidence_refs, limit=3)
    confidence = _normalize_confidence(incident_payload.get("confidence"))
    risk_level = "high" if str(incident_payload.get("severity") or "").lower() == "critical" else "medium"
    limitations = _build_claim_limitations(
        evidence_refs=evidence_refs,
        evidence_summary=evidence_summary,
        risk_level=risk_level,
    )
    claims: list[dict[str, Any]] = []

    summary_claim = _build_claim(
        claim_id=f"{incident_payload.get('incident_id')}_summary",
        kind="summary",
        title="异常结论",
        statement=str(incident_payload.get("summary") or ""),
        evidence_ids=default_evidence_ids,
        confidence=confidence,
        limitations=limitations,
        source="incident_detail",
        next_step=str(evidence_summary.get("next_step") or ""),
    )
    if summary_claim:
        claims.append(summary_claim)

    for index, raw_cause in enumerate(_to_string_list(incident_payload.get("reasoning_tags"), limit=3), start=1):
        statement = f"当前异常与“{raw_cause.replace('_', ' ')}”信号相关，需要继续交叉验证。"
        cause_claim = _build_claim(
            claim_id=f"{incident_payload.get('incident_id')}_cause_{index}",
            kind="cause",
            title=f"原因判断 {index}",
            statement=statement,
            evidence_ids=default_evidence_ids[:2] or default_evidence_ids,
            confidence=max(0.35, min(confidence, 0.82)),
            limitations=limitations,
            source="incident_detail",
        )
        if cause_claim:
            claims.append(cause_claim)

    for index, action in enumerate(_to_string_list(incident_payload.get("recommended_actions"), limit=2), start=1):
        action_claim = _build_claim(
            claim_id=f"{incident_payload.get('incident_id')}_action_{index}",
            kind="action",
            title=f"建议动作 {index}",
            statement=action,
            evidence_ids=default_evidence_ids[:2] or default_evidence_ids,
            confidence=max(0.3, min(confidence, 0.76)),
            limitations=["执行前请结合变更窗口、回滚预案和现场观察结果复核。"],
            source="incident_detail",
        )
        if action_claim:
            claims.append(action_claim)

    if risk_level:
        risk_statement = "当前异常风险较高，建议先控制影响面再进行后续定位。" if risk_level == "high" else "当前异常风险可控，但仍建议在观察窗口内逐步验证。"
        risk_claim = _build_claim(
            claim_id=f"{incident_payload.get('incident_id')}_risk",
            kind="risk",
            title="风险判断",
            statement=risk_statement,
            evidence_ids=default_evidence_ids[:2] or default_evidence_ids,
            confidence=max(0.35, min(confidence, 0.72)),
            limitations=limitations,
            source="incident_detail",
        )
        if risk_claim:
            claims.append(risk_claim)

    return claims


def _build_incident_ai_claims(
    incident,
    normalized_payload: dict[str, Any],
    evidence_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    confidence = _normalize_confidence(normalized_payload.get("confidence"))
    default_evidence_ids = _collect_evidence_ids(evidence_refs, limit=3)
    limitations = _build_claim_limitations(
        evidence_refs=evidence_refs,
        risk_level=str(normalized_payload.get("risk_level") or "medium"),
    )
    claims: list[dict[str, Any]] = []

    summary_claim = _build_claim(
        claim_id=f"{incident.incident_id}_ai_summary",
        kind="summary",
        title="AI 总结",
        statement=str(normalized_payload.get("summary") or ""),
        evidence_ids=default_evidence_ids,
        confidence=confidence,
        limitations=limitations,
        source="incident_ai_summary",
    )
    if summary_claim:
        claims.append(summary_claim)

    for index, cause in enumerate(_to_string_list(normalized_payload.get("primary_causes"), limit=3), start=1):
        cause_claim = _build_claim(
            claim_id=f"{incident.incident_id}_ai_cause_{index}",
            kind="cause",
            title=f"AI 原因判断 {index}",
            statement=cause,
            evidence_ids=default_evidence_ids[:2] or default_evidence_ids,
            confidence=max(0.35, min(confidence, 0.8)),
            limitations=limitations,
            source="incident_ai_summary",
        )
        if cause_claim:
            claims.append(cause_claim)

    for index, action in enumerate(_to_string_list(normalized_payload.get("recommended_actions"), limit=2), start=1):
        action_claim = _build_claim(
            claim_id=f"{incident.incident_id}_ai_action_{index}",
            kind="action",
            title=f"AI 建议动作 {index}",
            statement=action,
            evidence_ids=default_evidence_ids[:2] or default_evidence_ids,
            confidence=max(0.3, min(confidence, 0.74)),
            limitations=["AI 建议需结合真实发布窗口与回滚能力确认后再执行。"],
            source="incident_ai_summary",
        )
        if action_claim:
            claims.append(action_claim)

    return claims


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


def _build_evidence_summary(incident_payload: dict[str, Any]) -> dict[str, Any]:
    evidence_refs = incident_payload.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        evidence_refs = []
    return summarize_incident_evidence([item for item in evidence_refs if isinstance(item, dict)])


def _extract_recommendation_items(task_payload: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations = task_payload.get("recommendations")
    if not isinstance(recommendations, list):
        return []
    return [item for item in recommendations if isinstance(item, dict)]


def _task_matches_incident(task, incident_id: str) -> bool:
    payload_incident_id = str(task.payload.get("incident_id") or "").strip()
    if payload_incident_id == incident_id:
        return True
    result_ref = task.result_ref if isinstance(task.result_ref, dict) else {}
    result_incident_id = str(result_ref.get("incident_id") or "").strip()
    return result_incident_id == incident_id


def _serialize_linked_recommendation_task(task, task_manager) -> dict[str, Any]:
    payload = task.model_dump(mode="json")
    artifacts = task_manager.list_artifacts(task.task_id)
    artifact_count = len(artifacts)
    recommendation_items = _extract_recommendation_items(payload.get("result_ref") or {})
    recommendation_ids = [
        str(item.get("recommendation_id") or "").strip()
        for item in recommendation_items
        if str(item.get("recommendation_id") or "").strip()
    ]
    payload.update(
        {
            "artifact_ready": artifact_count > 0 or len(recommendation_items) > 0,
            "artifact_count": artifact_count,
            "recommendation_count": len(recommendation_items),
            "recommendation_ids": recommendation_ids,
        }
    )
    return payload


def _build_recommendation_task_links(incident_id: str, task_manager) -> list[dict[str, Any]]:
    linked_tasks = []
    tasks = task_manager.list_tasks(task_type=TaskType.RECOMMENDATION_GENERATION.value)
    for task in tasks:
        if not _task_matches_incident(task, incident_id):
            continue
        linked_tasks.append(_serialize_linked_recommendation_task(task, task_manager))
    return linked_tasks


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


def _build_fallback_role_views(
    incident,
    primary_causes: list[str],
    recommended_actions: list[str],
    samples: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    high_status_samples = [item for item in samples if int(item.get("status") or 0) >= 500]
    traffic_findings = [
        f"{item.get('method')} {item.get('path')} status={item.get('status')} latency={item.get('latency_ms')}ms"
        for item in (high_status_samples or samples)[:3]
    ]
    if not traffic_findings:
        traffic_findings = [cause for cause in primary_causes if "流量" in cause or "请求" in cause][:2]
    if not traffic_findings:
        traffic_findings = ["当前时间窗缺少可用流量样本"]

    resource_findings = [cause for cause in primary_causes if any(keyword in cause for keyword in ["CPU", "内存", "资源", "重启", "OOM"])]
    if not resource_findings:
        resource_findings = primary_causes[:2]
    if not resource_findings:
        resource_findings = ["资源侧证据不足，建议结合监控继续观察"]

    risk_findings = []
    if str(incident.severity).lower() == "critical":
        risk_findings.append("当前异常等级为 critical，需优先控制变更风险")
    risk_findings.extend(primary_causes[:2])
    if not risk_findings:
        risk_findings = ["当前异常风险可控，建议继续观察趋势变化"]

    traffic_headline = "入口流量侧存在异常波动，建议优先确认错误峰值与热点路径。"
    if high_status_samples:
        traffic_headline = "入口流量侧出现 5xx 聚集，需要先抑制失败请求扩散。"
    if not samples:
        traffic_headline = "缺少流量样本，流量侧结论可信度有限。"

    resource_headline = "资源侧出现紧张信号，建议优先核对容量与限额配置。"
    if not any(keyword in " ".join(resource_findings) for keyword in ["CPU", "内存", "资源", "重启", "OOM"]):
        resource_headline = "资源侧暂未观察到明确瓶颈，建议继续跟踪关键指标。"

    risk_headline = "风险侧建议采用小步变更策略，先验证再放量。"
    if str(incident.severity).lower() == "critical":
        risk_headline = "风险侧优先建议止血与回滚预案并行，避免影响继续扩大。"

    return {
        "traffic": {
            "headline": traffic_headline,
            "key_findings": traffic_findings[:6],
            "actions": (recommended_actions[:2] or ["先定位异常路径，再逐步限流验证"])[:6],
        },
        "resource": {
            "headline": resource_headline,
            "key_findings": resource_findings[:6],
            "actions": (recommended_actions[1:3] or recommended_actions[:2] or ["核对资源限额并补充容量余量"])[:6],
        },
        "risk": {
            "headline": risk_headline,
            "key_findings": risk_findings[:6],
            "actions": (recommended_actions[:3] or ["保留回滚预案并设定观察窗口"])[:6],
        },
    }


def _normalize_role_view(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    headline = str(value.get("headline") or "").strip() or str(fallback.get("headline") or "").strip() or "暂无结论"
    key_findings = _to_string_list(value.get("key_findings"), limit=6) or _to_string_list(fallback.get("key_findings"), limit=6)
    actions = _to_string_list(value.get("actions"), limit=6) or _to_string_list(fallback.get("actions"), limit=6)
    return {
        "headline": headline,
        "key_findings": key_findings,
        "actions": actions,
    }


def _normalize_role_views(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_views = payload.get("role_views")
    if not isinstance(raw_views, dict):
        raw_views = {}
    # 统一补齐三类视角，保证前端展示结构稳定。
    return {
        "traffic": _normalize_role_view(raw_views.get("traffic"), fallback["traffic"]),
        "resource": _normalize_role_view(raw_views.get("resource"), fallback["resource"]),
        "risk": _normalize_role_view(raw_views.get("risk"), fallback["risk"]),
    }


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
        "role_views": _build_fallback_role_views(incident, primary_causes, recommended_actions, samples),
    }


def _normalize_summary_payload(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": str(payload.get("summary") or "").strip() or fallback["summary"],
        "risk_level": _normalize_risk_level(payload.get("risk_level")),
        "confidence": _normalize_confidence(payload.get("confidence")),
        "primary_causes": _to_string_list(payload.get("primary_causes"), limit=6) or fallback["primary_causes"],
        "recommended_actions": _to_string_list(payload.get("recommended_actions"), limit=10) or fallback["recommended_actions"],
        "evidence_citations": _to_string_list(payload.get("evidence_citations"), limit=10) or fallback["evidence_citations"],
        "role_views": _normalize_role_views(payload, fallback["role_views"]),
    }


@router.get("/{incident_id}")
async def get_incident_detail(
    incident_id: str,
    incident_service=Depends(get_incident_service),
    recommendation_service=Depends(get_recommendation_service),
    traffic_engine=Depends(get_traffic_engine),
    task_manager=Depends(get_task_manager),
    writeback_repository=Depends(get_ai_writeback_repository_dep),
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

    incident_payload = _serialize_incident(incident)
    recommendation_tasks = _build_recommendation_task_links(incident_id, task_manager)
    evidence_summary = _build_evidence_summary(incident_payload)
    return {
        "incident": incident_payload,
        "recommendations": [item.model_dump(mode="json") for item in recommendations],
        "log_samples": log_samples,
        "evidence_summary": evidence_summary,
        "claims": _build_incident_claims(incident_payload, evidence_summary),
        "assistant_writebacks": [item.model_dump(mode="json") for item in (writeback_repository.list_by_incident(incident_id) if writeback_repository else [])],
        "recommendation_task": recommendation_tasks[0] if recommendation_tasks else None,
        "recommendation_tasks": recommendation_tasks,
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
                "primary_causes(string[]), recommended_actions(string[]), evidence_citations(string[]),"
                "role_views(object: traffic/resource/risk，每项包含 headline/key_findings/actions)。"
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

    guardrail_result = await run_guarded_scenario_chat(
        llm_router=llm_router,
        assistant_role="运维分析助手",
        required_fields=(
            "summary(string), risk_level(high|medium|low), confidence(0-1), "
            "primary_causes(string[]), recommended_actions(string[]), evidence_citations(string[]), "
            "role_views(object: traffic/resource/risk -> headline/key_findings/actions)"
        ),
        context_lines=[str(messages[1].get("content") or "-")],
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
    incident_payload = _serialize_incident(incident)
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
        claims=_build_incident_ai_claims(incident, normalized, incident_payload.get("evidence_refs") or []),
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
        evidence_summary = _build_evidence_summary(incident_payload)
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
                    "evidence_summary": evidence_summary,
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
                "evidence_summary": evidence_summary,
                "task_id": task.task_id,
            }
        )
        return {
            "incident": incident_payload,
            "evidence_summary": evidence_summary,
            "artifact": artifact.model_dump(mode="json"),
        }

    task = await task_manager.create_task(
        task_type=TaskType.INCIDENT_ANALYSIS,
        payload=request.model_dump(),
        runner=runner,
    )
    return task.model_dump(mode="json")
