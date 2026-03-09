"""
Docker 数据源适配器

提供 Docker 容器相关的底层数据访问能力。
"""
from typing import Dict, Any, List, Optional
from .base import DataSourceAdapter, DataSourceType, HealthStatus
import time
from datetime import datetime


class DockerAdapter(DataSourceAdapter):
    """
    Docker 数据源适配器

    提供容器状态查询、日志获取、事件监听等能力。
    """

    def __init__(self, host: str = "unix:///var/run/docker.sock"):
        """
        初始化 Docker 适配器

        Args:
            host: Docker 守护进程地址
        """
        self.host = host
        self._client = None

    @property
    def data_source_type(self) -> DataSourceType:
        return DataSourceType.Docker

    @property
    def display_name(self) -> str:
        return "Docker 容器"

    @property
    def client(self):
        """获取 Docker 客户端"""
        if self._client is None:
            raise RuntimeError("Docker 客户端未初始化")
        return self._client

    async def initialize(self) -> bool:
        """初始化 Docker 客户端"""
        try:
            import docker
            self._client = docker.DockerClient(base_url=self.host)
            self._client.ping()
            return True
        except Exception:
            return False

    async def health_check(self) -> HealthStatus:
        """健康检查"""
        start_time = time.time()
        try:
            import docker
            client = docker.DockerClient(base_url=self.host)
            client.ping()
            latency = (time.time() - start_time) * 1000
            return HealthStatus(
                healthy=True,
                message="Docker 守护进程正常",
                latency_ms=latency,
                last_check=datetime.now()
            )
        except Exception as e:
            return HealthStatus(
                healthy=False,
                message=str(e),
                last_check=datetime.now()
            )

    async def list_containers(self, all: bool = True) -> List[Dict[str, Any]]:
        """
        列出所有容器

        Args:
            all: 是否包含已停止的容器

        Returns:
            容器列表
        """
        try:
            containers = self._client.containers.list(all=all)
            return [
                {
                    "id": c.id[:12],
                    "name": c.name,
                    "image": c.image.tags[0] if c.image.tags else c.image.short_id,
                    "status": c.status,
                    "state": c.attrs["State"]["Status"],
                    "created": c.attrs["Created"]
                }
                for c in containers
            ]
        except Exception:
            return []

    async def get_container(self, name: str) -> Optional[Dict[str, Any]]:
        """
        获取容器详情

        Args:
            name: 容器名称或 ID

        Returns:
            容器详情
        """
        try:
            container = self._client.containers.get(name)
            return {
                "id": container.id,
                "name": container.name,
                "image": container.image.tags[0] if container.image.tags else "",
                "status": container.status,
                "state": container.attrs["State"],
                "network": container.attrs["NetworkSettings"],
                "mounts": container.attrs["Mounts"],
                "created": container.attrs["Created"]
            }
        except Exception:
            return None

    async def get_logs(self, name: str, lines: int = 100) -> Optional[str]:
        """
        获取容器日志

        Args:
            name: 容器名称
            lines: 日志行数

        Returns:
            日志内容
        """
        try:
            container = self._client.containers.get(name)
            logs = container.logs(tail=lines, stderr=True)
            return logs.decode("utf-8", errors="replace")
        except Exception:
            return None

    async def start_container(self, name: str) -> bool:
        """
        启动容器

        Args:
            name: 容器名称

        Returns:
            是否成功
        """
        try:
            container = self._client.containers.get(name)
            container.start()
            return True
        except Exception:
            return False

    async def stop_container(self, name: str, timeout: int = 10) -> bool:
        """
        停止容器

        Args:
            name: 容器名称
            timeout: 超时时间（秒）

        Returns:
            是否成功
        """
        try:
            container = self._client.containers.get(name)
            container.stop(timeout=timeout)
            return True
        except Exception:
            return False

    async def restart_container(self, name: str) -> bool:
        """
        重启容器

        Args:
            name: 容器名称

        Returns:
            是否成功
        """
        try:
            container = self._client.containers.get(name)
            container.restart()
            return True
        except Exception:
            return False

    async def remove_container(self, name: str, force: bool = False) -> bool:
        """
        删除容器

        Args:
            name: 容器名称
            force: 是否强制删除

        Returns:
            是否成功
        """
        try:
            container = self._client.containers.get(name)
            container.remove(force=force)
            return True
        except Exception:
            return False

    async def close(self):
        """关闭连接"""
        if self._client:
            self._client.close()
            self._client = None
