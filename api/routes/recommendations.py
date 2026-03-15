"""建议接口。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engine.llm.structured_output import run_guarded_structured_chat
from engine.runtime.models import ArtifactRef, RecommendationFeedback, TaskStatus, TaskType

from .deps import (
    get_incident_service,
    get_llm_router_dep,
    get_recommendation_feedback_repository_dep,
    get_recommendation_service,
    get_task_manager,
    get_traffic_engine,
    resolve_access_logs,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class RecommendationGenerateRequest(BaseModel):
    """建议生成请求。"""

    incident_id: str = Field(..., description="异常 ID")
    kinds: list[str] = Field(default_factory=list, description="建议类型")


class RecommendationAIReviewRequest(BaseModel):
    """AI 复核请求。"""

    provider: str | None = Field(default=None, description="指定 Provider")


class RecommendationReviewSchema(BaseModel):
    """AI 复核结构。"""

    summary: str = Field(..., min_length=1, max_length=800)
    risk_level: str = Field(..., pattern="^(high|medium|low)$")
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_assessment: str = Field(..., min_length=1, max_length=500)
    rollback_plan: list[str] = Field(default_factory=list, max_length=8)
    validation_checks: list[str] = Field(default_factory=list, max_length=8)
    evidence_citations: list[str] = Field(default_factory=list, max_length=8)


class RecommendationAIReviewPayload(BaseModel):
    """结构化 AI 复核响应。"""

    recommendation_id: str
    incident_id: str
    provider: str
    summary: str
    risk_level: str = "medium"
    confidence: float = 0.5
    risk_assessment: str = ""
    rollback_plan: list[str] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list)
    evidence_citations: list[str] = Field(default_factory=list)
    parse_mode: str = "fallback"
    validation_status: str = "fallback_template"
    retry_count: int = 0
    guardrail_error_code: str = ""
    guardrail_error_message: str = ""


class RecommendationFeedbackRequest(BaseModel):
    """建议反馈请求。"""

    action: str = Field(..., pattern="^(adopt|reject|rewrite)$")
    reason_code: str = Field(default="", max_length=120)
    comment: str = Field(default="", max_length=1000)
    operator: str = Field(default="anonymous", max_length=80)
    task_id: str | None = Field(default=None, max_length=80)


class RecommendationFeedbackListResponse(BaseModel):
    """建议反馈列表响应。"""

    recommendation_id: str
    summary: dict[str, int]
    items: list[dict[str, Any]]


def _artifact_filename(artifact: dict[str, Any]) -> str:
    raw_path = str(artifact.get("path") or "").strip()
    if not raw_path:
        return str(artifact.get("artifact_id") or "artifact")
    return Path(raw_path).name or raw_path


def _build_incident_metric_evidence(incident) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if not incident:
        return refs

    for index, item in enumerate(incident.evidence_refs[:8]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("metric") or item.get("type") or f"evidence_{index + 1}")
        summary = str(item.get("summary") or incident.summary or "").strip()
        metric = str(item.get("metric") or "").strip()
        value = item.get("value")
        unit = str(item.get("unit") or "").strip()
        value_text = ""
        if value is not None and str(value).strip():
            value_text = f"{value}{unit}" if unit else str(value)

        refs.append(
            {
                "evidence_id": f"metric_{incident.incident_id}_{index}",
                "source_type": "metric_snapshot",
                "title": title,
                "summary": summary or "指标快照证据",
                "quote": value_text,
                "metric": metric,
                "priority": int(item.get("priority") or 60),
                "signal_strength": str(item.get("signal_strength") or "medium"),
                "artifact_ref": None,
                "jump": {"kind": "none"},
            }
        )
    return refs


def _is_safe_artifact_path(path: Path, task_id: str) -> bool:
    """仅允许读取任务目录下的产物文件。"""
    if not task_id.strip():
        return False
    try:
        resolved = path.resolve()
    except Exception:  # noqa: BLE001
        return False
    lowered_parts = [part.lower() for part in resolved.parts]
    return "tasks" in lowered_parts and task_id.lower() in lowered_parts


def _read_artifact_excerpt(path: Path, max_lines: int = 12, max_chars: int = 420) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return ""
    lines = [line.rstrip() for line in content.splitlines()[:max_lines]]
    joined = "\n".join(lines).strip()
    if len(joined) > max_chars:
        return f"{joined[:max_chars]}..."
    return joined


def _extract_metric_quotes_from_text(text: str) -> list[tuple[str, str]]:
    if not text.strip():
        return []
    patterns = [
        ("error_rate", r"(?:error[_ ]?rate|错误率)[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)"),
        ("latency", r"(?:latency|延迟|request_time|avg_latency)[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)"),
        ("cpu", r"(?:cpu|CPU)[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)"),
        ("memory", r"(?:memory|内存)[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)"),
        ("restarts", r"(?:restart|重启)[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)"),
    ]
    found: list[tuple[str, str]] = []
    for metric, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        found.append((metric, match.group(1)))
        if len(found) >= 4:
            break
    return found


def _build_artifact_evidence(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    artifact_id = str(artifact.get("artifact_id") or "")
    task_id = str(artifact.get("task_id") or "")
    kind = str(artifact.get("kind") or "")
    preview = str(artifact.get("preview") or "").strip()
    raw_path = str(artifact.get("path") or "").strip()
    filename = _artifact_filename(artifact)

    refs: list[dict[str, Any]] = [
        {
            "evidence_id": f"artifact_{artifact_id or filename}",
            "source_type": "artifact",
            "title": filename,
            "summary": preview or f"任务产物（{kind or 'artifact'}）",
            "quote": preview[:200],
            "metric": "",
            "priority": 78,
            "signal_strength": "high" if kind in {"manifest", "diff", "json"} else "medium",
            "artifact_ref": artifact,
            "jump": {
                "kind": "artifact",
                "task_id": task_id,
                "artifact_id": artifact_id,
            },
        }
    ]

    if not raw_path:
        return refs
    artifact_path = Path(raw_path)
    if not artifact_path.exists() or not artifact_path.is_file():
        return refs
    if not _is_safe_artifact_path(artifact_path, task_id=task_id):
        return refs

    excerpt = _read_artifact_excerpt(artifact_path)
    if excerpt:
        if kind in {"log_snippet", "text"} or artifact_path.suffix.lower() == ".log" or "access" in filename.lower():
            refs.append(
                {
                    "evidence_id": f"log_{artifact_id or filename}",
                    "source_type": "log_snippet",
                    "title": f"{filename} 日志片段",
                    "summary": "来自任务产物的现场日志样本",
                    "quote": excerpt,
                    "metric": "",
                    "priority": 84,
                    "signal_strength": "high",
                    "artifact_ref": artifact,
                    "jump": {
                        "kind": "artifact",
                        "task_id": task_id,
                        "artifact_id": artifact_id,
                    },
                }
            )

        for metric, value in _extract_metric_quotes_from_text(excerpt):
            refs.append(
                {
                    "evidence_id": f"metric_{artifact_id or filename}_{metric}",
                    "source_type": "metric_snapshot",
                    "title": f"{filename} 指标快照",
                    "summary": f"从产物中提取到 {metric}={value}",
                    "quote": f"{metric}={value}",
                    "metric": metric,
                    "priority": 82,
                    "signal_strength": "medium",
                    "artifact_ref": artifact,
                    "jump": {
                        "kind": "artifact",
                        "task_id": task_id,
                        "artifact_id": artifact_id,
                    },
                }
            )
    return refs


def _build_log_sample_evidence(log_samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, item in enumerate(log_samples[:4]):
        status = int(item.get("status") or 0)
        latency_ms = float(item.get("latency_ms") or 0.0)
        refs.append(
            {
                "evidence_id": f"log_sample_{index}",
                "source_type": "log_snippet",
                "title": f"{item.get('path') or '/'} 访问日志样本",
                "summary": f"状态码 {status}，耗时 {round(latency_ms, 2)} ms，来源 {item.get('client_ip') or '-'}",
                "quote": str(item.get("user_agent") or "").strip(),
                "metric": "status" if status >= 500 else "latency_ms",
                "priority": 90 if status >= 500 else 76,
                "signal_strength": "high" if status >= 500 else "medium",
                "artifact_ref": None,
                "jump": {"kind": "none"},
            }
        )
    return refs


def _deduplicate_evidence(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in refs:
        artifact_ref = item.get("artifact_ref") or {}
        artifact_id = str(artifact_ref.get("artifact_id") or "")
        key = (
            str(item.get("source_type") or ""),
            str(item.get("title") or ""),
            str(item.get("quote") or "")[:120],
            artifact_id,
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
    return sorted(deduplicated, key=lambda item: int(item.get("priority") or 0), reverse=True)


def _build_evidence_summary(refs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(refs),
        "artifact": len([item for item in refs if item.get("source_type") == "artifact"]),
        "log_snippet": len([item for item in refs if item.get("source_type") == "log_snippet"]),
        "metric_snapshot": len([item for item in refs if item.get("source_type") == "metric_snapshot"]),
        "incident_evidence": len([item for item in refs if item.get("source_type") == "incident_evidence"]),
    }


def _build_insufficient_evidence_ref(recommendation, incident) -> dict[str, Any]:
    incident_summary = str(getattr(incident, "summary", "") or "").strip()
    recommendation_summary = str(getattr(recommendation, "recommendation", "") or "").strip()
    return {
        "evidence_id": f"incident_context_{recommendation.recommendation_id}",
        "source_type": "incident_evidence",
        "title": "证据不足说明",
        "summary": incident_summary or "当前建议缺少可追溯的现场证据，仅保留 incident 上下文作为提示。",
        "quote": recommendation_summary or "建议暂不具备执行条件",
        "metric": "",
        "priority": 95,
        "signal_strength": "low",
        "artifact_ref": None,
        "jump": {"kind": "none"},
    }


def _build_recommendation_evidence_payload(recommendation, incident, log_samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    refs: list[dict[str, Any]] = []
    refs.extend(_build_incident_metric_evidence(incident))
    refs.extend(_build_log_sample_evidence(log_samples or []))
    for artifact in recommendation.artifact_refs:
        if isinstance(artifact, dict):
            refs.extend(_build_artifact_evidence(artifact))

    evidence_refs = _deduplicate_evidence(refs)
    actionable_count = len(
        [item for item in evidence_refs if str(item.get("source_type") or "") in {"artifact", "log_snippet", "metric_snapshot"}]
    )
    insufficient = actionable_count == 0

    if insufficient:
        fallback_refs = [_build_insufficient_evidence_ref(recommendation, incident)]
        return {
            "evidence_refs": fallback_refs,
            "evidence_status": "insufficient",
            "evidence_message": "证据不足：当前缺少可追溯的任务产物、日志片段或指标快照，暂不建议执行强变更。",
            "confidence_effective": min(float(recommendation.confidence), 0.35),
            "recommendation_effective": "证据不足：建议先补充日志与指标证据，再进行变更决策。",
            "evidence_summary": _build_evidence_summary(fallback_refs),
        }

    return {
        "evidence_refs": evidence_refs,
        "evidence_status": "sufficient",
        "evidence_message": "已提取现场证据，可追溯到任务产物与指标快照。",
        "confidence_effective": float(recommendation.confidence),
        "recommendation_effective": recommendation.recommendation,
        "evidence_summary": _build_evidence_summary(evidence_refs),
    }


def _to_string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            output.append(text)
        if len(output) >= limit:
            break
    return output


def _normalize_risk_level(value: Any) -> str:
    level = str(value or "").strip().lower()
    if level in {"high", "medium", "low"}:
        return level
    return "medium"


def _normalize_confidence(value: Any, default: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return max(0.0, min(1.0, score))


def _build_fallback_review_payload(recommendation, incident) -> dict[str, Any]:
    risk_level = "high" if incident.severity == "critical" else "medium" if incident.severity == "warning" else "low"
    validation_checks = [
        "在测试或灰度环境先验证建议草稿。",
        "观察错误率、延迟和资源占用是否回落到基线。",
        "确认变更窗口与回滚窗口已经预留。",
    ]
    rollback_plan = [
        "保留当前线上配置快照。",
        "若指标恶化，先回滚到基线草稿并重启相关工作负载。",
        "回滚后复核关键监控项，确认服务恢复。",
    ]
    evidence_citations = [f"tag:{tag}" for tag in incident.reasoning_tags[:3]]
    for artifact in recommendation.artifact_refs[:3]:
        artifact_path = str(artifact.get("path") or artifact.get("artifact_id") or "")
        if artifact_path:
            evidence_citations.append(f"artifact:{artifact_path}")
    if not evidence_citations:
        evidence_citations = ["evidence:incident_summary"]

    return {
        "summary": recommendation.recommendation,
        "risk_level": risk_level,
        "confidence": max(0.5, float(recommendation.confidence)),
        "risk_assessment": recommendation.risk_note or "建议草稿需人工审核后再执行。",
        "rollback_plan": rollback_plan,
        "validation_checks": validation_checks,
        "evidence_citations": evidence_citations,
    }


def _normalize_review_payload(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": str(payload.get("summary") or "").strip() or fallback["summary"],
        "risk_level": _normalize_risk_level(payload.get("risk_level")),
        "confidence": _normalize_confidence(payload.get("confidence"), fallback["confidence"]),
        "risk_assessment": str(payload.get("risk_assessment") or "").strip() or fallback["risk_assessment"],
        "rollback_plan": _to_string_list(payload.get("rollback_plan"), limit=8) or fallback["rollback_plan"],
        "validation_checks": _to_string_list(payload.get("validation_checks"), limit=8) or fallback["validation_checks"],
        "evidence_citations": _to_string_list(payload.get("evidence_citations"), limit=8) or fallback["evidence_citations"],
    }


def _resolve_feedback_task_id(recommendation, requested_task_id: str | None) -> str | None:
    task_id = (requested_task_id or "").strip()
    if task_id:
        return task_id
    for artifact in recommendation.artifact_refs:
        if not isinstance(artifact, dict):
            continue
        candidate = str(artifact.get("task_id") or "").strip()
        if candidate:
            return candidate
    return None


@router.get("/{recommendation_id}")
async def get_recommendation_detail(
    recommendation_id: str,
    recommendation_service=Depends(get_recommendation_service),
    incident_service=Depends(get_incident_service),
    traffic_engine=Depends(get_traffic_engine),
):
    recommendation = recommendation_service.repository.get(recommendation_id)
    if not recommendation:
        raise HTTPException(status_code=404, detail="建议不存在")

    incident = incident_service.get_incident(recommendation.incident_id)
    log_samples: list[dict[str, Any]] = []
    log_paths = resolve_access_logs()
    if incident and log_paths:
        log_samples = traffic_engine.sample_records(
            log_paths,
            service_key=incident.service_key,
            start_time=incident.time_window_start,
            end_time=incident.time_window_end,
            limit=5,
        )
    evidence_payload = _build_recommendation_evidence_payload(recommendation, incident, log_samples=log_samples)

    detail = recommendation.model_dump(mode="json")
    detail.update(evidence_payload)
    detail["log_samples"] = log_samples
    return detail


@router.get("/{recommendation_id}/feedback")
async def list_recommendation_feedback(
    recommendation_id: str,
    recommendation_service=Depends(get_recommendation_service),
    feedback_repository=Depends(get_recommendation_feedback_repository_dep),
):
    recommendation = recommendation_service.repository.get(recommendation_id)
    if not recommendation:
        raise HTTPException(status_code=404, detail="建议不存在")
    if not feedback_repository:
        raise HTTPException(status_code=500, detail="反馈存储尚未初始化")

    items = feedback_repository.list_by_recommendation(recommendation_id, limit=80)
    summary = feedback_repository.summarize_by_recommendation(recommendation_id)
    payload = RecommendationFeedbackListResponse(
        recommendation_id=recommendation_id,
        summary=summary,
        items=[item.model_dump(mode="json") for item in items],
    )
    return payload.model_dump(mode="json")


@router.post("/{recommendation_id}/feedback")
async def save_recommendation_feedback(
    recommendation_id: str,
    request: RecommendationFeedbackRequest,
    recommendation_service=Depends(get_recommendation_service),
    feedback_repository=Depends(get_recommendation_feedback_repository_dep),
):
    recommendation = recommendation_service.repository.get(recommendation_id)
    if not recommendation:
        raise HTTPException(status_code=404, detail="建议不存在")
    if not feedback_repository:
        raise HTTPException(status_code=500, detail="反馈存储尚未初始化")

    action = request.action.strip().lower()
    reason_code = request.reason_code.strip()
    if action in {"reject", "rewrite"} and not reason_code:
        raise HTTPException(status_code=422, detail="拒绝或改写反馈必须提供 reason_code")

    feedback = RecommendationFeedback(
        recommendation_id=recommendation.recommendation_id,
        incident_id=recommendation.incident_id,
        task_id=_resolve_feedback_task_id(recommendation, request.task_id),
        action=action,
        reason_code=reason_code,
        comment=request.comment.strip(),
        operator=request.operator.strip() or "anonymous",
    )
    saved = feedback_repository.save(feedback)
    summary = feedback_repository.summarize_by_recommendation(recommendation_id)
    return {
        "item": saved.model_dump(mode="json"),
        "summary": summary,
    }


@router.post("/{recommendation_id}/ai-review")
async def review_recommendation_with_ai(
    recommendation_id: str,
    request: RecommendationAIReviewRequest,
    recommendation_service=Depends(get_recommendation_service),
    incident_service=Depends(get_incident_service),
    llm_router=Depends(get_llm_router_dep),
):
    recommendation = recommendation_service.repository.get(recommendation_id)
    if not recommendation:
        raise HTTPException(status_code=404, detail="建议不存在")

    incident = incident_service.get_incident(recommendation.incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="建议对应的异常不存在")

    if not llm_router:
        raise HTTPException(status_code=409, detail="当前未启用可用的 LLM Provider")

    evidence_lines = []
    for item in incident.evidence_refs[:6]:
        title = str(item.get("title") or item.get("metric") or item.get("type") or "evidence")
        summary = str(item.get("summary") or item.get("reason") or "")
        value = str(item.get("value") or "").strip()
        text = f"- {title}"
        if value:
            text = f"{text} value={value}"
        if summary:
            text = f"{text} ({summary})"
        evidence_lines.append(text)

    artifact_lines = []
    for artifact in recommendation.artifact_refs[:6]:
        kind = str(artifact.get("kind") or "artifact")
        path = str(artifact.get("path") or artifact.get("artifact_id") or "-")
        preview = str(artifact.get("preview") or "")
        line = f"- {kind}: {path}"
        if preview:
            line = f"{line} ({preview})"
        artifact_lines.append(line)

    fallback_payload = _build_fallback_review_payload(recommendation, incident)
    messages = [
        {
            "role": "system",
            "content": (
                "你是资深 SRE 评审助手。"
                "请严格输出 JSON 对象，字段固定为："
                "summary(string), risk_level(high|medium|low), confidence(0-1),"
                "risk_assessment(string), rollback_plan(string[]),"
                "validation_checks(string[]), evidence_citations(string[])。"
                "不要输出 markdown，不要输出额外字段。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"incident_id: {incident.incident_id}\n"
                f"service_key: {incident.service_key}\n"
                f"severity: {incident.severity}\n"
                f"incident_summary: {incident.summary}\n"
                f"incident_tags: {', '.join(incident.reasoning_tags) or '-'}\n"
                f"recommendation_kind: {recommendation.kind.value}\n"
                f"recommendation_text: {recommendation.recommendation}\n"
                f"risk_note: {recommendation.risk_note}\n"
                f"incident_evidence:\n{chr(10).join(evidence_lines) if evidence_lines else '-'}\n"
                f"artifacts:\n{chr(10).join(artifact_lines) if artifact_lines else '-'}"
            ),
        },
    ]

    guardrail_result = await run_guarded_structured_chat(
        llm_router=llm_router,
        messages=messages,
        schema_model=RecommendationReviewSchema,
        fallback_payload=fallback_payload,
        provider=request.provider,
        temperature=0.1,
        max_tokens=500,
        source="recommendation_center",
        endpoint="recommendation_ai_review",
        max_retries=1,
    )

    normalized = _normalize_review_payload(guardrail_result.data, fallback_payload)
    result = RecommendationAIReviewPayload(
        recommendation_id=recommendation.recommendation_id,
        incident_id=recommendation.incident_id,
        provider=request.provider or llm_router.default_client_name,
        parse_mode=guardrail_result.parse_mode,
        validation_status=guardrail_result.validation_status,
        retry_count=guardrail_result.retry_count,
        guardrail_error_code=guardrail_result.error_code,
        guardrail_error_message=guardrail_result.error_message,
        **normalized,
    )
    return result.model_dump(mode="json")


@router.post("/generate")
async def generate_recommendations(
    request: RecommendationGenerateRequest,
    task_manager=Depends(get_task_manager),
    incident_service=Depends(get_incident_service),
    recommendation_service=Depends(get_recommendation_service),
    llm_router=Depends(get_llm_router_dep),
):
    incident = incident_service.get_incident(request.incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="异常不存在")

    async def runner(task):
        await task_manager.set_stage(task.task_id, TaskStatus.COLLECTING, 20, "正在读取异常上下文")
        await task_manager.append_trace(
            task.task_id,
            "collect",
            "load_incident",
            TaskStatus.COLLECTING,
            "已加载异常详情",
            {"incident_id": incident.incident_id, "severity": incident.severity},
        )

        await task_manager.set_stage(task.task_id, TaskStatus.ANALYZING, 55, "正在匹配建议类型")
        await task_manager.append_trace(
            task.task_id,
            "analyze",
            "determine_recommendations",
            TaskStatus.ANALYZING,
            "已生成建议候选集合",
            {"reasoning_tags": incident.reasoning_tags},
        )

        await task_manager.set_stage(task.task_id, TaskStatus.GENERATING, 80, "正在生成配置草稿")
        recommendations, guardrail_summary = await recommendation_service.generate_for_incident(
            task.task_id,
            incident,
            allowed_kinds=request.kinds,
            llm_router=llm_router,
            return_guardrail=True,
        )

        await task_manager.append_trace(
            task.task_id,
            "generate",
            "llm_guardrail",
            TaskStatus.GENERATING,
            "已完成建议结构化校验",
            {
                "fallback_count": guardrail_summary.get("fallback_count", 0),
                "retried_count": guardrail_summary.get("retried_count", 0),
                "schema_error_count": guardrail_summary.get("schema_error_count", 0),
            },
        )

        for item in recommendations:
            for artifact in item.artifact_refs:
                artifact_ref = ArtifactRef.model_validate(artifact)
                await task_manager.attach_artifact(task.task_id, artifact_ref)

        result = {
            "incident_id": incident.incident_id,
            "recommendations": [item.model_dump(mode="json") for item in recommendations],
            "guardrail_summary": guardrail_summary,
        }
        if not recommendations:
            await task_manager.append_trace(
                task.task_id,
                "generate",
                "no_actionable_recommendation",
                TaskStatus.GENERATING,
                "未生成可确认建议，任务自动完成",
                {
                    "incident_id": incident.incident_id,
                    "guardrail_summary": guardrail_summary,
                },
            )
            await task_manager.complete_task(task.task_id, result)
            return result

        await task_manager.wait_for_confirm(task.task_id, result)
        return result

    task = await task_manager.create_task(
        task_type=TaskType.RECOMMENDATION_GENERATION,
        payload=request.model_dump(),
        runner=runner,
    )
    return task.model_dump(mode="json")
