"""
Incident 服务。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine.analytics.correlation_engine import CorrelationEngine
from engine.domain.incident_evidence import (
    build_alert_evidence,
    build_alignment_evidence,
    build_log_sample_evidence,
    build_task_evidence,
    normalize_incident_evidence,
    sort_incident_evidence,
)
from engine.domain.service_key_resolver import pick_best_service_key, resolve_explicit_service_key
from engine.runtime.models import Incident
from engine.storage.repositories import IncidentRepository


class IncidentService:
    """Incident 聚合与持久化服务。"""

    def __init__(self, incident_repository: IncidentRepository, correlation_engine: CorrelationEngine):
        self.incident_repository = incident_repository
        self.correlation_engine = correlation_engine

    def list_incidents(self, status: Optional[str] = None, severity: Optional[str] = None, service_key: Optional[str] = None) -> List[Incident]:
        incidents = self.incident_repository.list(status=status, severity=severity, service_key=service_key)
        return [self._normalize_incident(incident) for incident in incidents]

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        incident = self.incident_repository.get(incident_id)
        if not incident:
            return None
        return self._normalize_incident(incident)

    def build_incident(
        self,
        service_key: str,
        traffic_summary: Dict[str, object],
        resource_summary: Dict[str, object],
        related_asset_ids: List[str],
        active_alerts: Optional[List[Dict[str, Any]]] = None,
        task_context: Optional[Dict[str, Any]] = None,
    ) -> Incident:
        alignment = self._resolve_incident_service_key(service_key, traffic_summary, resource_summary)
        resolved_service_key = alignment["service_key"]
        correlated = self.correlation_engine.analyze(
            service_key=resolved_service_key,
            traffic_summary=traffic_summary,
            resource_summary=resource_summary,
            related_asset_ids=related_asset_ids,
        )
        evidence_refs = list(correlated["evidence_refs"])
        baseline_analysis = self._build_baseline_analysis(traffic_summary, resource_summary)
        evidence_refs.extend(
            self._build_baseline_evidence_refs(
                baseline_analysis,
                service_key=resolved_service_key,
                related_asset_ids=related_asset_ids,
            )
        )
        evidence_refs.extend(self._build_log_evidence_refs(traffic_summary, resolved_service_key, related_asset_ids))
        evidence_refs.extend(self._build_alert_evidence_refs(active_alerts or [], resolved_service_key, related_asset_ids))
        if task_context:
            evidence_refs.append(
                build_task_evidence(
                    task_context,
                    service_key=resolved_service_key,
                    related_asset_ids=related_asset_ids,
                )
            )
        if alignment["unmapped"] or alignment["source"] != "explicit":
            evidence_refs.append(
                build_alignment_evidence(
                    alignment,
                    service_key=resolved_service_key,
                    related_asset_ids=related_asset_ids,
                )
            )
        normalized_evidence_refs = sort_incident_evidence(
            [
                normalize_incident_evidence(
                    item,
                    default_service_key=resolved_service_key,
                    default_asset_ids=related_asset_ids,
                )
                for item in evidence_refs
            ]
        )
        incident = Incident(
            title=correlated["title"],
            severity=correlated["severity"],
            service_key=resolved_service_key,
            time_window_start=correlated["time_window_start"],
            time_window_end=correlated["time_window_end"],
            related_asset_ids=related_asset_ids,
            evidence_refs=normalized_evidence_refs,
            summary=correlated["summary"],
            confidence=correlated["confidence"],
            recommended_actions=correlated["recommended_actions"],
            reasoning_tags=correlated["reasoning_tags"],
        )
        return self._normalize_incident(self.incident_repository.save(incident))

    def _build_baseline_analysis(
        self,
        traffic_summary: Dict[str, object],
        resource_summary: Dict[str, object],
    ) -> Dict[str, object]:
        traffic_baseline = traffic_summary.get("baseline_summary") if isinstance(traffic_summary.get("baseline_summary"), dict) else {}
        resource_baseline = resource_summary.get("baseline_summary") if isinstance(resource_summary.get("baseline_summary"), dict) else {}

        highlights: List[Dict[str, Any]] = []
        source_modes: List[str] = []
        for section in (traffic_baseline, resource_baseline):
            if not isinstance(section, dict):
                continue
            source_mode = str(section.get("source") or "").strip()
            if source_mode and source_mode not in source_modes:
                source_modes.append(source_mode)
            for item in section.get("highlights") or []:
                if isinstance(item, dict):
                    highlights.append(item)

        highlights.sort(
            key=lambda item: (
                -self._baseline_severity_rank(str(item.get("severity") or "medium")),
                -abs(self._coerce_float(item.get("delta_percent") or item.get("delta_value"))),
                str(item.get("metric") or ""),
            )
        )
        layer_counts: Dict[str, int] = {}
        for item in highlights:
            layer = str(item.get("layer") or "other")
            layer_counts[layer] = layer_counts.get(layer, 0) + 1

        if highlights:
            top_highlight = highlights[0]
            return {
                "status": "ready",
                "source_modes": source_modes,
                "headline": str(top_highlight.get("title") or "已检测到基线偏移"),
                "message": "已把流量历史趋势和资源安全阈值合并成同一份基线偏移视图，便于判断异常是否明显偏离常态。",
                "layers": layer_counts,
                "highlights": highlights[:6],
                "next_step": str(top_highlight.get("next_step") or "继续结合证据链验证偏移原因。"),
            }

        fallback_messages = [
            str(item.get("headline") or "").strip()
            for item in (traffic_baseline, resource_baseline)
            if isinstance(item, dict) and str(item.get("headline") or "").strip()
        ]
        return {
            "status": "unavailable",
            "source_modes": source_modes,
            "headline": fallback_messages[0] if fallback_messages else "当前 incident 尚未形成可用的基线偏移信息。",
            "message": "现有数据不足以形成稳定的偏移结论，可以继续补采流量趋势或资源信号后再判断。",
            "layers": {},
            "highlights": [],
            "next_step": "继续补充趋势窗口和资源现场后再对照基线。",
        }

    def _build_baseline_evidence_refs(
        self,
        baseline_analysis: Dict[str, object],
        *,
        service_key: str,
        related_asset_ids: List[str],
    ) -> List[Dict[str, Any]]:
        if not isinstance(baseline_analysis, dict):
            return []

        evidence_refs: List[Dict[str, Any]] = []
        highlights = [item for item in baseline_analysis.get("highlights") or [] if isinstance(item, dict)]
        headline = str(baseline_analysis.get("headline") or "").strip()
        next_step = str(baseline_analysis.get("next_step") or "").strip()
        if headline:
            evidence_refs.append(
                normalize_incident_evidence(
                    {
                        "layer": "diagnosis",
                        "type": "baseline_summary",
                        "title": "基线偏移概览",
                        "summary": headline,
                        "metric": "baseline_deviation",
                        "value": len(highlights),
                        "unit": "项",
                        "priority": 82 if highlights else 58,
                        "signal_strength": "high" if highlights else "medium",
                        "service_key": service_key,
                        "tags": ["baseline", "deviation"],
                        "next_step": next_step,
                        "baseline": baseline_analysis,
                        "reasoning_tags": ["baseline_deviation"],
                    },
                    default_service_key=service_key,
                    default_asset_ids=related_asset_ids,
                )
            )

        for item in highlights[:4]:
            severity = str(item.get("severity") or "medium")
            delta_percent = item.get("delta_percent")
            delta_value = item.get("delta_value")
            evidence_refs.append(
                normalize_incident_evidence(
                    {
                        "layer": str(item.get("layer") or "diagnosis"),
                        "type": "baseline_deviation",
                        "title": str(item.get("title") or "基线偏移"),
                        "summary": str(item.get("summary") or ""),
                        "metric": str(item.get("metric") or "baseline"),
                        "value": round(self._coerce_float(delta_percent), 2) if delta_percent is not None else delta_value,
                        "unit": "%" if delta_percent is not None else str(item.get("unit") or ""),
                        "priority": 92 if severity == "high" else 76,
                        "signal_strength": "high" if severity == "high" else "medium",
                        "service_key": service_key,
                        "tags": ["baseline", "deviation", str(item.get("metric") or "baseline")],
                        "next_step": str(item.get("next_step") or next_step),
                        "baseline": item,
                    },
                    default_service_key=service_key,
                    default_asset_ids=related_asset_ids,
                )
            )
        return evidence_refs

    def _resolve_incident_service_key(
        self,
        service_key: str,
        traffic_summary: Dict[str, object],
        resource_summary: Dict[str, object],
    ) -> Dict[str, object]:
        explicit = resolve_explicit_service_key(service_key)
        if not explicit["unmapped"]:
            return explicit

        traffic_records = traffic_summary.get("records_sample") if isinstance(traffic_summary.get("records_sample"), list) else []
        traffic_candidates = [
            str(item.get("service_key") or "").strip()
            for item in traffic_records
            if isinstance(item, dict)
        ]
        hotspot_candidates = [
            str(item.get("service_key") or "").strip()
            for item in resource_summary.get("hotspots", [])
            if isinstance(item, dict)
        ]
        derived = pick_best_service_key([*traffic_candidates, *hotspot_candidates])
        if derived["unmapped"]:
            return explicit
        derived["source"] = "incident_context"
        derived["reason"] = ""
        return derived

    def _normalize_incident(self, incident: Incident) -> Incident:
        incident.evidence_refs = sort_incident_evidence(
            [
                normalize_incident_evidence(
                    item,
                    default_service_key=incident.service_key,
                    default_asset_ids=incident.related_asset_ids,
                )
                for item in incident.evidence_refs
            ]
        )
        return incident

    def _build_log_evidence_refs(
        self,
        traffic_summary: Dict[str, object],
        service_key: str,
        related_asset_ids: List[str],
    ) -> List[Dict[str, Any]]:
        candidates = traffic_summary.get("error_samples")
        if not isinstance(candidates, list) or not candidates:
            candidates = traffic_summary.get("records_sample")
        if not isinstance(candidates, list):
            return []

        evidence_refs: List[Dict[str, Any]] = []
        for item in candidates[:3]:
            if not isinstance(item, dict):
                continue
            evidence_refs.append(
                build_log_sample_evidence(
                    item,
                    service_key=service_key,
                    related_asset_ids=related_asset_ids,
                )
            )
        return evidence_refs

    def _build_alert_evidence_refs(
        self,
        active_alerts: List[Dict[str, Any]],
        service_key: str,
        related_asset_ids: List[str],
    ) -> List[Dict[str, Any]]:
        evidence_refs: List[Dict[str, Any]] = []
        for alert in active_alerts[:3]:
            if not isinstance(alert, dict):
                continue
            alert_service_key = str(alert.get("service_key") or "").strip()
            if alert_service_key and alert_service_key != service_key:
                continue
            evidence_refs.append(
                build_alert_evidence(
                    alert,
                    service_key=service_key,
                    related_asset_ids=related_asset_ids,
                )
            )
        return evidence_refs

    def _baseline_severity_rank(self, severity: str) -> int:
        if severity == "high":
            return 2
        if severity == "medium":
            return 1
        return 0

    def _coerce_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
