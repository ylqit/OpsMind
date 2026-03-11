"""
信号服务。

负责把告警、日志和资源摘要标准化为 Signal。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from engine.runtime.models import Signal, SignalType
from engine.storage.repositories import SignalRepository


class SignalService:
    """统一信号写入入口。"""

    def __init__(self, signal_repository: SignalRepository):
        self.signal_repository = signal_repository

    def capture_alerts(self, alerts: Iterable[Dict[str, Any]], service_key: str, asset_id: Optional[str] = None) -> List[Signal]:
        results: List[Signal] = []
        for alert in alerts:
            signal = Signal(
                signal_type=SignalType.ALERT,
                asset_id=asset_id,
                service_key=service_key,
                severity=alert.get("severity") or alert.get("level") or "warning",
                payload=alert,
                source="alert_store",
                timestamp=datetime.utcnow(),
            )
            self.signal_repository.save(signal)
            results.append(signal)
        return results

    def capture_log_summary(self, log_summary: Dict[str, Any], service_key: str, asset_id: Optional[str] = None) -> List[Signal]:
        signal = Signal(
            signal_type=SignalType.LOG,
            asset_id=asset_id,
            service_key=service_key,
            severity="warning" if float(log_summary.get("error_rate", 0.0)) >= 5 else "info",
            payload=log_summary,
            source="log_pipeline",
            timestamp=datetime.utcnow(),
        )
        self.signal_repository.save(signal)
        return [signal]

    def capture_resource_summary(self, resource_summary: Dict[str, Any], service_key: str, asset_id: Optional[str] = None) -> List[Signal]:
        signal = Signal(
            signal_type=SignalType.METRIC,
            asset_id=asset_id,
            service_key=service_key,
            severity="warning" if resource_summary.get("hotspots") else "info",
            payload=resource_summary,
            source="resource_analytics",
            timestamp=datetime.utcnow(),
        )
        self.signal_repository.save(signal)
        return [signal]
