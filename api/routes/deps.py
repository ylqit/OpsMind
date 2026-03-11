"""路由依赖。"""
from __future__ import annotations

from pathlib import Path
from typing import List


def get_runtime_config():
    from main import config
    return config


def get_alert_store():
    from main import alert_store
    return alert_store


def get_task_manager():
    from main import task_manager
    return task_manager


def get_asset_service():
    from main import asset_service
    return asset_service


def get_signal_service():
    from main import signal_service
    return signal_service


def get_incident_service():
    from main import incident_service
    return incident_service


def get_recommendation_service():
    from main import recommendation_service
    return recommendation_service


def get_traffic_engine():
    from main import traffic_analytics_engine
    return traffic_analytics_engine


def get_resource_engine():
    from main import resource_analytics_engine
    return resource_analytics_engine


def get_summary_builder():
    from main import summary_builder
    return summary_builder


def get_data_sources_status() -> dict:
    from main import data_sources_status
    return data_sources_status


def resolve_access_logs() -> List[str]:
    cfg = get_runtime_config()
    configured = [item for item in cfg.access_log_path_list if Path(item).exists()]
    if configured:
        return configured
    if not cfg.raw_log_dir:
        return []
    return [str(path) for path in sorted(cfg.raw_log_dir.glob("*.log")) if path.is_file()]
