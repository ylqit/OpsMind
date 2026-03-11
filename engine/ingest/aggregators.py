"""
日志聚合器。

把 access log 转成流量、错误率、TopN 和时间序列摘要。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, Iterable, List


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
                "top_ips": [],
                "status_distribution": [],
                "geo_distribution": [],
                "ua_distribution": [],
                "trend": [],
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
        for item in items:
            ts = str(item.get("timestamp", ""))
            bucket = self._bucket_minute(ts)
            trend_map[bucket]["requests"] += 1
            if int(item.get("status", 0)) >= 500:
                trend_map[bucket]["errors"] += 1

        return {
            "total_requests": total,
            "page_views": page_views,
            "error_rate": round((error_count / total) * 100, 2) if total else 0.0,
            "avg_latency": avg_latency,
            "top_paths": self._top_n(path_counter),
            "top_ips": self._top_n(ip_counter),
            "status_distribution": self._top_n(status_counter, 10),
            "geo_distribution": self._top_n(geo_counter, 10),
            "ua_distribution": self._top_n(ua_counter, 10),
            "trend": [
                {"timestamp": bucket, "requests": values["requests"], "errors": values["errors"]}
                for bucket, values in sorted(trend_map.items(), key=lambda item: item[0])
            ],
        }

    def _bucket_minute(self, iso_text: str) -> str:
        try:
            parsed = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
            return parsed.replace(second=0, microsecond=0).isoformat()
        except ValueError:
            return datetime.utcnow().replace(second=0, microsecond=0).isoformat()

    def _top_n(self, counter: Counter, limit: int = 5) -> List[Dict[str, object]]:
        return [{"name": name, "count": count} for name, count in counter.most_common(limit)]
