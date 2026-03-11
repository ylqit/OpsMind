"""
资源分析引擎。

统一主机、容器和 Prometheus 指标，输出资源热点摘要。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine.capabilities.host_monitor import HostMonitor
from engine.integrations.data_sources.docker_adapter import DockerAdapter
from engine.integrations.data_sources.prometheus_adapter import PrometheusAdapter


class ResourceAnalyticsEngine:
    """资源分析入口。"""

    DEFAULT_PROMQL = {
        "cpu_usage": "avg(rate(container_cpu_usage_seconds_total[5m])) by (pod)",
        "memory_usage": "avg(container_memory_working_set_bytes) by (pod)",
        "restarts": "sum(kube_pod_container_status_restarts_total) by (pod)",
    }

    def __init__(self, docker_host: str, prometheus_url: Optional[str], prometheus_api_key: Optional[str]):
        self.host_monitor = HostMonitor()
        self.docker_adapter = DockerAdapter(host=docker_host)
        self.prometheus_url = prometheus_url
        self.prometheus_api_key = prometheus_api_key

    async def summarize(self, service_key: Optional[str] = None) -> Dict[str, Any]:
        host_result = await self.host_monitor.dispatch(metrics=["cpu", "memory", "disk", "network"])
        docker_summary = await self._summarize_docker(service_key=service_key)
        prometheus_summary = await self._summarize_prometheus()
        return {
            "host": host_result.data.get("metrics", {}) if host_result.success else {},
            "alerts": host_result.data.get("alerts", []) if host_result.success else [],
            "containers": docker_summary,
            "prometheus": prometheus_summary,
            "hotspots": self._build_hotspots(
                host_result.data.get("metrics", {}) if host_result.success else {},
                docker_summary,
                prometheus_summary,
            ),
        }

    async def _summarize_docker(self, service_key: Optional[str]) -> Dict[str, Any]:
        if not await self.docker_adapter.initialize():
            return {"available": False, "items": []}
        containers = await self.docker_adapter.list_containers(all=True)
        items = []
        for container in containers:
            info = await self.docker_adapter.get_container(container["name"])
            labels = (info or {}).get("labels", {}) if isinstance(info, dict) else {}
            state = (info or {}).get("state", {}) if isinstance(info, dict) else {}
            service_name = labels.get("com.docker.compose.service") or container["name"]
            current_service_key = f"docker/{service_name}"
            if service_key and current_service_key != service_key:
                continue
            items.append(
                {
                    "asset_id": f"container::{container['id']}",
                    "name": container["name"],
                    "service_key": current_service_key,
                    "status": container["status"],
                    "state": container["state"],
                    "restarts": state.get("RestartCount", 0),
                    "oom_killed": state.get("OOMKilled", False),
                }
            )
        return {"available": True, "items": items}

    async def _summarize_prometheus(self) -> Dict[str, Any]:
        if not self.prometheus_url:
            return {"available": False, "metrics": {}}
        adapter = PrometheusAdapter(base_url=self.prometheus_url, api_key=self.prometheus_api_key)
        if not await adapter.initialize():
            return {"available": False, "metrics": {}}
        metrics: Dict[str, Any] = {}
        for name, query in self.DEFAULT_PROMQL.items():
            try:
                result = await adapter.query_instant(query)
                metrics[name] = result.get("data", {}).get("result", [])
            except Exception:
                metrics[name] = []
        await adapter.close()
        return {"available": True, "metrics": metrics}

    def _build_hotspots(self, host_metrics: Dict[str, Any], docker_summary: Dict[str, Any], prometheus_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
        hotspots: List[Dict[str, Any]] = []
        cpu_usage = float(host_metrics.get("cpu", {}).get("usage_percent", 0))
        if cpu_usage:
            hotspots.append({"name": "host-cpu", "type": "host", "score": cpu_usage, "reason": f"主机 CPU 使用率 {cpu_usage:.1f}%"})
        memory_usage = float(host_metrics.get("memory", {}).get("usage_percent", 0))
        if memory_usage:
            hotspots.append({"name": "host-memory", "type": "host", "score": memory_usage, "reason": f"主机内存使用率 {memory_usage:.1f}%"})
        for item in docker_summary.get("items", [])[:10]:
            if item.get("oom_killed"):
                hotspots.append({"name": item["name"], "type": "container", "score": 95, "reason": "容器发生 OOMKilled"})
            if item.get("restarts", 0):
                hotspots.append({"name": item["name"], "type": "container", "score": min(100, item["restarts"] * 10), "reason": f"容器重启次数 {item['restarts']}"})
        for name, result in prometheus_summary.get("metrics", {}).items():
            if result:
                hotspots.append({"name": f"promql::{name}", "type": "prometheus", "score": 80, "reason": f"Prometheus 指标 {name} 返回 {len(result)} 条结果"})
        return hotspots[:10]
