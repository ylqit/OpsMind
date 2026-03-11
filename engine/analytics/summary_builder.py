"""
总览页摘要构建器。
"""
from __future__ import annotations

from typing import Any, Dict, List

from engine.runtime.models import DashboardOverview, OverviewCard, ServiceHotspot, TimeSeriesPoint


class SummaryBuilder:
    """聚合多源结果，组装总览页结构。"""

    def build_overview(self, traffic_summary: Dict[str, Any], resource_summary: Dict[str, Any], incidents: List[Any], data_sources: Dict[str, Any]) -> DashboardOverview:
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
            data_sources=data_sources,
        )
