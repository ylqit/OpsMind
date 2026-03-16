"""
技能编排器

提供多能力组合编排功能，支持：
- 按流程自动执行多个能力
- 条件分支和循环
- 参数传递和结果聚合
- 编排执行日志
"""
from typing import Dict, Any, List, Optional, Callable
from pydantic import BaseModel, Field
from enum import Enum
import asyncio

from engine.capabilities.base import BaseCapability, CapabilityMetadata
from engine.capabilities.decorators import with_timeout, with_error_handling
from engine.contracts import ActionResult
from engine.runtime.time_utils import utc_now, utc_now_iso


class OrchestratorStepStatus(str, Enum):
    """编排步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class OrchestratorStep(BaseModel):
    """编排步骤定义"""
    id: str = Field(..., description="步骤 ID")
    name: str = Field(..., description="步骤名称")
    capability: str = Field(..., description="要调用的能力名称")
    params: Dict[str, Any] = Field(default={}, description="能力调用参数")
    condition: Optional[str] = Field(default=None, description="执行条件（Python 表达式）")
    on_failure: Optional[str] = Field(default=None, description="失败后的操作：continue/abort/retry")
    retry_count: int = Field(default=0, description="重试次数")
    timeout: Optional[int] = Field(default=None, description="超时时间（秒）")


class OrchestratorExecutionLog(BaseModel):
    """执行日志"""
    step_id: str
    step_name: str
    status: OrchestratorStepStatus
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_times: int = 0


class SkillOrchestratorInput(BaseModel):
    """
    技能编排输入参数

    Attributes:
        workflow_id: 工作流 ID
        workflow_name: 工作流名称
        steps: 步骤列表
        initial_context: 初始上下文数据
        stop_on_failure: 失败时是否停止
    """
    workflow_id: Optional[str] = Field(default=None, description="工作流 ID")
    workflow_name: str = Field(..., description="工作流名称")
    steps: List[OrchestratorStep] = Field(..., description="步骤列表")
    initial_context: Dict[str, Any] = Field(default={}, description="初始上下文")
    stop_on_failure: bool = Field(default=True, description="失败时是否停止")


class SkillOrchestrator(BaseCapability):
    """
    技能编排器

    将多个能力组合成工作流自动执行：
    - 支持顺序执行
    - 支持条件分支
    - 支持错误处理和重试
    - 提供完整的执行日志

    典型应用场景：
    - 故障诊断流程：检查容器 -> 检查主机 -> 分析日志 -> 生成报告
    - 部署验证流程：检查配置 -> 部署应用 -> 健康检查 -> 发送通知
    """

    # 预定义工作流模板
    WORKFLOW_TEMPLATES = {
        "diagnose_container": {
            "name": "容器诊断流程",
            "steps": [
                {
                    "id": "check_container",
                    "name": "检查容器状态",
                    "capability": "inspect_container",
                    "params": {"container_id": "{{container_id}}"},
                },
                {
                    "id": "check_logs",
                    "name": "分析容器日志",
                    "capability": "analyze_logs",
                    "params": {"source": "container", "container_id": "{{container_id}}"},
                },
                {
                    "id": "check_host",
                    "name": "检查主机资源",
                    "capability": "inspect_host",
                    "params": {"metrics": ["cpu", "memory", "disk"]},
                },
                {
                    "id": "generate_report",
                    "name": "生成诊断报告",
                    "capability": "generate_incident_report",
                    "params": {
                        "alert_type": "container_issue",
                        "affected_resources": ["{{container_id}}"]
                    },
                }
            ]
        },
        "health_check": {
            "name": "健康检查流程",
            "steps": [
                {
                    "id": "check_host",
                    "name": "检查主机资源",
                    "capability": "inspect_host",
                    "params": {"metrics": ["cpu", "memory", "disk", "network"]},
                },
                {
                    "id": "check_containers",
                    "name": "检查容器状态",
                    "capability": "inspect_container",
                    "params": {"list_only": True},
                },
                {
                    "id": "check_alerts",
                    "name": "检查活跃告警",
                    "capability": "manage_alerts",
                    "params": {"action": "query_alerts", "status": "active"},
                }
            ]
        }
    }

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="orchestrate_skills",
            description="编排执行多个能力（支持工作流、条件分支、错误处理）",
            version="1.0.0",
            tags=["orchestration", "workflow", "automation", "skill"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> type[BaseModel]:
        return SkillOrchestratorInput

    @with_timeout(timeout_seconds=300)
    @with_error_handling("ORCHESTRATOR_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        执行技能编排

        Args:
            **kwargs: 输入参数

        Returns:
            ActionResult: 编排执行结果
        """
        try:
            input_data = SkillOrchestratorInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        # 获取能力注册表
        try:
            from main import capability_registry
            registry = capability_registry
        except Exception:
            return ActionResult.fail("能力注册表不可用", code="REGISTRY_UNAVAILABLE")

        # 执行工作流
        execution_result = await self._execute_workflow(
            workflow_name=input_data.workflow_name,
            steps=input_data.steps,
            context=input_data.initial_context,
            stop_on_failure=input_data.stop_on_failure,
            registry=registry
        )

        return ActionResult.ok(execution_result)

    async def _execute_workflow(
        self,
        workflow_name: str,
        steps: List[OrchestratorStep],
        context: Dict[str, Any],
        stop_on_failure: bool,
        registry
    ) -> Dict[str, Any]:
        """
        执行工作流

        Args:
            workflow_name: 工作流名称
            steps: 步骤列表
            context: 执行上下文
            stop_on_failure: 失败时是否停止
            registry: 能力注册表

        Returns:
            执行结果
        """
        now = utc_now()
        workflow_id = f"WF-{now.strftime('%Y%m%d-%H%M%S')}"
        started_at = now.isoformat()

        execution_log: List[OrchestratorExecutionLog] = []
        step_results: Dict[str, Any] = {}
        overall_status = "running"

        for step in steps:
            log_entry = OrchestratorExecutionLog(
                step_id=step.id,
                step_name=step.name,
                status=OrchestratorStepStatus.PENDING
            )

            # 检查执行条件
            if step.condition and not self._evaluate_condition(step.condition, context):
                log_entry.status = OrchestratorStepStatus.SKIPPED
                log_entry.error = "条件不满足"
                execution_log.append(log_entry)
                continue

            # 执行步骤
            log_entry.status = OrchestratorStepStatus.RUNNING
            log_entry.started_at = utc_now_iso()

            result = await self._execute_step_with_retry(step, context, registry)

            if result.success:
                log_entry.status = OrchestratorStepStatus.COMPLETED
                log_entry.result = result.data
                step_results[step.id] = result.data

                # 将结果添加到上下文（供后续步骤使用）
                context[f"step_{step.id}_result"] = result.data
            else:
                log_entry.status = OrchestratorStepStatus.FAILED
                log_entry.error = result.error
                log_entry.retry_times = step.retry_count

                if stop_on_failure:
                    execution_log.append(log_entry)
                    overall_status = "failed"
                    break
                else:
                    # 继续执行
                    step_results[step.id] = {"error": result.error}

            log_entry.completed_at = utc_now_iso()
            execution_log.append(log_entry)

        # 所有步骤执行完成
        if overall_status != "failed":
            overall_status = "completed" if all(
                log.status in [OrchestratorStepStatus.COMPLETED, OrchestratorStepStatus.SKIPPED]
                for log in execution_log
            ) else "partial_failure"

        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "status": overall_status,
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "steps": [log.dict() for log in execution_log],
            "results": step_results,
            "final_context": context
        }

    async def _execute_step_with_retry(
        self,
        step: OrchestratorStep,
        context: Dict[str, Any],
        registry
    ) -> ActionResult:
        """
        执行步骤（支持重试）

        Args:
            step: 步骤定义
            context: 执行上下文
            registry: 能力注册表

        Returns:
            执行结果
        """
        # 解析参数中的模板变量
        params = self._resolve_templates(step.params, context)

        # 获取能力
        capability = registry.get(step.capability)
        if not capability:
            return ActionResult.fail(f"能力 '{step.capability}' 不存在", code="CAPABILITY_NOT_FOUND")

        # 执行（带重试）
        last_error = None
        for attempt in range(step.retry_count + 1):
            try:
                import asyncio
                timeout = step.timeout or 60
                result = await asyncio.wait_for(
                    capability.dispatch(**params),
                    timeout=timeout
                )
                if result.success:
                    return result
                last_error = result.error
            except asyncio.TimeoutError:
                last_error = f"步骤执行超时（{timeout}秒）"
            except Exception as e:
                last_error = str(e)

            # 如果不是最后一次尝试，等待后重试
            if attempt < step.retry_count:
                await asyncio.sleep(1 * (attempt + 1))  # 指数退避

        return ActionResult.fail(last_error or "未知错误", code="STEP_EXECUTION_FAILED")

    def _resolve_templates(
        self,
        params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        解析参数中的模板变量（如 {{container_id}}）

        Args:
            params: 原始参数
            context: 上下文数据

        Returns:
            解析后的参数
        """
        import re

        resolved = {}
        for key, value in params.items():
            if isinstance(value, str):
                # 查找模板变量
                matches = re.findall(r'\{\{(\w+)\}\}', value)
                if matches:
                    new_value = value
                    for var_name in matches:
                        # 从上下文中查找值
                        var_value = context.get(var_name) or context.get(f"step_{var_name}_result", {}).get("id")
                        if var_value:
                            new_value = new_value.replace(f"{{{{{var_name}}}}}", str(var_value))
                    resolved[key] = new_value
                else:
                    resolved[key] = value
            elif isinstance(value, dict):
                resolved[key] = self._resolve_templates(value, context)
            elif isinstance(value, list):
                resolved[key] = [
                    self._resolve_templates(v, context) if isinstance(v, dict) else v
                    for v in value
                ]
            else:
                resolved[key] = value

        return resolved

    def _evaluate_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        """
        评估条件表达式

        Args:
            condition: 条件表达式
            context: 上下文数据

        Returns:
            是否满足条件
        """
        try:
            # 安全地评估条件表达式
            # 只允许访问 context 中的变量
            local_vars = {"ctx": context, "get": context.get}
            # 将条件中的变量引用转换为 ctx.get 形式
            safe_condition = condition.replace("ctx.", "get(")
            return bool(eval(safe_condition, {"__builtins__": {}}, local_vars))
        except Exception:
            return False

    def get_workflow_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """
        获取预定义的工作流模板

        Args:
            template_id: 模板 ID

        Returns:
            工作流模板
        """
        return self.WORKFLOW_TEMPLATES.get(template_id)

    def list_workflow_templates(self) -> List[str]:
        """
        列出所有可用的工作流模板

        Returns:
            模板 ID 列表
        """
        return list(self.WORKFLOW_TEMPLATES.keys())
