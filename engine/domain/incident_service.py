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
