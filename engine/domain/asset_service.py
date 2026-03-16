"""
资产服务。

把 Docker、主机和 Prometheus 信息对齐成统一资产模型。
"""
from __future__ import annotations

from typing import List, Optional

from engine.domain.service_key_resolver import resolve_docker_service_key, resolve_host_service_key
from engine.integrations.data_sources.docker_adapter import DockerAdapter
from engine.runtime.models import Asset, AssetType
from engine.runtime.time_utils import utc_now
from engine.storage.repositories import AssetRepository


class AssetService:
    """统一资产服务。"""

    def __init__(self, asset_repository: AssetRepository, docker_host: str):
        self.asset_repository = asset_repository
        self.docker_host = docker_host

    async def sync_assets(self, service_key: Optional[str] = None) -> List[Asset]:
        assets = [self._build_host_asset()]
        assets.extend(await self._build_container_assets(service_key=service_key))
        for asset in assets:
            self.asset_repository.save(asset)
        return assets

    def list_assets(self, asset_type: Optional[str] = None, service_key: Optional[str] = None, health_status: Optional[str] = None) -> List[Asset]:
        return self.asset_repository.list(asset_type=asset_type, service_key=service_key, health_status=health_status)

    def _build_host_asset(self) -> Asset:
        alignment = resolve_host_service_key("local-host")
        return Asset(
            asset_id="asset_host_local",
            asset_type=AssetType.HOST,
            name="local-host",
            service_key=alignment["service_key"],
            labels={"platform": "opsMind"},
            source_refs={"source": "host_monitor", "alignment": alignment},
            health_status="healthy",
            unmapped=bool(alignment["unmapped"]),
            updated_at=utc_now(),
        )

    async def _build_container_assets(self, service_key: Optional[str]) -> List[Asset]:
        adapter = DockerAdapter(host=self.docker_host)
        if not await adapter.initialize():
            return []
        containers = await adapter.list_containers(all=True)
        results: List[Asset] = []
        for item in containers:
            detail = await adapter.get_container(item["name"]) or {}
            labels = detail.get("labels", {}) if isinstance(detail.get("labels"), dict) else {}
            alignment = resolve_docker_service_key(item["name"], labels)
            current_service_key = alignment["service_key"]
            if service_key and current_service_key != service_key:
                continue
            health_status = "healthy" if item["status"] == "running" else "warning"
            results.append(
                Asset(
                    asset_id=f"asset_container_{item['id']}",
                    asset_type=AssetType.CONTAINER,
                    name=item["name"],
                    service_key=current_service_key,
                    labels={
                        "image": item["image"],
                        "state": item["state"],
                        "compose_project": labels.get("com.docker.compose.project"),
                        "compose_service": labels.get("com.docker.compose.service"),
                    },
                    source_refs={"docker_id": item["id"], "alignment": alignment},
                    health_status=health_status,
                    unmapped=bool(alignment["unmapped"]),
                    updated_at=utc_now(),
                )
            )
        return results
