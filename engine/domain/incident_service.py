"""
Incident 服务。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from engine.analytics.correlation_engine import CorrelationEngine
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
        correlated = self.correlation_engine.analyze(
            service_key=service_key,
            traffic_summary=traffic_summary,
            resource_summary=resource_summary,
            related_asset_ids=related_asset_ids,
        )
        incident = Incident(
            title=correlated["title"],
            severity=correlated["severity"],
            service_key=service_key,
            time_window_start=correlated["time_window_start"],
            time_window_end=correlated["time_window_end"],
            related_asset_ids=related_asset_ids,
            evidence_refs=correlated["evidence_refs"],
            summary=correlated["summary"],
            confidence=correlated["confidence"],
            recommended_actions=correlated["recommended_actions"],
            reasoning_tags=correlated["reasoning_tags"],
        )
        return self.incident_repository.save(incident)
