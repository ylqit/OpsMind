"""
总览页摘要构建器。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from engine.runtime.models import DashboardOverview, OverviewCard, ServiceHotspot, TimeSeriesPoint


class SummaryBuilder:
    """聚合多源结果，组装总览页结构。"""

    def build_overview(self, traffic_summary: Dict[str, Any], resource_summary: Dict[str, Any], incidents: List[Any], data_sources: Dict[str, Any]) -> DashboardOverview:
        merged_data_sources = self._merge_data_sources(data_sources, traffic_summary, resource_summary)
        data_health = self._build_data_health(merged_data_sources)
        cards = [
            OverviewCard(key="requests", label="请求量", value=int(traffic_summary.get("total_requests", 0)), status="info"),
            OverviewCard(
                key="error_rate",
                label="错误率",
                value=float(traffic_summary.get("error_rate", 0.0)),
                unit="%",
                status="critical" if float(traffic_summary.get("error_rate", 0.0)) >= 5 else "normal",
            ),
            OverviewCard(
                key="host_cpu",
                label="主机 CPU",
                value=float(resource_summary.get("host", {}).get("cpu", {}).get("usage_percent", 0.0)),
                unit="%",
                status="warning" if float(resource_summary.get("host", {}).get("cpu", {}).get("usage_percent", 0.0)) >= 70 else "normal",
            ),
            OverviewCard(key="active_incidents", label="活跃异常", value=len(incidents), status="warning" if incidents else "normal"),
        ]

        hot_services = [
            ServiceHotspot(
                service_key=item.get("name", "unknown"),
                score=float(item.get("score", 0)),
                reason=item.get("reason", ""),
                metric_value=float(item.get("score", 0)),
            )
            for item in resource_summary.get("hotspots", [])[:5]
        ]

        traffic_trend = [
            TimeSeriesPoint(timestamp=item["timestamp"], value=float(item["requests"]))
            for item in traffic_summary.get("trend", [])[-30:]
        ]

        return DashboardOverview(
            cards=cards,
            traffic_trend=traffic_trend,
            recent_incidents=incidents[:5],
            hot_services=hot_services,
            data_health=data_health,
            data_sources=merged_data_sources,
        )

    def _merge_data_sources(
        self,
        data_sources: Dict[str, Any],
        traffic_summary: Dict[str, Any],
        resource_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = deepcopy(data_sources)
        resource_sources = resource_summary.get("source_health", {}) if isinstance(resource_summary.get("source_health"), dict) else {}

        host_source = merged.setdefault("host", {"enabled": True, "configured": True})
        host_enabled = host_source.get("enabled", True)
        host_source.update(resource_sources.get("host", {}))
        host_source["enabled"] = host_enabled

        docker_source = merged.setdefault("docker", {"enabled": True, "configured": False})
        docker_enabled = docker_source.get("enabled", True)
        docker_source.update(resource_sources.get("docker", {}))
        docker_source["enabled"] = docker_enabled

        prometheus_source = merged.setdefault("prometheus", {"enabled": True, "configured": False})
        prometheus_enabled = prometheus_source.get("enabled", True)
        prometheus_source.update(resource_sources.get("prometheus", {}))
        prometheus_source["enabled"] = prometheus_enabled

        logs_source = merged.setdefault("logs", {"enabled": True, "configured": False})
        traffic_status = str(traffic_summary.get("data_status") or logs_source.get("status") or "ready")
        logs_source["status"] = "not_configured" if not logs_source.get("configured") else traffic_status
        logs_source["available"] = traffic_status != "unavailable"
        logs_source["message"] = str(traffic_summary.get("data_message") or logs_source.get("message") or "")
        logs_source["details"] = traffic_summary.get("load_stats") or {}

        alerts_source = merged.setdefault("alerts", {"enabled": True, "configured": True})
        alerts_source.setdefault("available", True)
        alerts_source.setdefault("status", "ready")
        alerts_source.setdefault("message", "")
        return merged

    def _build_data_health(self, data_sources: Dict[str, Any]) -> Dict[str, Any]:
        active_items = []
        reasons: List[str] = []

        for source_name, payload in data_sources.items():
            if not isinstance(payload, dict) or not payload.get("enabled"):
                continue
            status = str(payload.get("status") or "ready")
            active_items.append((source_name, status))
            if status in {"ready", "empty"}:
                continue
            message = str(payload.get("message") or "")
            if message:
                reasons.append(f"{source_name}: {message}")

        ready_count = sum(1 for _, status in active_items if status in {"ready", "empty"})
        if not active_items or ready_count == 0:
            return {
                "status": "unavailable",
                "title": "核心数据源不可用",
                "message": "当前未获取到可用的数据源，部分页面结果会为空或仅展示本地占位信息。",
                "degradation_reasons": reasons,
            }
        if reasons:
            return {
                "status": "degraded",
                "title": "数据源部分降级",
                "message": "当前已有数据源可用，但部分来源不可用、待配置或结果为空，分析结果可能不完整。",
                "degradation_reasons": reasons,
            }
        return {
            "status": "ready",
            "title": "数据源运行正常",
            "message": "当前核心数据源运行正常。",
            "degradation_reasons": [],
        }
