"""
统一日志样本格式。
"""
from __future__ import annotations

from typing import Dict, Iterable, List


def format_log_sample(record: Dict[str, object]) -> Dict[str, object]:
    """把富化后的访问日志记录压成统一样本结构。"""
    geo = record.get("geo") or {}
    ua = record.get("ua") or {}
    has_request_time = record.get("request_time") is not None
    latency_ms = float(record.get("latency_ms") or 0.0)
    if has_request_time:
        latency_ms = float(record.get("request_time") or 0.0) * 1000

    geo_label = str(record.get("geo_label") or "").strip()
    if not geo_label:
        geo_label = "/".join(
            [str(item) for item in [geo.get("country"), geo.get("region"), geo.get("city")] if item],
        ) or "未知"

    return {
        "timestamp": record.get("timestamp"),
        "method": record.get("method") or "GET",
        "path": record.get("path") or "/",
        "status": int(record.get("status") or 0),
        "latency_ms": round(latency_ms, 2),
        "client_ip": record.get("client_ip") or record.get("remote_addr") or "-",
        "geo_label": geo_label,
        "user_agent": record.get("user_agent") or "Unknown",
        "browser": record.get("browser") or ua.get("browser") or "Unknown",
        "os": record.get("os") or ua.get("os") or "Unknown",
        "device": record.get("device") or ua.get("device") or "Unknown",
        "service_key": record.get("service_key") or "unknown/root",
    }


def select_log_sample_records(records: Iterable[Dict[str, object]], limit: int = 8) -> List[Dict[str, object]]:
    """挑出更适合直接排障阅读的日志记录。"""
    items = list(records)
    interesting = [
        item for item in items
        if int(item.get("status") or 0) >= 500 or float(item.get("request_time") or 0.0) >= 1
    ]
    source = interesting or items
    ranked = sorted(
        source,
        key=lambda item: (
            -int(item.get("status") or 0),
            -float(item.get("request_time") or 0.0),
            str(item.get("timestamp") or ""),
        ),
    )
    return ranked[:limit]


def build_log_samples(records: Iterable[Dict[str, object]], limit: int = 8) -> List[Dict[str, object]]:
    """直接输出统一格式的日志样本列表。"""
    return [format_log_sample(item) for item in select_log_sample_records(records, limit=limit)]
