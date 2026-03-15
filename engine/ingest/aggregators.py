"""
日志聚合器。

把 access log 转成流量、错误率、TopN 和时间序列摘要。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, Iterable, List

from .log_samples import build_log_samples


class LogAggregators:
    """日志聚合工具。"""

    def summarize(self, records: Iterable[Dict[str, object]]) -> Dict[str, object]:
        items = list(records)
        if not items:
            return {
                "total_requests": 0,
                "page_views": 0,
                "error_rate": 0.0,
                "avg_latency": 0.0,
                "top_paths": [],
                "hot_paths": [],
                "top_ips": [],
                "hot_ips": [],
                "status_distribution": [],
                "geo_distribution": [],
                "ua_distribution": [],
                "trend": [],
                "error_samples": [],
            }

        total = len(items)
        page_views = sum(1 for item in items if item.get("is_page_view"))
        error_count = sum(1 for item in items if int(item.get("status", 0)) >= 500)
        avg_latency = round(sum(float(item.get("request_time", 0.0)) for item in items) / total, 4)

        path_counter = Counter(str(item.get("path", "/")) for item in items)
        ip_counter = Counter(str(item.get("remote_addr", "unknown")) for item in items)
        status_counter = Counter(str(item.get("status", 0)) for item in items)
        geo_counter = Counter(str((item.get("geo") or {}).get("region", "未知")) for item in items)
        ua_counter = Counter(str((item.get("ua") or {}).get("browser", "Unknown")) for item in items)

        trend_map: Dict[str, Dict[str, float]] = defaultdict(lambda: {"requests": 0, "errors": 0})
        path_metrics: Dict[str, Dict[str, float]] = defaultdict(lambda: {"count": 0, "errors": 0, "latency_sum": 0.0})
        ip_metrics: Dict[str, Dict[str, object]] = defaultdict(
            lambda: {
                "count": 0,
                "errors": 0,
                "latency_sum": 0.0,
                "sample_path": "/",
                "geo_label": "未知",
            }
        )
        for item in items:
            ts = str(item.get("timestamp", ""))
            bucket = self._bucket_minute(ts)
            trend_map[bucket]["requests"] += 1

            path = str(item.get("path", "/"))
            ip = str(item.get("remote_addr", "unknown"))
            status = int(item.get("status", 0))
            latency = float(item.get("request_time", 0.0))

            path_metrics[path]["count"] += 1
            path_metrics[path]["latency_sum"] += latency

            ip_metrics[ip]["count"] = int(ip_metrics[ip]["count"]) + 1
            ip_metrics[ip]["latency_sum"] = float(ip_metrics[ip]["latency_sum"]) + latency
            if ip_metrics[ip]["sample_path"] == "/":
                ip_metrics[ip]["sample_path"] = path
            if ip_metrics[ip]["geo_label"] == "未知":
                geo = item.get("geo") or {}
                ip_metrics[ip]["geo_label"] = "/".join(
                    [str(part) for part in [geo.get("country"), geo.get("region"), geo.get("city")] if part],
                ) or "未知"

            if status >= 500:
                trend_map[bucket]["errors"] += 1
                path_metrics[path]["errors"] += 1
                ip_metrics[ip]["errors"] = int(ip_metrics[ip]["errors"]) + 1

        return {
            "total_requests": total,
            "page_views": page_views,
            "error_rate": round((error_count / total) * 100, 2) if total else 0.0,
            "avg_latency": avg_latency,
            "top_paths": self._top_paths(path_counter),
            "hot_paths": self._hot_paths(path_metrics),
            "top_ips": self._top_ips(ip_counter),
            "hot_ips": self._hot_ips(ip_metrics),
            "status_distribution": self._counter_to_named_list(status_counter, limit=10, key_name="status"),
            "geo_distribution": self._counter_to_named_list(geo_counter, limit=10),
            "ua_distribution": self._counter_to_named_list(ua_counter, limit=10),
            "trend": [
                {"timestamp": bucket, "requests": values["requests"], "errors": values["errors"]}
                for bucket, values in sorted(trend_map.items(), key=lambda item: item[0])
            ],
            "error_samples": self._error_samples(items),
        }

    def _bucket_minute(self, iso_text: str) -> str:
        try:
            parsed = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
            return parsed.replace(second=0, microsecond=0).isoformat()
        except ValueError:
            return datetime.utcnow().replace(second=0, microsecond=0).isoformat()

    def _counter_to_named_list(self, counter: Counter, limit: int = 5, key_name: str = "name") -> List[Dict[str, object]]:
        return [{key_name: name, "count": count} for name, count in counter.most_common(limit)]

    def _top_paths(self, counter: Counter, limit: int = 8) -> List[Dict[str, object]]:
        return [{"path": path, "count": count} for path, count in counter.most_common(limit)]

    def _top_ips(self, counter: Counter, limit: int = 8) -> List[Dict[str, object]]:
        return [{"ip": ip, "count": count} for ip, count in counter.most_common(limit)]

    # 热点路径不只看请求量，也把错误密度和平均耗时一起带上，前端可以直接用于排障排序。
    def _hot_paths(self, path_metrics: Dict[str, Dict[str, float]], limit: int = 8) -> List[Dict[str, object]]:
        ranked: List[Dict[str, object]] = []
        for path, metrics in path_metrics.items():
            count = int(metrics.get("count", 0))
            errors = int(metrics.get("errors", 0))
            avg_latency = round(float(metrics.get("latency_sum", 0.0)) / count, 4) if count else 0.0
            error_rate = round((errors / count) * 100, 2) if count else 0.0
            ranked.append(
                {
                    "path": path,
                    "count": count,
                    "error_count": errors,
                    "error_rate": error_rate,
                    "avg_latency": avg_latency,
                }
            )
        ranked.sort(key=lambda item: (-item["error_count"], -item["count"], -item["avg_latency"], item["path"]))
        return ranked[:limit]

    # 异常来源 IP 需要带上路径样本和地域，前端才能直接拿来做入口排障定位。
    def _hot_ips(self, ip_metrics: Dict[str, Dict[str, object]], limit: int = 8) -> List[Dict[str, object]]:
        ranked: List[Dict[str, object]] = []
        for ip, metrics in ip_metrics.items():
            count = int(metrics.get("count", 0))
            errors = int(metrics.get("errors", 0))
            avg_latency = round(float(metrics.get("latency_sum", 0.0)) / count, 4) if count else 0.0
            error_rate = round((errors / count) * 100, 2) if count else 0.0
            ranked.append(
                {
                    "ip": ip,
                    "count": count,
                    "error_count": errors,
                    "error_rate": error_rate,
                    "avg_latency": avg_latency,
                    "sample_path": str(metrics.get("sample_path", "/")),
                    "geo_label": str(metrics.get("geo_label", "未知")),
                }
            )
        ranked.sort(key=lambda item: (-item["error_count"], -item["count"], -item["avg_latency"], item["ip"]))
        return ranked[:limit]

    def _error_samples(self, items: List[Dict[str, object]], limit: int = 8) -> List[Dict[str, object]]:
        return build_log_samples(items, limit=limit)
