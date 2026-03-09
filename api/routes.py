"""
API 路由模块

提供 REST API 端点，直接调用能力实现。
"""
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel
from typing import Dict, Any, Optional, List

router = APIRouter()

# LLM 配置管理相关导入
from engine.llm.config import get_llm_config_manager, LLMProviderConfig, LLMProviderType
from engine.llm.client import LLMClient, LLMRouter


class DispatchRequest(BaseModel):
    """能力调用请求"""
    params: Dict[str, Any] = {}


def get_registry():
    """获取能力注册表（依赖注入）"""
    from main import capability_registry
    return capability_registry


def get_alert_store():
    """获取告警存储（依赖注入）"""
    from main import alert_store
    return alert_store


@router.get("/capabilities")
async def list_capabilities(registry=Depends(get_registry)) -> List[Dict[str, Any]]:
    """
    列出所有可用能力
    """
    return [
        {
            "name": cap.metadata.name,
            "description": cap.metadata.description,
            "tags": cap.metadata.tags,
            "requires_confirmation": cap.metadata.requires_confirmation,
            "schema": cap.to_openai_tool()
        }
        for cap in registry._capabilities.values()
    ]


@router.post("/capabilities/{name}/dispatch")
async def dispatch_capability(
    name: str,
    request: DispatchRequest,
    registry=Depends(get_registry)
) -> Dict[str, Any]:
    """
    调用指定能力

    Args:
        name: 能力名称
        request: 调用参数

    Returns:
        能力执行结果
    """
    cap = registry.get(name)
    if not cap:
        raise HTTPException(status_code=404, detail=f"能力 '{name}' 不存在")

    try:
        import asyncio
        result = await asyncio.wait_for(
            cap.dispatch(**request.params),
            timeout=60
        )
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts")
async def list_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 20,
    store=Depends(get_alert_store)
) -> Dict[str, Any]:
    """
    查询告警列表
    """
    alerts = await store.query_alerts(status=status, severity=severity, limit=limit)
    return {"alerts": alerts, "total": len(alerts)}


@router.post("/alerts/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    acknowledged_by: str = "user",
    store=Depends(get_alert_store)
) -> Dict[str, str]:
    """
    确认告警
    """
    success = await store.acknowledge_alert(alert_id, acknowledged_by)
    if success:
        return {"message": "告警已确认", "alert_id": alert_id}
    raise HTTPException(status_code=404, detail="告警不存在")


@router.post("/alerts/resolve")
async def resolve_alert(
    alert_id: str,
    resolved_by: str = "user",
    store=Depends(get_alert_store)
) -> Dict[str, str]:
    """
    解决告警
    """
    success = await store.resolve_alert(alert_id, resolved_by)
    if success:
        return {"message": "告警已解决", "alert_id": alert_id}
    raise HTTPException(status_code=404, detail="告警不存在")


@router.post("/alerts/rules")
async def create_alert_rule(
    rule_data: Dict[str, Any],
    store=Depends(get_alert_store)
) -> Dict[str, Any]:
    """
    创建告警规则

    Request Body:
        name: 规则名称
        metric: 监控指标
        threshold: 阈值
        operator: 比较运算符 (>, <, >=, <=, =)
        severity: 严重程度 (info, warning, critical)
    """
    rule_id = await store.create_rule(rule_data)
    return {"rule_id": rule_id, "message": "规则创建成功"}


@router.get("/alerts/rules")
async def list_alert_rules(store=Depends(get_alert_store)) -> Dict[str, Any]:
    """
    列出所有告警规则
    """
    rules = await store.get_rules()
    return {"rules": rules, "total": len(rules)}


@router.delete("/alerts/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: str,
    store=Depends(get_alert_store)
) -> Dict[str, str]:
    """
    删除告警规则
    """
    success = await store.delete_rule(rule_id)
    if success:
        return {"message": "规则已删除", "rule_id": rule_id}
    raise HTTPException(status_code=404, detail="规则不存在")


@router.get("/remediation/plans")
async def list_remediation_plans() -> List[Dict[str, Any]]:
    """
    列出所有修复预案
    """
    from engine.capabilities.remediation import RemediationPlan
    plan = RemediationPlan()
    return [
        {
            "plan_id": p["id"],
            "name": p["name"],
            "description": p["description"],
            "risk_level": p.get("risk_level", "medium")
        }
        for p in plan._REMEDIATION_PLANS.values()
    ]


@router.get("/remediation/plans/{plan_id}")
async def get_remediation_plan(plan_id: str) -> Dict[str, Any]:
    """
    获取修复预案详情
    """
    from engine.capabilities.remediation import RemediationPlan
    registry = RemediationPlan()
    for p in registry._REMEDIATION_PLANS.values():
        if p["id"] == plan_id:
            return p
    raise HTTPException(status_code=404, detail="预案不存在")


@router.post("/remediation/execute")
async def execute_remediation(
    plan_id: str,
    step_indices: List[int],
    dry_run: bool = True,
    container_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    执行修复预案

    Args:
        plan_id: 预案 ID
        step_indices: 要执行的步骤索引列表
        dry_run: 是否预演模式
        container_name: 容器名称（如需要）
    """
    from engine.capabilities.execute_remediation import ExecuteRemediation
    import asyncio

    executor = ExecuteRemediation()
    result = await asyncio.wait_for(
        executor.dispatch(
            plan_id=plan_id,
            step_indices=step_indices,
            dry_run=dry_run,
            container_name=container_name
        ),
        timeout=120
    )
    return result.to_dict()


@router.get("/containers")
async def list_containers() -> Dict[str, Any]:
    """
    列出所有 Docker 容器
    """
    from engine.capabilities.container_inspector import ContainerInspector

    inspector = ContainerInspector()
    result = inspector.list_containers(all=True)
    return result.to_dict()


@router.get("/containers/{name}")
async def get_container(name: str) -> Dict[str, Any]:
    """
    获取容器详情
    """
    from engine.capabilities.container_inspector import ContainerInspector
    import asyncio

    inspector = ContainerInspector()
    result = await asyncio.wait_for(inspector.dispatch(
        container_name=name,
        include_logs=False
    ), timeout=30)
    return result.to_dict()


@router.get("/containers/{name}/logs")
async def get_container_logs(name: str, lines: int = 50) -> Dict[str, Any]:
    """
    获取容器日志
    """
    from engine.capabilities.container_inspector import ContainerInspector
    import asyncio

    inspector = ContainerInspector()
    result = await asyncio.wait_for(inspector.dispatch(
        container_name=name,
        include_logs=True,
        log_lines=lines
    ), timeout=30)
    return result.to_dict()


@router.get("/host/metrics")
async def get_host_metrics() -> Dict[str, Any]:
    """
    获取主机资源指标
    """
    from engine.capabilities.host_monitor import HostMonitor

    monitor = HostMonitor()
    result = await asyncio.wait_for(monitor.dispatch(
        metrics=["cpu", "memory", "disk", "network"]
    ), timeout=30)
    return result.to_dict()


@router.get("/diagnose")
async def diagnose_system() -> Dict[str, Any]:
    """
    系统诊断端点

    返回系统详细信息，包括：
    - 主机资源状态
    - 活动告警数量
    - 告警规则数量
    - Docker 容器状态
    """
    import psutil
    from engine.capabilities.container_inspector import ContainerInspector
    from engine.storage.alert_store import AlertStore
    from main import alert_store

    # 主机资源
    cpu_percent = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('C:/')

    # 容器状态
    container_status = "unavailable"
    container_count = 0
    try:
        inspector = ContainerInspector()
        if inspector._is_docker_available():
            container_status = "available"
            result = inspector.list_containers(all=True)
            if result.success:
                container_count = result.data.get('total', 0)
    except Exception:
        pass

    # 告警统计
    active_alerts = 0
    rules_count = 0
    if alert_store:
        alerts = await alert_store.query_alerts(status="active", limit=1)
        active_alerts = len(alerts)
        rules = await alert_store.get_rules()
        rules_count = len(rules)

    return {
        "system": {
            "cpu_usage": cpu_percent,
            "memory_usage": memory.percent,
            "memory_available_mb": round(memory.available / 1024 / 1024, 1),
            "disk_usage": disk.percent,
            "disk_free_gb": round(disk.free / 1024 / 1024 / 1024, 1),
        },
        "services": {
            "docker": {
                "status": container_status,
                "containers": container_count,
            },
            "alerts": {
                "active": active_alerts,
                "rules": rules_count,
            },
        },
        "timestamp": psutil.boot_time(),
    }


@router.post("/logs/analyze")
async def analyze_logs(
    log_path: str,
    lines: int = 1000,
    level: Optional[str] = None,
    pattern: Optional[str] = None
) -> Dict[str, Any]:
    """
    分析日志文件

    Args:
        log_path: 日志文件路径
        lines: 读取行数
        level: 日志级别过滤
        pattern: 正则过滤模式

    Returns:
        分析结果
    """
    from engine.capabilities.log_analyzer import LogAnalyzer
    import asyncio

    analyzer = LogAnalyzer()
    result = await asyncio.wait_for(analyzer.dispatch(
        log_path=log_path,
        lines=lines,
        level=level,
        pattern=pattern
    ), timeout=60)
    return result.to_dict()


@router.get("/logs/scan")
async def scan_log_directory(
    log_dir: str = ".",
    file_pattern: str = "*.log"
) -> Dict[str, Any]:
    """
    扫描日志目录

    Returns:
        日志文件列表
    """
    from engine.capabilities.log_analyzer import ScanLogDirectory
    import asyncio

    scanner = ScanLogDirectory()
    result = await asyncio.wait_for(scanner.dispatch(
        log_dir=log_dir,
        file_pattern=file_pattern
    ), timeout=30)
    return result.to_dict()


@router.post("/k8s/generate")
async def generate_k8s_yaml(
    app_name: str,
    image: str,
    replicas: int = 1,
    port: int = 80,
    cpu_request: str = "100m",
    memory_request: str = "128Mi",
    cpu_limit: str = "500m",
    memory_limit: str = "512Mi"
) -> Dict[str, Any]:
    """
    生成 K8s Deployment 和 Service YAML

    Args:
        app_name: 应用名称
        image: 容器镜像
        replicas: 副本数
        port: 容器端口
        cpu_request: CPU 请求
        memory_request: 内存请求
        cpu_limit: CPU 限制
        memory_limit: 内存限制

    Returns:
        YAML 配置
    """
    from engine.capabilities.k8s_yaml_generator import K8sYamlGenerator
    import asyncio

    generator = K8sYamlGenerator()
    result = await asyncio.wait_for(generator.dispatch(
        app_name=app_name,
        image=image,
        replicas=replicas,
        port=port,
        cpu_request=cpu_request,
        memory_request=memory_request,
        cpu_limit=cpu_limit,
        memory_limit=memory_limit
    ), timeout=30)
    return result.to_dict()


@router.post("/k8s/configmap")
async def generate_k8s_configmap(
    app_name: str,
    env_vars: Dict[str, str]
) -> Dict[str, Any]:
    """
    生成 K8s ConfigMap YAML

    Args:
        app_name: 配置名称
        env_vars: 配置数据

    Returns:
        ConfigMap YAML
    """
    from engine.capabilities.k8s_yaml_generator import K8sConfigMapGenerator
    import asyncio

    generator = K8sConfigMapGenerator()
    result = await asyncio.wait_for(generator.dispatch(
        app_name=app_name,
        env_vars=env_vars
    ), timeout=15)
    return result.to_dict()


@router.post("/k8s/ingress")
async def generate_k8s_ingress(
    name: str,
    host: str,
    service_name: str,
    service_port: int = 80,
    path: str = "/",
    ingress_class: str = "nginx",
    tls_secret: Optional[str] = None
) -> Dict[str, Any]:
    """
    生成 K8s Ingress YAML

    Args:
        name: Ingress 名称
        host: 域名
        service_name: 后端服务名称
        service_port: 后端服务端口
        path: 路径
        ingress_class: Ingress 类型
        tls_secret: TLS 密钥名称

    Returns:
        Ingress YAML
    """
    from engine.capabilities.k8s_yaml_generator import K8sIngressGenerator
    import asyncio

    generator = K8sIngressGenerator()
    result = await asyncio.wait_for(generator.dispatch(
        name=name,
        host=host,
        service_name=service_name,
        service_port=service_port,
        path=path,
        ingress_class=ingress_class,
        tls_secret=tls_secret
    ), timeout=15)
    return result.to_dict()


# ========== LLM 配置管理端点 ==========

@router.get("/llm/providers")
async def list_llm_providers() -> Dict[str, Any]:
    """
    列出所有 LLM Provider 配置
    """
    config_manager = get_llm_config_manager()
    config = config_manager.load_config()

    providers = []
    for p in config.providers:
        providers.append({
            "name": p.name,
            "type": p.provider_type.value,
            "model": p.model,
            "base_url": p.base_url,
            "enabled": p.enabled,
            "timeout": p.timeout,
            "api_key_configured": bool(p.api_key)
        })

    return {
        "providers": providers,
        "default_provider": config.default_provider,
        "total": len(providers)
    }


@router.get("/llm/providers/{provider_name}")
async def get_llm_provider(provider_name: str) -> Dict[str, Any]:
    """
    获取指定 LLM Provider 配置详情
    """
    config_manager = get_llm_config_manager()
    config = config_manager.load_config()

    provider = config.get_provider(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")

    return {
        "name": provider.name,
        "type": provider.provider_type.value,
        "model": provider.model,
        "base_url": provider.base_url,
        "enabled": provider.enabled,
        "timeout": provider.timeout,
        "max_retries": provider.max_retries,
        "api_key_configured": bool(provider.api_key)
    }


@router.post("/llm/providers")
async def create_llm_provider(provider_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    创建新的 LLM Provider

    Request Body:
        name: Provider 名称
        type: Provider 类型 (openai, anthropic, custom)
        api_key: API Key
        model: 模型名称
        base_url: API 基础 URL（可选，OpenAI 兼容需要）
        enabled: 是否启用（默认 true）
        timeout: 超时时间（默认 30 秒）
    """
    config_manager = get_llm_config_manager()

    try:
        provider = LLMProviderConfig(
            name=provider_data.get("name"),
            provider_type=LLMProviderType(provider_data.get("type", "custom")),
            api_key=provider_data.get("api_key", ""),
            model=provider_data.get("model"),
            base_url=provider_data.get("base_url"),
            enabled=provider_data.get("enabled", True),
            timeout=provider_data.get("timeout", 30),
            max_retries=provider_data.get("max_retries", 2)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    success = config_manager.add_provider(provider)
    if success:
        return {"message": f"Provider '{provider.name}' 创建成功", "name": provider.name}
    else:
        raise HTTPException(status_code=400, detail=f"Provider '{provider.name}' 已存在")


@router.put("/llm/providers/{provider_name}")
async def update_llm_provider(
    provider_name: str,
    updates: Dict[str, Any]
) -> Dict[str, Any]:
    """
    更新 LLM Provider 配置

    Request Body:
        api_key: API Key（可选，更新时提供）
        model: 模型名称（可选）
        base_url: API 基础 URL（可选）
        enabled: 是否启用（可选）
        timeout: 超时时间（可选）
    """
    config_manager = get_llm_config_manager()

    # 只允许更新特定字段
    allowed_fields = ["api_key", "model", "base_url", "enabled", "timeout", "max_retries"]
    filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}

    success = config_manager.update_provider(provider_name, filtered_updates)
    if success:
        return {"message": f"Provider '{provider_name}' 更新成功"}
    else:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")


@router.delete("/llm/providers/{provider_name}")
async def delete_llm_provider(provider_name: str) -> Dict[str, str]:
    """
    删除 LLM Provider 配置
    """
    config_manager = get_llm_config_manager()

    if provider_name in ["openai", "anthropic"] and config_manager.load_config().get_provider(provider_name):
        # 内置 Provider 不建议删除，改为禁用
        config_manager.update_provider(provider_name, {"enabled": False})
        return {"message": f"Provider '{provider_name}' 已禁用（内置 Provider 不建议删除）"}

    success = config_manager.remove_provider(provider_name)
    if success:
        return {"message": f"Provider '{provider_name}' 已删除"}
    else:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")


@router.post("/llm/providers/{provider_name}/test")
async def test_llm_provider(provider_name: str) -> Dict[str, Any]:
    """
    测试 LLM Provider 连接

    发送一个简单的测试请求，验证 API Key 和配置是否正确
    """
    config_manager = get_llm_config_manager()
    config = config_manager.load_config()

    provider = config.get_provider(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")

    if not provider.api_key:
        raise HTTPException(status_code=400, detail="API Key 未配置")

    # 创建临时客户端进行测试
    from engine.llm.client import LLMClient

    client = LLMClient(provider)

    try:
        import asyncio
        response = await asyncio.wait_for(
            client.chat(
                messages=[{"role": "user", "content": "Hello, this is a test message."}],
                max_tokens=50
            ),
            timeout=30
        )
        return {
            "status": "success",
            "message": "连接测试成功",
            "response_preview": response[:200] if len(response) > 200 else response
        }
    except Exception as e:
        return {
            "status": "failed",
            "message": f"连接测试失败：{str(e)}"
        }


@router.post("/llm/default-provider")
async def set_default_llm_provider(data: Dict[str, str]) -> Dict[str, Any]:
    """
    设置默认 LLM Provider
    """
    config_manager = get_llm_config_manager()

    provider_name = data.get("provider_name")
    if not provider_name:
        raise HTTPException(status_code=400, detail="缺少 provider_name 参数")

    success = config_manager.set_default_provider(provider_name)
    if success:
        return {"message": f"默认 Provider 已设置为 '{provider_name}'"}
    else:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")


@router.post("/llm/analyze")
async def llm_analyze(
    messages: List[Dict[str, str]] = Body(..., description="消息列表"),
    provider: Optional[str] = Body(default=None, description="指定 Provider"),
    temperature: float = Body(default=0.7, description="温度参数"),
    max_tokens: int = Body(default=2000, description="最大 token 数")
) -> Dict[str, Any]:
    """
    直接使用 LLM 进行分析

    Request Body:
        messages: 消息列表 [{"role": "user", "content": "..."}]
        provider: 指定 Provider（可选，默认使用默认 Provider）
        temperature: 温度参数（可选）
        max_tokens: 最大 token 数（可选）

    Returns:
        LLM 响应内容
    """
    config_manager = get_llm_config_manager()
    config = config_manager.load_config()

    # 构建路由器
    llm_clients = {}
    for p in config.get_enabled_providers():
        llm_clients[p.name] = LLMClient(p)

    if not llm_clients:
        raise HTTPException(status_code=500, detail="没有可用的 LLM Provider")

    router = LLMRouter(llm_clients, config.default_provider)

    try:
        import asyncio
        response = await asyncio.wait_for(
            router.chat(messages, provider=provider, temperature=temperature, max_tokens=max_tokens),
            timeout=60
        )
        return {
            "content": response,
            "provider": provider or config.default_provider
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 调用失败：{str(e)}")
