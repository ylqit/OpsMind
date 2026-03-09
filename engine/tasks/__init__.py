"""
后台任务模块

提供定时任务、后台监控等能力。
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional
from engine.capabilities.host_monitor import HostMonitor
from engine.storage.alert_store import AlertStore

logger = logging.getLogger(__name__)


class AlertChecker:
    """
    告警检查器

    定期轮询主机指标，根据告警规则自动生成告警。
    """

    def __init__(self, alert_store: AlertStore, check_interval: int = 60):
        """
        初始化告警检查器

        Args:
            alert_store: 告警存储实例
            check_interval: 检查间隔（秒），默认 60 秒
        """
        self.alert_store = alert_store
        self.check_interval = check_interval
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.host_monitor = HostMonitor()

    async def start(self):
        """启动告警检查任务"""
        if self.running:
            logger.warning("告警检查任务已在运行中")
            return

        self.running = True
        self.task = asyncio.create_task(self._check_loop())
        logger.info(f"告警检查任务已启动，检查间隔：{self.check_interval}秒")

    async def stop(self):
        """停止告警检查任务"""
        if not self.running:
            return

        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.info("告警检查任务已停止")

    async def _check_loop(self):
        """告警检查循环"""
        while self.running:
            try:
                await self._check_alerts()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"告警检查失败：{e}")

            await asyncio.sleep(self.check_interval)

    async def _check_alerts(self):
        """执行一次告警检查"""
        logger.debug("开始执行告警检查...")

        # 获取主机指标
        monitor_result = await self.host_monitor.dispatch(
            metrics=["cpu", "memory", "disk", "network"]
        )

        if not monitor_result.success:
            logger.warning(f"获取主机指标失败：{monitor_result.error_message}")
            return

        metrics = monitor_result.data.get("metrics", {})
        alerts = monitor_result.data.get("alerts", [])

        # 获取告警规则
        rules = await self.alert_store.get_rules()

        # 根据规则检查告警
        for rule in rules:
            if not rule.get("enabled", True):
                continue

            matched = await self._check_rule(rule, metrics)
            if matched:
                # 检查是否已有相同的活动告警
                existing = await self._find_existing_alert(rule)
                if not existing:
                    # 创建新告警
                    await self._create_alert(rule, metrics)

        # 同时记录主机监控自动检测到的告警
        for alert in alerts:
            await self._create_auto_alert(alert)

        logger.debug(f"告警检查完成，检测到 {len(alerts)} 条告警")

    async def _check_rule(self, rule: dict, metrics: dict) -> bool:
        """
        检查单条规则是否触发告警

        Args:
            rule: 告警规则
            metrics: 监控指标

        Returns:
            是否触发告警
        """
        metric = rule.get("metric", "")
        threshold = rule.get("threshold", 0)
        operator = rule.get("operator", ">")

        # 获取当前指标值
        current_value = self._get_metric_value(metric, metrics)
        if current_value is None:
            return False

        # 比较阈值
        matched = False
        if operator == ">" and current_value > threshold:
            matched = True
        elif operator == ">=" and current_value >= threshold:
            matched = True
        elif operator == "<" and current_value < threshold:
            matched = True
        elif operator == "<=" and current_value <= threshold:
            matched = True
        elif operator == "=" and current_value == threshold:
            matched = True

        if matched:
            logger.info(f"规则 '{rule.get('name')}' 触发告警：{metric}={current_value} {operator} {threshold}")

        return matched

    def _get_metric_value(self, metric: str, metrics: dict) -> Optional[float]:
        """
        获取指标当前值

        Args:
            metric: 指标名称
            metrics: 指标字典

        Returns:
            指标值，如果不存在则返回 None
        """
        metric_mapping = {
            "cpu_usage": lambda m: m.get("cpu", {}).get("usage_percent", 0),
            "memory_usage": lambda m: m.get("memory", {}).get("usage_percent", 0),
            "disk_usage_c": lambda m: self._get_disk_usage(m, "C:\\"),
            "disk_usage_d": lambda m: self._get_disk_usage(m, "D:\\"),
        }

        if metric in metric_mapping:
            return metric_mapping[metric](metrics)
        return None

    def _get_disk_usage(self, metrics: dict, mountpoint: str) -> Optional[float]:
        """获取指定挂载点的磁盘使用率"""
        partitions = metrics.get("disk", {}).get("partitions", [])
        for p in partitions:
            if p.get("mountpoint", "").lower() == mountpoint.lower():
                return p.get("usage_percent", 0)
        return None

    async def _find_existing_alert(self, rule: dict) -> Optional[dict]:
        """查找是否存在相同规则的活动告警"""
        alerts = await self.alert_store.query_alerts(status="active", limit=100)
        for alert in alerts:
            if alert.get("rule_id") == rule.get("id"):
                return alert
        return None

    async def _create_alert(self, rule: dict, metrics: dict):
        """创建告警记录"""
        metric = rule.get("metric", "")
        current_value = self._get_metric_value(metric, metrics)

        alert_data = {
            "rule_id": rule.get("id"),
            "level": rule.get("severity", "warning"),
            "metric": metric,
            "message": f"{rule.get('name')}: {metric}={current_value} (阈值：{rule.get('operator')} {threshold})",
            "suggestion": f"检查{metric}使用情况",
            "severity": rule.get("severity", "warning"),
            "source": "auto",
            "raw_value": current_value,
            "threshold": rule.get("threshold"),
        }

        await self.alert_store.create_alert(alert_data)
        logger.info(f"已创建告警：{rule.get('name')}")

    async def _create_auto_alert(self, alert: dict):
        """创建主机监控自动检测的告警"""
        alert_data = {
            "level": alert.get("level", "warning"),
            "metric": alert.get("metric", "unknown"),
            "message": alert.get("message", ""),
            "suggestion": alert.get("suggestion", ""),
            "severity": alert.get("level", "warning"),
            "source": "host_monitor",
            "source_data": alert,
        }

        # 检查是否已有相同告警
        existing = await self._find_existing_auto_alert(alert.get("metric"))
        if not existing:
            await self.alert_store.create_alert(alert_data)

    async def _find_existing_auto_alert(self, metric: str) -> Optional[dict]:
        """查找是否存在相同的自动检测告警"""
        alerts = await self.alert_store.query_alerts(status="active", limit=100)
        for alert in alerts:
            if alert.get("metric") == metric and alert.get("source") == "host_monitor":
                return alert
        return None


class BackgroundTaskManager:
    """
    后台任务管理器

    统一管理所有后台任务的生命周期。
    """

    def __init__(self, alert_store: AlertStore):
        """
        初始化后台任务管理器

        Args:
            alert_store: 告警存储实例
        """
        self.alert_store = alert_store
        self.alert_checker: Optional[AlertChecker] = None

    async def start(self):
        """启动所有后台任务"""
        logger.info("启动后台任务管理器...")

        # 启动告警检查器（每分钟检查一次）
        self.alert_checker = AlertChecker(self.alert_store, check_interval=60)
        await self.alert_checker.start()

        logger.info("所有后台任务已启动")

    async def stop(self):
        """停止所有后台任务"""
        logger.info("停止后台任务管理器...")

        if self.alert_checker:
            await self.alert_checker.stop()

        logger.info("所有后台任务已停止")
