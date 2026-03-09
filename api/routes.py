"""
API 路由模块

提供 REST API 端点，直接调用能力实现。
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional, List

router = APIRouter()


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
    import asyncio
    alerts = asyncio.get_event_loop().run_until_complete(
        store.query_alerts(status=status, severity=severity, limit=limit)
    )
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
    import asyncio
    success = asyncio.get_event_loop().run_until_complete(
        store.acknowledge_alert(alert_id, acknowledged_by)
    )
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
    import asyncio
    success = asyncio.get_event_loop().run_until_complete(
        store.resolve_alert(alert_id, resolved_by)
    )
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
    import asyncio
    rule_id = asyncio.get_event_loop().run_until_complete(
        store.create_rule(rule_data)
    )
    return {"rule_id": rule_id, "message": "规则创建成功"}


@router.get("/alerts/rules")
async def list_alert_rules(store=Depends(get_alert_store)) -> Dict[str, Any]:
    """
    列出所有告警规则
    """
    import asyncio
    rules = asyncio.get_event_loop().run_until_complete(store.get_rules())
    return {"rules": rules, "total": len(rules)}


@router.delete("/alerts/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: str,
    store=Depends(get_alert_store)
) -> Dict[str, str]:
    """
    删除告警规则
    """
    import asyncio
    success = asyncio.get_event_loop().run_until_complete(
        store.delete_rule(rule_id)
    )
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
    import asyncio

    inspector = ContainerInspector()
    result = await asyncio.wait_for(inspector.dispatch(
        container_name="_list_",
        include_logs=False
    ), timeout=30)
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
    import asyncio

    monitor = HostMonitor()
    result = await asyncio.wait_for(monitor.dispatch(
        metrics=["cpu", "memory", "disk", "network"]
    ), timeout=30)
    return result.to_dict()
