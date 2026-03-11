"""opsMind 服务入口。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import legacy_routes, websocket
from api.routes import router as aggregate_router
from engine.analytics.correlation_engine import CorrelationEngine
from engine.analytics.resource_analytics import ResourceAnalyticsEngine
from engine.analytics.summary_builder import SummaryBuilder
from engine.analytics.traffic_analytics import TrafficAnalyticsEngine
from engine.capabilities.alert_manager import AlertManager
from engine.capabilities.base import CapabilityRegistry
from engine.capabilities.container_inspector import ContainerInspector
from engine.capabilities.execute_remediation import ExecuteRemediation
from engine.capabilities.host_monitor import HostMonitor
from engine.capabilities.k8s_yaml_generator import K8sConfigMapGenerator, K8sIngressGenerator, K8sYamlGenerator
from engine.capabilities.log_analyzer import LogAnalyzer, ScanLogDirectory
from engine.capabilities.notification import (
    AlertNotificationManager,
    SendDingTalkNotification,
    SendEmailNotification,
    SendSlackNotification,
    SendWeComNotification,
)
from engine.capabilities.remediation import RemediationPlan
from engine.capabilities.smart_alert import AlertAggregator, AlertDeduplicator, RootCauseAnalyzer, SmartAlertEngine
from engine.domain.asset_service import AssetService
from engine.domain.incident_service import IncidentService
from engine.domain.recommendation_service import RecommendationService
from engine.domain.signal_service import SignalService
from engine.llm.client import LLMClient, LLMRouter
from engine.llm.config import get_llm_config_manager
from engine.operations.incident_reporter import IncidentReporter
from engine.operations.skill_orchestrator import SkillOrchestrator
from engine.runtime.artifact_store import ArtifactStore
from engine.runtime.event_bus import EventBus
from engine.runtime.task_manager import TaskManager
from engine.runtime.trace_store import TraceStore
from engine.storage.alert_store import AlertStore
from engine.storage.repositories import (
    ArtifactRepository,
    AssetRepository,
    IncidentRepository,
    RecommendationRepository,
    SignalRepository,
    TaskRepository,
)
from engine.storage.sqlite import SQLiteDatabase
from engine.tasks import BackgroundTaskManager
from settings import RuntimeConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

config: RuntimeConfig | None = None
capability_registry: CapabilityRegistry | None = None
alert_store: AlertStore | None = None
background_task_manager: BackgroundTaskManager | None = None
alert_notifier: websocket.AlertNotifier | None = None
runtime_db: SQLiteDatabase | None = None
event_bus: EventBus | None = None
task_manager: TaskManager | None = None
asset_service: AssetService | None = None
signal_service: SignalService | None = None
incident_service: IncidentService | None = None
recommendation_service: RecommendationService | None = None
traffic_analytics_engine: TrafficAnalyticsEngine | None = None
resource_analytics_engine: ResourceAnalyticsEngine | None = None
summary_builder: SummaryBuilder | None = None
data_sources_status: dict[str, Any] = {}


def _build_data_sources_status(runtime_config: RuntimeConfig) -> dict[str, Any]:
    raw_logs = []
    if runtime_config.raw_log_dir:
        raw_logs = [item for item in runtime_config.raw_log_dir.glob("*.log") if item.is_file()]
    access_logs = runtime_config.access_log_path_list
    return {
        "docker": {
            "enabled": "docker" in runtime_config.enabled_data_sources,
            "configured": bool(runtime_config.docker_host),
        },
        "prometheus": {
            "enabled": "prometheus" in runtime_config.enabled_data_sources,
            "configured": bool(runtime_config.prometheus_url),
            "base_url": runtime_config.prometheus_url or "",
        },
        "logs": {
            "enabled": True,
            "configured": bool(access_logs or raw_logs),
            "configured_paths": access_logs,
            "discovered_files": [str(path) for path in raw_logs],
        },
        "alerts": {
            "enabled": True,
            "configured": True,
        },
    }


def _register_capabilities(registry: CapabilityRegistry, current_alert_store: AlertStore, llm_router: LLMRouter | None) -> None:
    registry.register(HostMonitor())
    registry.register(AlertManager(current_alert_store))
    registry.register(RemediationPlan())
    registry.register(ExecuteRemediation())
    registry.register(ContainerInspector())
    registry.register(LogAnalyzer())
    registry.register(ScanLogDirectory())
    registry.register(K8sYamlGenerator())
    registry.register(K8sConfigMapGenerator())
    registry.register(K8sIngressGenerator())
    registry.register(SendEmailNotification())
    registry.register(SendDingTalkNotification())
    registry.register(SendWeComNotification())
    registry.register(SendSlackNotification())
    registry.register(AlertNotificationManager())
    registry.register(AlertAggregator())
    registry.register(AlertDeduplicator())
    registry.register(RootCauseAnalyzer(llm_router))
    registry.register(SmartAlertEngine())
    registry.register(IncidentReporter())
    registry.register(SkillOrchestrator())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global config, capability_registry, alert_store, background_task_manager, alert_notifier
    global runtime_db, event_bus, task_manager, asset_service, signal_service
    global incident_service, recommendation_service, traffic_analytics_engine, resource_analytics_engine, summary_builder, data_sources_status

    logger.info("正在启动 opsMind")
    config = RuntimeConfig.load_from_env()
    config.ensure_directories()
    for error in config.validate():
        logger.warning("配置警告：%s", error)

    llm_config_manager = get_llm_config_manager(config.config_dir or Path("config"))
    llm_config = llm_config_manager.load_config()
    llm_clients = {
        provider_config.name: LLMClient(provider_config)
        for provider_config in llm_config.get_enabled_providers()
    }
    llm_router = LLMRouter(llm_clients, llm_config.default_provider) if llm_clients else None

    capability_registry = CapabilityRegistry()
    alert_store = AlertStore((config.data_dir or config.base_dir / "data") / "alerts")
    await alert_store.initialize()
    _register_capabilities(capability_registry, alert_store, llm_router)

    runtime_db = SQLiteDatabase(config.sqlite_path or (config.data_dir or config.base_dir / "data") / "opsmind.db")
    runtime_db.initialize()
    task_repository = TaskRepository(runtime_db)
    artifact_repository = ArtifactRepository(runtime_db)
    asset_repository = AssetRepository(runtime_db)
    signal_repository = SignalRepository(runtime_db)
    incident_repository = IncidentRepository(runtime_db)
    recommendation_repository = RecommendationRepository(runtime_db)

    event_bus = EventBus()
    trace_store = TraceStore(config.tasks_dir or (config.data_dir or config.base_dir / "data") / "tasks")
    artifact_store = ArtifactStore(config.tasks_dir or (config.data_dir or config.base_dir / "data") / "tasks")
    task_manager = TaskManager(task_repository, artifact_repository, trace_store, artifact_store, event_bus)

    asset_service = AssetService(asset_repository, config.docker_host)
    signal_service = SignalService(signal_repository)
    incident_service = IncidentService(incident_repository, CorrelationEngine())
    recommendation_service = RecommendationService(recommendation_repository, artifact_store)
    traffic_analytics_engine = TrafficAnalyticsEngine(config.raw_log_dir or (config.data_dir or config.base_dir / "data") / "raw_logs")
    resource_analytics_engine = ResourceAnalyticsEngine(config.docker_host, config.prometheus_url, config.prometheus_api_key)
    summary_builder = SummaryBuilder()
    data_sources_status = _build_data_sources_status(config)

    app.state.runtime_config = config
    app.state.capability_registry = capability_registry
    app.state.alert_store = alert_store
    app.state.task_manager = task_manager
    app.state.asset_service = asset_service
    app.state.signal_service = signal_service
    app.state.incident_service = incident_service
    app.state.recommendation_service = recommendation_service
    app.state.traffic_analytics_engine = traffic_analytics_engine
    app.state.resource_analytics_engine = resource_analytics_engine
    app.state.summary_builder = summary_builder
    app.state.data_sources_status = data_sources_status

    websocket.bind_event_bus(event_bus)
    background_task_manager = BackgroundTaskManager(alert_store)
    await background_task_manager.start()
    alert_notifier = websocket.AlertNotifier(alert_store, check_interval=5)
    await alert_notifier.start()

    logger.info("opsMind 启动完成")
    try:
        yield
    finally:
        logger.info("正在关闭 opsMind")
        if background_task_manager:
            await background_task_manager.stop()
        if alert_notifier:
            await alert_notifier.stop()
        logger.info("opsMind 已关闭")


app = FastAPI(
    title="opsMind",
    description="智能运维助手",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(legacy_routes.router, prefix="/api")
app.include_router(aggregate_router, prefix="/api")
app.include_router(websocket.router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "opsMind", "version": "0.1.0", "description": "智能运维助手"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/api/capabilities/{name}/schema")
async def get_capability_schema(name: str) -> dict[str, Any]:
    if not capability_registry:
        return {"error": "能力注册表尚未初始化"}
    cap = capability_registry.get(name)
    if not cap:
        return {"error": f"能力 '{name}' 不存在"}
    return cap.to_openai_tool()


if __name__ == "__main__":
    import uvicorn

    runtime_config = RuntimeConfig.load_from_env()
    uvicorn.run("main:app", host=runtime_config.host, port=runtime_config.port, reload=runtime_config.debug)
