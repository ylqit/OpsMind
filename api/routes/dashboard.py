"""总览与报表接口。"""
from __future__ import annotations

import json
from datetime import date as date_type

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from engine.runtime.models import ArtifactKind, TaskStatus, TaskType

from .deps import (
    get_data_sources_status,
    get_incident_service,
    get_resource_engine,
    get_summary_builder,
    get_task_manager,
    get_traffic_engine,
    resolve_access_logs,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
report_router = APIRouter(prefix="/reports", tags=["reports"])


class DailyReportRequest(BaseModel):
    """日报生成请求。"""

    date: str = Field(default_factory=lambda: date_type.today().isoformat(), description="日期")
    scope: str = Field(default="global", description="报表范围")


@router.get("/overview")
async def get_dashboard_overview(
    time_range: str = "1h",
    service_key: str | None = None,
    traffic_engine=Depends(get_traffic_engine),
    resource_engine=Depends(get_resource_engine),
    incident_service=Depends(get_incident_service),
    summary_builder=Depends(get_summary_builder),
    data_sources_status=Depends(get_data_sources_status),
):
    log_paths = resolve_access_logs()
    traffic_summary = traffic_engine.summarize(log_paths, time_range=time_range, service_key=service_key)
    resource_summary = await resource_engine.summarize(service_key=service_key)
    incidents = incident_service.list_incidents(service_key=service_key)
    overview = summary_builder.build_overview(traffic_summary, resource_summary, incidents, data_sources_status)
    return overview.model_dump(mode="json")


@report_router.post("/daily")
async def create_daily_report(
    request: DailyReportRequest,
    task_manager=Depends(get_task_manager),
    traffic_engine=Depends(get_traffic_engine),
    resource_engine=Depends(get_resource_engine),
    incident_service=Depends(get_incident_service),
    summary_builder=Depends(get_summary_builder),
    data_sources_status=Depends(get_data_sources_status),
):
    async def runner(task):
        await task_manager.set_stage(task.task_id, TaskStatus.COLLECTING, 20, "正在收集总览数据")
        await task_manager.append_trace(task.task_id, "collect", "collect_overview", TaskStatus.COLLECTING, "已开始收集总览、流量、资源与异常数据")
        log_paths = resolve_access_logs()
        traffic_summary = traffic_engine.summarize(log_paths, time_range="24h")
        resource_summary = await resource_engine.summarize()
        incidents = incident_service.list_incidents()

        await task_manager.set_stage(task.task_id, TaskStatus.ANALYZING, 60, "正在整理日报内容")
        await task_manager.append_trace(task.task_id, "analyze", "build_daily_report", TaskStatus.ANALYZING, "已生成日报摘要结构")
        overview = summary_builder.build_overview(traffic_summary, resource_summary, incidents, data_sources_status)
        report_payload = {
            "date": request.date,
            "scope": request.scope,
            "overview": overview.model_dump(mode="json"),
            "incident_count": len(incidents),
        }

        await task_manager.set_stage(task.task_id, TaskStatus.GENERATING, 85, "正在输出日报文件")
        artifact = task_manager.artifact_store.write_text(
            task_id=task.task_id,
            kind=ArtifactKind.REPORT,
            content=json.dumps(report_payload, ensure_ascii=False, indent=2),
            filename=f"daily-report-{request.date}.json",
        )
        await task_manager.attach_artifact(task.task_id, artifact)
        return {"report": report_payload, "artifact": artifact.model_dump(mode="json")}

    task = await task_manager.create_task(
        task_type=TaskType.REPORT_GENERATION,
        payload=request.model_dump(),
        runner=runner,
    )
    return task.model_dump(mode="json")
