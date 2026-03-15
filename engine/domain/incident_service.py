"""
Incident 服务。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from engine.analytics.correlation_engine import CorrelationEngine
from engine.domain.service_key_resolver import pick_best_service_key, resolve_explicit_service_key
from engine.runtime.models import Incident
from engine.storage.repositories import IncidentRepository


class IncidentService:
    """Incident 聚合与持久化服务。"""

    def __init__(self, incident_repository: IncidentRepository, correlation_engine: CorrelationEngine):
        self.incident_repository = incident_repository
        self.correlation_engine = correlation_engine

    def list_incidents(self, status: Optional[str] = None, severity: Optional[str] = None, service_key: Optional[str] = None) -> List[Incident]:
        return self.incident_repository.list(status=status, severity=severity, service_key=service_key)

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        return self.incident_repository.get(incident_id)

    def build_incident(self, service_key: str, traffic_summary: Dict[str, object], resource_summary: Dict[str, object], related_asset_ids: List[str]) -> Incident:
        alignment = self._resolve_incident_service_key(service_key, traffic_summary, resource_summary)
        resolved_service_key = alignment["service_key"]
        correlated = self.correlation_engine.analyze(
            service_key=resolved_service_key,
            traffic_summary=traffic_summary,
            resource_summary=resource_summary,
            related_asset_ids=related_asset_ids,
        )
        evidence_refs = list(correlated["evidence_refs"])
        if alignment["unmapped"]:
            evidence_refs.append(
                {
                    "layer": "diagnosis",
                    "type": "service_key_alignment",
                    "title": "service_key 对齐不足",
                    "summary": f"当前 service_key 仍为 {resolved_service_key}，存在未完全对齐风险。",
                    "metric": "service_key_alignment",
                    "value": alignment.get("reason") or "unmapped",
                    "unit": "",
                    "priority": 78,
                    "signal_strength": "medium",
                    "alignment": alignment,
                }
            )
        elif alignment["source"] != "explicit":
            evidence_refs.append(
                {
                    "layer": "diagnosis",
                    "type": "service_key_alignment",
                    "title": "service_key 已自动回补",
                    "summary": f"本次 incident 使用 {resolved_service_key} 作为统一关联键。",
                    "metric": "service_key_alignment",
                    "value": alignment["source"],
                    "unit": "",
                    "priority": 74,
                    "signal_strength": "medium",
                    "alignment": alignment,
                }
            )
        incident = Incident(
            title=correlated["title"],
            severity=correlated["severity"],
            service_key=resolved_service_key,
            time_window_start=correlated["time_window_start"],
            time_window_end=correlated["time_window_end"],
            related_asset_ids=related_asset_ids,
            evidence_refs=evidence_refs,
            summary=correlated["summary"],
            confidence=correlated["confidence"],
            recommended_actions=correlated["recommended_actions"],
            reasoning_tags=correlated["reasoning_tags"],
        )
        return self.incident_repository.save(incident)

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
