"""
opsMind - 智能运维助手

主程序入口
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from settings import RuntimeConfig
from engine.capabilities.base import CapabilityRegistry
from engine.capabilities.host_monitor import HostMonitor
from engine.capabilities.alert_manager import AlertManager
from engine.capabilities.remediation import RemediationPlan
from engine.capabilities.execute_remediation import ExecuteRemediation
from engine.capabilities.container_inspector import ContainerInspector
from engine.capabilities.log_analyzer import LogAnalyzer, ScanLogDirectory
from engine.capabilities.k8s_yaml_generator import K8sYamlGenerator, K8sConfigMapGenerator, K8sIngressGenerator
from engine.storage.alert_store import AlertStore
from engine.tasks import BackgroundTaskManager

# 导入 API 路由
from api import routes

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# 全局变量
config: RuntimeConfig
capability_registry: CapabilityRegistry
alert_store: AlertStore
background_task_manager: BackgroundTaskManager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    应用生命周期管理

    负责初始化和清理资源。
    """
    global config, capability_registry, alert_store

    # ========== 启动时初始化 ==========
    logger.info("正在启动 opsMind...")

    # 加载配置
    config = RuntimeConfig.load_from_env()
    logger.info(f"配置已加载：app_name={config.app_name}, port={config.port}")

    # 验证配置
    errors = config.validate()
    if errors:
        for error in errors:
            logger.warning(f"配置警告：{error}")

    # 确保目录存在
    config.ensure_directories()
    logger.info("数据目录已准备")

    # 初始化能力注册表
    capability_registry = CapabilityRegistry()
    logger.info("能力注册表已初始化")

    # 初始化告警存储
    alert_store = AlertStore(config.data_dir / "alerts")
    await alert_store.initialize()
    logger.info("告警存储已初始化")

    # 注册内置能力
    capability_registry.register(HostMonitor())
    logger.info("已注册能力：inspect_host")

    capability_registry.register(AlertManager(alert_store))
    logger.info("已注册能力：manage_alerts")

    capability_registry.register(RemediationPlan())
    logger.info("已注册能力：get_remediation_plan")

    capability_registry.register(ExecuteRemediation())
    logger.info("已注册能力：execute_remediation")

    capability_registry.register(ContainerInspector())
    logger.info("已注册能力：inspect_container")

    # 注册 API 路由
    app.include_router(routes.router, prefix="/api")

    # 启动后台任务
    background_task_manager = BackgroundTaskManager(alert_store)
    await background_task_manager.start()
    logger.info("后台任务已启动")

    logger.info("opsMind 启动完成")

    yield

    # ========== 关闭时清理 ==========
    logger.info("正在关闭 opsMind...")

    # 停止后台任务
    if background_task_manager:
        await background_task_manager.stop()

    logger.info("opsMind 已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="opsMind",
    description="智能运维助手 - 可控、可追溯的运维诊断与告警管理",
    version="0.1.0",
    lifespan=lifespan
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict:
    """
    根路径

    Returns:
        应用信息
    """
    return {
        "name": "opsMind",
        "version": "0.1.0",
        "description": "智能运维助手"
    }


@app.get("/health")
async def health_check() -> dict:
    """
    健康检查端点

    Returns:
        健康状态
    """
    return {
        "status": "healthy",
        "version": "0.1.0"
    }


@app.get("/api/capabilities")
async def list_capabilities() -> list:
    """
    列出所有已注册的能力

    Returns:
        能力列表
    """
    return [
        {
            "name": cap.metadata.name,
            "description": cap.metadata.description,
            "tags": cap.metadata.tags,
            "requires_confirmation": cap.metadata.requires_confirmation
        }
        for cap in capability_registry._capabilities.values()
    ]


@app.get("/api/capabilities/{name}/schema")
async def get_capability_schema(name: str) -> dict:
    """
    获取能力的 OpenAI Tool 定义

    Args:
        name: 能力名称

    Returns:
        Tool 定义
    """
    cap = capability_registry.get(name)
    if not cap:
        return {"error": f"能力 '{name}' 不存在"}
    return cap.to_openai_tool()


# 导入路由（后续创建）
# from api import routes
# app.include_router(routes.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=config.host,
        port=config.port,
        reload=config.debug
    )
