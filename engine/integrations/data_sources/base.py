"""
数据源适配器基类

定义所有数据源适配器的统一接口。
"""
from abc import ABC, abstractmethod
from enum import IntEnum
from typing import Optional, Any
from dataclasses import dataclass
from datetime import datetime


class DataSourceType(IntEnum):
    """
    数据源类型枚举

    Attributes:
        Docker: Docker 容器
        LogFile: 日志文件
        Prometheus: Prometheus 监控
        Kubernetes: Kubernetes 集群
        Elasticsearch: Elasticsearch 日志
    """
    Docker = 0
    LogFile = 1
    Prometheus = 2
    Kubernetes = 3
    Elasticsearch = 4


@dataclass
class HealthStatus:
    """
    健康状态数据类

    Attributes:
        healthy: 是否健康
        message: 状态消息
        latency_ms: 响应延迟（毫秒）
        last_check: 最后检查时间
    """
    healthy: bool
    message: str
    latency_ms: Optional[float] = None
    last_check: Optional[datetime] = None


class DataSourceAdapter(ABC):
    """
    数据源适配器基类
    """

    @property
    @abstractmethod
    def data_source_type(self) -> DataSourceType:
        """
        返回数据源类型

        Returns:
            DataSourceType: 数据源类型
        """
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        显示名称

        Returns:
            str: 数据源显示名称
        """
        pass

    @abstractmethod
    async def initialize(self) -> bool:
        """
        初始化数据源连接

        Returns:
            bool: 是否初始化成功
        """
        pass

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """
        健康检查

        Returns:
            HealthStatus: 健康状态
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """
        关闭连接

        清理资源。
        """
        pass

    def is_available(self) -> bool:
        """
        检查数据源是否可用

        Returns:
            bool: 是否可用
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            status = loop.run_until_complete(self.health_check())
            return status.healthy
        except Exception:
            return False
