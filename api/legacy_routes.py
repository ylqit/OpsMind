"""
API 路由模块

提供 REST API 端点，直接调用能力实现。
"""
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel
from typing import Dict, Any, Optional, List

router = APIRouter()

# LLM 兼容路由相关导入
from engine.llm.config import LLMProviderType
from engine.runtime.models import AIProviderConfigRecord


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


def _get_ai_provider_repository():
    """获取统一 Provider 仓储。"""
    from main import ai_provider_config_repository
    return ai_provider_config_repository


def _get_ai_call_log_repository():
    """获取统一 AI 调用日志仓储。"""
    from main import ai_call_log_repository
    return ai_call_log_repository


def _refresh_llm_router() -> None:
    """刷新运行时 LLM 路由。"""
    from main import refresh_llm_router_from_db
    refresh_llm_router_from_db()


def _get_runtime_llm_router():
    """获取运行时路由实例。"""
    from main import llm_router_instance
    return llm_router_instance


def _serialize_legacy_provider(record) -> Dict[str, Any]:
    """统一序列化，兼容旧前端字段。"""
    return {
        "provider_id": record.provider_id,
        "name": record.name,
        "type": record.provider_type,
        "model": record.model,
        "base_url": record.base_url,
        "enabled": record.enabled,
        "timeout": record.timeout,
        "max_retries": record.max_retries,
        "api_key_configured": bool(record.api_key),
        "is_default": record.is_default,
    }


def _ensure_default_provider(provider_repository) -> None:
    """兼容路由下保持默认 Provider 可用。"""
    default_provider = provider_repository.get_default()
    if default_provider and default_provider.enabled:
        return

    enabled_items = provider_repository.list(enabled_only=True)
    if enabled_items:
        provider_repository.set_default(enabled_items[0].provider_id)


# ========== LLM 配置管理端点（兼容入口，内部统一走 /api/ai 数据源） ==========

@router.get("/llm/providers")
async def list_llm_providers() -> Dict[str, Any]:
    """列出 Provider（兼容路径，数据源与 /api/ai 一致）。"""
    provider_repository = _get_ai_provider_repository()
    if not provider_repository:
        return {
            "providers": [],
            "default_provider": "",
            "default_provider_id": "",
            "total": 0,
        }

    providers = provider_repository.list()
    default_provider = provider_repository.get_default()
    return {
        "providers": [_serialize_legacy_provider(item) for item in providers],
        "default_provider": default_provider.name if default_provider else "",
        "default_provider_id": default_provider.provider_id if default_provider else "",
        "total": len(providers),
    }


@router.get("/llm/call-logs")
async def list_llm_call_logs(
    provider_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """读取调用日志（兼容路径）。"""
    normalized_status = (status or "").strip().lower()
    if normalized_status and normalized_status not in {"success", "error"}:
        raise HTTPException(status_code=400, detail="status 仅支持 success 或 error")

    safe_limit = max(1, min(limit, 500))
    call_log_repository = _get_ai_call_log_repository()
    if not call_log_repository:
        return {
            "items": [],
            "total": 0,
            "provider_name": provider_name or "",
            "status": normalized_status,
            "limit": safe_limit,
        }

    logs = call_log_repository.list(
        provider_name=provider_name,
        status=normalized_status or None,
        limit=safe_limit,
    )
    return {
        "items": [item.model_dump(mode="json") for item in logs],
        "total": len(logs),
        "provider_name": provider_name or "",
        "status": normalized_status,
        "limit": safe_limit,
    }


@router.get("/llm/providers/{provider_name}")
async def get_llm_provider(provider_name: str) -> Dict[str, Any]:
    """读取单个 Provider（兼容路径）。"""
    provider_repository = _get_ai_provider_repository()
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    provider = provider_repository.get_by_name(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")

    return _serialize_legacy_provider(provider)


@router.post("/llm/providers")
async def create_llm_provider(provider_data: Dict[str, Any]) -> Dict[str, Any]:
    """新增 Provider（兼容路径）。"""
    provider_repository = _get_ai_provider_repository()
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    normalized_name = str(provider_data.get("name") or "").strip()
    normalized_model = str(provider_data.get("model") or "").strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Provider 名称不能为空")
    if not normalized_model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if provider_repository.get_by_name(normalized_name):
        raise HTTPException(status_code=409, detail=f"Provider '{normalized_name}' 已存在")

    try:
        provider_type = LLMProviderType(str(provider_data.get("type") or "custom")).value
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    enabled = bool(provider_data.get("enabled", True))
    is_default = bool(provider_data.get("is_default", False))
    if not provider_repository.get_default() and enabled:
        is_default = True
    if is_default and not enabled:
        raise HTTPException(status_code=400, detail="默认 Provider 必须处于启用状态")

    try:
        timeout = int(provider_data.get("timeout") or 30)
        max_retries = int(provider_data.get("max_retries") or 2)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="timeout 或 max_retries 参数不合法") from exc

    record = AIProviderConfigRecord(
        name=normalized_name,
        provider_type=provider_type,
        api_key=str(provider_data.get("api_key") or "").strip(),
        model=normalized_model,
        base_url=(str(provider_data.get("base_url") or "").strip() or None),
        enabled=enabled,
        is_default=is_default,
        timeout=timeout,
        max_retries=max_retries,
    )
    saved = provider_repository.save(record)
    _ensure_default_provider(provider_repository)
    _refresh_llm_router()

    latest = provider_repository.get(saved.provider_id)
    return {
        "message": f"Provider '{normalized_name}' 创建成功",
        "provider": _serialize_legacy_provider(latest or saved),
    }


@router.put("/llm/providers/{provider_name}")
async def update_llm_provider(
    provider_name: str,
    updates: Dict[str, Any]
) -> Dict[str, Any]:
    """更新 Provider（兼容路径）。"""
    provider_repository = _get_ai_provider_repository()
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    current = provider_repository.get_by_name(provider_name)
    if not current:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")

    mapped_updates: Dict[str, Any] = {}
    if updates.get("type") is not None:
        try:
            mapped_updates["provider_type"] = LLMProviderType(str(updates.get("type"))).value
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if updates.get("model") is not None:
        model_value = str(updates.get("model") or "").strip()
        if not model_value:
            raise HTTPException(status_code=400, detail="模型名称不能为空")
        mapped_updates["model"] = model_value

    if updates.get("base_url") is not None:
        mapped_updates["base_url"] = str(updates.get("base_url") or "").strip() or None

    if updates.get("enabled") is not None:
        enabled_value = bool(updates.get("enabled"))
        if current.is_default and not enabled_value:
            raise HTTPException(status_code=400, detail="默认 Provider 不能直接禁用，请先切换默认")
        mapped_updates["enabled"] = enabled_value

    if updates.get("timeout") is not None:
        try:
            mapped_updates["timeout"] = int(updates.get("timeout"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="timeout 参数不合法") from exc

    if updates.get("max_retries") is not None:
        try:
            mapped_updates["max_retries"] = int(updates.get("max_retries"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="max_retries 参数不合法") from exc

    if updates.get("api_key") is not None:
        api_key_value = str(updates.get("api_key") or "").strip()
        if api_key_value:
            mapped_updates["api_key"] = api_key_value

    if updates.get("name") is not None:
        new_name = str(updates.get("name") or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Provider 名称不能为空")
        duplicate = provider_repository.get_by_name(new_name)
        if duplicate and duplicate.provider_id != current.provider_id:
            raise HTTPException(status_code=409, detail="Provider 名称已存在")
        mapped_updates["name"] = new_name

    updated = current
    if mapped_updates:
        updated = provider_repository.update(current.provider_id, mapped_updates)
        if not updated:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")

    _ensure_default_provider(provider_repository)
    _refresh_llm_router()

    latest = provider_repository.get(current.provider_id)
    return {
        "message": f"Provider '{provider_name}' 更新成功",
        "provider": _serialize_legacy_provider(latest or updated),
    }


@router.delete("/llm/providers/{provider_name}")
async def delete_llm_provider(provider_name: str) -> Dict[str, str]:
    """删除 Provider（兼容路径）。"""
    provider_repository = _get_ai_provider_repository()
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    current = provider_repository.get_by_name(provider_name)
    if not current:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")
    if provider_repository.count() <= 1:
        raise HTTPException(status_code=409, detail="至少保留一个 Provider")

    enabled_items = provider_repository.list(enabled_only=True)
    if current.is_default and len(enabled_items) <= 1:
        raise HTTPException(status_code=409, detail="至少保留一个启用状态的默认 Provider")

    deleted = provider_repository.delete(current.provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")

    _ensure_default_provider(provider_repository)
    _refresh_llm_router()
    return {"message": f"Provider '{provider_name}' 已删除"}


@router.post("/llm/providers/{provider_name}/test")
async def test_llm_provider(provider_name: str) -> Dict[str, Any]:
    """测试 Provider 连通性（兼容路径）。"""
    provider_repository = _get_ai_provider_repository()
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    provider = provider_repository.get_by_name(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")

    if not provider.api_key and provider.provider_type != LLMProviderType.CUSTOM.value:
        return {
            "status": "error",
            "message": "API Key 未配置，无法测试连接",
        }

    runtime_router = _get_runtime_llm_router()
    if not runtime_router:
        return {
            "status": "error",
            "message": "当前未启用可用的 LLM Provider",
        }

    try:
        response = await runtime_router.chat(
            messages=[
                {"role": "system", "content": "你是连接测试助手，请简短作答。"},
                {"role": "user", "content": "请仅回复 OK"},
            ],
            provider=provider_name,
            temperature=0,
            max_tokens=32,
            _source="legacy_route",
            _endpoint="provider_test",
        )
        return {
            "status": "success",
            "message": "连接测试成功",
            "response_preview": response[:200],
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"连接测试失败：{exc}",
        }


@router.post("/llm/default-provider")
async def set_default_llm_provider(data: Dict[str, str]) -> Dict[str, Any]:
    """设置默认 Provider（兼容路径）。"""
    provider_repository = _get_ai_provider_repository()
    if not provider_repository:
        raise HTTPException(status_code=409, detail="Provider 仓储未初始化")

    provider_name = str(data.get("provider_name") or "").strip()
    if not provider_name:
        raise HTTPException(status_code=400, detail="缺少 provider_name 参数")

    provider = provider_repository.get_by_name(provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")

    default_record = provider_repository.set_default(provider.provider_id)
    if not default_record:
        raise HTTPException(status_code=400, detail="默认 Provider 必须处于启用状态")

    _refresh_llm_router()
    return {"message": f"默认 Provider 已设置为 '{provider_name}'"}


@router.post("/llm/analyze")
async def llm_analyze(
    messages: List[Dict[str, str]] = Body(..., description="消息列表"),
    provider: Optional[str] = Body(default=None, description="指定 Provider"),
    temperature: float = Body(default=0.7, description="温度参数"),
    max_tokens: int = Body(default=2000, description="最大 token 数")
) -> Dict[str, Any]:
    """LLM 分析兼容入口，内部复用运行时路由。"""
    runtime_router = _get_runtime_llm_router()
    if not runtime_router:
        raise HTTPException(status_code=500, detail="没有可用的 LLM Provider")

    if provider and provider not in runtime_router.clients:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' 不存在")

    try:
        response = await runtime_router.chat(
            messages,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens,
            _source="legacy_route",
            _endpoint="analyze",
        )
        return {
            "content": response,
            "provider": provider or runtime_router.default_client_name,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM 调用失败：{exc}") from exc


# ========== Prometheus 数据源 API ==========

@router.get("/prometheus/health")
async def check_prometheus_health(
    url: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    检查 Prometheus 服务健康状态
    """
    from engine.integrations.data_sources import PrometheusAdapter

    prometheus_url = url or "http://localhost:9090"
    adapter = PrometheusAdapter(base_url=prometheus_url, api_key=api_key)

    try:
        await adapter.initialize()
        status = await adapter.health_check()
        await adapter.close()

        return {
            "healthy": status.healthy,
            "message": status.message,
            "latency_ms": status.latency_ms,
            "url": prometheus_url
        }
    except Exception as e:
        return {
            "healthy": False,
            "message": str(e),
            "url": prometheus_url
        }


@router.post("/prometheus/query")
async def prometheus_query(
    query: str = Body(..., description="PromQL 查询语句"),
    url: Optional[str] = Body(default=None),
    api_key: Optional[str] = Body(default=None),
    time: Optional[str] = Body(default=None)
) -> Dict[str, Any]:
    """
    Prometheus 即时查询
    """
    from engine.integrations.data_sources import PrometheusAdapter
    from datetime import datetime

    prometheus_url = url or "http://localhost:9090"
    adapter = PrometheusAdapter(base_url=prometheus_url, api_key=api_key)

    try:
        await adapter.initialize()
        query_time = datetime.fromisoformat(time) if time else None
        result = await adapter.query_instant(query, query_time)
        await adapter.close()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败：{str(e)}")


@router.post("/prometheus/query_range")
async def prometheus_query_range(
    query: str = Body(..., description="PromQL 查询语句"),
    start: str = Body(..., description="开始时间（ISO 格式）"),
    end: str = Body(..., description="结束时间（ISO 格式）"),
    step: str = Body(default="5m", description="步长"),
    url: Optional[str] = Body(default=None),
    api_key: Optional[str] = Body(default=None)
) -> Dict[str, Any]:
    """
    Prometheus 范围查询
    """
    from engine.integrations.data_sources import PrometheusAdapter
    from datetime import datetime

    prometheus_url = url or "http://localhost:9090"
    adapter = PrometheusAdapter(base_url=prometheus_url, api_key=api_key)

    try:
        await adapter.initialize()
        result = await adapter.query_range(
            query,
            datetime.fromisoformat(start),
            datetime.fromisoformat(end),
            step
        )
        await adapter.close()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败：{str(e)}")


@router.get("/prometheus/alerts")
async def get_prometheus_alerts(
    url: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取 Prometheus 当前告警
    """
    from engine.integrations.data_sources import PrometheusAdapter

    prometheus_url = url or "http://localhost:9090"
    adapter = PrometheusAdapter(base_url=prometheus_url, api_key=api_key)

    try:
        await adapter.initialize()
        alerts = await adapter.get_alerts()
        await adapter.close()
        return {"alerts": alerts, "total": len(alerts)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取告警失败：{str(e)}")


@router.get("/prometheus/rules")
async def get_prometheus_rules(
    group_name: Optional[str] = None,
    url: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取 Prometheus 告警规则
    """
    from engine.integrations.data_sources import PrometheusAdapter

    prometheus_url = url or "http://localhost:9090"
    adapter = PrometheusAdapter(base_url=prometheus_url, api_key=api_key)

    try:
        await adapter.initialize()
        rules = await adapter.get_alert_rules(group_name)
        await adapter.close()
        return {"rules": rules, "total": len(rules)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取规则失败：{str(e)}")


@router.post("/prometheus/metric")
async def get_prometheus_metric(
    metric_name: str = Body(..., description="指标名称"),
    labels: Optional[Dict[str, str]] = Body(default=None, description="标签过滤器"),
    start: Optional[str] = Body(default=None, description="开始时间"),
    end: Optional[str] = Body(default=None, description="结束时间"),
    step: str = Body(default="5m", description="步长"),
    url: Optional[str] = Body(default=None),
    api_key: Optional[str] = Body(default=None)
) -> Dict[str, Any]:
    """
    查询 Prometheus 指标
    """
    from engine.integrations.data_sources import PrometheusAdapter
    from datetime import datetime

    prometheus_url = url or "http://localhost:9090"
    adapter = PrometheusAdapter(base_url=prometheus_url, api_key=api_key)

    try:
        await adapter.initialize()
        result = await adapter.query_metric(
            metric_name,
            labels,
            datetime.fromisoformat(start) if start else None,
            datetime.fromisoformat(end) if end else None,
            step
        )
        await adapter.close()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败：{str(e)}")

