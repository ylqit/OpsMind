"""建议接口。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engine.llm.structured_output import run_guarded_structured_chat
from engine.runtime.models import ArtifactRef, TaskStatus, TaskType

from .deps import get_incident_service, get_llm_router_dep, get_recommendation_service, get_task_manager

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


@router.get("/{recommendation_id}")
async def get_recommendation_detail(
    recommendation_id: str,
    recommendation_service=Depends(get_recommendation_service),
):
    recommendation = recommendation_service.repository.get(recommendation_id)
    if not recommendation:
        raise HTTPException(status_code=404, detail="建议不存在")
    return recommendation.model_dump(mode="json")


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
        await task_manager.wait_for_confirm(task.task_id, result)
        return result

    task = await task_manager.create_task(
        task_type=TaskType.RECOMMENDATION_GENERATION,
        payload=request.model_dump(),
        runner=runner,
    )
    return task.model_dump(mode="json")
