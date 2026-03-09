"""
修复预案能力

根据告警类型自动推荐修复方案。
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from .base import BaseCapability, CapabilityMetadata
from .decorators import with_timeout, with_error_handling
from ..contracts import ActionResult


class RemediationPlanInput(BaseModel):
    """
    修复预案查询输入

    Attributes:
        alert_type: 告警类型
        metric: 指标名称
        current_value: 当前值
    """
    alert_type: str = Field(..., description="告警类型", min_length=1, max_length=64)
    metric: str = Field(..., description="指标名称", min_length=1)
    current_value: float = Field(..., description="当前值")


class RemediationPlan(BaseCapability):
    """
    修复预案管理器

    根据告警类型自动推荐修复方案，支持预演和执行。

    内置预案:
        - cpu_high: CPU 使用率过高
        - memory_high: 内存使用率过高
        - disk_full: 磁盘空间不足
        - container_crash: 容器崩溃
    """

    # 内置修复预案库
    _REMEDIATION_PLANS = {
        "cpu_high": {
            "id": "plan_cpu_high",
            "name": "CPU 使用率过高修复预案",
            "description": "当 CPU 使用率持续高于阈值时的处理流程",
            "trigger": {"metric": "cpu_usage", "operator": ">", "threshold": 80},
            "steps": [
                {
                    "order": 1,
                    "name": "识别高负载进程",
                    "action": "exec",
                    "command": "ps aux --sort=-%cpu | head -10",
                    "description": "查看 CPU 占用最高的 10 个进程",
                    "risk": "low",
                    "rollback": None
                },
                {
                    "order": 2,
                    "name": "检查是否有异常进程",
                    "action": "analyze",
                    "description": "分析进程列表，识别异常行为",
                    "risk": "low",
                    "rollback": None
                },
                {
                    "order": 3,
                    "name": "重启异常服务",
                    "action": "service_restart",
                    "description": "重启问题服务",
                    "risk": "medium",
                    "rollback": "恢复服务到重启前状态"
                },
                {
                    "order": 4,
                    "name": "扩容（如需要）",
                    "action": "scale_up",
                    "description": "增加 CPU 资源或扩容节点",
                    "risk": "medium",
                    "rollback": "恢复原资源配置"
                }
            ],
            "estimated_time": "10-30 分钟",
            "risk_level": "medium"
        },
        "memory_high": {
            "id": "plan_memory_high",
            "name": "内存使用率过高修复预案",
            "description": "当内存使用率持续高于阈值时的处理流程",
            "trigger": {"metric": "memory_usage", "operator": ">", "threshold": 85},
            "steps": [
                {
                    "order": 1,
                    "name": "识别内存占用进程",
                    "action": "exec",
                    "command": "ps aux --sort=-%mem | head -10",
                    "description": "查看内存占用最高的 10 个进程",
                    "risk": "low",
                    "rollback": None
                },
                {
                    "order": 2,
                    "name": "清理系统缓存",
                    "action": "exec",
                    "command": "sync && echo 3 > /proc/sys/vm/drop_caches",
                    "description": "清理页面缓存、目录项和 inode",
                    "risk": "low",
                    "rollback": None
                },
                {
                    "order": 3,
                    "name": "重启内存泄漏服务",
                    "action": "service_restart",
                    "description": "重启疑似内存泄漏的服务",
                    "risk": "medium",
                    "rollback": "恢复服务状态"
                }
            ],
            "estimated_time": "5-15 分钟",
            "risk_level": "low"
        },
        "disk_full": {
            "id": "plan_disk_full",
            "name": "磁盘空间不足修复预案",
            "description": "当磁盘使用率接近上限时的处理流程",
            "trigger": {"metric": "disk_usage", "operator": ">", "threshold": 85},
            "steps": [
                {
                    "order": 1,
                    "name": "分析磁盘使用",
                    "action": "exec",
                    "command": "df -h && du -sh /* 2>/dev/null | sort -rh | head -20",
                    "description": "查看磁盘使用情况和最大的目录",
                    "risk": "low",
                    "rollback": None
                },
                {
                    "order": 2,
                    "name": "清理日志文件",
                    "action": "exec",
                    "command": "find /var/log -type f -name '*.log' -mtime +7 -delete",
                    "description": "删除 7 天前的日志文件",
                    "risk": "low",
                    "rollback": None
                },
                {
                    "order": 3,
                    "name": "清理临时文件",
                    "action": "exec",
                    "command": "rm -rf /tmp/*",
                    "description": "清理临时目录",
                    "risk": "low",
                    "rollback": None
                },
                {
                    "order": 4,
                    "name": "扩容磁盘",
                    "action": "disk_expand",
                    "description": "增加磁盘容量",
                    "risk": "high",
                    "rollback": "无法自动回滚"
                }
            ],
            "estimated_time": "15-60 分钟",
            "risk_level": "medium"
        },
        "container_crash": {
            "id": "plan_container_crash",
            "name": "容器崩溃修复预案",
            "description": "当容器异常退出时的处理流程",
            "trigger": {"metric": "container_status", "operator": "=", "value": "exited"},
            "steps": [
                {
                    "order": 1,
                    "name": "查看容器日志",
                    "action": "exec",
                    "command": "docker logs --tail 100 {container_name}",
                    "description": "查看容器最后 100 行日志",
                    "risk": "low",
                    "rollback": None
                },
                {
                    "order": 2,
                    "name": "检查容器状态",
                    "action": "exec",
                    "command": "docker inspect {container_name}",
                    "description": "查看容器详细信息",
                    "risk": "low",
                    "rollback": None
                },
                {
                    "order": 3,
                    "name": "重启容器",
                    "action": "container_restart",
                    "description": "重启问题容器",
                    "risk": "medium",
                    "rollback": "停止容器"
                }
            ],
            "estimated_time": "5-10 分钟",
            "risk_level": "low"
        }
    }

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="get_remediation_plan",
            description="获取故障修复预案（含推荐步骤和风险评估）",
            version="1.0.0",
            tags=["remediation", "auto-fix", "playbook"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return RemediationPlanInput

    @with_timeout(timeout_seconds=15)
    @with_error_handling("REMEDIATION_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        获取修复预案

        Args:
            alert_type: 告警类型
            metric: 指标名称
            current_value: 当前值

        Returns:
            ActionResult: 修复预案
        """
        try:
            input_data = RemediationPlanInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        plan = self._match_plan(input_data.alert_type, input_data.metric)

        if not plan:
            return ActionResult.fail(
                f"未找到适用于 '{input_data.alert_type}' 的修复预案",
                code="PLAN_NOT_FOUND"
            )

        return ActionResult.ok({
            "plan_id": plan["id"],
            "name": plan["name"],
            "description": plan["description"],
            "steps": plan["steps"],
            "estimated_time": plan.get("estimated_time", "未知"),
            "risk_level": plan.get("risk_level", "medium")
        })

    def _match_plan(self, alert_type: str, metric: str) -> Optional[Dict]:
        """
        匹配修复预案

        Args:
            alert_type: 告警类型
            metric: 指标名称

        Returns:
            匹配的预案，未找到返回 None
        """
        # 直接匹配
        if alert_type in self._REMEDIATION_PLANS:
            return self._REMEDIATION_PLANS[alert_type]

        # 指标匹配
        for plan in self._REMEDIATION_PLANS.values():
            trigger = plan.get("trigger", {})
            if trigger.get("metric") == metric:
                return plan

        return None

    def get_plan_ids(self) -> List[str]:
        """
        获取所有预案 ID

        Returns:
            预案 ID 列表
        """
        return list(self._REMEDIATION_PLANS.keys())
