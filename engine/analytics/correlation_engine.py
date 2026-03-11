"""
关联分析引擎。

使用规则与证据链解释访问异常和资源异常之间的关系。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List


class CorrelationEngine:
    """访问异常与资源异常关联解释。"""

    def analyze(self, service_key: str, traffic_summary: Dict[str, Any], resource_summary: Dict[str, Any], related_asset_ids: List[str]) -> Dict[str, Any]:
        total_requests = int(traffic_summary.get("total_requests", 0))
        error_rate = float(traffic_summary.get("error_rate", 0.0))
        avg_latency = float(traffic_summary.get("avg_latency", 0.0))
        host_cpu = float(resource_summary.get("host", {}).get("cpu", {}).get("usage_percent", 0.0))
        host_memory = float(resource_summary.get("host", {}).get("memory", {}).get("usage_percent", 0.0))
        hotspots = resource_summary.get("hotspots", [])

        severity = "info"
        summary = "未发现明显异常。"
        confidence = 0.35
        reasoning_tags: List[str] = []
        recommended_actions: List[str] = []
        evidence_refs: List[Dict[str, Any]] = []

        if error_rate >= 5 and host_cpu >= 70:
            severity = "critical"
            confidence = 0.86
            summary = "访问错误率上升且主机 CPU 同时偏高，疑似流量驱动的资源瓶颈。"
            reasoning_tags = ["traffic_spike", "resource_bottleneck"]
            recommended_actions = ["优先检查热点路径和异常来源 IP", "评估是否先做限流，再考虑扩容副本或资源上限"]
        elif error_rate >= 5 and host_cpu < 70:
            severity = "warning"
            confidence = 0.74
            summary = "访问错误率上升，但主机 CPU 未显著饱和，更像路由、依赖或配置失衡问题。"
            reasoning_tags = ["traffic_error", "upstream_or_config_issue"]
            recommended_actions = ["检查 upstream 服务依赖和入口路由配置", "避免直接给出扩容建议"]
        elif avg_latency >= 1.0 and (host_cpu >= 70 or host_memory >= 80):
            severity = "warning"
            confidence = 0.79
            summary = "请求延迟升高，并伴随资源压力上升，存在性能退化风险。"
            reasoning_tags = ["latency_increase", "resource_pressure"]
            recommended_actions = ["检查慢请求路径与资源限制", "核对 requests/limits 与副本配置"]
        elif any(item.get("oom_killed") for item in resource_summary.get("containers", {}).get("items", [])):
            severity = "critical"
            confidence = 0.91
            summary = "容器出现 OOMKilled，疑似内存限制不足或应用内存泄漏。"
            reasoning_tags = ["oom_killed", "memory_pressure"]
            recommended_actions = ["提高内存 requests/limits", "检查应用内存占用趋势和探针配置"]

        if total_requests:
            evidence_refs.append({"type": "traffic_summary", "metric": "total_requests", "value": total_requests})
        if error_rate:
            evidence_refs.append({"type": "traffic_summary", "metric": "error_rate", "value": error_rate})
        if avg_latency:
            evidence_refs.append({"type": "traffic_summary", "metric": "avg_latency", "value": avg_latency})
        if host_cpu:
            evidence_refs.append({"type": "resource_summary", "metric": "host_cpu", "value": host_cpu})
        if host_memory:
            evidence_refs.append({"type": "resource_summary", "metric": "host_memory", "value": host_memory})
        evidence_refs.extend({"type": "hotspot", **item} for item in hotspots[:5])

        return {
            "service_key": service_key,
            "title": f"{service_key} 异常分析",
            "severity": severity,
            "summary": summary,
            "confidence": confidence,
            "reasoning_tags": reasoning_tags,
            "recommended_actions": recommended_actions,
            "evidence_refs": evidence_refs,
            "related_asset_ids": related_asset_ids,
            "time_window_start": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
            "time_window_end": datetime.utcnow().isoformat(),
        }
