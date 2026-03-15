"""资源与资产接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .deps import get_asset_service, get_resource_engine

router = APIRouter(tags=["resources"])


def _serialize_asset(asset):
    payload = asset.model_dump(mode="json")
    source_refs = payload.get("source_refs", {}) if isinstance(payload, dict) else {}
    alignment = source_refs.get("alignment", {}) if isinstance(source_refs, dict) else {}
    payload["service_key_source"] = alignment.get("source", "")
    payload["service_key_candidates"] = alignment.get("candidates", [])
    payload["unmapped_reason"] = alignment.get("reason", "") if payload.get("unmapped") else ""
    payload["alignment_confidence"] = alignment.get("confidence", "")
    return payload


@router.get("/resources/summary")
async def get_resource_summary(
    time_range: str = "1h",
    service_key: str | None = None,
    asset_id: str | None = None,
    resource_engine=Depends(get_resource_engine),
):
    del asset_id
    return await resource_engine.summarize(time_range=time_range, service_key=service_key)


@router.get("/assets")
async def list_assets(
    asset_type: str | None = None,
    service_key: str | None = None,
    health_status: str | None = None,
    asset_service=Depends(get_asset_service),
):
    assets = await asset_service.sync_assets(service_key=service_key)
    filtered_assets = asset_service.list_assets(asset_type=asset_type, service_key=service_key, health_status=health_status)
    return {
        "items": [_serialize_asset(asset) for asset in filtered_assets],
        "total": len(filtered_assets),
        "synced": len(assets),
    }
