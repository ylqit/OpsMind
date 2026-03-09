"""
API 路由模块

"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List

router = APIRouter()


class CapabilityDispatchRequest(BaseModel):
    """能力调用请求"""
    capability: str
    params: Dict[str, Any] = {}


class CapabilityResponse(BaseModel):
    """能力调用响应"""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


@router.get("/")
async def api_root() -> Dict[str, str]:
    """API 根路径"""
    return {"message": "Welcome to opsMind API", "version": "0.1.0"}


@router.get("/capabilities")
async def list_capabilities() -> List[Dict[str, Any]]:
    """
    列出所有可用能力

    注意：此路由需要在 main.py 中注入 capability_registry
    """
    return []


@router.post("/capabilities/{name}/dispatch")
async def dispatch_capability(
    name: str,
    request: CapabilityDispatchRequest
) -> CapabilityResponse:
    """
    调用指定能力

    Args:
        name: 能力名称
        request: 调用请求

    Returns:
        能力执行结果
    """
    return CapabilityResponse(
        success=True,
        data={"message": f"Capability {name} dispatched"}
    )


@router.get("/alerts")
async def list_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 20
) -> Dict[str, Any]:
    """
    查询告警列表

    Args:
        status: 告警状态筛选
        severity: 严重程度筛选
        limit: 返回数量限制

    Returns:
        告警列表
    """
    return {"alerts": [], "total": 0}


@router.post("/alerts/acknowledge")
async def acknowledge_alert(alert_id: str) -> Dict[str, str]:
    """
    确认告警

    Args:
        alert_id: 告警 ID

    Returns:
        操作结果
    """
    return {"message": f"Alert {alert_id} acknowledged"}


@router.post("/alerts/resolve")
async def resolve_alert(alert_id: str) -> Dict[str, str]:
    """
    解决告警

    Args:
        alert_id: 告警 ID

    Returns:
        操作结果
    """
    return {"message": f"Alert {alert_id} resolved"}


@router.get("/remediation/plans")
async def list_remediation_plans() -> List[Dict[str, Any]]:
    """
    列出所有修复预案

    Returns:
        预案列表
    """
    return []


@router.post("/remediation/execute")
async def execute_remediation(
    plan_id: str,
    step_indices: List[int],
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    执行修复预案

    Args:
        plan_id: 预案 ID
        step_indices: 要执行的步骤索引
        dry_run: 是否预演模式

    Returns:
        执行结果
    """
    return {
        "mode": "dry_run" if dry_run else "execute",
        "plan_id": plan_id,
        "results": []
    }
