"""
执行修复能力

实际执行修复预案中的步骤。
"""
import asyncio
import subprocess
from typing import Dict, Any, Type, List
from pydantic import BaseModel, Field
from .base import BaseCapability, CapabilityMetadata
from .decorators import with_timeout, with_error_handling
from ..contracts import ActionResult
from .remediation import RemediationPlan


class ExecuteRemediationInput(BaseModel):
    """
    执行修复输入

    Attributes:
        plan_id: 预案 ID
        step_indices: 要执行的步骤索引列表
        dry_run: 是否预演模式
        container_name: 容器名称（如需要）
    """
    plan_id: str = Field(..., description="预案 ID", min_length=1)
    step_indices: List[int] = Field(default=[], description="要执行的步骤索引")
    dry_run: bool = Field(default=True, description="是否预演模式")
    container_name: str = Field(default=None, description="容器名称（如需要）")


class ExecuteRemediation(BaseCapability):
    """
    修复执行器

    执行修复预案中的具体步骤，支持预演模式。

    """

    def __init__(self):
        """初始化修复执行器"""
        self._plan_registry = RemediationPlan()
        super().__init__()

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="execute_remediation",
            description="执行故障修复预案（需要 HITL 确认）",
            version="1.0.0",
            tags=["remediation", "execute", "auto-fix"],
            requires_confirmation=True
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return ExecuteRemediationInput

    @with_timeout(timeout_seconds=120)
    @with_error_handling("EXECUTE_REMEDIATION_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        执行修复

        Args:
            plan_id: 预案 ID
            step_indices: 要执行的步骤索引
            dry_run: 是否预演模式
            container_name: 容器名称

        Returns:
            ActionResult: 执行结果
        """
        try:
            input_data = ExecuteRemediationInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        if input_data.dry_run:
            return await self._dry_run(input_data)
        else:
            return await self._execute(input_data)

    async def _dry_run(self, input_data: ExecuteRemediationInput) -> ActionResult:
        """
        预演模式：显示将要执行的命令

        Args:
            input_data: 输入参数

        Returns:
            ActionResult: 预演结果
        """
        plan = self._get_plan(input_data.plan_id)
        if not plan:
            return ActionResult.fail("预案不存在", code="PLAN_NOT_FOUND")

        steps_to_execute = []
        for idx in input_data.step_indices:
            if 0 <= idx < len(plan["steps"]):
                steps_to_execute.append(plan["steps"][idx])

        return ActionResult.ok({
            "mode": "dry_run",
            "plan_name": plan["name"],
            "steps": steps_to_execute,
            "warning": "预演模式：未实际执行任何操作"
        })

    async def _execute(self, input_data: ExecuteRemediationInput) -> ActionResult:
        """
        实际执行

        Args:
            input_data: 输入参数

        Returns:
            ActionResult: 执行结果
        """
        plan = self._get_plan(input_data.plan_id)
        if not plan:
            return ActionResult.fail("预案不存在", code="PLAN_NOT_FOUND")

        results = []
        for idx in input_data.step_indices:
            if 0 <= idx < len(plan["steps"]):
                step = plan["steps"][idx]
                result = await self._execute_step(step, input_data.container_name)
                results.append({
                    "step": idx + 1,
                    "name": step["name"],
                    "success": result["success"],
                    "output": result.get("output"),
                    "error": result.get("error")
                })

                if not result["success"]:
                    break

        return ActionResult.ok({
            "mode": "execute",
            "plan_name": plan["name"],
            "results": results
        })

    async def _execute_step(self, step: Dict, container_name: str = None) -> Dict:
        """
        执行单个步骤

        Args:
            step: 步骤定义
            container_name: 容器名称

        Returns:
            执行结果
        """
        action = step.get("action")
        command = step.get("command", "")

        if container_name:
            command = command.replace("{container_name}", container_name)

        try:
            if action == "exec":
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode == 0:
                    return {"success": True, "output": stdout.decode()}
                else:
                    return {"success": False, "error": stderr.decode()}

            elif action in ["service_restart", "container_restart"]:
                if action == "container_restart" and container_name:
                    cmd = f"docker restart {container_name}"
                else:
                    cmd = command

                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()

                return {
                    "success": proc.returncode == 0,
                    "output": stdout.decode() if stdout else "",
                    "error": stderr.decode() if stderr else ""
                }

            else:
                return {
                    "success": True,
                    "output": f"步骤 '{step['name']}' 为分析步骤，无需执行"
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_plan(self, plan_id: str) -> Dict:
        """
        获取预案

        Args:
            plan_id: 预案 ID

        Returns:
            预案字典
        """
        for plan in self._plan_registry._REMEDIATION_PLANS.values():
            if plan["id"] == plan_id:
                return plan
        return {}
