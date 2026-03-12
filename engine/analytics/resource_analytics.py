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

    HOST_CPU_HOTSPOT_THRESHOLD = 60.0
    HOST_MEMORY_HOTSPOT_THRESHOLD = 70.0
    RESTART_CRITICAL_THRESHOLD = 5
    RESTART_HIGH_THRESHOLD = 3

    DEFAULT_PROMQL = {
        "cpu_usage": "avg(rate(container_cpu_usage_seconds_total[5m])) by (namespace,pod,service)",
        "memory_usage": "avg(container_memory_working_set_bytes) by (namespace,pod,service)",
        "restarts": "sum(kube_pod_container_status_restarts_total) by (namespace,pod,service)",
    }

    def __init__(self, docker_host: str, prometheus_url: Optional[str], prometheus_api_key: Optional[str]):
        self.host_monitor = HostMonitor()
        self.docker_adapter = DockerAdapter(host=docker_host)
        self.prometheus_url = prometheus_url
        self.prometheus_api_key = prometheus_api_key

    async def summarize(self, time_range: str = "1h", service_key: Optional[str] = None) -> Dict[str, Any]:
        del time_range
        host_result = await self.host_monitor.dispatch(metrics=["cpu", "memory", "disk", "network"])
        docker_summary = await self._summarize_docker(service_key=service_key)
        prometheus_summary = await self._summarize_prometheus()

        host_metrics = host_result.data.get("metrics", {}) if host_result.success else {}
        hotspot_layers = self._build_hotspot_layers(host_metrics, docker_summary, prometheus_summary)
        flat_hotspots = self._flatten_hotspot_layers(hotspot_layers)
        risk_report = self._build_risk_report(docker_summary, hotspot_layers)

        return {
            "host": host_metrics,
            "alerts": host_result.data.get("alerts", []) if host_result.success else [],
            "containers": docker_summary,
            "prometheus": prometheus_summary,
            "hotspots": flat_hotspots,
            "hotspot_layers": hotspot_layers,
            "risk_summary": risk_report["summary"],
            "risk_items": risk_report["items"],
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

    # 资源热点需要按对象层级拆分，前端才能在不同层做风险定位而不是混在一起看。
    def _build_hotspot_layers(
        self,
        host_metrics: Dict[str, Any],
        docker_summary: Dict[str, Any],
        prometheus_summary: Dict[str, Any],
    ) -> Dict[str, List[Dict[str, Any]]]:
        layers: Dict[str, List[Dict[str, Any]]] = {
            "host": [],
            "container": [],
            "pod": [],
            "service": [],
            "other": [],
        }

        cpu_usage = float(host_metrics.get("cpu", {}).get("usage_percent", 0))
        if cpu_usage >= self.HOST_CPU_HOTSPOT_THRESHOLD:
            layers["host"].append(
                self._hotspot(
                    name="host-cpu",
                    layer="host",
                    score=min(100.0, cpu_usage),
                    reason=f"主机 CPU 使用率 {cpu_usage:.1f}%",
                    metric="cpu_usage",
                    value=round(cpu_usage, 2),
                    unit="%",
                )
            )

        memory_usage = float(host_metrics.get("memory", {}).get("usage_percent", 0))
        if memory_usage >= self.HOST_MEMORY_HOTSPOT_THRESHOLD:
            layers["host"].append(
                self._hotspot(
                    name="host-memory",
                    layer="host",
                    score=min(100.0, memory_usage),
                    reason=f"主机内存使用率 {memory_usage:.1f}%",
                    metric="memory_usage",
                    value=round(memory_usage, 2),
                    unit="%",
                )
            )

        for item in docker_summary.get("items", [])[:30]:
            restarts = int(item.get("restarts", 0) or 0)
            if item.get("oom_killed"):
                layers["container"].append(
                    self._hotspot(
                        name=str(item.get("name") or "container"),
                        layer="container",
                        score=95,
                        reason="容器发生 OOMKilled",
                        metric="oom_killed",
                        value=1,
                        unit="次",
                        service_key=str(item.get("service_key") or ""),
                    )
                )
            if restarts > 0:
                layers["container"].append(
                    self._hotspot(
                        name=str(item.get("name") or "container"),
                        layer="container",
                        score=min(100, 40 + restarts * 10),
                        reason=f"容器重启次数 {restarts}",
                        metric="restarts",
                        value=restarts,
                        unit="次",
                        service_key=str(item.get("service_key") or ""),
                    )
                )
            status = str(item.get("status") or "")
            if status and status != "running":
                layers["container"].append(
                    self._hotspot(
                        name=str(item.get("name") or "container"),
                        layer="container",
                        score=75,
                        reason=f"容器状态异常：{status}",
                        metric="status",
                        value=status,
                        service_key=str(item.get("service_key") or ""),
                    )
                )

        prom_metrics = prometheus_summary.get("metrics", {})
        for metric_name, result in prom_metrics.items():
            parsed = self._extract_prometheus_hotspots(metric_name, result)
            for item in parsed:
                layer = str(item.get("layer") or "other")
                if layer not in layers:
                    layers[layer] = []
                layers[layer].append(item)

        for layer_name, items in layers.items():
            items.sort(key=lambda item: (-float(item.get("score", 0)), str(item.get("name", ""))))
            layers[layer_name] = items[:10]

        return layers

    def _flatten_hotspot_layers(self, layers: Dict[str, List[Dict[str, Any]]], limit: int = 12) -> List[Dict[str, Any]]:
        ordered_layers = ["host", "container", "pod", "service", "other"]
        all_items: List[Dict[str, Any]] = []
        for layer_name in ordered_layers:
            all_items.extend(layers.get(layer_name, []))
        all_items.sort(key=lambda item: (-float(item.get("score", 0)), str(item.get("name", ""))))
        return all_items[:limit]

    def _extract_prometheus_hotspots(self, metric_name: str, result: Any) -> List[Dict[str, Any]]:
        entries = result if isinstance(result, list) else []
        hotspots: List[Dict[str, Any]] = []
        service_aggregate: Dict[str, Dict[str, float]] = {}

        for entry in entries[:200]:
            if not isinstance(entry, dict):
                continue
            labels = entry.get("metric", {}) if isinstance(entry.get("metric"), dict) else {}
            raw_value = entry.get("value")
            value = self._extract_metric_value(raw_value)
            if value <= 0:
                continue

            namespace = str(labels.get("namespace") or "default")
            pod_name = str(labels.get("pod") or "")
            service_label = str(labels.get("service") or labels.get("app") or labels.get("app_kubernetes_io_name") or "")
            service_name = f"{namespace}/{service_label}" if service_label else ""

            if metric_name == "cpu_usage":
                cpu_percent = value * 100
                if pod_name and cpu_percent >= 60:
                    hotspots.append(
                        self._hotspot(
                            name=pod_name,
                            layer="pod",
                            score=min(100, cpu_percent),
                            reason=f"Pod CPU 使用率估算 {cpu_percent:.1f}%",
                            metric="cpu_usage",
                            value=round(cpu_percent, 2),
                            unit="%",
                            namespace=namespace,
                            service_key=service_name,
                        )
                    )
                if service_name and cpu_percent >= 60:
                    current = service_aggregate.get(service_name, {"score": 0.0, "value": 0.0})
                    if cpu_percent > current["score"]:
                        service_aggregate[service_name] = {"score": min(100, cpu_percent), "value": round(cpu_percent, 2)}

            elif metric_name == "memory_usage":
                memory_mb = value / (1024 * 1024)
                if pod_name and memory_mb >= 256:
                    score = min(100, 50 + memory_mb / 64)
                    hotspots.append(
                        self._hotspot(
                            name=pod_name,
                            layer="pod",
                            score=score,
                            reason=f"Pod 内存使用约 {memory_mb:.1f} MiB",
                            metric="memory_usage",
                            value=round(memory_mb, 2),
                            unit="MiB",
                            namespace=namespace,
                            service_key=service_name,
                        )
                    )
                if service_name and memory_mb >= 256:
                    current = service_aggregate.get(service_name, {"score": 0.0, "value": 0.0})
                    score = min(100, 50 + memory_mb / 64)
                    if score > current["score"]:
                        service_aggregate[service_name] = {"score": score, "value": round(memory_mb, 2)}

            elif metric_name == "restarts":
                restarts = int(round(value))
                if pod_name and restarts > 0:
                    hotspots.append(
                        self._hotspot(
                            name=pod_name,
                            layer="pod",
                            score=min(100, 40 + restarts * 10),
                            reason=f"Pod 重启次数 {restarts}",
                            metric="restarts",
                            value=restarts,
                            unit="次",
                            namespace=namespace,
                            service_key=service_name,
                        )
                    )
                if service_name and restarts > 0:
                    current = service_aggregate.get(service_name, {"score": 0.0, "value": 0.0})
                    current["score"] = min(100, current["score"] + 10 + restarts * 5)
                    current["value"] = current["value"] + restarts
                    service_aggregate[service_name] = current

        for service_name, aggregate in service_aggregate.items():
            if metric_name == "memory_usage":
                reason = f"Service 内存热点约 {aggregate['value']:.1f} MiB"
                unit = "MiB"
            elif metric_name == "cpu_usage":
                reason = f"Service CPU 使用率估算 {aggregate['value']:.1f}%"
                unit = "%"
            else:
                reason = f"Service 重启累计 {int(aggregate['value'])} 次"
                unit = "次"
            hotspots.append(
                self._hotspot(
                    name=service_name,
                    layer="service",
                    score=aggregate["score"],
                    reason=reason,
                    metric=metric_name,
                    value=round(aggregate["value"], 2),
                    unit=unit,
                    service_key=service_name,
                )
            )

        if not hotspots and entries:
            hotspots.append(
                self._hotspot(
                    name=f"promql::{metric_name}",
                    layer="other",
                    score=60,
                    reason=f"Prometheus 指标 {metric_name} 返回 {len(entries)} 条结果",
                    metric=metric_name,
                    value=len(entries),
                    unit="条",
                )
            )

        return hotspots

    def _hotspot(
        self,
        name: str,
        layer: str,
        score: float,
        reason: str,
        metric: str,
        value: Any,
        unit: str = "",
        service_key: str = "",
        namespace: str = "",
    ) -> Dict[str, Any]:
        return {
            "name": name,
            "type": layer,
            "layer": layer,
            "score": round(float(score), 2),
            "reason": reason,
            "metric": metric,
            "value": value,
            "unit": unit,
            "service_key": service_key,
            "namespace": namespace,
        }

    def _build_risk_report(
        self,
        docker_summary: Dict[str, Any],
        hotspot_layers: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        # 统一把 OOM 与重启信号映射成风险项，方便前端做固定展示和后续策略扩展。
        candidates: List[Dict[str, Any]] = []

        for item in docker_summary.get("items", [])[:100]:
            target_name = str(item.get("name") or "container")
            service_key = str(item.get("service_key") or "")
            restarts = int(item.get("restarts", 0) or 0)

            if item.get("oom_killed"):
                candidates.append(
                    self._risk_item(
                        risk_type="oom",
                        level="critical",
                        layer="container",
                        target=target_name,
                        service_key=service_key,
                        metric="oom_killed",
                        value=1,
                        unit="次",
                        evidence="容器发生 OOMKilled",
                        source="docker",
                    )
                )

            if restarts > 0:
                candidates.append(
                    self._risk_item(
                        risk_type="restart",
                        level=self._restart_level(restarts),
                        layer="container",
                        target=target_name,
                        service_key=service_key,
                        metric="restarts",
                        value=restarts,
                        unit="次",
                        evidence=f"容器重启次数 {restarts}",
                        source="docker",
                    )
                )

        for layer_name in ("pod", "service"):
            for hotspot in hotspot_layers.get(layer_name, [])[:100]:
                if str(hotspot.get("metric") or "") != "restarts":
                    continue
                restart_count = int(round(self._extract_metric_value(hotspot.get("value"))))
                if restart_count <= 0:
                    continue
                candidates.append(
                    self._risk_item(
                        risk_type="restart",
                        level=self._restart_level(restart_count),
                        layer=layer_name,
                        target=str(hotspot.get("name") or layer_name),
                        service_key=str(hotspot.get("service_key") or ""),
                        metric="restarts",
                        value=restart_count,
                        unit=str(hotspot.get("unit") or "次"),
                        evidence=str(hotspot.get("reason") or f"{layer_name} 重启次数 {restart_count}"),
                        source="prometheus",
                    )
                )

        dedup: Dict[str, Dict[str, Any]] = {}
        for item in candidates:
            dedup_key = str(item.get("risk_id") or "")
            if dedup_key not in dedup:
                dedup[dedup_key] = item
                continue
            current = dedup[dedup_key]
            incoming_rank = self._risk_rank(str(item.get("level") or "medium"))
            current_rank = self._risk_rank(str(current.get("level") or "medium"))
            incoming_value = self._extract_metric_value(item.get("value"))
            current_value = self._extract_metric_value(current.get("value"))
            if incoming_rank > current_rank or (incoming_rank == current_rank and incoming_value > current_value):
                dedup[dedup_key] = item

        items = list(dedup.values())
        items.sort(
            key=lambda item: (
                -self._risk_rank(str(item.get("level") or "medium")),
                -self._extract_metric_value(item.get("value")),
                str(item.get("target") or ""),
            )
        )

        summary: Dict[str, Any] = {
            "total": len(items),
            "levels": {"critical": 0, "high": 0, "medium": 0},
            "oom": {"total": 0, "critical": 0, "high": 0, "medium": 0},
            "restart": {"total": 0, "critical": 0, "high": 0, "medium": 0},
        }

        for item in items:
            risk_type = str(item.get("risk_type") or "restart")
            level = str(item.get("level") or "medium")
            if level not in summary["levels"]:
                continue
            summary["levels"][level] += 1
            if risk_type in ("oom", "restart"):
                summary[risk_type]["total"] += 1
                summary[risk_type][level] += 1

        return {
            "summary": summary,
            "items": items[:30],
        }

    def _risk_item(
        self,
        risk_type: str,
        level: str,
        layer: str,
        target: str,
        service_key: str,
        metric: str,
        value: Any,
        unit: str,
        evidence: str,
        source: str,
    ) -> Dict[str, Any]:
        risk_id = f"{risk_type}:{layer}:{target}:{service_key}:{metric}"
        return {
            "risk_id": risk_id,
            "risk_type": risk_type,
            "level": level,
            "layer": layer,
            "target": target,
            "service_key": service_key,
            "metric": metric,
            "value": value,
            "unit": unit,
            "evidence": evidence,
            "source": source,
        }

    def _restart_level(self, restart_count: int) -> str:
        if restart_count >= self.RESTART_CRITICAL_THRESHOLD:
            return "critical"
        if restart_count >= self.RESTART_HIGH_THRESHOLD:
            return "high"
        return "medium"

    def _risk_rank(self, level: str) -> int:
        mapping = {
            "critical": 3,
            "high": 2,
            "medium": 1,
        }
        return mapping.get(level, 0)

    def _extract_metric_value(self, raw_value: Any) -> float:
        if isinstance(raw_value, list) and len(raw_value) >= 2:
            raw_value = raw_value[1]
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return 0.0
