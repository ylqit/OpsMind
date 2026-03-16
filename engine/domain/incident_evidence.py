"""
异常证据标准化工具。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List

from engine.runtime.time_utils import parse_utc_datetime


LAYER_ORDER = {
    "diagnosis": 0,
    "traffic": 1,
    "resource": 2,
    "alert": 3,
    "task": 4,
    "other": 5,
}

SIGNAL_STRENGTH_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
}


def normalize_incident_evidence(
    payload: Dict[str, Any],
    *,
    default_service_key: str = "",
    default_asset_ids: Iterable[str] | None = None,
) -> Dict[str, Any]:
    item = dict(payload or {})
    layer = _normalize_layer(item)
    evidence_type = _normalize_type(item)
    title = str(item.get("title") or item.get("name") or item.get("metric") or evidence_type or "证据项")
    summary = str(item.get("summary") or item.get("reason") or "")
    metric = str(item.get("metric") or evidence_type or "unknown")
    unit = str(item.get("unit") or "")
    priority = _normalize_priority(item.get("priority"))
    signal_strength = _normalize_signal_strength(item.get("signal_strength"), priority)
    tags = _normalize_tags(item)
    source_ref = _normalize_source_ref(
        item,
        layer=layer,
        default_service_key=default_service_key,
        default_asset_ids=list(default_asset_ids or []),
    )
    evidence_id = str(item.get("evidence_id") or _make_evidence_id(layer, evidence_type, title, summary, source_ref))

    normalized = {
        **item,
        "evidence_id": evidence_id,
        "layer": layer,
        "type": evidence_type,
        "source_type": str(item.get("source_type") or evidence_type),
        "title": title,
        "summary": summary,
        "metric": metric,
        "value": item.get("value"),
        "unit": unit,
        "priority": priority,
        "signal_strength": signal_strength,
        "source_ref": source_ref,
        "tags": tags,
    }

    if source_ref.get("service_key") and not normalized.get("service_key"):
        normalized["service_key"] = source_ref["service_key"]
    return normalized


def sort_incident_evidence(evidence_refs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        evidence_refs,
        key=lambda item: (
            LAYER_ORDER.get(str(item.get("layer") or "other"), 99),
            -int(item.get("priority") or 0),
            SIGNAL_STRENGTH_ORDER.get(str(item.get("signal_strength") or "low"), 99),
            -_normalize_timestamp_order(item),
            str(item.get("title") or item.get("metric") or ""),
        ),
    )


def summarize_incident_evidence(evidence_refs: List[Dict[str, Any]]) -> Dict[str, Any]:
    sorted_refs = sort_incident_evidence(evidence_refs)
    layer_counts: Dict[str, int] = {}
    for item in sorted_refs:
        layer = str(item.get("layer") or "other")
        layer_counts[layer] = layer_counts.get(layer, 0) + 1

    diagnosis_item = next((item for item in sorted_refs if item.get("layer") == "diagnosis"), None)
    highlights = [item for item in sorted_refs if item.get("layer") != "diagnosis"][:3]
    primary_layer = _pick_primary_layer(layer_counts)

    return {
        "total": len(sorted_refs),
        "layers": layer_counts,
        "primary_layer": primary_layer,
        "headline": str(diagnosis_item.get("summary") or "") if diagnosis_item else "",
        "next_step": str(diagnosis_item.get("next_step") or "") if diagnosis_item else "",
        "reasoning_tags": list(diagnosis_item.get("reasoning_tags") or []) if diagnosis_item else [],
        "highlights": highlights,
        "summary_lines": [_build_summary_line(item) for item in highlights],
    }


def build_log_sample_evidence(
    sample: Dict[str, Any],
    *,
    service_key: str,
    related_asset_ids: List[str],
) -> Dict[str, Any]:
    status = _coerce_int(sample.get("status"))
    latency_ms = _coerce_float(sample.get("latency_ms"))
    priority = 90 if status >= 500 else 78 if status >= 400 else 64
    if latency_ms >= 1000:
        priority = max(priority, 84)
    method = str(sample.get("method") or "GET")
    path = str(sample.get("path") or "/")
    summary = (
        f"{sample.get('timestamp') or '-'} {method} {path} "
        f"status={status or '-'} latency_ms={int(latency_ms) if latency_ms else 0} "
        f"ip={sample.get('client_ip') or '-'}"
    )
    return normalize_incident_evidence(
        {
            "layer": "traffic",
            "type": "log_sample",
            "title": f"{method} {path}",
            "summary": summary,
            "metric": "http_status",
            "value": status or sample.get("status"),
            "unit": "",
            "priority": priority,
            "signal_strength": "high" if status >= 500 or latency_ms >= 1000 else "medium",
            "timestamp": sample.get("timestamp"),
            "path": path,
            "status": status or sample.get("status"),
            "service_key": sample.get("service_key") or service_key,
            "client_ip": sample.get("client_ip"),
            "geo_label": sample.get("geo_label"),
            "tags": ["log", "traffic"],
        },
        default_service_key=service_key,
        default_asset_ids=related_asset_ids,
    )


def build_alert_evidence(
    alert: Dict[str, Any],
    *,
    service_key: str,
    related_asset_ids: List[str],
) -> Dict[str, Any]:
    severity = str(alert.get("severity") or "warning")
    title = str(alert.get("title") or alert.get("name") or alert.get("metric") or "活动告警")
    summary = str(
        alert.get("summary")
        or alert.get("message")
        or alert.get("description")
        or f"{title} 仍处于活动状态。"
    )
    priority = 92 if severity == "critical" else 80 if severity == "warning" else 68
    metric = str(alert.get("metric") or "alert")
    value = alert.get("value")
    if value in (None, ""):
        value = severity
    return normalize_incident_evidence(
        {
            "layer": "alert",
            "type": "alert_signal",
            "title": title,
            "summary": summary,
            "metric": metric,
            "value": value,
            "unit": str(alert.get("unit") or ""),
            "priority": priority,
            "signal_strength": "high" if severity == "critical" else "medium",
            "alert_id": alert.get("id") or alert.get("alert_id"),
            "service_key": alert.get("service_key") or service_key,
            "severity": severity,
            "status": alert.get("status"),
            "timestamp": alert.get("created_at") or alert.get("updated_at"),
            "tags": ["alert", severity],
        },
        default_service_key=service_key,
        default_asset_ids=related_asset_ids,
    )


def build_task_evidence(
    task_context: Dict[str, Any],
    *,
    service_key: str,
    related_asset_ids: List[str],
) -> Dict[str, Any]:
    status = str(task_context.get("status") or task_context.get("current_stage") or "ANALYZING")
    progress = _coerce_int(task_context.get("progress"))
    summary = str(task_context.get("summary") or task_context.get("progress_message") or "异常分析任务已进入当前阶段。")
    return normalize_incident_evidence(
        {
            "layer": "task",
            "type": "task_trace",
            "title": "异常分析任务",
            "summary": summary,
            "metric": "task_status",
            "value": status,
            "unit": "",
            "priority": 70,
            "signal_strength": "medium",
            "task_id": task_context.get("task_id"),
            "trace_id": task_context.get("trace_id"),
            "service_key": service_key,
            "progress": progress,
            "current_stage": task_context.get("current_stage"),
            "tags": ["task", str(task_context.get("task_type") or "incident_analysis")],
        },
        default_service_key=service_key,
        default_asset_ids=related_asset_ids,
    )


def build_alignment_evidence(
    alignment: Dict[str, Any],
    *,
    service_key: str,
    related_asset_ids: List[str],
) -> Dict[str, Any]:
    is_unmapped = bool(alignment.get("unmapped"))
    return normalize_incident_evidence(
        {
            "layer": "diagnosis",
            "type": "service_key_alignment",
            "title": "service_key 对齐状态" if is_unmapped else "service_key 已自动回补",
            "summary": (
                f"当前 service_key 仍为 {service_key}，存在未完全对齐风险。"
                if is_unmapped
                else f"本次 incident 使用 {service_key} 作为统一关联键。"
            ),
            "metric": "service_key_alignment",
            "value": alignment.get("reason") or alignment.get("source") or ("unmapped" if is_unmapped else "aligned"),
            "unit": "",
            "priority": 78 if is_unmapped else 74,
            "signal_strength": "medium",
            "alignment": alignment,
            "service_key": service_key,
            "tags": ["alignment", str(alignment.get("source") or "unknown")],
        },
        default_service_key=service_key,
        default_asset_ids=related_asset_ids,
    )


def _normalize_layer(item: Dict[str, Any]) -> str:
    layer = str(item.get("layer") or "").strip().lower()
    if layer:
        return layer
    evidence_type = str(item.get("type") or item.get("source_type") or "").strip().lower()
    if evidence_type in {"traffic_summary", "log_sample"}:
        return "traffic"
    if evidence_type in {"resource_summary", "hotspot"}:
        return "resource"
    if evidence_type in {"alert_signal"}:
        return "alert"
    if evidence_type in {"task_trace"}:
        return "task"
    if evidence_type in {"diagnosis", "service_key_alignment"}:
        return "diagnosis"
    return "other"


def _normalize_type(item: Dict[str, Any]) -> str:
    evidence_type = str(item.get("type") or item.get("source_type") or "").strip()
    if evidence_type:
        return evidence_type
    layer = str(item.get("layer") or "").strip().lower()
    if layer == "traffic":
        return "traffic_summary"
    if layer == "resource":
        return "resource_summary"
    if layer == "alert":
        return "alert_signal"
    if layer == "task":
        return "task_trace"
    if layer == "diagnosis":
        return "diagnosis"
    return "other"


def _normalize_priority(value: Any) -> int:
    try:
        priority = int(value)
    except (TypeError, ValueError):
        priority = 50
    return max(0, min(priority, 100))


def _normalize_signal_strength(value: Any, priority: int) -> str:
    signal = str(value or "").strip().lower()
    if signal in {"high", "medium", "low"}:
        return signal
    if priority >= 85:
        return "high"
    if priority >= 60:
        return "medium"
    return "low"


def _normalize_tags(item: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    for key in ("tags", "labels", "reasoning_tags"):
        value = item.get(key)
        if isinstance(value, list):
            for raw in value:
                text = str(raw).strip()
                if text and text not in tags:
                    tags.append(text)
    return tags


def _normalize_source_ref(
    item: Dict[str, Any],
    *,
    layer: str,
    default_service_key: str,
    default_asset_ids: List[str],
) -> Dict[str, Any]:
    raw_ref = item.get("source_ref")
    source_ref = dict(raw_ref) if isinstance(raw_ref, dict) else {}
    if default_service_key and not source_ref.get("service_key"):
        source_ref["service_key"] = default_service_key
    if default_asset_ids and not source_ref.get("asset_ids"):
        source_ref["asset_ids"] = list(default_asset_ids)
    if item.get("service_key") and not source_ref.get("service_key"):
        source_ref["service_key"] = str(item.get("service_key"))
    if item.get("task_id") and not source_ref.get("task_id"):
        source_ref["task_id"] = str(item.get("task_id"))
    if item.get("trace_id") and not source_ref.get("trace_id"):
        source_ref["trace_id"] = str(item.get("trace_id"))
    if item.get("alert_id") and not source_ref.get("alert_id"):
        source_ref["alert_id"] = str(item.get("alert_id"))
    if item.get("timestamp") and not source_ref.get("timestamp"):
        source_ref["timestamp"] = str(item.get("timestamp"))
    if item.get("path") and not source_ref.get("path"):
        source_ref["path"] = str(item.get("path"))
    if item.get("status") is not None and source_ref.get("status") is None:
        source_ref["status"] = item.get("status")
    if item.get("source") and not source_ref.get("source"):
        source_ref["source"] = str(item.get("source"))
    if item.get("namespace") and not source_ref.get("namespace"):
        source_ref["namespace"] = str(item.get("namespace"))
    if item.get("client_ip") and not source_ref.get("client_ip"):
        source_ref["client_ip"] = str(item.get("client_ip"))
    if item.get("geo_label") and not source_ref.get("geo_label"):
        source_ref["geo_label"] = str(item.get("geo_label"))
    if not source_ref.get("layer"):
        source_ref["layer"] = layer
    return source_ref


def _make_evidence_id(layer: str, evidence_type: str, title: str, summary: str, source_ref: Dict[str, Any]) -> str:
    basis = json.dumps(
        {
            "layer": layer,
            "type": evidence_type,
            "title": title,
            "summary": summary,
            "source_ref": source_ref,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"evidence_{hashlib.sha1(basis.encode('utf-8')).hexdigest()[:12]}"


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_timestamp_order(item: Dict[str, Any]) -> float:
    source_ref = item.get("source_ref")
    candidate = None
    if isinstance(source_ref, dict):
        candidate = source_ref.get("timestamp")
    if not candidate:
        candidate = item.get("timestamp")
    if not candidate:
        return 0.0
    text = str(candidate).strip()
    if not text:
        return 0.0
    try:
        return parse_utc_datetime(text).timestamp()
    except ValueError:
        return 0.0


def _pick_primary_layer(layer_counts: Dict[str, int]) -> str:
    ranked_layers = [
        layer
        for layer in ("traffic", "resource", "alert", "task", "diagnosis", "other")
        if layer_counts.get(layer)
    ]
    return ranked_layers[0] if ranked_layers else "other"


def _build_summary_line(item: Dict[str, Any]) -> str:
    layer = str(item.get("layer") or "other")
    layer_label = {
        "diagnosis": "判断",
        "traffic": "流量",
        "resource": "资源",
        "alert": "告警",
        "task": "任务",
        "other": "其他",
    }.get(layer, "其他")
    title = str(item.get("title") or item.get("metric") or item.get("type") or "证据")
    value = item.get("value")
    unit = str(item.get("unit") or "").strip()
    summary = str(item.get("summary") or "").strip()
    if value in (None, ""):
        return f"{layer_label}: {title} - {summary or '已记录'}"
    suffix = f"{value}{f' {unit}' if unit else ''}"
    return f"{layer_label}: {title} - {suffix}"
