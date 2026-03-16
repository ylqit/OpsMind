"""
资源分析引擎。

统一主机、容器和 Prometheus 指标，输出资源热点摘要。
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from engine.capabilities.host_monitor import HostMonitor
from engine.domain.service_key_resolver import resolve_docker_service_key
from engine.integrations.data_sources.docker_adapter import DockerAdapter
from engine.integrations.data_sources.prometheus_adapter import PrometheusAdapter
from engine.runtime.time_utils import utc_now
from engine.storage.repositories import AssetRepository, SignalRepository


class ResourceAnalyticsEngine:
    """资源分析入口。"""

    HOST_CPU_HOTSPOT_THRESHOLD = 60.0
    HOST_MEMORY_HOTSPOT_THRESHOLD = 70.0
    HOST_DISK_HOTSPOT_THRESHOLD = 75.0
    RESTART_CRITICAL_THRESHOLD = 5
    RESTART_HIGH_THRESHOLD = 3

    DEFAULT_PROMQL = {
        "cpu_usage": "avg(rate(container_cpu_usage_seconds_total[5m])) by (namespace,pod,service)",
        "memory_usage": "avg(container_memory_working_set_bytes) by (namespace,pod,service)",
        "restarts": "sum(kube_pod_container_status_restarts_total) by (namespace,pod,service)",
    }

    def __init__(
        self,
        docker_host: str,
        prometheus_url: Optional[str],
        prometheus_api_key: Optional[str],
        asset_repository: Optional[AssetRepository] = None,
        signal_repository: Optional[SignalRepository] = None,
    ):
        self.host_monitor = HostMonitor()
        self.docker_adapter = DockerAdapter(host=docker_host)
        self.prometheus_url = prometheus_url
        self.prometheus_api_key = prometheus_api_key
        self.asset_repository = asset_repository
        self.signal_repository = signal_repository

    async def summarize(self, time_range: str = "1h", service_key: Optional[str] = None) -> Dict[str, Any]:
        host_result = await self.host_monitor.dispatch(metrics=["cpu", "memory", "disk", "network"])
        docker_summary = await self._summarize_docker(service_key=service_key)
        prometheus_summary = await self._summarize_prometheus()
        seed_snapshot = None
        # 当容器与 Prometheus 都不可用时，自动启用演示样本兜底，避免页面全空白。
        if self._should_use_seed_fallback(docker_summary, prometheus_summary):
            seed_snapshot = self._build_seed_resource_snapshot(time_range=time_range, service_key=service_key)

        host_metrics = host_result.data.get("metrics", {}) if host_result.success else {}
        if seed_snapshot:
            host_metrics = self._merge_host_metrics(host_metrics, seed_snapshot.get("host_metrics", {}))
            docker_summary = self._merge_docker_summary(docker_summary, seed_snapshot.get("containers", []))

        hotspot_layers = self._build_hotspot_layers(host_metrics, docker_summary, prometheus_summary)
        if seed_snapshot:
            hotspot_layers = self._merge_hotspot_layers(hotspot_layers, seed_snapshot.get("hotspot_layers", {}))

        flat_hotspots = self._flatten_hotspot_layers(hotspot_layers)
        hotspot_summary = self._build_hotspot_summary(flat_hotspots, hotspot_layers)
        risk_report = self._build_risk_report(docker_summary, hotspot_layers)
        risk_items = risk_report["items"]
        risk_summary = risk_report["summary"]
        if seed_snapshot:
            risk_items = self._merge_risk_items(risk_items, seed_snapshot.get("risk_items", []))
            risk_summary = self._build_risk_summary(risk_items)

        source_health = self._build_source_health(host_result, docker_summary, prometheus_summary)
        data_health = self._build_resource_data_health(source_health)
        if seed_snapshot:
            source_health["seed"] = {
                "enabled": True,
                "configured": True,
                "available": True,
                "status": "ready",
                "message": "已启用内置演示数据补齐资源分析结果",
                "details": {
                    "container_count": len(seed_snapshot.get("containers", [])),
                    "signal_count": int(seed_snapshot.get("signal_count", 0)),
                },
            }
            data_health = self._merge_data_health_with_seed(data_health)

        return {
            "host": host_metrics,
            "alerts": host_result.data.get("alerts", []) if host_result.success else [],
            "containers": docker_summary,
            "prometheus": prometheus_summary,
            "hotspots": flat_hotspots,
            "hotspot_layers": hotspot_layers,
            "hotspot_summary": hotspot_summary,
            "risk_summary": risk_summary,
            "risk_items": risk_items,
            "source_health": source_health,
            "data_status": data_health["status"],
            "data_message": data_health["message"],
            "degradation_reasons": data_health["degradation_reasons"],
        }

    async def _summarize_docker(self, service_key: Optional[str]) -> Dict[str, Any]:
        if not self.docker_adapter.host:
            return {"available": False, "configured": False, "items": [], "message": "未配置 Docker 主机地址"}
        if not await self.docker_adapter.initialize():
            return {"available": False, "configured": True, "items": [], "message": "Docker 连接不可用"}
        containers = await self.docker_adapter.list_containers(all=True)
        items = []
        for container in containers:
            info = await self.docker_adapter.get_container(container["name"])
            labels = (info or {}).get("labels", {}) if isinstance(info, dict) else {}
            state = (info or {}).get("state", {}) if isinstance(info, dict) else {}
            alignment = resolve_docker_service_key(container["name"], labels)
            current_service_key = alignment["service_key"]
            if service_key and current_service_key != service_key:
                continue
            items.append(
                {
                    "asset_id": f"container::{container['id']}",
                    "name": container["name"],
                    "service_key": current_service_key,
                    "alignment": alignment,
                    "unmapped": alignment["unmapped"],
                    "status": container["status"],
                    "state": container["state"],
                    "restarts": state.get("RestartCount", 0),
                    "oom_killed": state.get("OOMKilled", False),
                }
            )
        return {
            "available": True,
            "configured": True,
            "items": items,
            "message": "未发现容器" if not items else "",
        }

    async def _summarize_prometheus(self) -> Dict[str, Any]:
        if not self.prometheus_url:
            return {"available": False, "configured": False, "metrics": {}, "message": "未配置 Prometheus 地址"}
        adapter = PrometheusAdapter(base_url=self.prometheus_url, api_key=self.prometheus_api_key)
        if not await adapter.initialize():
            return {"available": False, "configured": True, "metrics": {}, "message": "Prometheus 连接不可用"}
        metrics: Dict[str, Any] = {}
        for name, query in self.DEFAULT_PROMQL.items():
            try:
                result = await adapter.query_instant(query)
                metrics[name] = result.get("data", {}).get("result", [])
            except Exception:
                metrics[name] = []
        await adapter.close()
        total_series = sum(len(value) for value in metrics.values() if isinstance(value, list))
        return {
            "available": True,
            "configured": True,
            "metrics": metrics,
            "message": "当前查询未返回指标序列" if total_series == 0 else "",
        }

    def _build_source_health(self, host_result: Any, docker_summary: Dict[str, Any], prometheus_summary: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        host_message = ""
        if not host_result.success:
            host_message = str(getattr(host_result, "error_message", "") or "主机监控采集失败")
        elif not host_result.data.get("metrics"):
            host_message = "当前未返回主机指标"

        docker_configured = bool(docker_summary.get("configured", False))
        docker_available = bool(docker_summary.get("available", False))
        docker_items = docker_summary.get("items", []) if isinstance(docker_summary.get("items"), list) else []

        prometheus_configured = bool(prometheus_summary.get("configured", False))
        prometheus_available = bool(prometheus_summary.get("available", False))
        prometheus_metrics = prometheus_summary.get("metrics", {}) if isinstance(prometheus_summary.get("metrics"), dict) else {}
        prometheus_series = sum(len(value) for value in prometheus_metrics.values() if isinstance(value, list))

        return {
            "host": {
                "enabled": True,
                "configured": True,
                "available": bool(host_result.success),
                "status": "ready" if host_result.success else "unavailable",
                "message": host_message,
                "details": {
                    "metric_groups": len(host_result.data.get("metrics", {}) if host_result.success else {}),
                    "alert_count": len(host_result.data.get("alerts", []) if host_result.success else []),
                },
            },
            "docker": {
                "enabled": True,
                "configured": docker_configured,
                "available": docker_available,
                "status": "not_configured" if not docker_configured else ("ready" if docker_available else "unavailable"),
                "message": str(docker_summary.get("message") or ""),
                "details": {
                    "container_count": len(docker_items),
                },
            },
            "prometheus": {
                "enabled": True,
                "configured": prometheus_configured,
                "available": prometheus_available,
                "status": "not_configured" if not prometheus_configured else ("ready" if prometheus_available else "unavailable"),
                "message": str(prometheus_summary.get("message") or ""),
                "details": {
                    "metric_series": prometheus_series,
                    "metric_groups": len(prometheus_metrics),
                },
            },
        }

    def _build_resource_data_health(self, source_health: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        active_sources = [item for item in source_health.values() if item.get("enabled")]
        ready_sources = [item for item in active_sources if item.get("status") == "ready"]
        problematic = []
        reasons: List[str] = []

        for name, item in source_health.items():
            status = str(item.get("status") or "ready")
            if status == "ready":
                continue
            problematic.append(name)
            message = str(item.get("message") or "")
            if message:
                reasons.append(f"{name}: {message}")

        if not active_sources or not ready_sources:
            return {
                "status": "unavailable",
                "message": "当前资源数据源不可用，暂时无法形成完整的资源分析结果。",
                "degradation_reasons": reasons,
            }

        if problematic:
            return {
                "status": "degraded",
                "message": "部分资源数据源不可用或待配置，当前结果可能不完整。",
                "degradation_reasons": reasons,
            }

        return {
            "status": "ready",
            "message": "资源数据源运行正常。",
            "degradation_reasons": [],
        }

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
                    severity=self._score_to_severity(cpu_usage),
                    category="cpu",
                    reason=f"主机 CPU 使用率 {cpu_usage:.1f}%",
                    explanation="主机 CPU 已进入高位，说明容器与系统进程正在争抢核数，容易放大接口延迟和调度抖动。",
                    recommended_action="优先检查热点进程与高流量服务，再决定限流、扩容或调整副本。",
                    metric="cpu_usage",
                    value=round(cpu_usage, 2),
                    unit="%",
                    source="host",
                    labels=["host", "cpu"],
                )
            )

        memory_usage = float(host_metrics.get("memory", {}).get("usage_percent", 0))
        if memory_usage >= self.HOST_MEMORY_HOTSPOT_THRESHOLD:
            layers["host"].append(
                self._hotspot(
                    name="host-memory",
                    layer="host",
                    score=min(100.0, memory_usage),
                    severity=self._score_to_severity(memory_usage),
                    category="memory",
                    reason=f"主机内存使用率 {memory_usage:.1f}%",
                    explanation="主机内存压力偏高，可能已经接近缓存回收、Swap 抖动或容器内存争抢区间。",
                    recommended_action="检查大内存进程、缓存占用和容器 requests/limits，必要时拆分负载或扩容内存。",
                    metric="memory_usage",
                    value=round(memory_usage, 2),
                    unit="%",
                    source="host",
                    labels=["host", "memory"],
                )
            )

        for partition in host_metrics.get("disk", {}).get("partitions", [])[:10]:
            usage_percent = float(partition.get("usage_percent", 0) or 0)
            if usage_percent < self.HOST_DISK_HOTSPOT_THRESHOLD:
                continue
            mountpoint = str(partition.get("mountpoint") or partition.get("device") or "/")
            layers["host"].append(
                self._hotspot(
                    name=f"disk::{mountpoint}",
                    layer="host",
                    score=min(100.0, usage_percent),
                    severity=self._score_to_severity(usage_percent),
                    category="disk",
                    reason=f"磁盘 {mountpoint} 使用率 {usage_percent:.1f}%",
                    explanation="磁盘使用率持续升高会挤压日志写入和容器临时文件空间，进一步引发重启或探针失败。",
                    recommended_action="优先清理日志、临时文件和历史制品，必要时扩容卷或调整落盘策略。",
                    metric="disk_usage",
                    value=round(usage_percent, 2),
                    unit="%",
                    source="host",
                    labels=["host", "disk"],
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
                        severity="critical",
                        category="oom",
                        reason="容器发生 OOMKilled",
                        explanation="容器已经触发 OOMKilled，说明当前内存上限不足或进程存在瞬时峰值/泄漏问题。",
                        recommended_action="先核对容器内存峰值与 limits，再评估是否需要调高内存、拆分实例或排查泄漏。",
                        metric="oom_killed",
                        value=1,
                        unit="次",
                        source="docker",
                        labels=["container", "oom"],
                        service_key=str(item.get("service_key") or ""),
                    )
                )
            if restarts > 0:
                restart_score = min(100, 40 + restarts * 10)
                layers["container"].append(
                    self._hotspot(
                        name=str(item.get("name") or "container"),
                        layer="container",
                        score=restart_score,
                        severity=self._restart_level(restarts),
                        category="restart",
                        reason=f"容器重启次数 {restarts}",
                        explanation="容器持续重启通常意味着启动探针、依赖连接、资源上限或进程崩溃仍未稳定。",
                        recommended_action="先查看重启前日志和探针结果，再确认是否由 OOM、配置错误或外部依赖失败触发。",
                        metric="restarts",
                        value=restarts,
                        unit="次",
                        source="docker",
                        labels=["container", "restart"],
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
                        severity="high",
                        category="status",
                        reason=f"容器状态异常：{status}",
                        explanation="容器当前不在稳定运行态，服务健康检查和入口流量可能已经受到影响。",
                        recommended_action="检查容器最近事件、启动命令和依赖连接，再决定是否需要重建或回滚。",
                        metric="status",
                        value=status,
                        source="docker",
                        labels=["container", "status"],
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
                            severity=self._score_to_severity(cpu_percent),
                            category="cpu",
                            reason=f"Pod CPU 使用率估算 {cpu_percent:.1f}%",
                            explanation="Pod CPU 已进入高位，常见原因是流量突增、热点接口集中或工作线程被打满。",
                            recommended_action="结合请求趋势和热点路径确认是否需要扩容、限流或排查慢查询/热点逻辑。",
                            metric="cpu_usage",
                            value=round(cpu_percent, 2),
                            unit="%",
                            namespace=namespace,
                            source="prometheus",
                            labels=["pod", "cpu"],
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
                            severity=self._score_to_severity(score),
                            category="memory",
                            reason=f"Pod 内存使用约 {memory_mb:.1f} MiB",
                            explanation="Pod 内存占用持续偏高，可能来自缓存堆积、对象泄漏或突发请求导致的堆内增长。",
                            recommended_action="先检查进程内存曲线和对象堆积，再调整 requests/limits 或拆分负载。",
                            metric="memory_usage",
                            value=round(memory_mb, 2),
                            unit="MiB",
                            namespace=namespace,
                            source="prometheus",
                            labels=["pod", "memory"],
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
                    restart_score = min(100, 40 + restarts * 10)
                    hotspots.append(
                        self._hotspot(
                            name=pod_name,
                            layer="pod",
                            score=restart_score,
                            severity=self._restart_level(restarts),
                            category="restart",
                            reason=f"Pod 重启次数 {restarts}",
                            explanation="Pod 重启会打断请求处理链路，通常意味着探针失败、资源上限或依赖异常尚未恢复。",
                            recommended_action="结合事件、探针和容器日志确认根因，再决定回滚、扩容或修正配置。",
                            metric="restarts",
                            value=restarts,
                            unit="次",
                            namespace=namespace,
                            source="prometheus",
                            labels=["pod", "restart"],
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
                    severity=self._score_to_severity(aggregate["score"]),
                    category=self._metric_to_category(metric_name),
                    reason=reason,
                    explanation=self._build_service_hotspot_explanation(metric_name, service_name, aggregate["value"]),
                    recommended_action=self._build_service_hotspot_action(metric_name),
                    metric=metric_name,
                    value=round(aggregate["value"], 2),
                    unit=unit,
                    source="prometheus",
                    labels=["service", self._metric_to_category(metric_name)],
                    service_key=service_name,
                )
            )

        if not hotspots and entries:
            hotspots.append(
                self._hotspot(
                    name=f"promql::{metric_name}",
                    layer="other",
                    score=60,
                    severity="medium",
                    category=self._metric_to_category(metric_name),
                    reason=f"Prometheus 指标 {metric_name} 返回 {len(entries)} 条结果",
                    explanation="Prometheus 查询已返回结果，但当前热点对象未达到单点阈值，说明需要结合更多服务上下文再做判断。",
                    recommended_action="优先下钻到具体服务或 Pod，再确认是否存在局部资源热点。",
                    metric=metric_name,
                    value=len(entries),
                    unit="条",
                    source="prometheus",
                    labels=["prometheus", metric_name],
                )
            )

        return hotspots

    def _hotspot(
        self,
        name: str,
        layer: str,
        score: float,
        severity: str,
        category: str,
        reason: str,
        explanation: str,
        recommended_action: str,
        metric: str,
        value: Any,
        unit: str = "",
        source: str = "",
        labels: Optional[List[str]] = None,
        service_key: str = "",
        namespace: str = "",
    ) -> Dict[str, Any]:
        return {
            "name": name,
            "type": layer,
            "layer": layer,
            "score": round(float(score), 2),
            "severity": severity,
            "category": category,
            "reason": reason,
            "explanation": explanation,
            "recommended_action": recommended_action,
            "metric": metric,
            "value": value,
            "unit": unit,
            "source": source,
            "labels": labels or [],
            "service_key": service_key,
            "namespace": namespace,
        }

    def _build_hotspot_summary(
        self,
        hotspots: List[Dict[str, Any]],
        hotspot_layers: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        severity_counter: Counter[str] = Counter()
        category_counter: Counter[str] = Counter()
        service_stats: Dict[str, Dict[str, float]] = {}

        for item in hotspots:
            severity_counter[str(item.get("severity") or "medium")] += 1
            category_counter[str(item.get("category") or "other")] += 1
            service_key = str(item.get("service_key") or "").strip()
            if not service_key:
                continue
            current = service_stats.setdefault(service_key, {"count": 0, "top_score": 0.0})
            current["count"] += 1
            current["top_score"] = max(current["top_score"], float(item.get("score") or 0.0))

        top_services = [
            {
                "service_key": service_key,
                "count": int(values["count"]),
                "top_score": round(float(values["top_score"]), 2),
            }
            for service_key, values in service_stats.items()
        ]
        top_services.sort(key=lambda item: (-item["count"], -item["top_score"], item["service_key"]))

        return {
            "total": len(hotspots),
            "layers": {layer: len(items) for layer, items in hotspot_layers.items()},
            "severities": {
                "critical": severity_counter.get("critical", 0),
                "high": severity_counter.get("high", 0),
                "medium": severity_counter.get("medium", 0),
            },
            "categories": dict(category_counter),
            "top_services": top_services[:5],
        }

    def _should_use_seed_fallback(self, docker_summary: Dict[str, Any], prometheus_summary: Dict[str, Any]) -> bool:
        docker_available = bool(docker_summary.get("available"))
        prometheus_available = bool(prometheus_summary.get("available"))
        return not docker_available and not prometheus_available

    def _build_seed_resource_snapshot(self, time_range: str, service_key: Optional[str]) -> Optional[Dict[str, Any]]:
        if not self.asset_repository or not self.signal_repository:
            return None

        since = self._resolve_since_time(time_range)
        assets = self.asset_repository.list(service_key=service_key)
        signals = self.signal_repository.list(service_key=service_key, since=since, limit=300)
        if not assets and not signals:
            return None

        asset_map = {asset.asset_id: asset for asset in assets}
        container_assets = [
            asset for asset in assets
            if getattr(asset.asset_type, "value", str(asset.asset_type)) == "container"
        ]

        restarts_by_asset: Dict[str, int] = {}
        oom_by_asset: Dict[str, bool] = {}
        layers: Dict[str, List[Dict[str, Any]]] = {
            "host": [],
            "container": [],
            "pod": [],
            "service": [],
            "other": [],
        }
        risk_items: List[Dict[str, Any]] = []
        host_metrics: Dict[str, Any] = {}

        # 演示样本信号同样走热点与风险结构，保证前端展示口径与真实数据一致。
        for signal in signals:
            payload = signal.payload if isinstance(signal.payload, dict) else {}
            metric_name = str(payload.get("metric") or "")
            value = self._extract_metric_value(payload.get("value"))
            signal_service_key = str(signal.service_key or "")
            asset = asset_map.get(signal.asset_id or "")
            target_name = asset.name if asset else (signal_service_key or "seed-target")
            target_service_key = signal_service_key or (asset.service_key if asset else "")
            severity = str(signal.severity or "medium")

            if metric_name == "cpu_usage":
                score = min(100.0, max(0.0, value))
                layers["container"].append(
                    self._hotspot(
                        name=target_name,
                        layer="container",
                        score=score,
                        severity=self._score_to_severity(score),
                        category="cpu",
                        reason=f"样本指标显示 CPU 使用率约 {value:.1f}%",
                        explanation="当前结果来自内置演示样本，表示该服务在高峰窗口存在明显 CPU 热点。",
                        recommended_action="建议结合真实监控确认是否需要扩容副本或优化热点路径。",
                        metric="cpu_usage",
                        value=round(value, 2),
                        unit="%",
                        source="seed",
                        labels=["seed", "cpu"],
                        service_key=target_service_key,
                    )
                )
                if "cpu" not in host_metrics:
                    host_metrics["cpu"] = {"usage_percent": round(value, 2)}

            if metric_name == "memory_usage":
                memory_score = min(100.0, value)
                layers["container"].append(
                    self._hotspot(
                        name=target_name,
                        layer="container",
                        score=memory_score,
                        severity=self._score_to_severity(memory_score),
                        category="memory",
                        reason=f"样本指标显示内存使用率约 {value:.1f}%",
                        explanation="该热点来自演示样本，用于在未接入真实监控时提供资源风险定位入口。",
                        recommended_action="建议补充 requests/limits 或结合容器日志排查内存抖动原因。",
                        metric="memory_usage",
                        value=round(value, 2),
                        unit="%",
                        source="seed",
                        labels=["seed", "memory"],
                        service_key=target_service_key,
                    )
                )
                if "memory" not in host_metrics:
                    host_metrics["memory"] = {"usage_percent": round(value, 2)}

            if metric_name in {"restarts", "restart_count"}:
                restart_count = int(round(value))
                if signal.asset_id:
                    restarts_by_asset[signal.asset_id] = max(restarts_by_asset.get(signal.asset_id, 0), restart_count)
                layers["container"].append(
                    self._hotspot(
                        name=target_name,
                        layer="container",
                        score=min(100.0, 40 + restart_count * 10),
                        severity=self._restart_level(restart_count),
                        category="restart",
                        reason=f"样本指标显示重启次数 {restart_count}",
                        explanation="重启信号来自内置样本，说明该服务存在持续不稳定风险。",
                        recommended_action="建议优先核查探针、依赖连接和容器资源上限配置。",
                        metric="restarts",
                        value=restart_count,
                        unit="次",
                        source="seed",
                        labels=["seed", "restart"],
                        service_key=target_service_key,
                    )
                )
                risk_items.append(
                    self._risk_item(
                        risk_type="restart",
                        level=self._restart_level(restart_count),
                        layer="container",
                        target=target_name,
                        service_key=target_service_key,
                        metric="restarts",
                        value=restart_count,
                        unit="次",
                        evidence=f"样本记录显示重启次数 {restart_count}",
                        source="seed",
                    )
                )

            if metric_name in {"oom_killed", "oom"} or bool(payload.get("oom_killed")):
                if signal.asset_id:
                    oom_by_asset[signal.asset_id] = True
                layers["container"].append(
                    self._hotspot(
                        name=target_name,
                        layer="container",
                        score=95,
                        severity="critical",
                        category="oom",
                        reason="样本事件显示容器出现 OOM 风险",
                        explanation="该信号用于演示 OOM 风险识别链路，真实环境应结合容器事件进一步确认。",
                        recommended_action="建议优先检查内存限制和应用进程峰值，再决定是否扩容。",
                        metric="oom_killed",
                        value=1,
                        unit="次",
                        source="seed",
                        labels=["seed", "oom"],
                        service_key=target_service_key,
                    )
                )
                risk_items.append(
                    self._risk_item(
                        risk_type="oom",
                        level="critical",
                        layer="container",
                        target=target_name,
                        service_key=target_service_key,
                        metric="oom_killed",
                        value=1,
                        unit="次",
                        evidence="样本事件记录了 OOM 风险",
                        source="seed",
                    )
                )

            status_code = int(self._extract_metric_value(payload.get("status")))
            if status_code >= 500:
                score = 85 if severity in {"high", "critical"} else 75
                layers["service"].append(
                    self._hotspot(
                        name=target_service_key or target_name,
                        layer="service",
                        score=score,
                        severity="high" if score < 90 else "critical",
                        category="status",
                        reason=f"样本日志显示状态码 {status_code}",
                        explanation="该异常来自演示日志样本，用于展示入口错误定位和证据串联效果。",
                        recommended_action="建议优先检查上游依赖和入口限流策略，确认错误率是否持续抬升。",
                        metric="status",
                        value=status_code,
                        unit="code",
                        source="seed",
                        labels=["seed", "log"],
                        service_key=target_service_key,
                    )
                )

        containers = []
        for asset in container_assets:
            alignment = asset.source_refs.get("alignment", {}) if isinstance(asset.source_refs, dict) else {}
            restarts = restarts_by_asset.get(asset.asset_id, 0)
            oom_killed = bool(oom_by_asset.get(asset.asset_id, False))
            health_status = str(asset.health_status or "unknown")
            runtime_status = "running" if health_status in {"healthy", "warning"} else "unknown"
            containers.append(
                {
                    "asset_id": asset.asset_id,
                    "name": asset.name,
                    "service_key": asset.service_key,
                    "alignment": alignment,
                    "unmapped": bool(asset.unmapped),
                    "status": runtime_status,
                    "state": health_status,
                    "restarts": restarts,
                    "oom_killed": oom_killed,
                }
            )

        if not host_metrics and layers["container"]:
            top_container = max(layers["container"], key=lambda item: float(item.get("score", 0.0)))
            host_metrics = {"cpu": {"usage_percent": round(float(top_container.get("score", 0.0)), 2)}}

        for layer_name, items in layers.items():
            items.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("name", ""))))
            layers[layer_name] = items[:10]

        if not containers and not any(layers.values()) and not risk_items:
            return None

        return {
            "host_metrics": host_metrics,
            "containers": containers,
            "hotspot_layers": layers,
            "risk_items": risk_items[:30],
            "signal_count": len(signals),
        }

    def _resolve_since_time(self, time_range: str) -> datetime:
        normalized = (time_range or "1h").strip().lower()
        now = utc_now()
        if normalized.endswith("m"):
            return now - timedelta(minutes=max(1, int(normalized[:-1] or "60")))
        if normalized.endswith("h"):
            return now - timedelta(hours=max(1, int(normalized[:-1] or "1")))
        if normalized.endswith("d"):
            return now - timedelta(days=max(1, int(normalized[:-1] or "1")))
        return now - timedelta(hours=1)

    def _merge_host_metrics(self, host_metrics: Dict[str, Any], seed_host_metrics: Dict[str, Any]) -> Dict[str, Any]:
        if not seed_host_metrics:
            return host_metrics
        merged = dict(host_metrics)
        for metric_name, metric_payload in seed_host_metrics.items():
            if metric_name not in merged:
                merged[metric_name] = metric_payload
        return merged

    def _merge_docker_summary(self, docker_summary: Dict[str, Any], seed_containers: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not seed_containers:
            return docker_summary
        merged = dict(docker_summary)
        items = list(merged.get("items", [])) if isinstance(merged.get("items"), list) else []
        if not items:
            merged["items"] = seed_containers
            merged["message"] = str(merged.get("message") or "当前容器数据来自演示样本")
        return merged

    def _merge_hotspot_layers(
        self,
        base_layers: Dict[str, List[Dict[str, Any]]],
        seed_layers: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        merged: Dict[str, List[Dict[str, Any]]] = {}
        for layer_name in ("host", "container", "pod", "service", "other"):
            candidates: Dict[str, Dict[str, Any]] = {}
            for item in base_layers.get(layer_name, []) + seed_layers.get(layer_name, []):
                dedup_key = f"{layer_name}:{item.get('name')}:{item.get('metric')}:{item.get('source')}"
                existed = candidates.get(dedup_key)
                if not existed or float(item.get("score", 0.0)) > float(existed.get("score", 0.0)):
                    candidates[dedup_key] = item
            ordered = sorted(
                candidates.values(),
                key=lambda item: (-float(item.get("score", 0.0)), str(item.get("name", ""))),
            )
            merged[layer_name] = ordered[:10]
        return merged

    def _merge_risk_items(self, base_items: List[Dict[str, Any]], seed_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not seed_items:
            return base_items
        dedup: Dict[str, Dict[str, Any]] = {}
        for item in base_items + seed_items:
            risk_id = str(item.get("risk_id") or "")
            if not risk_id:
                continue
            existed = dedup.get(risk_id)
            if not existed:
                dedup[risk_id] = item
                continue
            incoming_level = self._risk_rank(str(item.get("level") or "medium"))
            existed_level = self._risk_rank(str(existed.get("level") or "medium"))
            if incoming_level > existed_level:
                dedup[risk_id] = item
        result = list(dedup.values())
        result.sort(
            key=lambda item: (
                -self._risk_rank(str(item.get("level") or "medium")),
                -self._extract_metric_value(item.get("value")),
                str(item.get("target") or ""),
            )
        )
        return result[:30]

    def _build_risk_summary(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "total": len(items),
            "levels": {"critical": 0, "high": 0, "medium": 0},
            "oom": {"total": 0, "critical": 0, "high": 0, "medium": 0},
            "restart": {"total": 0, "critical": 0, "high": 0, "medium": 0},
        }
        for item in items:
            level = str(item.get("level") or "medium")
            risk_type = str(item.get("risk_type") or "restart")
            if level not in summary["levels"]:
                continue
            summary["levels"][level] += 1
            if risk_type in ("oom", "restart"):
                summary[risk_type]["total"] += 1
                summary[risk_type][level] += 1
        return summary

    def _merge_data_health_with_seed(self, data_health: Dict[str, Any]) -> Dict[str, Any]:
        reasons = list(data_health.get("degradation_reasons", []))
        seed_reason = "seed: 已启用演示数据补齐资源热点"
        if seed_reason not in reasons:
            reasons.append(seed_reason)

        # 有样本兜底时维持 degraded，更符合真实可用性表达。
        return {
            "status": "degraded",
            "message": "Docker/Prometheus 不可用时已自动启用演示数据回退，页面仍可展示完整资源视图。",
            "degradation_reasons": reasons,
        }

    def _score_to_severity(self, score: float) -> str:
        if score >= 90:
            return "critical"
        if score >= 75:
            return "high"
        return "medium"

    def _metric_to_category(self, metric_name: str) -> str:
        mapping = {
            "cpu_usage": "cpu",
            "memory_usage": "memory",
            "restarts": "restart",
            "oom_killed": "oom",
            "disk_usage": "disk",
            "status": "status",
            "network_usage": "network",
        }
        return mapping.get(metric_name, "other")

    def _build_service_hotspot_explanation(self, metric_name: str, service_name: str, value: float) -> str:
        if metric_name == "cpu_usage":
            return f"服务 {service_name} 的 CPU 压力已经抬升到 {value:.1f}% 左右，说明热点请求很可能集中在同一组副本上。"
        if metric_name == "memory_usage":
            return f"服务 {service_name} 的内存占用约 {value:.1f} MiB，若持续上升，后续容易演化为 OOM 或频繁 GC。"
        if metric_name == "restarts":
            return f"服务 {service_name} 已累计重启 {int(value)} 次，说明故障已经不是单个 Pod 的偶发抖动。"
        return f"服务 {service_name} 存在 {metric_name} 资源热点，需要继续结合上下游与日志定位。"

    def _build_service_hotspot_action(self, metric_name: str) -> str:
        if metric_name == "cpu_usage":
            return "优先确认是否需要扩容副本、限流或排查热点接口的 CPU 消耗。"
        if metric_name == "memory_usage":
            return "优先核对缓存、对象堆积与内存 limits，再决定扩容或调优。"
        if metric_name == "restarts":
            return "优先查看事件与容器日志，确认是否由探针、依赖或资源上限导致持续重启。"
        return "优先结合对应指标与日志继续下钻。"

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
