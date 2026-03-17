"""路由依赖。"""
from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any, List

from fastapi import HTTPException, Request

from engine.llm.config import get_llm_config_manager as build_llm_config_manager

_MAIN_FALLBACK_ATTRS: dict[str, str] = {
    "runtime_config": "config",
    "alert_store": "alert_store",
    "task_manager": "task_manager",
    "asset_service": "asset_service",
    "signal_service": "signal_service",
    "incident_service": "incident_service",
    "recommendation_service": "recommendation_service",
    "traffic_analytics_engine": "traffic_analytics_engine",
    "resource_analytics_engine": "resource_analytics_engine",
    "summary_builder": "summary_builder",
    "data_sources_status": "data_sources_status",
    "llm_config_manager": "llm_config_manager_instance",
    "ai_call_log_repository": "ai_call_log_repository",
    "recommendation_feedback_repository": "recommendation_feedback_repository",
    "usage_metrics_daily_repository": "usage_metrics_daily_repository",
    "llm_router": "llm_router_instance",
    "ai_provider_config_repository": "ai_provider_config_repository",
    "analysis_session_repository": "analysis_session_repository",
    "ai_writeback_repository": "ai_writeback_repository",
    "refresh_llm_router": "refresh_llm_router_from_db",
    "executor_service": "executor_service",
}


def _read_main_fallback(attr_name: str) -> Any | None:
    fallback_name = _MAIN_FALLBACK_ATTRS.get(attr_name)
    if not fallback_name:
        return None
    try:
        main_module = import_module("main")
    except Exception:  # noqa: BLE001
        return None
    return getattr(main_module, fallback_name, None)


def _get_state_component(request: Request | None, attr_name: str, *, required: bool = True) -> Any:
    """优先从 app.state 读取依赖，回退到 main 仅用于兼容旧测试与脚本。"""

    state = getattr(request.app, "state", None) if request is not None else None
    if state is not None and hasattr(state, attr_name):
        value = getattr(state, attr_name)
        if value is not None or not required:
            return value

    fallback_value = _read_main_fallback(attr_name)
    if fallback_value is not None or not required:
        return fallback_value

    raise HTTPException(status_code=503, detail=f"{attr_name} 尚未初始化")


def get_runtime_config(request: Request):
    return _get_state_component(request, "runtime_config")


def get_alert_store(request: Request):
    return _get_state_component(request, "alert_store")


def get_task_manager(request: Request):
    return _get_state_component(request, "task_manager")


def get_asset_service(request: Request):
    return _get_state_component(request, "asset_service")


def get_signal_service(request: Request):
    return _get_state_component(request, "signal_service")


def get_incident_service(request: Request):
    return _get_state_component(request, "incident_service")


def get_recommendation_service(request: Request):
    return _get_state_component(request, "recommendation_service")


def get_traffic_engine(request: Request):
    return _get_state_component(request, "traffic_analytics_engine")


def get_resource_engine(request: Request):
    return _get_state_component(request, "resource_analytics_engine")


def get_summary_builder(request: Request):
    return _get_state_component(request, "summary_builder")


def get_data_sources_status(request: Request) -> dict:
    return _get_state_component(request, "data_sources_status")


def get_llm_config_manager_dep(request: Request):
    manager = _get_state_component(request, "llm_config_manager", required=False)
    if manager:
        return manager

    cfg = get_runtime_config(request)
    config_dir = cfg.config_dir if cfg and cfg.config_dir else Path("config")
    return build_llm_config_manager(config_dir)


def get_ai_call_log_repository_dep(request: Request):
    return _get_state_component(request, "ai_call_log_repository", required=False)


def get_recommendation_feedback_repository_dep(request: Request):
    return _get_state_component(request, "recommendation_feedback_repository", required=False)


def get_usage_metrics_daily_repository_dep(request: Request):
    return _get_state_component(request, "usage_metrics_daily_repository", required=False)


def get_llm_router_dep(request: Request):
    return _get_state_component(request, "llm_router", required=False)


def get_ai_provider_config_repository_dep(request: Request):
    return _get_state_component(request, "ai_provider_config_repository", required=False)


def get_analysis_session_repository_dep(request: Request):
    return _get_state_component(request, "analysis_session_repository", required=False)


def get_ai_writeback_repository_dep(request: Request):
    return _get_state_component(request, "ai_writeback_repository", required=False)


def get_refresh_llm_router_dep(request: Request):
    return _get_state_component(request, "refresh_llm_router")


def get_executor_service_dep(request: Request):
    return _get_state_component(request, "executor_service", required=False)


def resolve_access_logs(request: Request | None = None) -> List[str]:
    cfg = get_runtime_config(request)
    configured = [item for item in cfg.access_log_path_list if Path(item).exists()]
    if configured:
        return configured
    if not cfg.raw_log_dir:
        return []
    return [str(path) for path in sorted(cfg.raw_log_dir.glob("*.log")) if path.is_file()]
