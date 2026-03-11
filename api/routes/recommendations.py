"""建议接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from engine.runtime.models import ArtifactRef, TaskStatus, TaskType

from .deps import get_incident_service, get_recommendation_service, get_task_manager

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class RecommendationGenerateRequest(BaseModel):
    """建议生成请求。"""

    incident_id: str = Field(..., description="异常 ID")
    kinds: list[str] = Field(default_factory=list, description="建议类型")


@router.get("/{recommendation_id}")
async def get_recommendation_detail(
    recommendation_id: str,
    recommendation_service=Depends(get_recommendation_service),
):
    recommendation = recommendation_service.repository.get(recommendation_id)
    if not recommendation:
        raise HTTPException(status_code=404, detail="建议不存在")
    return recommendation.model_dump(mode="json")


@router.post("/generate")
async def generate_recommendations(
    request: RecommendationGenerateRequest,
    task_manager=Depends(get_task_manager),
    incident_service=Depends(get_incident_service),
    recommendation_service=Depends(get_recommendation_service),
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
        recommendations = await recommendation_service.generate_for_incident(
            task.task_id,
            incident,
            allowed_kinds=request.kinds,
        )
        for item in recommendations:
            for artifact in item.artifact_refs:
                artifact_ref = ArtifactRef.model_validate(artifact)
                await task_manager.attach_artifact(task.task_id, artifact_ref)

        result = {
            "incident_id": incident.incident_id,
            "recommendations": [item.model_dump(mode="json") for item in recommendations],
        }
        await task_manager.wait_for_confirm(task.task_id, result)
        return result

    task = await task_manager.create_task(
        task_type=TaskType.RECOMMENDATION_GENERATION,
        payload=request.model_dump(),
        runner=runner,
    )
    return task.model_dump(mode="json")
