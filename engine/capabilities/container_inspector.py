"""
容器检查能力

提供 Docker 容器状态检查、日志获取等能力。
"""
from typing import Dict, Any, Type, Optional, List
from pydantic import BaseModel, Field
from .base import BaseCapability, CapabilityMetadata
from .decorators import with_timeout, with_error_handling
from ..contracts import ActionResult


class ContainerInspectInput(BaseModel):
    """
    容器检查输入参数

    Attributes:
        container_name: 容器名称或 ID
        include_logs: 是否包含日志
        log_lines: 日志行数
    """
    container_name: str = Field(..., description="容器名称或 ID", min_length=1, max_length=128)
    include_logs: bool = Field(default=False, description="是否包含日志")
    log_lines: int = Field(default=50, description="日志行数", ge=1, le=1000)


class ContainerInspector(BaseCapability):
    """
    容器检查器

    提供容器状态查询、健康分析、日志查看等能力。
    """

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="inspect_container",
            description="检查 Docker 容器的状态、配置和健康情况",
            version="1.0.0",
            tags=["docker", "container", "diagnose"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return ContainerInspectInput

    @with_timeout(timeout_seconds=30)
    @with_error_handling("CONTAINER_INSPECT_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        执行容器检查

        Args:
            container_name: 容器名称
            include_logs: 是否包含日志
            log_lines: 日志行数

        Returns:
            ActionResult: 检查结果
        """
        try:
            input_data = ContainerInspectInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        # 检查 docker 是否可用
        if not self._is_docker_available():
            return ActionResult.fail(
                "Docker 服务不可用",
                code="DOCKER_UNAVAILABLE"
            )

        # 获取容器信息
        container_info = self._get_container_info(input_data.container_name)
        if not container_info:
            return ActionResult.fail(
                f"容器 '{input_data.container_name}' 不存在",
                code="CONTAINER_NOT_FOUND"
            )

        # 构建诊断报告
        diagnosis = self._analyze_container(container_info)

        # 获取日志（可选）
        logs = None
        if input_data.include_logs:
            logs = self._get_container_logs(
                input_data.container_name,
                input_data.log_lines
            )

        result_data = {
            "container": container_info,
            "diagnosis": diagnosis,
            "logs": logs
        }

        return ActionResult.ok(result_data)

    def _is_docker_available(self) -> bool:
        """
        检查 Docker 是否可用

        Returns:
            Docker 是否可用
        """
        try:
            import docker
            client = docker.from_env()
            client.ping()
            return True
        except Exception:
            return False

    def _get_container_info(self, name: str) -> Optional[Dict[str, Any]]:
        """
        获取容器信息

        Args:
            name: 容器名称

        Returns:
            容器信息字典
        """
        try:
            import docker
            client = docker.from_env()
            container = client.containers.get(name)

            return {
                "id": container.id[:12],
                "name": container.name,
                "image": container.image.tags[0] if container.image.tags else "",
                "status": container.status,
                "state": container.attrs.get("State", {}),
                "created": container.attrs.get("Created", ""),
                "network": container.attrs.get("NetworkSettings", {}),
                "mounts": container.attrs.get("Mounts", [])
            }
        except Exception:
            return None

    def _get_container_logs(self, name: str, lines: int = 50) -> Optional[str]:
        """
        获取容器日志

        Args:
            name: 容器名称
            lines: 日志行数

        Returns:
            日志内容
        """
        try:
            import docker
            client = docker.from_env()
            container = client.containers.get(name)
            logs = container.logs(tail=lines, stderr=True)
            return logs.decode("utf-8", errors="replace")
        except Exception:
            return None

    def _analyze_container(self, container: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析容器状态

        Args:
            container: 容器信息

        Returns:
            诊断报告
        """
        state = container.get("state", {})
        status = state.get("Status", "unknown")
        health = state.get("Health", {})

        diagnosis = {
            "status": status,
            "running": status == "running",
            "healthy": None,
            "issues": [],
            "recommendations": []
        }

        # 健康状态
        if health:
            diagnosis["healthy"] = health.get("Status") == "healthy"

        # 问题检测
        if status == "exited":
            exit_code = state.get("ExitCode", -1)
            if exit_code != 0:
                diagnosis["issues"].append(f"容器异常退出，退出码：{exit_code}")
                diagnosis["recommendations"].append("检查容器日志定位退出原因")

        if status == "restarting":
            diagnosis["issues"].append("容器正在重启")
            diagnosis["recommendations"].append("检查容器是否配置了自动重启策略")

        if status == "dead":
            diagnosis["issues"].append("容器已死亡")
            diagnosis["recommendations"].append("检查系统资源是否充足")

        # oom 检测
        if state.get("OOMKilled", False):
            diagnosis["issues"].append("容器因 OOM 被杀死")
            diagnosis["recommendations"].append("增加容器内存限制或优化内存使用")

        return diagnosis

    def list_containers(self, all: bool = True) -> ActionResult:
        """
        列出所有容器

        Args:
            all: 是否包含已停止的容器

        Returns:
            ActionResult: 容器列表
        """
        try:
            if not self._is_docker_available():
                return ActionResult.fail("Docker 服务不可用", code="DOCKER_UNAVAILABLE")

            import docker
            client = docker.from_env()
            containers = client.containers.list(all=all)

            result = [
                {
                    "id": c.id[:12],
                    "name": c.name,
                    "image": c.image.tags[0] if c.image.tags else "",
                    "status": c.status,
                    "state": c.attrs.get("State", {}).get("Status", "")
                }
                for c in containers
            ]

            return ActionResult.ok({"containers": result, "total": len(result)})
        except Exception as e:
            return ActionResult.fail(str(e), code="LIST_CONTAINERS_ERROR")
