"""
信号服务。

负责把告警、日志和资源摘要标准化为 Signal。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from engine.domain.service_key_resolver import merge_alignment, pick_best_service_key, resolve_explicit_service_key
from engine.runtime.models import Signal, SignalType
from engine.runtime.time_utils import utc_now
from engine.storage.repositories import SignalRepository


class SignalService:
    """统一信号写入入口。"""

    def __init__(self, signal_repository: SignalRepository):
        self.signal_repository = signal_repository

    def capture_alerts(self, alerts: Iterable[Dict[str, Any]], service_key: str, asset_id: Optional[str] = None) -> List[Signal]:
        results: List[Signal] = []
        for alert in alerts:
            alignment = self._resolve_alert_alignment(alert, service_key)
            signal = Signal(
                signal_type=SignalType.ALERT,
                asset_id=asset_id,
                service_key=alignment["service_key"],
                severity=alert.get("severity") or alert.get("level") or "warning",
                payload={**alert, "alignment": alignment},
                source="alert_store",
                timestamp=utc_now(),
            )
            self.signal_repository.save(signal)
            results.append(signal)
        return results

    def capture_log_summary(self, log_summary: Dict[str, Any], service_key: str, asset_id: Optional[str] = None) -> List[Signal]:
        alignment = self._resolve_log_alignment(log_summary, service_key)
        signal = Signal(
            signal_type=SignalType.LOG,
            asset_id=asset_id,
            service_key=alignment["service_key"],
            severity="warning" if float(log_summary.get("error_rate", 0.0)) >= 5 else "info",
            payload={**log_summary, "alignment": alignment},
            source="log_pipeline",
            timestamp=utc_now(),
        )
        self.signal_repository.save(signal)
        return [signal]

    def capture_resource_summary(self, resource_summary: Dict[str, Any], service_key: str, asset_id: Optional[str] = None) -> List[Signal]:
        alignment = self._resolve_resource_alignment(resource_summary, service_key)
        signal = Signal(
            signal_type=SignalType.METRIC,
            asset_id=asset_id,
            service_key=alignment["service_key"],
            severity="warning" if resource_summary.get("hotspots") else "info",
            payload={**resource_summary, "alignment": alignment},
            source="resource_analytics",
            timestamp=utc_now(),
        )
        self.signal_repository.save(signal)
        return [signal]

    def _resolve_alert_alignment(self, alert: Dict[str, Any], service_key: str) -> Dict[str, Any]:
        explicit = resolve_explicit_service_key(service_key)
        labels = alert.get("labels") if isinstance(alert.get("labels"), dict) else {}
        candidates = []
        if labels.get("namespace") and labels.get("service"):
            candidates.append(f"{labels.get('namespace')}/{labels.get('service')}")
        if explicit["unmapped"] and candidates:
            return merge_alignment(explicit, pick_best_service_key(candidates))
        return explicit

    def _resolve_log_alignment(self, log_summary: Dict[str, Any], service_key: str) -> Dict[str, Any]:
        explicit = resolve_explicit_service_key(service_key)
        if not explicit["unmapped"]:
            return explicit
        records = log_summary.get("records_sample") if isinstance(log_summary.get("records_sample"), list) else []
        candidates = [
            str(item.get("service_key") or "").strip()
            for item in records
            if isinstance(item, dict)
        ]
        derived = pick_best_service_key(candidates)
        derived["source"] = "log_records"
        return merge_alignment(explicit, derived)

    def _resolve_resource_alignment(self, resource_summary: Dict[str, Any], service_key: str) -> Dict[str, Any]:
        explicit = resolve_explicit_service_key(service_key)
        if not explicit["unmapped"]:
            return explicit
        hotspots = resource_summary.get("hotspots") if isinstance(resource_summary.get("hotspots"), list) else []
        candidates = [
            str(item.get("service_key") or "").strip()
            for item in hotspots
            if isinstance(item, dict) and str(item.get("service_key") or "").strip()
        ]
        derived = pick_best_service_key(candidates)
        derived["source"] = "resource_hotspots"
        return merge_alignment(explicit, derived)
