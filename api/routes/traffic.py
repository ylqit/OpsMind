"""流量接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .deps import get_traffic_engine, resolve_access_logs

router = APIRouter(prefix="/traffic", tags=["traffic"])


@router.get("/summary")
async def get_traffic_summary(
    time_range: str = "1h",
    service_key: str | None = None,
    asset_id: str | None = None,
    traffic_engine=Depends(get_traffic_engine),
):
    del asset_id
    log_paths = resolve_access_logs()
    return traffic_engine.summarize(log_paths, time_range=time_range, service_key=service_key)
