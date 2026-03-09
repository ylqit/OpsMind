"""
主机资源监控能力

监控 CPU、内存、磁盘、网络等系统资源。
"""
import psutil
from typing import Dict, Any, Type, List
from pydantic import BaseModel, Field
from .base import BaseCapability, CapabilityMetadata
from .decorators import with_timeout, with_error_handling
from ..contracts import ActionResult


class HostMonitorInput(BaseModel):
    """
    主机监控输入参数

    Attributes:
        metrics: 要监控的指标列表
        history_seconds: 历史数据时长（秒）
    """
    metrics: List[str] = Field(
        default=["cpu", "memory", "disk", "network"],
        description="要监控的指标列表"
    )
    history_seconds: int = Field(
        default=60,
        description="历史数据时长（秒）",
        ge=10,
        le=3600
    )


class HostMonitor(BaseCapability):
    """
    主机资源监控器

    提供服务器资源实时监控能力，包括：
    - CPU 使用率
    - 内存使用率
    - 磁盘使用率
    - 网络流量

    使用示例:
        >>> monitor = HostMonitor()
        >>> result = await monitor.dispatch(metrics=["cpu", "memory"])
    """

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="inspect_host",
            description="监控服务器资源状态（CPU/内存/磁盘/网络）",
            version="1.0.0",
            tags=["host", "monitor", "metrics"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return HostMonitorInput

    @with_timeout(timeout_seconds=30)
    @with_error_handling("HOST_MONITOR_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        执行主机监控

        Args:
            metrics: 要监控的指标列表
            history_seconds: 历史数据时长

        Returns:
            ActionResult: 监控结果
        """
        try:
            input_data = HostMonitorInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        result = {
            "timestamp": psutil.boot_time(),
            "metrics": {}
        }

        # CPU 监控
        if "cpu" in input_data.metrics:
            result["metrics"]["cpu"] = self._get_cpu_metrics()

        # 内存监控
        if "memory" in input_data.metrics:
            result["metrics"]["memory"] = self._get_memory_metrics()

        # 磁盘监控
        if "disk" in input_data.metrics:
            result["metrics"]["disk"] = self._get_disk_metrics()

        # 网络监控
        if "network" in input_data.metrics:
            result["metrics"]["network"] = self._get_network_metrics()

        # 告警检测
        alerts = self._check_thresholds(result["metrics"])
        if alerts:
            result["alerts"] = alerts

        return ActionResult.ok(result)

    def _get_cpu_metrics(self) -> Dict[str, Any]:
        """
        获取 CPU 指标

        Returns:
            CPU 指标字典
        """
        return {
            "usage_percent": psutil.cpu_percent(interval=1),
            "per_cpu_usage": psutil.cpu_percent(interval=1, percpu=True),
            "cpu_count": psutil.cpu_count(),
            "cpu_freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None,
            "load_avg": psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None
        }

    def _get_memory_metrics(self) -> Dict[str, Any]:
        """
        获取内存指标

        Returns:
            内存指标字典
        """
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return {
            "total_mb": mem.total / 1024 / 1024,
            "available_mb": mem.available / 1024 / 1024,
            "usage_percent": mem.percent,
            "used_mb": mem.used / 1024 / 1024,
            "swap_total_mb": swap.total / 1024 / 1024,
            "swap_usage_percent": swap.percent
        }

    def _get_disk_metrics(self) -> Dict[str, Any]:
        """
        获取磁盘指标

        Returns:
            磁盘指标字典
        """
        partitions = psutil.disk_partitions()
        disk_info = []
        for partition in partitions:
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disk_info.append({
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "fstype": partition.fstype,
                    "total_gb": usage.total / 1024 / 1024 / 1024,
                    "used_gb": usage.used / 1024 / 1024 / 1024,
                    "usage_percent": usage.percent,
                    "free_gb": usage.free / 1024 / 1024 / 1024
                })
            except (PermissionError, OSError):
                # 跳过无权限或无法访问的分区
                continue
        return {"partitions": disk_info}

    def _get_network_metrics(self) -> Dict[str, Any]:
        """
        获取网络指标

        Returns:
            网络指标字典
        """
        net_io = psutil.net_io_counters()
        net_if = psutil.net_if_addrs()

        # 获取 IPv4 地址列表
        interfaces = {}
        for iface, addrs in net_if.items():
            ipv4_addrs = []
            for addr in addrs:
                if addr.family.name == 'AF_INET':  # type: ignore
                    ipv4_addrs.append(addr.address)
            if ipv4_addrs:
                interfaces[iface] = ipv4_addrs

        return {
            "bytes_sent_mb": net_io.bytes_sent / 1024 / 1024,
            "bytes_recv_mb": net_io.bytes_recv / 1024 / 1024,
            "packets_sent": net_io.packets_sent,
            "packets_recv": net_io.packets_recv,
            "interfaces": interfaces
        }

    def _check_thresholds(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        检查阈值，生成告警

        Args:
            metrics: 监控指标字典

        Returns:
            告警列表
        """
        alerts = []

        # CPU 告警
        cpu_usage = metrics.get("cpu", {}).get("usage_percent", 0)
        if cpu_usage > 90:
            alerts.append({
                "level": "critical",
                "metric": "cpu_usage",
                "message": f"CPU 使用率过高：{cpu_usage}%",
                "suggestion": "检查高负载进程，考虑扩容或优化"
            })
        elif cpu_usage > 70:
            alerts.append({
                "level": "warning",
                "metric": "cpu_usage",
                "message": f"CPU 使用率偏高：{cpu_usage}%",
                "suggestion": "关注 CPU 趋势"
            })

        # 内存告警
        mem_usage = metrics.get("memory", {}).get("usage_percent", 0)
        if mem_usage > 90:
            alerts.append({
                "level": "critical",
                "metric": "memory_usage",
                "message": f"内存使用率过高：{mem_usage}%",
                "suggestion": "检查内存泄漏，清理缓存或增加内存"
            })
        elif mem_usage > 70:
            alerts.append({
                "level": "warning",
                "metric": "memory_usage",
                "message": f"内存使用率偏高：{mem_usage}%",
                "suggestion": "关注内存趋势"
            })

        # 磁盘告警
        for partition in metrics.get("disk", {}).get("partitions", []):
            usage_percent = partition.get("usage_percent", 0)
            mountpoint = partition.get("mountpoint", "unknown")

            if usage_percent > 90:
                alerts.append({
                    "level": "critical",
                    "metric": "disk_usage",
                    "message": f"磁盘 {mountpoint} 使用率过高：{usage_percent}%",
                    "suggestion": "清理日志文件、临时文件或扩容磁盘"
                })
            elif usage_percent > 70:
                alerts.append({
                    "level": "warning",
                    "metric": "disk_usage",
                    "message": f"磁盘 {mountpoint} 使用率偏高：{usage_percent}%",
                    "suggestion": "关注磁盘使用趋势"
                })

        return alerts
