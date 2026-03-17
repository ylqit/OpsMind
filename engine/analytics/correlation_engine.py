"""
关联分析引擎。

使用规则与证据链解释访问异常和资源异常之间的关系。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from engine.domain.incident_evidence import normalize_incident_evidence, sort_incident_evidence
from engine.runtime.time_utils import utc_now


class CorrelationEngine:
    """访问异常与资源异常关联解释。"""

    def analyze(self, service_key: str, traffic_summary: Dict[str, Any], resource_summary: Dict[str, Any], related_asset_ids: List[str]) -> Dict[str, Any]:
        total_requests = int(traffic_summary.get("total_requests", 0))
        error_rate = float(traffic_summary.get("error_rate", 0.0))
        avg_latency = float(traffic_summary.get("avg_latency", 0.0))
        host_cpu = float(resource_summary.get("host", {}).get("cpu", {}).get("usage_percent", 0.0))
        host_memory = float(resource_summary.get("host", {}).get("memory", {}).get("usage_percent", 0.0))
        hotspots = resource_summary.get("hotspots", [])
        traffic_baseline = traffic_summary.get("baseline_summary") if isinstance(traffic_summary.get("baseline_summary"), dict) else {}
        resource_baseline = resource_summary.get("baseline_summary") if isinstance(resource_summary.get("baseline_summary"), dict) else {}
        traffic_request_growth = self._find_baseline_highlight(traffic_baseline, "request_volume")
        traffic_error_growth = self._find_baseline_highlight(traffic_baseline, "error_rate")
        resource_cpu_shift = self._find_baseline_highlight(resource_baseline, "host_cpu")
        resource_memory_shift = self._find_baseline_highlight(resource_baseline, "host_memory")
        resource_restart_shift = self._find_baseline_highlight(resource_baseline, "restarts")
        resource_oom_shift = self._find_baseline_highlight(resource_baseline, "oom_killed")
        resource_hotspot_score = max((float(item.get("score") or 0) for item in hotspots if isinstance(item, dict)), default=0.0)
        traffic_shift_without_resource_pressure = (
            self._is_upward_highlight(traffic_request_growth)
            and host_cpu < 70
            and host_memory < 80
            and not self._is_upward_highlight(resource_cpu_shift)
            and not self._is_upward_highlight(resource_memory_shift)
        )
        error_without_resource_pressure = (
            error_rate >= 5
            and host_cpu < 70
            and host_memory < 80
            and not self._is_upward_highlight(resource_cpu_shift)
            and not self._is_upward_highlight(resource_memory_shift)
        )
        latency_without_resource_pressure = (
            avg_latency >= 1.0
            and host_cpu < 70
            and host_memory < 80
            and resource_hotspot_score < 75
        )
        resource_pressure_without_traffic_growth = (
            (host_cpu >= 70 or host_memory >= 80 or self._is_upward_highlight(resource_cpu_shift) or self._is_upward_highlight(resource_memory_shift) or resource_hotspot_score >= 80)
            and not self._is_upward_highlight(traffic_request_growth)
            and error_rate < 5
        )

        severity = "info"
        summary = "未发现明显异常。"
        confidence = 0.35
        reasoning_tags: List[str] = []
        reasoning_details: List[str] = []
        recommended_actions: List[str] = []
        evidence_refs: List[Dict[str, Any]] = []

        if any(item.get("oom_killed") for item in resource_summary.get("containers", {}).get("items", [])) or self._is_upward_highlight(resource_oom_shift):
            severity = "critical"
            confidence = 0.91
            summary = "容器出现 OOMKilled，疑似内存限制不足、缓存堆积或应用内存泄漏。"
            reasoning_tags = ["oom_killed", "memory_pressure"]
            reasoning_details = [
                "OOM 已经是明确的资源失稳信号，优先级高于普通流量波动判断。",
                "即使入口流量没有明显放大，也要先核查容器内存 limits、对象堆积和进程峰值。",
            ]
            recommended_actions = ["提高内存 requests/limits", "检查应用内存占用趋势和探针配置"]
        elif error_rate >= 5 and host_cpu >= 70:
            severity = "critical"
            confidence = 0.86
            summary = "访问错误率上升且主机 CPU 同时偏高，疑似流量驱动的资源瓶颈。"
            reasoning_tags = ["traffic_spike", "resource_bottleneck"]
            reasoning_details = [
                "错误率和 CPU 同时抬升，说明入口流量已经在放大现有资源瓶颈。",
                "这类场景更像容量不足或热点请求集中，而不是单纯的路由配置问题。",
            ]
            recommended_actions = ["优先检查热点路径和异常来源 IP", "评估是否先做限流，再考虑扩容副本或资源上限"]
        elif error_without_resource_pressure:
            severity = "warning"
            confidence = 0.78
            summary = "访问错误率上升，但 CPU/内存未显著饱和，更像上游依赖、入口路由或配置失衡问题。"
            reasoning_tags = ["error_without_resource_pressure", "upstream_or_config_issue"]
            reasoning_details = [
                "错误率已经抬升，但资源侧没有同步打满，说明问题不像单纯容量不足。",
                "这类场景更需要优先排查 upstream 依赖、网关配置和外部接口可用性，而不是直接扩容。",
            ]
            recommended_actions = ["检查 upstream 服务依赖和入口路由配置", "避免直接给出扩容建议"]
        elif latency_without_resource_pressure:
            severity = "warning"
            confidence = 0.76
            summary = "请求延迟升高，但资源侧没有同步打满，更像下游依赖、网络抖动或慢查询放大。"
            reasoning_tags = ["latency_without_resource_pressure", "dependency_or_network_latency"]
            reasoning_details = [
                "延迟已经抬升，但 CPU/内存和热点资源并未同步进入高位，说明瓶颈可能不在本服务容量。",
                "优先检查慢查询、下游依赖响应时间和网络链路抖动，再决定是否需要扩容。",
            ]
            recommended_actions = ["检查下游依赖响应时间和错误码", "核对慢查询、连接池与网络抖动情况"]
        elif avg_latency >= 1.0 and (host_cpu >= 70 or host_memory >= 80):
            severity = "warning"
            confidence = 0.79
            summary = "请求延迟升高，并伴随资源压力上升，存在性能退化风险。"
            reasoning_tags = ["latency_increase", "resource_pressure"]
            reasoning_details = [
                "延迟和资源压力同时抬升，说明当前性能退化更像本服务内部瓶颈在放大。",
                "需要把慢请求路径和资源限制一起排查，避免只调副本却忽略热点逻辑。",
            ]
            recommended_actions = ["检查慢请求路径与资源限制", "核对 requests/limits 与副本配置"]
        elif traffic_shift_without_resource_pressure:
            severity = "warning"
            confidence = 0.72
            summary = "请求量明显高于基线，但资源侧仍平稳，说明实例余量还在，优先关注流量结构变化。"
            reasoning_tags = ["traffic_growth_without_resource_pressure", "traffic_pattern_shift"]
            reasoning_details = [
                "请求量已经偏离历史基线，但 CPU/内存没有同步抬升，说明当前实例还有容量余量。",
                "这类场景更适合先分析热点路径、来源 IP 和业务流量结构，而不是立即扩容。",
            ]
            recommended_actions = ["检查热点路径、来源 IP 和地区分布", "确认是否存在业务活动、机器人流量或入口放量"]
        elif resource_pressure_without_traffic_growth:
            severity = "warning"
            confidence = 0.77
            summary = "资源压力升高，但流量并未同步放量，更像后台任务、缓存堆积或应用内部泄漏。"
            reasoning_tags = ["resource_pressure_without_traffic_growth", "background_load_or_leak"]
            reasoning_details = [
                "资源已经进入高位，但入口流量没有同步偏离基线，说明压力可能来自服务内部或旁路任务。",
                "优先排查后台作业、缓存堆积、批处理和应用自身泄漏，再决定是否扩容。",
            ]
            recommended_actions = ["检查后台任务、缓存和批处理负载", "核对近期变更、定时任务和服务内部资源占用"]

        if total_requests:
            evidence_refs.append(
                self._build_evidence(
                    layer="traffic",
                    evidence_type="traffic_summary",
                    title="请求总量",
                    summary=f"当前窗口累计请求 {total_requests} 次。",
                    metric="total_requests",
                    value=total_requests,
                    unit="req",
                    priority=48,
                    signal_strength="medium",
                    service_key=service_key,
                    related_asset_ids=related_asset_ids,
                )
            )
        if error_rate:
            evidence_refs.append(
                self._build_evidence(
                    layer="traffic",
                    evidence_type="traffic_summary",
                    title="错误率",
                    summary=f"错误率达到 {error_rate:.2f}%，已经高于常规稳定阈值。",
                    metric="error_rate",
                    value=error_rate,
                    unit="%",
                    priority=96 if error_rate >= 5 else 72,
                    signal_strength="high" if error_rate >= 5 else "medium",
                    service_key=service_key,
                    related_asset_ids=related_asset_ids,
                )
            )
        if avg_latency:
            evidence_refs.append(
                self._build_evidence(
                    layer="traffic",
                    evidence_type="traffic_summary",
                    title="平均延迟",
                    summary=f"平均请求耗时约 {avg_latency:.3f} 秒。",
                    metric="avg_latency",
                    value=avg_latency,
                    unit="s",
                    priority=88 if avg_latency >= 1 else 62,
                    signal_strength="high" if avg_latency >= 1 else "medium",
                    service_key=service_key,
                    related_asset_ids=related_asset_ids,
                )
            )
        if host_cpu:
            evidence_refs.append(
                self._build_evidence(
                    layer="resource",
                    evidence_type="resource_summary",
                    title="主机 CPU 使用率",
                    summary=f"主机 CPU 使用率约为 {host_cpu:.2f}%。",
                    metric="host_cpu",
                    value=host_cpu,
                    unit="%",
                    priority=92 if host_cpu >= 70 else 58,
                    signal_strength="high" if host_cpu >= 70 else "medium",
                    service_key=service_key,
                    related_asset_ids=related_asset_ids,
                )
            )
        if host_memory:
            evidence_refs.append(
                self._build_evidence(
                    layer="resource",
                    evidence_type="resource_summary",
                    title="主机内存使用率",
                    summary=f"主机内存使用率约为 {host_memory:.2f}%。",
                    metric="host_memory",
                    value=host_memory,
                    unit="%",
                    priority=84 if host_memory >= 80 else 56,
                    signal_strength="high" if host_memory >= 80 else "medium",
                    service_key=service_key,
                    related_asset_ids=related_asset_ids,
                )
            )
        for item in hotspots[:5]:
            hotspot_score = float(item.get("score") or 0)
            evidence_refs.append(
                self._build_evidence(
                    layer="resource",
                    evidence_type="hotspot",
                    title=str(item.get("name") or "热点对象"),
                    summary=str(item.get("reason") or "检测到资源热点。"),
                    metric=str(item.get("type") or "hotspot"),
                    value=hotspot_score,
                    unit="score",
                    priority=min(max(int(hotspot_score), 52), 94),
                    signal_strength="high" if hotspot_score >= 80 else "medium",
                    extra=item,
                    service_key=service_key,
                    related_asset_ids=related_asset_ids,
                )
            )

        next_step = recommended_actions[0] if recommended_actions else "继续观察错误率、延迟和热点资源变化。"
        evidence_refs.append(
            self._build_evidence(
                layer="diagnosis",
                evidence_type="diagnosis",
                title="关联判断",
                summary=summary,
                metric="confidence",
                value=confidence,
                unit="score",
                priority=100,
                signal_strength="high",
                extra={
                    "reasoning_tags": reasoning_tags,
                    "reasoning_details": reasoning_details,
                    "next_step": next_step,
                },
                service_key=service_key,
                related_asset_ids=related_asset_ids,
            )
        )

        sorted_evidence = self._sort_evidence(evidence_refs)
        return {
            "service_key": service_key,
            "title": f"{service_key} 异常分析",
            "severity": severity,
            "summary": summary,
            "confidence": confidence,
            "reasoning_tags": reasoning_tags,
            "reasoning_details": reasoning_details,
            "recommended_actions": recommended_actions,
            "evidence_refs": sorted_evidence,
            "related_asset_ids": related_asset_ids,
            "time_window_start": (utc_now() - timedelta(hours=1)).isoformat(),
            "time_window_end": utc_now().isoformat(),
        }

    # 证据对象会被详情页、日报和后续导出链路复用，因此这里统一补齐优先级和信号强度。
    def _build_evidence(
        self,
        layer: str,
        evidence_type: str,
        title: str,
        summary: str,
        metric: str,
        value: Any,
        unit: str = "",
        priority: int = 50,
        signal_strength: str = "medium",
        extra: Dict[str, Any] | None = None,
        service_key: str = "",
        related_asset_ids: List[str] | None = None,
    ) -> Dict[str, Any]:
        payload = {
            "layer": layer,
            "type": evidence_type,
            "title": title,
            "summary": summary,
            "metric": metric,
            "value": value,
            "unit": unit,
            "priority": priority,
            "signal_strength": signal_strength,
            "service_key": service_key,
            "source_ref": {
                "service_key": service_key,
                "asset_ids": list(related_asset_ids or []),
                "layer": layer,
            },
        }
        if extra:
            payload.update(extra)
        return normalize_incident_evidence(
            payload,
            default_service_key=service_key,
            default_asset_ids=list(related_asset_ids or []),
        )

    def _sort_evidence(self, evidence_refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sort_incident_evidence(evidence_refs)

    def _find_baseline_highlight(self, summary: Dict[str, Any], metric: str) -> Dict[str, Any] | None:
        highlights = summary.get("highlights") if isinstance(summary.get("highlights"), list) else []
        for item in highlights:
            if not isinstance(item, dict):
                continue
            if str(item.get("metric") or "").strip() == metric:
                return item
        return None

    def _is_upward_highlight(self, item: Dict[str, Any] | None) -> bool:
        if not isinstance(item, dict):
            return False
        direction = str(item.get("direction") or "").strip().lower()
        severity = str(item.get("severity") or "").strip().lower()
        if direction == "up" and severity in {"high", "medium"}:
            return True
        delta_value = self._coerce_float(item.get("delta_value"))
        return delta_value > 0

    def _coerce_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
