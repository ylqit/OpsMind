"""路由依赖。"""
from __future__ import annotations

from pathlib import Path
from typing import List

from engine.llm.config import get_llm_config_manager as build_llm_config_manager


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


def get_llm_config_manager_dep():
    from main import config, llm_config_manager_instance

    if llm_config_manager_instance:
        return llm_config_manager_instance

    cfg = config
    config_dir = cfg.config_dir if cfg and cfg.config_dir else Path("config")
    return build_llm_config_manager(config_dir)


def get_ai_call_log_repository_dep():
    from main import ai_call_log_repository
    return ai_call_log_repository


def get_recommendation_feedback_repository_dep():
    from main import recommendation_feedback_repository
    return recommendation_feedback_repository


def get_usage_metrics_daily_repository_dep():
    from main import usage_metrics_daily_repository
    return usage_metrics_daily_repository


def get_llm_router_dep():
    from main import llm_router_instance
    return llm_router_instance


def get_ai_provider_config_repository_dep():
    from main import ai_provider_config_repository
    return ai_provider_config_repository


def get_analysis_session_repository_dep():
    from main import analysis_session_repository
    return analysis_session_repository


def get_refresh_llm_router_dep():
    from main import refresh_llm_router_from_db
    return refresh_llm_router_from_db


def get_executor_service_dep():
    from main import executor_service
    return executor_service


def resolve_access_logs() -> List[str]:
    cfg = get_runtime_config()
    configured = [item for item in cfg.access_log_path_list if Path(item).exists()]
    if configured:
        return configured
    if not cfg.raw_log_dir:
        return []
    return [str(path) for path in sorted(cfg.raw_log_dir.glob("*.log")) if path.is_file()]
