"""
告警管理能力

创建、查询、确认、解决告警规则。
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from .base import BaseCapability, CapabilityMetadata
from .decorators import with_timeout, with_error_handling
from ..contracts import ActionResult
from ..storage.alert_store import AlertStore


class AlertRuleInput(BaseModel):
    """
    告警规则输入参数

    Attributes:
        name: 规则名称
        metric: 监控指标
        threshold: 阈值
        operator: 比较运算符
        severity: 严重程度
        notification_channels: 通知渠道列表
    """
    name: str = Field(..., description="规则名称", min_length=1, max_length=64)
    metric: str = Field(..., description="监控指标")
    threshold: float = Field(..., description="阈值")
    operator: str = Field(default=">", description="比较运算符 (>, <, >=, <=, =)")
    severity: str = Field(default="warning", description="严重程度 (info, warning, critical)")
    notification_channels: List[str] = Field(default=[], description="通知渠道列表")


class AlertQueryInput(BaseModel):
    """
    告警查询输入参数

    Attributes:
        status: 告警状态筛选
        severity: 严重程度筛选
        limit: 返回数量限制
    """
    status: Optional[str] = Field(default=None, description="告警状态 (active, acknowledged, resolved)")
    severity: Optional[str] = Field(default=None, description="严重程度")
    limit: int = Field(default=20, ge=1, le=100, description="返回数量限制")


class AlertManager(BaseCapability):
    """
    告警管理器

    提供告警规则管理和告警查询能力。

    支持的操作:
        - create_rule: 创建告警规则
        - query_alerts: 查询告警列表
        - acknowledge: 确认告警
        - resolve: 解决告警
        - delete_rule: 删除规则

    使用示例:
        >>> store = AlertStore(data_dir)
        >>> manager = AlertManager(store)
        >>> result = await manager.dispatch(action="query_alerts", status="active")
    """

    def __init__(self, alert_store: AlertStore):
        """
        初始化告警管理器

        Args:
            alert_store: 告警存储实例
        """
        self.store = alert_store
        super().__init__()

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="manage_alerts",
            description="管理告警规则（创建、查询、确认、解决）",
            version="1.0.0",
            tags=["alert", "monitor", "notification"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        # 使用通用输入模式，实际操作由 action 参数决定
        return AlertRuleInput

    @with_timeout(timeout_seconds=10)
    @with_error_handling("ALERT_MANAGER_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        执行告警管理操作

        Args:
            action: 操作类型 (create_rule, query_alerts, acknowledge, resolve, delete_rule)
            **kwargs: 操作参数

        Returns:
            ActionResult: 操作结果
        """
        action = kwargs.get("action")

        if action == "create_rule":
            return await self._create_rule(kwargs)
        elif action == "query_alerts":
            return await self._query_alerts(kwargs)
        elif action == "acknowledge":
            return await self._acknowledge_alert(kwargs)
        elif action == "resolve":
            return await self._resolve_alert(kwargs)
        elif action == "delete_rule":
            return await self._delete_rule(kwargs)
        elif action == "list_rules":
            return await self._list_rules(kwargs)
        else:
            return ActionResult.fail(f"未知操作：{action}", code="UNKNOWN_ACTION")

    async def _create_rule(self, kwargs: Dict[str, Any]) -> ActionResult:
        """
        创建告警规则

        Args:
            kwargs: 规则参数

        Returns:
            ActionResult: 创建结果
        """
        try:
            # 提取规则相关参数
            rule_data = {
                "name": kwargs.get("name"),
                "metric": kwargs.get("metric"),
                "threshold": kwargs.get("threshold"),
                "operator": kwargs.get("operator", ">"),
                "severity": kwargs.get("severity", "warning"),
                "notification_channels": kwargs.get("notification_channels", [])
            }
            rule = AlertRuleInput(**rule_data)  # 验证参数
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        rule_id = await self.store.create_rule(rule.model_dump())

        return ActionResult.ok({
            "rule_id": rule_id,
            "message": f"告警规则 '{rule.name}' 创建成功"
        })

    async def _query_alerts(self, kwargs: Dict[str, Any]) -> ActionResult:
        """
        查询告警列表

        Args:
            kwargs: 查询参数

        Returns:
            ActionResult: 查询结果
        """
        try:
            query = AlertQueryInput(
                status=kwargs.get("status"),
                severity=kwargs.get("severity"),
                limit=kwargs.get("limit", 20)
            )
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        alerts = await self.store.query_alerts(
            status=query.status,
            severity=query.severity,
            limit=query.limit
        )

        return ActionResult.ok({
            "alerts": alerts,
            "total": len(alerts)
        })

    async def _acknowledge_alert(self, kwargs: Dict[str, Any]) -> ActionResult:
        """
        确认告警

        Args:
            kwargs: 包含 alert_id 的字典

        Returns:
            ActionResult: 确认结果
        """
        alert_id = kwargs.get("alert_id")
        if not alert_id:
            return ActionResult.fail("缺少 alert_id 参数", code="MISSING_PARAMETER")

        acknowledged_by = kwargs.get("acknowledged_by", "system")
        success = await self.store.acknowledge_alert(alert_id, acknowledged_by)

        if success:
            return ActionResult.ok({"message": "告警已确认"})
        else:
            return ActionResult.fail("告警不存在", code="ALERT_NOT_FOUND")

    async def _resolve_alert(self, kwargs: Dict[str, Any]) -> ActionResult:
        """
        解决告警

        Args:
            kwargs: 包含 alert_id 的字典

        Returns:
            ActionResult: 解决结果
        """
        alert_id = kwargs.get("alert_id")
        if not alert_id:
            return ActionResult.fail("缺少 alert_id 参数", code="MISSING_PARAMETER")

        resolved_by = kwargs.get("resolved_by", "system")
        success = await self.store.resolve_alert(alert_id, resolved_by)

        if success:
            return ActionResult.ok({"message": "告警已解决"})
        else:
            return ActionResult.fail("告警不存在", code="ALERT_NOT_FOUND")

    async def _delete_rule(self, kwargs: Dict[str, Any]) -> ActionResult:
        """
        删除告警规则

        Args:
            kwargs: 包含 rule_id 的字典

        Returns:
            ActionResult: 删除结果
        """
        rule_id = kwargs.get("rule_id")
        if not rule_id:
            return ActionResult.fail("缺少 rule_id 参数", code="MISSING_PARAMETER")

        success = await self.store.delete_rule(rule_id)

        if success:
            return ActionResult.ok({"message": "规则已删除"})
        else:
            return ActionResult.fail("规则不存在", code="RULE_NOT_FOUND")

    async def _list_rules(self, kwargs: Dict[str, Any]) -> ActionResult:
        """
        列出所有规则

        Args:
            kwargs: 未使用

        Returns:
            ActionResult: 规则列表
        """
        rules = await self.store.get_rules()
        return ActionResult.ok({"rules": rules, "total": len(rules)})
